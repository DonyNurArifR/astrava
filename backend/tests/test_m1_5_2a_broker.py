"""M1.5-2a: broker service behaviour through the real HTTP front end (ASGI) and runtime client."""

import json
import stat
import time
import uuid

import httpx
import pytest

from app.worker_runtime.base import (
    CreateWorkerRequest,
    RuntimeCapacityError,
    RuntimeConflictError,
    RuntimeDeniedError,
    RuntimeNotFoundError,
    RuntimeUnavailableError,
    WorkerRef,
)
from app.worker_runtime.broker import BrokerWorkerRuntime
from astrava_broker import contract as c
from astrava_broker.contract import Profile, WorkerKind, WorkerState
from tests.m152a_support import KEY, SHA, Clock, create_args, envelope, make_app, make_service


class Env:
    def __init__(self, tmp_path, **kw):
        self.clock = Clock()
        self.service = make_service(tmp_path, clock=self.clock, **kw)
        self.app = make_app(self.service)
        self.transport = httpx.ASGITransport(app=self.app, client=("127.0.0.1", 1))
        self.rt = BrokerWorkerRuntime(key=KEY, transport=self.transport, clock=self.clock)
        self.exec = uuid.uuid4()

    def ref(self, epoch=1, wid=None, execution=None) -> WorkerRef:
        return WorkerRef(wid or uuid.uuid4(), execution or self.exec, epoch)

    def req(self, ref, job="{}", **kw) -> CreateWorkerRequest:
        d = dict(
            ref=ref,
            task_id=uuid.uuid4(),
            attempt=0,
            kind=WorkerKind.AGENT,
            profile=Profile.AGENT_STANDARD,
            image_alias=c.ImageAlias.AGENT_BASE,
            repo_id="repo-one",
            base_ref=SHA,
            wall_timeout_s=60,
            job=job,
        )
        d.update(kw)
        return CreateWorkerRequest(**d)

    async def raw(self, body: bytes, content_type="application/json"):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://b") as cl:
            return await cl.post("/v1/call", content=body, headers={"content-type": content_type})


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def sim(**kw) -> str:
    return json.dumps({"fake": kw})


# ---- lifecycle ------------------------------------------------------------------------------
async def test_full_lifecycle_and_idempotency(env):
    ref = env.ref()
    req = env.req(ref, job=sim(runtime_s=5, log="hello", files={"out/a.txt": "A"}))
    w = await env.rt.create_worker(req)
    assert w.state == WorkerState.CREATED and w.lease_epoch == 1
    assert (await env.rt.create_worker(req)).worker_id == w.worker_id  # idempotent

    r = await env.rt.start_worker(ref)
    assert r.state == WorkerState.RUNNING and r.deadline is not None
    assert (await env.rt.start_worker(ref)).state == WorkerState.RUNNING  # idempotent

    with pytest.raises(RuntimeConflictError):  # never export a running worker
        await env.rt.export_artifacts(ref, 10, 1000)
    with pytest.raises(RuntimeConflictError):  # never clean a running worker
        await env.rt.cleanup_worker(ref)

    env.clock.advance(6)
    st = await env.rt.get_status(ref)
    assert st.state == WorkerState.EXITED and st.exit_code == 0
    out = await env.rt.collect_output(ref, 1000)
    assert out.log == "hello"
    manifest = await env.rt.export_artifacts(ref, 10, 1000)
    assert [e.path for e in manifest.entries] == ["out/a.txt"]

    cl = await env.rt.cleanup_worker(ref)
    assert cl.state == WorkerState.CLEANED
    assert (await env.rt.cleanup_worker(ref)).state == WorkerState.CLEANED  # idempotent
    assert await env.rt.list_workers(env.exec, 1) == []  # cleaned workers are not listed


async def test_create_same_id_other_params_conflicts(env):
    ref = env.ref()
    await env.rt.create_worker(env.req(ref, job="{}"))
    with pytest.raises(RuntimeConflictError):
        await env.rt.create_worker(env.req(ref, job=sim(exit_code=3)))


async def test_deadline_times_out_a_running_worker(env):
    ref = env.ref()
    await env.rt.create_worker(env.req(ref, job=sim(runtime_s=10_000), wall_timeout_s=30))
    await env.rt.start_worker(ref)
    env.clock.advance(31)
    st = await env.rt.get_status(ref)
    assert st.state == WorkerState.TIMED_OUT and st.reason == c.StopReason.DEADLINE


async def test_reaper_enforces_deadline_without_any_api_call(env):
    ref = env.ref()
    await env.rt.create_worker(env.req(ref, job=sim(runtime_s=10_000), wall_timeout_s=30))
    await env.rt.start_worker(ref)
    env.clock.advance(31)
    assert env.service.reap() == 1
    assert env.service.backend.get(str(ref.worker_run_id)).state == "timed_out"


async def test_created_but_never_started_worker_is_reaped(tmp_path):
    env = Env(tmp_path, created_ttl_s=10)
    ref = env.ref()
    await env.rt.create_worker(env.req(ref))
    env.clock.advance(11)
    env.service.reap()
    assert env.service.backend.get(str(ref.worker_run_id)).reason == "never_started"


async def test_capacity_is_enforced_and_freed(tmp_path):
    env = Env(tmp_path, max_active_workers=1)
    a, b = env.ref(), env.ref()
    await env.rt.create_worker(env.req(a))
    with pytest.raises(RuntimeCapacityError):
        await env.rt.create_worker(env.req(b))
    await env.rt.terminate_worker(a)
    await env.rt.create_worker(env.req(b))  # slot freed by termination


async def test_terminate_is_idempotent_and_blocks_start(env):
    ref = env.ref()
    await env.rt.create_worker(env.req(ref, job=sim(runtime_s=100)))
    await env.rt.start_worker(ref)
    assert (await env.rt.terminate_worker(ref)).state == WorkerState.KILLED
    assert (await env.rt.terminate_worker(ref)).state == WorkerState.KILLED
    with pytest.raises(RuntimeConflictError):
        await env.rt.start_worker(ref)


# ---- authorization and fencing --------------------------------------------------------------
async def test_worker_is_bound_to_its_execution_without_existence_oracle(env):
    ref = env.ref()
    await env.rt.create_worker(env.req(ref))
    other = WorkerRef(ref.worker_run_id, uuid.uuid4(), 1)
    with pytest.raises(RuntimeNotFoundError):
        await env.rt.get_status(other)
    with pytest.raises(RuntimeNotFoundError):  # same answer as a genuinely unknown id
        await env.rt.get_status(env.ref(execution=other.execution_id))
    with pytest.raises(RuntimeNotFoundError):
        await env.rt.terminate_worker(other)


async def test_cross_execution_input_ref_is_refused(env):
    src = env.ref(execution=uuid.uuid4())
    await env.rt.create_worker(env.req(src))
    verify = env.req(
        env.ref(),
        kind=WorkerKind.VERIFY,
        profile=Profile.VERIFY_STANDARD,
        image_alias=c.ImageAlias.VERIFY_BASE,
        input_ref=src.worker_run_id,
        wall_timeout_s=60,
    )
    with pytest.raises(RuntimeNotFoundError):
        await env.rt.create_worker(verify)


async def test_stale_epoch_is_rejected_for_every_operation(env):
    old = env.ref(epoch=1)
    await env.rt.create_worker(env.req(old, job=sim(runtime_s=100)))
    await env.rt.start_worker(old)
    # A recovering API process (epoch 2) makes first contact.
    assert [w.worker_run_id for w in await env.rt.list_workers(env.exec, 2)] == [old.worker_run_id]
    stale = WorkerRef(old.worker_run_id, env.exec, 1)
    for call in (
        env.rt.get_status(stale),
        env.rt.start_worker(stale),
        env.rt.terminate_worker(stale),
        env.rt.cleanup_worker(stale),
        env.rt.collect_output(stale, 10),
        env.rt.list_workers(env.exec, 1),
        env.rt.create_worker(env.req(env.ref(epoch=1))),
    ):
        with pytest.raises(RuntimeConflictError):
            await call


async def test_new_epoch_may_stop_and_clean_but_not_adopt_old_workers(env):
    old = env.ref(epoch=1)
    await env.rt.create_worker(env.req(old, job=sim(runtime_s=100)))
    await env.rt.start_worker(old)
    new = WorkerRef(old.worker_run_id, env.exec, 2)
    with pytest.raises(RuntimeConflictError):  # cannot progress another epoch's worker
        await env.rt.collect_output(new, 10)
    assert (await env.rt.get_status(new)).lease_epoch == 1
    assert (await env.rt.terminate_worker(new)).state == WorkerState.KILLED
    assert (await env.rt.cleanup_worker(new)).state == WorkerState.CLEANED


async def test_reaper_kills_stale_epoch_workers_when_api_is_dead(env):
    old = env.ref(epoch=1)
    await env.rt.create_worker(env.req(old, job=sim(runtime_s=100)))
    await env.rt.start_worker(old)
    await env.rt.list_workers(env.exec, 2)  # epoch high-water becomes 2, then the API dies
    env.service.reap()
    rec = env.service.backend.get(str(old.worker_run_id))
    assert rec.state == "killed" and rec.reason == "stale_epoch"


# ---- authentication / transport -------------------------------------------------------------
async def test_replayed_request_is_denied_even_after_broker_restart(tmp_path):
    env = Env(tmp_path)
    body = json.dumps(envelope("health")).encode()
    assert (await env.raw(body)).status_code == 200
    assert (await env.raw(body)).status_code == 403  # replay
    env2 = Env(tmp_path)  # same state dir: ledger is persistent
    assert (await env2.raw(body)).status_code == 403


async def test_bad_mac_and_garbage_are_rejected_with_authenticated_or_empty_replies(env):
    bad = envelope("health", key=b"x" * 40)
    r = await env.raw(json.dumps(bad).encode())
    assert r.status_code == 403
    assert (await env.raw(b"not json")).status_code == 400
    assert (await env.raw(b"{}", content_type="text/plain")).status_code == 415


async def test_oversize_body_rejected_by_http_layer(env):
    assert (await env.raw(b"x" * (c.MAX_REQUEST_BYTES + 10))).status_code == 413


async def test_only_one_route_exists(env):
    async with httpx.AsyncClient(transport=env.transport, base_url="http://b") as cl:
        for path in ("/", "/docs", "/openapi.json", "/v1/exec", "/v1", "/metrics", "/health"):
            assert (await cl.get(path)).status_code == 404
        assert (await cl.get("/v1/call")).status_code == 405
        assert (await cl.put("/v1/call", content=b"{}")).status_code == 405


async def test_client_rejects_a_spoofed_broker(env, tmp_path):
    spoof = BrokerWorkerRuntime(key=b"s" * 40, transport=env.transport)
    with pytest.raises(RuntimeDeniedError):
        await spoof.health()  # server denies; its reply is not signed with the spoofer's key either


async def test_client_fails_closed_when_broker_unreachable():
    class Dead(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):  # noqa: ANN001
            raise httpx.ConnectError("refused")

    rt = BrokerWorkerRuntime(key=KEY, transport=Dead())
    with pytest.raises(RuntimeUnavailableError):
        await rt.health()


async def test_client_rejects_unsigned_or_wrong_request_response(env):
    class Liar(httpx.AsyncBaseTransport):
        def __init__(self, body):
            self.body = body

        async def handle_async_request(self, request):  # noqa: ANN001
            return httpx.Response(200, content=self.body)

    unsigned = json.dumps({"ok": True, "code": "ok"}).encode()
    for body in (unsigned, b"", b"<html>"):
        with pytest.raises(RuntimeDeniedError):
            await BrokerWorkerRuntime(key=KEY, transport=Liar(body)).health()


async def test_internal_errors_do_not_leak_details(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret path /Users/x/.ssh")

    monkeypatch.setattr(env.service.backend, "list_active", boom)
    r = await env.raw(json.dumps(envelope("health")).encode())
    assert r.status_code == 500 and b"secret" not in r.content and b"/Users" not in r.content


# ---- audit and persistence ------------------------------------------------------------------
async def test_audit_log_records_ops_but_never_job_or_output(env):
    ref = env.ref()
    await env.rt.create_worker(env.req(ref, job=sim(log="TOPSECRET-LOG")))
    await env.rt.start_worker(ref)
    audit = env.service.state.audit_path.read_text()
    assert "create_worker" in audit and "start_worker" in audit
    assert "TOPSECRET" not in audit
    assert str(ref.worker_run_id) in audit


async def test_broker_restart_reconstructs_workers_from_persisted_state(tmp_path):
    env = Env(tmp_path)
    ref = env.ref()
    await env.rt.create_worker(env.req(ref, job=sim(runtime_s=100)))
    await env.rt.start_worker(ref)
    env2 = Env(tmp_path)  # a brand-new service object over the same state dir
    env2.clock.t = env.clock.t
    listed = await env2.rt.list_workers(ref.execution_id, 1)
    assert [w.worker_run_id for w in listed] == [ref.worker_run_id]
    assert listed[0].state == WorkerState.RUNNING and listed[0].deadline is not None


async def test_health_reports_tier_backend_and_contract_digest(env):
    h = await env.rt.health()
    assert (h.status, h.tier, h.backend) == ("ok", "A", "fake")
    assert h.contract_digest == c.contract_digest()


def test_server_refuses_non_fake_backend_and_unsafe_keys(tmp_path):
    from astrava_broker.config import BrokerConfig, BrokerConfigError, load_key

    base = {
        "ASTRAVA_BROKER_SOCKET": str(tmp_path / "s"),
        "ASTRAVA_BROKER_KEY_FILE": str(tmp_path / "k"),
        "ASTRAVA_BROKER_STATE_DIR": str(tmp_path / "st"),
    }
    for backend in ("docker", "", "podman"):
        with pytest.raises(BrokerConfigError):
            BrokerConfig.from_env({**base, "ASTRAVA_BROKER_BACKEND": backend})
    BrokerConfig.from_env({**base, "ASTRAVA_BROKER_BACKEND": "fake"})

    key = tmp_path / "k"
    key.write_bytes(b"s" * 40)
    key.chmod(0o644)
    with pytest.raises(BrokerConfigError):
        load_key(key)
    key.chmod(0o600)
    assert load_key(key) == b"s" * 40
    short = tmp_path / "short"
    short.write_bytes(b"abc")
    short.chmod(0o600)
    with pytest.raises(BrokerConfigError):
        load_key(short)
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(BrokerConfigError):
        load_key(link)
    assert stat.S_IMODE(key.stat().st_mode) == 0o600


def test_no_time_dependence_in_clock_fixture():
    assert abs(Clock().t - time.time()) < 5
    assert c.CLOCK_SKEW_S == 30.0
    assert create_args()["attempt"] == 0


async def test_authorize_still_fences_if_epoch_mark_is_lost(env):
    """Defense in depth: even with the epoch table wiped, a worker refuses an older epoch."""
    w2 = env.ref(epoch=2)
    await env.rt.create_worker(env.req(w2))
    with env.service.state._db:
        env.service.state._db.execute("DELETE FROM epochs")
    with pytest.raises(RuntimeConflictError):
        await env.rt.get_status(WorkerRef(w2.worker_run_id, env.exec, 1))


async def test_chunked_oversize_body_without_content_length_is_rejected(env):
    async def gen():
        for _ in range(c.MAX_REQUEST_BYTES // 4096 + 5):
            yield b"x" * 4096

    async with httpx.AsyncClient(transport=env.transport, base_url="http://b") as cl:
        r = await cl.post("/v1/call", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 413
