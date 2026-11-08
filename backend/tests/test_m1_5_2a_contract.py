"""M1.5-2a: the broker contract is closed, bounded, authenticated and has no passthrough."""

import json
import time
import uuid

import pytest

from astrava_broker import contract as c
from astrava_broker.contract import ContractError, ErrorCode, Op, parse_request
from tests.m152a_support import KEY, create_args, envelope

EXEC = str(uuid.uuid4())
WRK = str(uuid.uuid4())


def parse(obj: dict, key: bytes = KEY, now: float | None = None):
    return parse_request(json.dumps(obj).encode(), key, now=now or time.time())


def good(op="create_worker", **kw):
    fields = dict(worker_run_id=WRK, execution_id=EXEC, lease_epoch=1, args=create_args())
    fields.update(kw)
    return envelope(op, **fields)


def code_of(obj, **kw) -> ErrorCode:
    with pytest.raises(ContractError) as ei:
        parse(obj, **kw)
    return ei.value.code


def test_exactly_nine_operations():
    assert {o.value for o in Op} == {
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
    assert set(c.OP_SPECS) == set(Op)


def test_valid_create_parses():
    req = parse(good())
    assert req.op == Op.CREATE_WORKER


@pytest.mark.parametrize("op", ["exec", "attach", "run", "docker", "pull", "build", "inspect", ""])
def test_unknown_operation_rejected(op):
    assert code_of(good(op=op)) == ErrorCode.INVALID


# Every key that could carry Docker configuration must be rejected wherever it is put.
SMUGGLE = [
    "image", "command", "cmd", "entrypoint", "env", "environment", "mounts", "binds",
    "volumes", "network", "network_mode", "privileged", "cap_add", "devices", "user",
    "security_opt", "pid_mode", "ipc_mode", "host_config", "docker", "labels", "ports",
    "working_dir", "extra_hosts", "dns", "tmpfs", "sysctls", "ulimits", "memory", "cpus",
]  # fmt: skip


@pytest.mark.parametrize("key", SMUGGLE)
def test_no_passthrough_in_args(key):
    args = create_args()
    args[key] = "x"
    assert code_of(good(args=args)) == ErrorCode.INVALID


@pytest.mark.parametrize("key", SMUGGLE)
def test_no_passthrough_in_envelope(key):
    obj = good()
    unsigned = {k: v for k, v in obj.items() if k != "mac"}
    unsigned[key] = "x"
    assert code_of(c.sign_request(KEY, unsigned)) == ErrorCode.INVALID


@pytest.mark.parametrize(
    "op", ["start_worker", "get_status", "cleanup_worker", "list_workers", "health"]
)
def test_argless_ops_reject_any_argument(op):
    scoped = op != "health"
    fields = dict(args={"image": "evil"})
    if op != "health":
        fields.update(execution_id=EXEC, lease_epoch=1)
    if op not in ("list_workers", "health"):
        fields.update(worker_run_id=WRK)
    assert scoped or op == "health"
    assert code_of(envelope(op, **fields)) == ErrorCode.INVALID


@pytest.mark.parametrize(
    "over",
    [
        {"image_alias": "ubuntu:latest"},
        {"image_alias": "../../etc"},
        {"profile": "privileged"},
        {"profile": "verify-standard"},  # kind/profile mismatch
        {"kind": "verify"},  # kind vs profile mismatch
        {"base_ref": "main"},
        {"base_ref": "--upload-pack=evil"},
        {"base_ref": "A" * 40},
        {"repo_id": "../x"},
        {"repo_id": "/abs"},
        {"repo_id": "a b"},
        {"repo_id": ""},
        {"repo_id": "x" * 65},
        {"attempt": -1},
        {"attempt": 21},
        {"attempt": True},
        {"attempt": "1"},
        {"attempt": 1.5},
        {"wall_timeout_s": 0},
        {"wall_timeout_s": 1801},  # above the agent profile cap
        {"wall_timeout_s": 10**9},
        {"job": "x" * (c.MAX_JOB_BYTES + 1)},
        {"job": "a\x00b"},
        {"job": "é" * (c.MAX_JOB_BYTES // 2 + 1)},  # byte length, not character count
        {"task_id": "not-a-uuid"},
        {"input_ref": str(uuid.uuid4())},  # input_ref only for verify workers
    ],
)
def test_create_value_bounds(over):
    assert code_of(good(args=create_args(**over))) == ErrorCode.INVALID


def test_verify_profile_accepts_input_ref():
    args = create_args(
        kind="verify",
        image_alias="verify-base",
        profile="verify-standard",
        input_ref=str(uuid.uuid4()),
        wall_timeout_s=900,
    )
    assert parse(good(args=args)).op == Op.CREATE_WORKER


@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("collect_output", {"max_bytes": 0}),
        ("collect_output", {"max_bytes": c.MAX_OUTPUT_BYTES + 1}),
        ("export_artifacts", {"max_files": 0, "max_bytes": 1}),
        ("export_artifacts", {"max_files": c.MAX_EXPORT_FILES + 1, "max_bytes": 1}),
        ("export_artifacts", {"max_files": 1, "max_bytes": c.MAX_EXPORT_BYTES + 1}),
        ("terminate_worker", {"grace_s": -1}),
        ("terminate_worker", {"grace_s": c.MAX_TERMINATE_GRACE_S + 1}),
        ("terminate_worker", {}),
    ],
)
def test_limits_above_caps_rejected(op, args):
    obj = envelope(op, worker_run_id=WRK, execution_id=EXEC, lease_epoch=1, args=args)
    assert code_of(obj) == ErrorCode.INVALID


@pytest.mark.parametrize(
    "fields",
    [
        dict(worker_run_id=None),  # worker op without worker id
        dict(execution_id=None),
        dict(lease_epoch=None),
        dict(lease_epoch=-1),
        dict(lease_epoch=2**31),
    ],
)
def test_scope_fields_required_for_worker_ops(fields):
    base = dict(worker_run_id=WRK, execution_id=EXEC, lease_epoch=1, args=create_args())
    base.update(fields)
    assert code_of(envelope("create_worker", **base)) == ErrorCode.INVALID


def test_health_must_not_carry_scope():
    assert code_of(envelope("health", execution_id=EXEC, lease_epoch=1)) == ErrorCode.INVALID
    assert code_of(envelope("health", worker_run_id=WRK)) == ErrorCode.INVALID
    assert parse(envelope("health")).op == Op.HEALTH


def test_list_workers_requires_execution_scope_and_forbids_worker_id():
    assert code_of(envelope("list_workers")) == ErrorCode.INVALID
    assert (
        code_of(envelope("list_workers", execution_id=EXEC, lease_epoch=1, worker_run_id=WRK))
        == ErrorCode.INVALID
    )
    assert parse(envelope("list_workers", execution_id=EXEC, lease_epoch=1)).op == Op.LIST_WORKERS


# ---- authentication ------------------------------------------------------------------------
def test_bad_mac_denied_before_anything_else():
    obj = good()
    obj["args"]["attempt"] = 3  # tamper after signing
    assert code_of(obj) == ErrorCode.DENIED


def test_wrong_key_denied():
    assert code_of(good(), key=b"z" * 40) == ErrorCode.DENIED


def test_missing_or_garbage_mac_denied():
    obj = good()
    del obj["mac"]
    assert code_of(obj) == ErrorCode.DENIED
    obj["mac"] = "zz"
    assert code_of(obj) == ErrorCode.DENIED


def test_unauthenticated_invalid_garbage_is_denied_not_validated():
    # An attacker without the key learns nothing about validation rules.
    assert code_of({"op": "exec", "args": {"image": "x"}}) == ErrorCode.DENIED


def test_timestamp_window():
    now = time.time()
    assert code_of(good(ts=now - 120), now=now) == ErrorCode.DENIED
    assert code_of(good(ts=now + 120), now=now) == ErrorCode.DENIED
    assert parse(good(ts=now - 5), now=now).op == Op.CREATE_WORKER


def test_malformed_json_and_oversize():
    with pytest.raises(ContractError) as ei:
        parse_request(b"{not json", KEY, now=time.time())
    assert ei.value.code == ErrorCode.INVALID
    with pytest.raises(ContractError):
        parse_request(b"[]", KEY, now=time.time())
    with pytest.raises(ContractError) as ei2:
        parse_request(b" " * (c.MAX_REQUEST_BYTES + 1), KEY, now=time.time())
    assert ei2.value.code == ErrorCode.INVALID
    with pytest.raises(ContractError):
        parse_request(b"[" * 100000, KEY, now=time.time())  # deep nesting must not crash


def test_request_and_response_macs_are_domain_separated():
    unsigned = {"x": 1}
    assert c.sign_request(KEY, unsigned)["mac"] != c.sign_response(KEY, unsigned)["mac"]


# ---- responses are untrusted too ----------------------------------------------------------
def _resp(request_id, **over):
    body = {
        "ok": True,
        "code": "ok",
        "message": "",
        "request_id": str(request_id),
        "ts": time.time(),
    }
    body.update(over)
    return json.dumps(c.sign_response(KEY, body)).encode()


def test_response_must_match_request_id_and_mac():
    rid = uuid.uuid4()
    assert c.parse_response(_resp(rid), KEY, request_id=rid).ok
    with pytest.raises(ContractError):
        c.parse_response(_resp(rid), KEY, request_id=uuid.uuid4())  # replayed answer
    with pytest.raises(ContractError):
        c.parse_response(_resp(rid), b"w" * 40, request_id=rid)  # spoofed broker


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd", "../x", "a/../b", "a//b", "./a", "a/./b", ".git/config", "a/.git/x",
        "a\\b", "C:/x", "a\x00b", "a\nb", "", "x" * 300,
        "a\uff0fb", "a\u200bb", "a\u202eb", "\ufb01le", "a\ue000b",
    ],
)  # fmt: skip
def test_manifest_paths_from_the_broker_are_revalidated(path):
    rid = uuid.uuid4()
    manifest = {
        "entries": [{"path": path, "size": 1, "sha256": "a" * 64}],
        "total_bytes": 1,
    }
    with pytest.raises(ContractError):
        c.parse_response(_resp(rid, manifest=manifest), KEY, request_id=rid)


def test_manifest_rejects_case_collisions_and_bad_totals():
    rid = uuid.uuid4()
    entries = [
        {"path": "A.txt", "size": 1, "sha256": "a" * 64},
        {"path": "a.txt", "size": 1, "sha256": "b" * 64},
    ]
    with pytest.raises(ContractError):
        c.parse_response(
            _resp(rid, manifest={"entries": entries, "total_bytes": 2}), KEY, request_id=rid
        )
    with pytest.raises(ContractError):
        c.parse_response(
            _resp(rid, manifest={"entries": entries[:1], "total_bytes": 99}), KEY, request_id=rid
        )


def test_response_extra_fields_rejected():
    rid = uuid.uuid4()
    with pytest.raises(ContractError):
        c.parse_response(_resp(rid, docker_command="rm -rf /"), KEY, request_id=rid)


def test_profiles_are_constants_with_network_none():
    from astrava_broker.profiles import PROFILES

    for limits in PROFILES.values():
        assert limits.network == "none"  # provider egress is undecided (D1); nothing enabled
        assert limits.max_wall_timeout_s <= 1800
