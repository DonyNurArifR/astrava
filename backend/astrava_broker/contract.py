"""The closed, versioned API-to-broker contract (wire v1).

Design rules enforced here (and pinned by tests):

* Exactly nine operations. An unknown operation is rejected; there is no passthrough.
* Every model forbids extra fields, so no key can smuggle an image reference, command,
  environment variable, mount, network, capability or Docker option into the broker.
* Every value is bounded (length, range, regex, enum). Identifiers are UUIDs or strict slugs.
* The envelope is authenticated with HMAC-SHA256 over a canonical encoding; time-bounded and
  nonce-protected against replay. Responses are authenticated too.

This module is pure data and validation: no I/O, no Docker, no ``app`` imports.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from astrava_broker.profiles import PROFILES, ImageAlias, Profile, WorkerKind

PROTOCOL_VERSION = 1

# ---- size and count caps (constants, never caller-controlled) -----------------------------
MAX_JOB_BYTES = 256 * 1024
MAX_REQUEST_BYTES = MAX_JOB_BYTES + 16 * 1024  # envelope overhead; the HTTP layer enforces it
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 256 * 1024
MAX_EXPORT_FILES = 1000
MAX_EXPORT_BYTES = 64 * 1024 * 1024
MAX_PATH_LEN = 240
MAX_TERMINATE_GRACE_S = 30
MAX_ATTEMPT = 20
CLOCK_SKEW_S = 30.0

__all__ = [
    "PROTOCOL_VERSION",
    "Op",
    "WorkerKind",
    "ImageAlias",
    "Profile",
    "WorkerState",
    "StopReason",
    "ErrorCode",
    "Envelope",
    "Response",
    "WorkerSummary",
    "OutputResult",
    "ExportEntry",
    "ExportManifest",
    "HealthResult",
    "ContractError",
    "parse_request",
    "parse_response",
    "sign_request",
    "sign_response",
    "verify_mac",
    "canonical_bytes",
]


class ContractError(Exception):
    """A request or response violates the contract. ``code`` is a closed ErrorCode value."""

    def __init__(self, code: ErrorCode, message: str, request_id: uuid.UUID | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        # Set only once the MAC has verified, so a forger cannot elicit chosen request ids.
        self.request_id = request_id


class Op(StrEnum):
    CREATE_WORKER = "create_worker"
    START_WORKER = "start_worker"
    GET_STATUS = "get_status"
    COLLECT_OUTPUT = "collect_output"
    EXPORT_ARTIFACTS = "export_artifacts"
    TERMINATE_WORKER = "terminate_worker"
    CLEANUP_WORKER = "cleanup_worker"
    LIST_WORKERS = "list_workers"
    HEALTH = "health"


class WorkerState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    EXITED = "exited"
    KILLED = "killed"
    TIMED_OUT = "timed_out"
    LOST = "lost"
    CLEANED = "cleaned"


TERMINAL_STATES = frozenset(
    {WorkerState.EXITED, WorkerState.KILLED, WorkerState.TIMED_OUT, WorkerState.LOST}
)


class StopReason(StrEnum):
    EXITED = "exited"
    TERMINATED = "terminated"
    DEADLINE = "deadline"
    STALE_EPOCH = "stale_epoch"
    NEVER_STARTED = "never_started"
    LOST = "lost"


class ErrorCode(StrEnum):
    OK = "ok"
    INVALID = "invalid"
    DENIED = "denied"
    CAPACITY = "capacity"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    INTERNAL = "internal"


# ---- primitive constrained types ----------------------------------------------------------
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Hex32 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
MacHex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
OpaqueId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
Message = Annotated[str, StringConstraints(max_length=200)]

_STRICT = ConfigDict(extra="forbid", strict=False, frozen=True)


class _Model(BaseModel):
    model_config = _STRICT


# ---- per-operation argument models --------------------------------------------------------
class EmptyArgs(_Model):
    """For operations that take no arguments: any key at all is rejected."""


class CreateWorkerArgs(_Model):
    kind: WorkerKind
    image_alias: ImageAlias
    profile: Profile
    repo_id: Slug
    base_ref: GitSha
    task_id: uuid.UUID
    attempt: int = Field(ge=0, le=MAX_ATTEMPT, strict=True)
    wall_timeout_s: int = Field(ge=1, strict=True)
    job: str = Field(max_length=MAX_JOB_BYTES)
    input_ref: uuid.UUID | None = None

    @field_validator("job")
    @classmethod
    def _job_bytes(cls, v: str) -> str:
        if "\x00" in v:
            raise ValueError("job must not contain NUL")
        if len(v.encode("utf-8")) > MAX_JOB_BYTES:
            raise ValueError("job too large")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> CreateWorkerArgs:
        limits = PROFILES[self.profile]
        if limits.kind != self.kind:
            raise ValueError("profile does not match kind")
        if limits.image_alias != self.image_alias:
            raise ValueError("image_alias does not match profile")
        if self.wall_timeout_s > limits.max_wall_timeout_s:
            raise ValueError("wall_timeout_s above the profile cap")
        if self.input_ref is not None and self.kind != WorkerKind.VERIFY:
            raise ValueError("input_ref is only valid for verify workers")
        return self


class CollectOutputArgs(_Model):
    max_bytes: int = Field(ge=1, le=MAX_OUTPUT_BYTES, strict=True)


class ExportArtifactsArgs(_Model):
    max_files: int = Field(ge=1, le=MAX_EXPORT_FILES, strict=True)
    max_bytes: int = Field(ge=1, le=MAX_EXPORT_BYTES, strict=True)


class TerminateArgs(_Model):
    grace_s: int = Field(ge=0, le=MAX_TERMINATE_GRACE_S, strict=True)


# op -> (args model, requires worker_run_id, requires execution_id+epoch)
class _OpSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    args: type[_Model]
    worker_scoped: bool
    execution_scoped: bool


OP_SPECS: dict[Op, _OpSpec] = {
    Op.CREATE_WORKER: _OpSpec(args=CreateWorkerArgs, worker_scoped=True, execution_scoped=True),
    Op.START_WORKER: _OpSpec(args=EmptyArgs, worker_scoped=True, execution_scoped=True),
    Op.GET_STATUS: _OpSpec(args=EmptyArgs, worker_scoped=True, execution_scoped=True),
    Op.COLLECT_OUTPUT: _OpSpec(args=CollectOutputArgs, worker_scoped=True, execution_scoped=True),
    Op.EXPORT_ARTIFACTS: _OpSpec(
        args=ExportArtifactsArgs, worker_scoped=True, execution_scoped=True
    ),
    Op.TERMINATE_WORKER: _OpSpec(args=TerminateArgs, worker_scoped=True, execution_scoped=True),
    Op.CLEANUP_WORKER: _OpSpec(args=EmptyArgs, worker_scoped=True, execution_scoped=True),
    Op.LIST_WORKERS: _OpSpec(args=EmptyArgs, worker_scoped=False, execution_scoped=True),
    Op.HEALTH: _OpSpec(args=EmptyArgs, worker_scoped=False, execution_scoped=False),
}
assert set(OP_SPECS) == set(Op), "every operation needs a spec; the contract is closed"


# ---- envelope -----------------------------------------------------------------------------
class Envelope(_Model):
    v: Literal[1]
    op: Op
    request_id: uuid.UUID
    worker_run_id: uuid.UUID | None = None
    execution_id: uuid.UUID | None = None
    lease_epoch: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    ts: float = Field(ge=0, strict=True)
    nonce: Hex32
    args: dict[str, Any]
    mac: MacHex


class ParsedRequest(BaseModel):
    """A fully validated request: envelope plus typed args."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    envelope: Envelope
    args: _Model

    @property
    def op(self) -> Op:
        return self.envelope.op


# ---- responses ----------------------------------------------------------------------------
class WorkerSummary(_Model):
    worker_run_id: uuid.UUID
    execution_id: uuid.UUID
    lease_epoch: int = Field(ge=0, strict=True)
    task_id: uuid.UUID
    attempt: int = Field(ge=0, le=MAX_ATTEMPT, strict=True)
    kind: WorkerKind
    profile: Profile
    state: WorkerState
    worker_id: OpaqueId
    exit_code: int | None = None
    reason: StopReason | None = None
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    deadline: float | None = None


class OutputResult(_Model):
    log: str = Field(max_length=MAX_OUTPUT_BYTES)
    log_truncated: bool
    result: str | None = Field(default=None, max_length=MAX_RESULT_BYTES)
    result_truncated: bool = False


_WIN_DRIVE = re.compile(r"^[A-Za-z]:")


def validate_relative_path(path: str) -> str:
    """Strict relative POSIX path: the broker's output is untrusted, so the API re-checks it."""
    if not path or len(path) > MAX_PATH_LEN:
        raise ValueError("path length")
    if "\x00" in path or "\\" in path or path.startswith("/") or _WIN_DRIVE.match(path):
        raise ValueError("path form")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("path component")
    if parts[0] == ".git" or ".git" in parts:
        raise ValueError("git metadata path")
    if any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise ValueError("control character in path")
    if unicodedata.normalize("NFKC", path) != path:
        raise ValueError("path is not NFKC-normalized (look-alike characters)")
    if any(unicodedata.category(c) in ("Cf", "Cs", "Co", "Cn", "Zl", "Zp") for c in path):
        raise ValueError("invisible or format character in path")
    return path


class ExportEntry(_Model):
    path: str
    size: int = Field(ge=0, le=MAX_EXPORT_BYTES, strict=True)
    sha256: MacHex
    mode: Literal["regular", "executable"] = "regular"

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return validate_relative_path(v)


class ExportManifest(_Model):
    entries: list[ExportEntry] = Field(max_length=MAX_EXPORT_FILES)
    total_bytes: int = Field(ge=0, le=MAX_EXPORT_BYTES, strict=True)
    truncated: bool = False

    @model_validator(mode="after")
    def _unique_and_sum(self) -> ExportManifest:
        seen: set[str] = set()
        for e in self.entries:
            key = e.path.casefold()
            if key in seen:
                raise ValueError("duplicate (case-folded) path")
            seen.add(key)
        if sum(e.size for e in self.entries) != self.total_bytes:
            raise ValueError("total_bytes does not match entries")
        return self


class HealthResult(_Model):
    status: Literal["ok", "degraded"]
    tier: Literal["A", "B"]
    backend: Literal["fake"]  # 2b adds the real backend value; 2a ships none
    active_workers: int = Field(ge=0, strict=True)
    capacity: int = Field(ge=0, strict=True)
    contract_digest: Hex32


class Response(_Model):
    ok: bool
    code: ErrorCode
    message: Message = ""
    request_id: uuid.UUID
    ts: float
    worker: WorkerSummary | None = None
    workers: list[WorkerSummary] | None = Field(default=None, max_length=1000)
    output: OutputResult | None = None
    manifest: ExportManifest | None = None
    health: HealthResult | None = None
    mac: MacHex


# ---- canonical encoding and authentication ------------------------------------------------
def canonical_bytes(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _mac(key: bytes, domain: bytes, obj: dict[str, Any]) -> str:
    body = {k: v for k, v in obj.items() if k != "mac"}
    return hmac.new(key, domain + canonical_bytes(body), hashlib.sha256).hexdigest()


def verify_mac(key: bytes, domain: bytes, obj: dict[str, Any]) -> bool:
    given = obj.get("mac")
    if not isinstance(given, str):
        return False
    return hmac.compare_digest(_mac(key, domain, obj), given)


REQUEST_DOMAIN = b"astrava-broker/req/v1|"
RESPONSE_DOMAIN = b"astrava-broker/resp/v1|"


def sign_request(key: bytes, unsigned: dict[str, Any]) -> dict[str, Any]:
    return {**unsigned, "mac": _mac(key, REQUEST_DOMAIN, unsigned)}


def sign_response(key: bytes, unsigned: dict[str, Any]) -> dict[str, Any]:
    return {**unsigned, "mac": _mac(key, RESPONSE_DOMAIN, unsigned)}


def contract_digest() -> str:
    """Stable digest of the operation set; lets both sides notice contract drift."""
    ident = json.dumps(
        {op.value: spec.args.__name__ for op, spec in OP_SPECS.items()}, sort_keys=True
    )
    return hashlib.sha256(ident.encode()).hexdigest()[:32]


def parse_request(raw: bytes, key: bytes, *, now: float) -> ParsedRequest:
    """Authenticate, then validate. Order matters: nothing is trusted before the MAC passes.

    Raises ``ContractError`` with ``denied`` (bad MAC, stale timestamp) or ``invalid``.
    """
    if len(raw) > MAX_REQUEST_BYTES:
        raise ContractError(ErrorCode.INVALID, "request too large")
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        raise ContractError(ErrorCode.INVALID, "malformed JSON") from None
    if not isinstance(obj, dict):
        raise ContractError(ErrorCode.INVALID, "request must be an object")
    if not verify_mac(key, REQUEST_DOMAIN, obj):
        raise ContractError(ErrorCode.DENIED, "authentication failed")
    try:
        rid: uuid.UUID | None = uuid.UUID(str(obj.get("request_id")))
    except ValueError:
        rid = None
    try:
        env = Envelope.model_validate(obj)
    except ValueError:
        raise ContractError(ErrorCode.INVALID, "envelope rejected", rid) from None
    if abs(now - env.ts) > CLOCK_SKEW_S:
        raise ContractError(ErrorCode.DENIED, "timestamp outside the accepted window", rid)

    spec = OP_SPECS[env.op]
    if spec.worker_scoped != (env.worker_run_id is not None):
        raise ContractError(
            ErrorCode.INVALID, "worker_run_id presence does not match operation", rid
        )
    if spec.execution_scoped != (env.execution_id is not None and env.lease_epoch is not None):
        raise ContractError(ErrorCode.INVALID, "execution scope does not match operation", rid)
    if not spec.execution_scoped and (env.execution_id is not None or env.lease_epoch is not None):
        raise ContractError(
            ErrorCode.INVALID, "execution scope not allowed for this operation", rid
        )
    try:
        args = spec.args.model_validate(env.args)
    except ValueError:
        raise ContractError(ErrorCode.INVALID, "arguments rejected", rid) from None
    return ParsedRequest(envelope=env, args=args)


def parse_response(raw: bytes, key: bytes, *, request_id: uuid.UUID) -> Response:
    """Client side: the broker's answer is authenticated and bound to the request it answers."""
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ContractError(ErrorCode.INVALID, "response too large")
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        raise ContractError(ErrorCode.INVALID, "malformed response") from None
    if not isinstance(obj, dict) or not verify_mac(key, RESPONSE_DOMAIN, obj):
        raise ContractError(ErrorCode.DENIED, "response authentication failed")
    try:
        resp = Response.model_validate(obj)
    except ValueError:
        raise ContractError(ErrorCode.INVALID, "response rejected") from None
    if resp.request_id != request_id:
        raise ContractError(ErrorCode.DENIED, "response is for a different request")
    return resp
