"""``FakeWorkerRuntime``: an independent in-process implementation of the interface.

Used by orchestration tests so they need no broker process. It is deliberately NOT a wrapper of
the broker service: the conformance suite runs the same behavioural checks against both, which is
what proves the interface is replaceable. It can also inject faults.
"""

import time
import uuid
from dataclasses import dataclass, field

from app.worker_runtime.base import (
    CreateWorkerRequest,
    RuntimeCapacityError,
    RuntimeConflictError,
    RuntimeNotFoundError,
    RuntimeUnavailableError,
    WorkerRef,
    WorkerRuntime,
    WorkerRuntimeError,
)
from astrava_broker.contract import (
    TERMINAL_STATES,
    ExportManifest,
    HealthResult,
    OutputResult,
    StopReason,
    WorkerState,
    WorkerSummary,
    contract_digest,
)
from astrava_broker.profiles import PROFILES


@dataclass
class _W:
    summary: WorkerSummary
    req: CreateWorkerRequest


@dataclass
class FakeWorkerRuntime(WorkerRuntime):
    capacity: int = 2
    workers: dict[uuid.UUID, _W] = field(default_factory=dict)
    epochs: dict[uuid.UUID, int] = field(default_factory=dict)
    fail_next: dict[str, WorkerRuntimeError] = field(default_factory=dict)
    unavailable: bool = False
    calls: list[tuple[str, uuid.UUID | None]] = field(default_factory=list)

    # ---- helpers --------------------------------------------------------------------------
    def _enter(self, op: str, execution_id: uuid.UUID | None, epoch: int | None) -> None:
        self.calls.append((op, execution_id))
        if self.unavailable:
            raise RuntimeUnavailableError("fake runtime unavailable")
        if op in self.fail_next:
            raise self.fail_next.pop(op)
        if execution_id is not None and epoch is not None:
            if epoch < self.epochs.get(execution_id, -1):
                raise RuntimeConflictError("stale lease epoch")
            self.epochs[execution_id] = epoch

    def _get(self, ref: WorkerRef, *, same_epoch: bool = False) -> _W:
        w = self.workers.get(ref.worker_run_id)
        if w is None or w.summary.execution_id != ref.execution_id:
            raise RuntimeNotFoundError("unknown worker")
        if same_epoch and w.summary.lease_epoch != ref.lease_epoch:
            raise RuntimeConflictError("worker belongs to another lease epoch")
        if ref.lease_epoch < w.summary.lease_epoch:
            raise RuntimeConflictError("stale lease epoch")
        return w

    def _set(self, w: _W, **changes: object) -> WorkerSummary:
        w.summary = w.summary.model_copy(update=changes)
        return w.summary

    def _settle(self, w: _W) -> None:
        s = w.summary
        if s.state == WorkerState.RUNNING and s.deadline is not None and time.time() >= s.deadline:
            self._set(
                w,
                state=WorkerState.TIMED_OUT,
                reason=StopReason.DEADLINE,
                finished_at=time.time(),
            )
        if s.state in (WorkerState.CREATED, WorkerState.RUNNING) and (
            s.lease_epoch < self.epochs.get(s.execution_id, -1)
        ):
            self._set(
                w, state=WorkerState.KILLED, reason=StopReason.STALE_EPOCH, finished_at=time.time()
            )

    # ---- the nine operations --------------------------------------------------------------
    async def create_worker(self, request: CreateWorkerRequest) -> WorkerSummary:
        ref = request.ref
        self._enter("create_worker", ref.execution_id, ref.lease_epoch)
        existing = self.workers.get(ref.worker_run_id)
        if existing is not None:
            r = existing.req
            same = r.ref == ref and (
                r.task_id,
                r.attempt,
                r.kind,
                r.profile,
                r.job,
                r.wall_timeout_s,
            ) == (
                request.task_id,
                request.attempt,
                request.kind,
                request.profile,
                request.job,
                request.wall_timeout_s,
            )
            if not same:
                raise RuntimeConflictError("worker_run_id already used with other parameters")
            return existing.summary
        active = [
            w
            for w in self.workers.values()
            if w.summary.state in (WorkerState.CREATED, WorkerState.RUNNING)
        ]
        if len(active) >= self.capacity:
            raise RuntimeCapacityError("worker capacity reached")
        if PROFILES[request.profile].kind != request.kind:
            raise WorkerRuntimeError("profile does not match kind")
        summary = WorkerSummary(
            worker_run_id=ref.worker_run_id,
            execution_id=ref.execution_id,
            lease_epoch=ref.lease_epoch,
            task_id=request.task_id,
            attempt=request.attempt,
            kind=request.kind,
            profile=request.profile,
            state=WorkerState.CREATED,
            worker_id=f"fakert-{str(ref.worker_run_id)[:12]}",
            created_at=time.time(),
        )
        self.workers[ref.worker_run_id] = _W(summary, request)
        return summary

    async def start_worker(self, ref: WorkerRef) -> WorkerSummary:
        self._enter("start_worker", ref.execution_id, ref.lease_epoch)
        w = self._get(ref, same_epoch=True)
        self._settle(w)
        if w.summary.state == WorkerState.RUNNING:
            return w.summary
        if w.summary.state != WorkerState.CREATED:
            raise RuntimeConflictError(f"cannot start a {w.summary.state.value} worker")
        now = time.time()
        return self._set(
            w,
            state=WorkerState.RUNNING,
            started_at=now,
            deadline=now + w.req.wall_timeout_s,
        )

    async def get_status(self, ref: WorkerRef) -> WorkerSummary:
        self._enter("get_status", ref.execution_id, ref.lease_epoch)
        w = self._get(ref)
        self._settle(w)
        return w.summary

    async def collect_output(self, ref: WorkerRef, max_bytes: int) -> OutputResult:
        self._enter("collect_output", ref.execution_id, ref.lease_epoch)
        w = self._get(ref, same_epoch=True)
        if w.summary.state in (WorkerState.CREATED, WorkerState.CLEANED):
            raise RuntimeConflictError(f"no output for a {w.summary.state.value} worker")
        return OutputResult(log="", log_truncated=False)

    async def export_artifacts(
        self, ref: WorkerRef, max_files: int, max_bytes: int
    ) -> ExportManifest:
        self._enter("export_artifacts", ref.execution_id, ref.lease_epoch)
        w = self._get(ref, same_epoch=True)
        self._settle(w)
        if w.summary.state not in TERMINAL_STATES:
            raise RuntimeConflictError("export requires a stopped worker")
        return ExportManifest(entries=[], total_bytes=0)

    async def terminate_worker(self, ref: WorkerRef, grace_s: int = 5) -> WorkerSummary:
        self._enter("terminate_worker", ref.execution_id, ref.lease_epoch)
        w = self._get(ref)
        self._settle(w)
        if w.summary.state in (WorkerState.CREATED, WorkerState.RUNNING):
            reason = (
                StopReason.NEVER_STARTED
                if w.summary.state == WorkerState.CREATED
                else StopReason.TERMINATED
            )
            self._set(w, state=WorkerState.KILLED, reason=reason, finished_at=time.time())
        return w.summary

    async def cleanup_worker(self, ref: WorkerRef) -> WorkerSummary:
        self._enter("cleanup_worker", ref.execution_id, ref.lease_epoch)
        w = self._get(ref)
        self._settle(w)
        if w.summary.state == WorkerState.RUNNING:
            raise RuntimeConflictError("refusing to clean a running worker")
        return self._set(w, state=WorkerState.CLEANED)

    async def list_workers(self, execution_id: uuid.UUID, lease_epoch: int) -> list[WorkerSummary]:
        self._enter("list_workers", execution_id, lease_epoch)
        out = []
        for w in self.workers.values():
            if w.summary.execution_id == execution_id:
                self._settle(w)
                if w.summary.state != WorkerState.CLEANED:
                    out.append(w.summary)
        return out

    async def health(self) -> HealthResult:
        self._enter("health", None, None)
        active = sum(
            1
            for w in self.workers.values()
            if w.summary.state in (WorkerState.CREATED, WorkerState.RUNNING)
        )
        return HealthResult(
            status="ok",
            tier="A",
            backend="fake",
            active_workers=active,
            capacity=self.capacity,
            contract_digest=contract_digest(),
        )
