"""Broker request handling: authentication, replay/epoch fencing, authorization, state machine.

Everything the broker does for a caller goes through ``BrokerService.handle``. It accepts only
contract-validated requests and drives a ``WorkerBackend`` through a narrow typed interface.
There is no code path that forwards caller-supplied data as backend configuration.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid

from pydantic import BaseModel

from astrava_broker.backend import WorkerBackend, WorkerRecord
from astrava_broker.config import BrokerConfig
from astrava_broker.contract import (
    TERMINAL_STATES,
    CollectOutputArgs,
    ContractError,
    CreateWorkerArgs,
    ErrorCode,
    ExportArtifactsArgs,
    HealthResult,
    Op,
    OutputResult,
    ParsedRequest,
    StopReason,
    TerminateArgs,
    WorkerState,
    WorkerSummary,
    contract_digest,
    parse_request,
    sign_response,
)
from astrava_broker.profiles import PROFILES
from astrava_broker.state import BrokerState

logger = logging.getLogger(__name__)

_HTTP = {
    ErrorCode.OK: 200,
    ErrorCode.INVALID: 400,
    ErrorCode.DENIED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.CAPACITY: 429,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.RUNTIME_UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
}

# Operations that make progress for a worker: the caller's epoch must equal the worker's epoch.
# Observation and teardown (get_status, terminate, cleanup, list) accept any epoch >= the worker's.
_SAME_EPOCH_OPS = {Op.START_WORKER, Op.COLLECT_OUTPUT, Op.EXPORT_ARTIFACTS}


def http_status(code: ErrorCode) -> int:
    return _HTTP[code]


def _summary(rec: WorkerRecord) -> WorkerSummary:
    return WorkerSummary(
        worker_run_id=uuid.UUID(rec.worker_run_id),
        execution_id=uuid.UUID(rec.execution_id),
        lease_epoch=rec.lease_epoch,
        task_id=uuid.UUID(rec.task_id),
        attempt=rec.attempt,
        kind=rec.kind,  # type: ignore[arg-type]
        profile=rec.profile,  # type: ignore[arg-type]
        state=WorkerState(rec.state),
        worker_id=rec.worker_id,
        exit_code=rec.exit_code,
        reason=StopReason(rec.reason) if rec.reason else None,
        created_at=rec.created_at,
        started_at=rec.started_at,
        finished_at=rec.finished_at,
        deadline=rec.deadline,
    )


class _Reject(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BrokerService:
    def __init__(
        self,
        config: BrokerConfig,
        key: bytes,
        backend: WorkerBackend,
        state: BrokerState,
        clock=time.time,  # noqa: ANN001
    ) -> None:
        self.config = config
        self._key = key
        self.backend = backend
        self.state = state
        self.clock = clock
        self._lock = asyncio.Lock()

    # ---- entry point ----------------------------------------------------------------------
    async def handle(self, raw: bytes) -> tuple[int, bytes]:
        """Returns (http_status, signed response bytes). Never raises on caller input."""
        now = self.clock()
        request_id = uuid.UUID(int=0)
        try:
            req = parse_request(raw, self._key, now=now)
            request_id = req.envelope.request_id
        except ContractError as exc:
            self.state.audit(op="?", outcome=exc.code.value, why=exc.message)
            return self._reply(exc.request_id or request_id, now, exc.code, exc.message)

        async with self._lock:
            try:
                if self.state.seen_or_record(req.envelope.nonce.lower(), now):
                    raise _Reject(ErrorCode.DENIED, "replayed request")
                payload = self._dispatch(req, now)
            except _Reject as rej:
                self._audit(req, rej.code, rej.message)
                return self._reply(request_id, now, rej.code, rej.message)
            except Exception:  # noqa: BLE001 - never leak internals to the caller
                logger.exception("broker internal error")  # broker-local log only
                self._audit(req, ErrorCode.INTERNAL, "internal error")
                return self._reply(request_id, now, ErrorCode.INTERNAL, "internal error")
        self._audit(req, ErrorCode.OK, "")
        return self._reply(request_id, now, ErrorCode.OK, "", **payload)

    def _audit(self, req: ParsedRequest, code: ErrorCode, why: str) -> None:
        e = req.envelope
        self.state.audit(
            op=e.op.value,
            request_id=str(e.request_id),
            worker_run_id=str(e.worker_run_id) if e.worker_run_id else None,
            execution_id=str(e.execution_id) if e.execution_id else None,
            lease_epoch=e.lease_epoch,
            outcome=code.value,
            why=why,
        )

    def _reply(
        self, request_id: uuid.UUID, now: float, code: ErrorCode, message: str, **payload: object
    ) -> tuple[int, bytes]:
        import json

        body: dict = {
            "ok": code == ErrorCode.OK,
            "code": code.value,
            "message": message[:200],
            "request_id": str(request_id),
            "ts": now,
        }
        for k, v in payload.items():
            if isinstance(v, list):
                body[k] = [x.model_dump(mode="json") for x in v if isinstance(x, BaseModel)]
            elif isinstance(v, BaseModel):
                body[k] = v.model_dump(mode="json")
        signed = sign_response(self._key, body)
        return http_status(code), json.dumps(signed, separators=(",", ":")).encode()

    # ---- dispatch -------------------------------------------------------------------------
    def _dispatch(self, req: ParsedRequest, now: float) -> dict:
        env = req.envelope
        if env.op == Op.HEALTH:
            return {"health": self._health()}

        assert env.execution_id is not None and env.lease_epoch is not None
        exec_id = str(env.execution_id)
        hw = self.state.epoch(exec_id)
        if env.lease_epoch < hw:
            raise _Reject(ErrorCode.CONFLICT, "stale lease epoch")
        self.state.raise_epoch(exec_id, env.lease_epoch)

        if env.op == Op.LIST_WORKERS:
            recs = []
            for rec in self.backend.list_for_execution(exec_id):
                resolved = self._settle(rec.worker_run_id, now)
                if resolved and resolved.state != WorkerState.CLEANED.value:
                    recs.append(_summary(resolved))
            return {"workers": recs}

        assert env.worker_run_id is not None
        wid = str(env.worker_run_id)
        if env.op == Op.CREATE_WORKER:
            assert isinstance(req.args, CreateWorkerArgs)
            return {"worker": self._create(wid, exec_id, env.lease_epoch, req.args, now)}

        rec = self._authorize(wid, exec_id, env.lease_epoch, env.op, now)
        if env.op == Op.START_WORKER:
            if rec.state == WorkerState.RUNNING.value:
                return {"worker": _summary(rec)}
            if rec.state != WorkerState.CREATED.value:
                raise _Reject(ErrorCode.CONFLICT, f"cannot start a {rec.state} worker")
            return {"worker": _summary(self.backend.start(wid, now))}
        if env.op == Op.GET_STATUS:
            return {"worker": _summary(rec)}
        if env.op == Op.COLLECT_OUTPUT:
            assert isinstance(req.args, CollectOutputArgs)
            if rec.state in (WorkerState.CREATED.value, WorkerState.CLEANED.value):
                raise _Reject(ErrorCode.CONFLICT, f"no output for a {rec.state} worker")
            log, trunc, result, rtrunc = self.backend.read_output(wid, req.args.max_bytes)
            return {
                "output": OutputResult(
                    log=log, log_truncated=trunc, result=result, result_truncated=rtrunc
                )
            }
        if env.op == Op.EXPORT_ARTIFACTS:
            assert isinstance(req.args, ExportArtifactsArgs)
            if WorkerState(rec.state) not in TERMINAL_STATES:
                raise _Reject(ErrorCode.CONFLICT, "export requires a stopped worker")
            return {"manifest": self.backend.export(wid, req.args.max_files, req.args.max_bytes)}
        if env.op == Op.TERMINATE_WORKER:
            assert isinstance(req.args, TerminateArgs)
            if rec.state in (WorkerState.CREATED.value, WorkerState.RUNNING.value):
                reason = (
                    StopReason.NEVER_STARTED
                    if rec.state == WorkerState.CREATED.value
                    else StopReason.TERMINATED
                )
                rec = self.backend.kill(wid, reason, now)
            return {"worker": _summary(rec)}
        if env.op == Op.CLEANUP_WORKER:
            if rec.state == WorkerState.RUNNING.value:
                raise _Reject(ErrorCode.CONFLICT, "refusing to clean a running worker")
            if rec.state != WorkerState.CLEANED.value:
                rec = self.backend.remove(wid)
            return {"worker": _summary(rec)}
        raise _Reject(ErrorCode.INVALID, "unsupported operation")  # unreachable: closed enum

    # ---- helpers --------------------------------------------------------------------------
    def _health(self) -> HealthResult:
        active = len(self.backend.list_active())
        return HealthResult(
            status="ok" if active <= self.config.max_active_workers else "degraded",
            tier=self.config.tier,  # type: ignore[arg-type]
            backend="fake",
            active_workers=active,
            capacity=self.config.max_active_workers,
            contract_digest=contract_digest(),
        )

    def _settle(self, worker_run_id: str, now: float) -> WorkerRecord | None:
        """Apply deadline / stale-epoch / never-started rules, then return the current record."""
        rec = self.backend.resolve(worker_run_id, now)
        if rec is None:
            return None
        if (
            rec.state == WorkerState.RUNNING.value
            and rec.deadline is not None
            and now >= rec.deadline
        ):
            rec = self.backend.kill(worker_run_id, StopReason.DEADLINE, now)
        if (
            rec.state == WorkerState.CREATED.value
            and now - rec.created_at > self.config.created_ttl_s
        ):
            rec = self.backend.kill(worker_run_id, StopReason.NEVER_STARTED, now)
        if rec.state in (WorkerState.CREATED.value, WorkerState.RUNNING.value) and (
            rec.lease_epoch < self.state.epoch(rec.execution_id)
        ):
            rec = self.backend.kill(worker_run_id, StopReason.STALE_EPOCH, now)
        return rec

    def reap(self) -> int:
        """Safety net run by the server loop: enforce deadlines and fence stale-epoch workers
        even if no API process is alive. Returns the number of workers it stopped."""
        now = self.clock()
        stopped = 0
        for rec in self.backend.list_active():
            before = rec.state
            after = self._settle(rec.worker_run_id, now)
            if after and after.state != before:
                stopped += 1
                self.state.audit(
                    op="reap",
                    worker_run_id=rec.worker_run_id,
                    execution_id=rec.execution_id,
                    outcome=after.state,
                    why=after.reason,
                )
        self.state.prune_ledger(now - self.config.ledger_retention_s)
        return stopped

    def _authorize(self, wid: str, exec_id: str, epoch: int, op: Op, now: float) -> WorkerRecord:
        rec = self._settle(wid, now)
        if rec is None:
            raise _Reject(ErrorCode.NOT_FOUND, "unknown worker")
        # Binding: a worker_run_id belongs to exactly one execution. Probing another
        # execution's worker looks identical to an unknown worker (no existence oracle).
        if rec.execution_id != exec_id:
            raise _Reject(ErrorCode.NOT_FOUND, "unknown worker")
        if op in _SAME_EPOCH_OPS and rec.lease_epoch != epoch:
            raise _Reject(ErrorCode.CONFLICT, "worker belongs to another lease epoch")
        if epoch < rec.lease_epoch:
            raise _Reject(ErrorCode.CONFLICT, "stale lease epoch")
        return rec

    def _create(
        self, wid: str, exec_id: str, epoch: int, a: CreateWorkerArgs, now: float
    ) -> WorkerSummary:
        job_sha = hashlib.sha256(a.job.encode()).hexdigest()
        existing = self.backend.get(wid)
        if existing is not None:
            same = (
                existing.execution_id == exec_id
                and existing.lease_epoch == epoch
                and existing.task_id == str(a.task_id)
                and existing.attempt == a.attempt
                and existing.kind == a.kind.value
                and existing.profile == a.profile.value
                and existing.repo_id == a.repo_id
                and existing.base_ref == a.base_ref
                and existing.wall_timeout_s == a.wall_timeout_s
                and existing.job_sha256 == job_sha
                and existing.input_ref == (str(a.input_ref) if a.input_ref else None)
            )
            if not same:
                raise _Reject(
                    ErrorCode.CONFLICT, "worker_run_id already used with other parameters"
                )
            return _summary(existing)

        if a.input_ref is not None:
            src = self.backend.get(str(a.input_ref))
            # Cross-execution inputs are refused; a mismatch looks like a missing input.
            if src is None or src.execution_id != exec_id:
                raise _Reject(ErrorCode.NOT_FOUND, "input_ref not found in this execution")
        if len(self.backend.list_active()) >= self.config.max_active_workers:
            raise _Reject(ErrorCode.CAPACITY, "worker capacity reached")

        limits = PROFILES[a.profile]
        rec = WorkerRecord(
            worker_run_id=wid,
            execution_id=exec_id,
            lease_epoch=epoch,
            task_id=str(a.task_id),
            attempt=a.attempt,
            kind=a.kind.value,
            profile=a.profile.value,
            image_alias=limits.image_alias.value,  # from the constant profile, not the caller
            repo_id=a.repo_id,
            base_ref=a.base_ref,
            wall_timeout_s=a.wall_timeout_s,
            job_sha256=job_sha,
            input_ref=str(a.input_ref) if a.input_ref else None,
            worker_id=f"fake-{wid[:12]}",
            created_at=now,
        )
        self.backend.create(rec, a.job)
        return _summary(rec)
