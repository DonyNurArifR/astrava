"""M1.5-2a: the runtime interface is replaceable. One behavioural suite, two implementations."""

import uuid

import httpx
import pytest

from app.worker_runtime.base import (
    CreateWorkerRequest,
    RuntimeCapacityError,
    RuntimeConflictError,
    RuntimeNotFoundError,
    RuntimeUnavailableError,
    WorkerRef,
    WorkerRuntime,
)
from app.worker_runtime.broker import BrokerWorkerRuntime
from app.worker_runtime.fake import FakeWorkerRuntime
from astrava_broker.contract import ImageAlias, Profile, WorkerKind, WorkerState
from tests.m152a_support import KEY, SHA, make_app, make_service


@pytest.fixture(params=["fake", "broker"])
def rt(request, tmp_path) -> WorkerRuntime:
    if request.param == "fake":
        return FakeWorkerRuntime(capacity=2)
    service = make_service(tmp_path, max_active_workers=2)
    transport = httpx.ASGITransport(app=make_app(service), client=("127.0.0.1", 1))
    return BrokerWorkerRuntime(key=KEY, transport=transport)


def mk(ref: WorkerRef, **kw) -> CreateWorkerRequest:
    d = dict(
        ref=ref,
        task_id=uuid.uuid4(),
        attempt=0,
        kind=WorkerKind.AGENT,
        profile=Profile.AGENT_STANDARD,
        image_alias=ImageAlias.AGENT_BASE,
        repo_id="repo-one",
        base_ref=SHA,
        wall_timeout_s=60,
        job='{"fake": {"runtime_s": 100000}}',  # only the fake broker backend reads this
    )
    d.update(kw)
    return CreateWorkerRequest(**d)


def new_ref(execution=None, epoch=1) -> WorkerRef:
    return WorkerRef(uuid.uuid4(), execution or uuid.uuid4(), epoch)


async def test_lifecycle_parity(rt):
    ref = new_ref()
    req = mk(ref)
    first = await rt.create_worker(req)
    assert first.state == WorkerState.CREATED
    assert (await rt.create_worker(req)).worker_id == first.worker_id
    assert (await rt.start_worker(ref)).state == WorkerState.RUNNING
    with pytest.raises(RuntimeConflictError):
        await rt.cleanup_worker(ref)
    assert (await rt.terminate_worker(ref)).state == WorkerState.KILLED
    assert (await rt.terminate_worker(ref)).state == WorkerState.KILLED
    assert (await rt.cleanup_worker(ref)).state == WorkerState.CLEANED
    assert (await rt.cleanup_worker(ref)).state == WorkerState.CLEANED
    assert await rt.list_workers(ref.execution_id, 1) == []


async def test_export_requires_stopped_worker(rt):
    ref = new_ref()
    await rt.create_worker(mk(ref))
    await rt.start_worker(ref)
    with pytest.raises(RuntimeConflictError):
        await rt.export_artifacts(ref, 10, 100)
    await rt.terminate_worker(ref)
    assert (await rt.export_artifacts(ref, 10, 100)).entries == []


async def test_unknown_and_cross_execution_workers_are_not_found(rt):
    ref = new_ref()
    await rt.create_worker(mk(ref))
    with pytest.raises(RuntimeNotFoundError):
        await rt.get_status(new_ref())
    with pytest.raises(RuntimeNotFoundError):
        await rt.get_status(WorkerRef(ref.worker_run_id, uuid.uuid4(), 1))


async def test_capacity(rt):
    a, b, c = new_ref(), new_ref(), new_ref()
    await rt.create_worker(mk(a))
    await rt.create_worker(mk(b))
    with pytest.raises(RuntimeCapacityError):
        await rt.create_worker(mk(c))


async def test_stale_epoch_fenced_and_new_epoch_can_reap(rt):
    ref = new_ref(epoch=1)
    await rt.create_worker(mk(ref))
    await rt.start_worker(ref)
    listed = await rt.list_workers(ref.execution_id, 2)
    assert [w.worker_run_id for w in listed] == [ref.worker_run_id]
    with pytest.raises(RuntimeConflictError):
        await rt.start_worker(ref)  # the old epoch is fenced
    new = WorkerRef(ref.worker_run_id, ref.execution_id, 2)
    assert (await rt.terminate_worker(new)).state == WorkerState.KILLED
    assert (await rt.cleanup_worker(new)).state == WorkerState.CLEANED


async def test_conflicting_reuse_of_worker_run_id(rt):
    ref = new_ref()
    await rt.create_worker(mk(ref))
    with pytest.raises(RuntimeConflictError):
        await rt.create_worker(mk(ref, attempt=1))


async def test_health_shape(rt):
    h = await rt.health()
    assert h.backend == "fake" and h.capacity == 2


async def test_unavailable_runtime_fails_closed():
    fake = FakeWorkerRuntime(unavailable=True)
    with pytest.raises(RuntimeUnavailableError):
        await fake.health()
    assert fake.workers == {}  # nothing was created behind the caller's back


def test_runtime_interface_has_exactly_the_nine_operations():
    abstract = {n for n in WorkerRuntime.__abstractmethods__}
    assert abstract == {
        "create_worker",
        "start_worker",
        "get_status",
        "collect_output",
        "export_artifacts",
        "terminate_worker",
        "cleanup_worker",
        "list_workers",
        "health",
    }
