"""Control-plane bookkeeping for workers and their reconciliation during recovery (M1.5-2a).

Every ``worker_runs`` write is fenced on the execution epoch (``assert_epoch`` locks the
execution row first), so a stale API process cannot record or advance a worker after a newer
owner claimed the execution. Recovery order (M1.5-1c extended):

    claim lease -> reconcile workers (this module) -> expire orphaned reservations -> re-enter graph

A worker that cannot be proven stopped blocks recovery (fail closed): a live stale worker must
never run alongside a fresh attempt.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.worker_run import ACTIVE_STATES, STATE_RANK, WorkerRun, WorkerRunState
from app.services.execution_lease import assert_epoch
from app.worker_runtime.base import (
    CreateWorkerRequest,
    RuntimeNotFoundError,
    WorkerRef,
    WorkerRuntime,
    WorkerRuntimeError,
)
from astrava_broker.contract import WorkerState, WorkerSummary
from astrava_broker.profiles import PROFILES, Profile

logger = logging.getLogger(__name__)


class WorkerReconcileError(Exception):
    """Recovery cannot proceed because a stale worker may still be running or is unaccounted for."""


@dataclass
class ReconcileReport:
    terminated: list[str] = field(default_factory=list)
    cleaned: list[str] = field(default_factory=list)
    lost: list[str] = field(default_factory=list)
    unknown_at_broker: list[str] = field(default_factory=list)

    def as_event(self) -> dict[str, list[str]]:
        return {
            "terminated": self.terminated,
            "cleaned": self.cleaned,
            "lost": self.lost,
            "unknown_at_broker": self.unknown_at_broker,
        }


_BROKER_TO_RUN = {
    WorkerState.CREATED: WorkerRunState.CREATED,
    WorkerState.RUNNING: WorkerRunState.RUNNING,
    WorkerState.EXITED: WorkerRunState.EXITED,
    WorkerState.KILLED: WorkerRunState.KILLED,
    WorkerState.TIMED_OUT: WorkerRunState.TIMED_OUT,
    WorkerState.LOST: WorkerRunState.LOST,
    WorkerState.CLEANED: WorkerRunState.CLEANED,
}


def _ts(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value is not None else None


def _ref(run: WorkerRun, epoch: int) -> WorkerRef:
    """A worker is addressed under the CALLER's epoch (the broker enforces ownership rules)."""
    return WorkerRef(worker_run_id=run.id, execution_id=run.execution_id, lease_epoch=epoch)


class WorkerRunService:
    # ---- fenced persistence ---------------------------------------------------------------
    @staticmethod
    async def _advance(
        db: AsyncSession,
        run: WorkerRun,
        epoch: int,
        state: WorkerRunState,
        summary: WorkerSummary | None = None,
        error: str | None = None,
    ) -> None:
        """Fenced, forward-only state write. Commits."""
        await assert_epoch(db, run.execution_id, epoch)
        await db.refresh(run)
        current = WorkerRunState(run.state)
        # Never move backwards (REQUESTED < CREATED < RUNNING < stopped < COLLECTED < CLEANED);
        # CLEANUP_FAILED may be superseded by CLEANED.
        if current == WorkerRunState.CLEANUP_FAILED:
            if state in (WorkerRunState.CLEANED, WorkerRunState.CLEANUP_FAILED):
                run.state = state.value
        elif STATE_RANK[state] >= STATE_RANK[current]:
            run.state = state.value
        if summary is not None:
            run.worker_id = summary.worker_id
            run.exit_code = summary.exit_code if summary.exit_code is not None else run.exit_code
            run.stop_reason = summary.reason.value if summary.reason else run.stop_reason
            run.started_at = _ts(summary.started_at) or run.started_at
            run.finished_at = _ts(summary.finished_at) or run.finished_at
        if error is not None:
            run.error = error[:500]
        await db.commit()

    # ---- launch ---------------------------------------------------------------------------
    @staticmethod
    async def launch(
        db: AsyncSession,
        runtime: WorkerRuntime,
        *,
        execution_id: uuid.UUID,
        epoch: int,
        task_id: uuid.UUID,
        attempt: int,
        profile: Profile,
        repo_id: str,
        base_ref: str,
        wall_timeout_s: int,
        job: str,
        reservation_id: uuid.UUID | None = None,
        fence_token: str | None = None,
        input_ref: uuid.UUID | None = None,
    ) -> WorkerRun:
        """Record intent, ask the broker to create the worker, record the result.

        The row is committed BEFORE the broker is called, so a crash between the two leaves a
        REQUESTED row and (maybe) a CREATED worker: both are found and reaped by recovery.
        Idempotent on (execution, task, attempt, kind).
        """
        limits = PROFILES[profile]
        await assert_epoch(db, execution_id, epoch)
        existing = (
            await db.execute(
                select(WorkerRun).where(
                    WorkerRun.execution_id == execution_id,
                    WorkerRun.task_id == task_id,
                    WorkerRun.attempt == attempt,
                    WorkerRun.kind == limits.kind.value,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            await db.commit()
            return existing
        run = WorkerRun(
            id=uuid.uuid4(),
            execution_id=execution_id,
            task_id=task_id,
            attempt=attempt,
            kind=limits.kind.value,
            profile=profile.value,
            image_alias=limits.image_alias.value,
            lease_epoch=epoch,
            state=WorkerRunState.REQUESTED.value,
            wall_timeout_s=wall_timeout_s,
            reservation_id=reservation_id,
            fence_token_sha256=hashlib.sha256(fence_token.encode()).hexdigest()
            if fence_token
            else None,
        )
        db.add(run)
        await db.commit()

        try:
            summary = await runtime.create_worker(
                CreateWorkerRequest(
                    ref=_ref(run, epoch),
                    task_id=task_id,
                    attempt=attempt,
                    kind=limits.kind,
                    profile=profile,
                    image_alias=limits.image_alias,
                    repo_id=repo_id,
                    base_ref=base_ref,
                    wall_timeout_s=wall_timeout_s,
                    job=job,
                    input_ref=input_ref,
                )
            )
        except WorkerRuntimeError as exc:
            await WorkerRunService._advance(
                db, run, epoch, WorkerRunState.LOST, error=f"create failed: {exc}"
            )
            raise
        await WorkerRunService._advance(db, run, epoch, WorkerRunState.CREATED, summary)
        return run

    @staticmethod
    async def start(db: AsyncSession, runtime: WorkerRuntime, run: WorkerRun, epoch: int) -> None:
        summary = await runtime.start_worker(_ref(run, epoch))
        await WorkerRunService._advance(db, run, epoch, _BROKER_TO_RUN[summary.state], summary)

    @staticmethod
    async def refresh(db: AsyncSession, runtime: WorkerRuntime, run: WorkerRun, epoch: int) -> None:
        summary = await runtime.get_status(_ref(run, epoch))
        await WorkerRunService._advance(db, run, epoch, _BROKER_TO_RUN[summary.state], summary)

    @staticmethod
    async def stop_and_clean(
        db: AsyncSession, runtime: WorkerRuntime, run: WorkerRun, epoch: int
    ) -> None:
        summary = await runtime.terminate_worker(_ref(run, epoch), grace_s=2)
        await WorkerRunService._advance(db, run, epoch, _BROKER_TO_RUN[summary.state], summary)
        summary = await runtime.cleanup_worker(_ref(run, epoch))
        await WorkerRunService._advance(db, run, epoch, WorkerRunState.CLEANED, summary)

    # ---- recovery -------------------------------------------------------------------------
    @staticmethod
    async def reconcile_for_recovery(
        db: AsyncSession, runtime: WorkerRuntime | None, execution_id: uuid.UUID, new_epoch: int
    ) -> ReconcileReport:
        """Stop and clean every worker of an older epoch; settle the DB rows. Idempotent.

        Raises ``WorkerReconcileError`` (caller aborts recovery and releases the lease) if the
        runtime is unavailable or any stale worker cannot be proven stopped and cleaned.
        """
        report = ReconcileReport()
        rows = list(
            (await db.execute(select(WorkerRun).where(WorkerRun.execution_id == execution_id)))
            .scalars()
            .all()
        )
        open_rows = [r for r in rows if WorkerRunState(r.state) != WorkerRunState.CLEANED]
        if runtime is None:
            if open_rows:
                raise WorkerReconcileError(
                    f"{len(open_rows)} worker run(s) exist but no worker runtime is configured"
                )
            return report

        try:
            listed = await runtime.list_workers(execution_id, new_epoch)
            by_id = {w.worker_run_id: w for w in listed}
            for run in open_rows:
                if run.lease_epoch >= new_epoch:
                    continue  # impossible for a freshly claimed epoch; never touch a newer owner
                broker = by_id.pop(run.id, None)
                if broker is None:
                    # The broker has no such worker: never created, or already cleaned there.
                    was_active = WorkerRunState(run.state) in ACTIVE_STATES
                    await WorkerRunService._advance(
                        db, run, new_epoch, WorkerRunState.CLEANED, error="absent at broker"
                    )
                    if was_active:
                        report.lost.append(str(run.id))
                    continue
                await WorkerRunService._reap_one(db, runtime, run, new_epoch, report)
            # Workers the broker knows that the DB has no row for (crash between create and the
            # row commit cannot happen by construction, but a lost DB must not hide a worker).
            for wid in by_id:
                ref = WorkerRef(wid, execution_id, new_epoch)
                await runtime.terminate_worker(ref, grace_s=2)
                await runtime.cleanup_worker(ref)
                report.unknown_at_broker.append(str(wid))
                logger.warning("Reaped worker %s with no worker_runs row", wid)
        except WorkerRuntimeError as exc:
            raise WorkerReconcileError(f"worker reconciliation failed: {exc}") from exc
        return report

    @staticmethod
    async def _reap_one(
        db: AsyncSession,
        runtime: WorkerRuntime,
        run: WorkerRun,
        epoch: int,
        report: ReconcileReport,
    ) -> None:
        ref = _ref(run, epoch)
        try:
            summary = await runtime.terminate_worker(ref, grace_s=2)
            report.terminated.append(str(run.id))
            await WorkerRunService._advance(db, run, epoch, _BROKER_TO_RUN[summary.state], summary)
            summary = await runtime.cleanup_worker(ref)
        except RuntimeNotFoundError:
            await WorkerRunService._advance(
                db, run, epoch, WorkerRunState.LOST, error="vanished during reconcile"
            )
            report.lost.append(str(run.id))
            return
        except WorkerRuntimeError as exc:
            await WorkerRunService._advance(
                db, run, epoch, WorkerRunState.CLEANUP_FAILED, error=f"cleanup failed: {exc}"
            )
            raise
        await WorkerRunService._advance(db, run, epoch, WorkerRunState.CLEANED, summary)
        report.cleaned.append(str(run.id))
