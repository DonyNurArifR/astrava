"""Single-writer ownership of a workflow execution (M1.5-1c).

A runner process must hold the execution's lease to run or recover it. The lease is a row-level
compare-and-set on ``workflow_executions`` so it works across processes and survives a crash:

* ``claim`` is one atomic ``UPDATE ... WHERE (lease is free or expired) AND status IN (...)``.
  It increments ``run_epoch``; of two simultaneous claimers exactly one update matches a row.
* ``heartbeat`` extends the lease only while the caller's epoch is still current.
* ``assert_epoch`` fences a state write: it locks the row ``FOR UPDATE`` and compares the epoch,
  so a stale worker (whose epoch was superseded) cannot write after a newer owner claimed.

Time comes from PostgreSQL (``clock_timestamp()``), never from a worker's clock.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import ExecutionStatus

logger = logging.getLogger(__name__)


class ExecutionLeaseError(Exception):
    """Base class for lease failures."""


class LeaseHeldError(ExecutionLeaseError):
    """Another live owner holds the lease (or the status does not allow a claim)."""


class StaleWorkerError(ExecutionLeaseError):
    """The caller's epoch is no longer current: a newer owner claimed the execution."""


_CLAIM_SQL = text(
    """
    UPDATE workflow_executions
       SET run_epoch = run_epoch + 1,
           lease_owner = :owner,
           lease_expires_at = clock_timestamp() + make_interval(secs => CAST(:ttl AS DOUBLE PRECISION)),
           status = COALESCE(CAST(:new_status AS VARCHAR), status)
     WHERE id = :id
       AND status = ANY(CAST(:statuses AS VARCHAR[]))
       AND (:ignore_lease OR lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp())
 RETURNING run_epoch
    """
)

_HEARTBEAT_SQL = text(
    """
    UPDATE workflow_executions
       SET lease_expires_at = clock_timestamp() + make_interval(secs => CAST(:ttl AS DOUBLE PRECISION))
     WHERE id = :id AND run_epoch = :epoch AND lease_owner = :owner
 RETURNING run_epoch
    """
)

_RELEASE_SQL = text(
    """
    UPDATE workflow_executions
       SET lease_owner = NULL, lease_expires_at = NULL
     WHERE id = :id AND run_epoch = :epoch AND lease_owner = :owner
    """
)


def new_owner_id(label: str = "runner") -> str:
    """Unique owner identity for one runner invocation (process-unique, not a credential)."""
    return f"{label}:{uuid.uuid4().hex[:16]}"


async def claim(
    db: AsyncSession,
    execution_id: uuid.UUID,
    owner: str,
    ttl_seconds: float,
    *,
    statuses: Iterable[ExecutionStatus] = (ExecutionStatus.RUNNING,),
    new_status: ExecutionStatus | None = None,
    ignore_lease: bool = False,
) -> int:
    """Atomically claim the execution; returns the new ``run_epoch``. Commits.

    Raises ``LeaseHeldError`` when a live lease exists or the status is not claimable.
    ``ignore_lease`` is for statuses that by definition have no running worker (an execution
    waiting for approval); exclusivity then comes from the status change in the same UPDATE.
    """
    result = await db.execute(
        _CLAIM_SQL,
        {
            "id": execution_id,
            "owner": owner,
            "ttl": float(ttl_seconds),
            "new_status": new_status.name if new_status else None,
            "statuses": [s.name for s in statuses],  # enum NAMES are what the column stores
            "ignore_lease": ignore_lease,
        },
    )
    row = result.first()
    await db.commit()
    if row is None:
        raise LeaseHeldError(
            f"Execution {execution_id} is not claimable (live lease held or status not eligible)"
        )
    return int(row[0])


async def heartbeat(
    db: AsyncSession, execution_id: uuid.UUID, owner: str, epoch: int, ttl_seconds: float
) -> bool:
    """Extend the lease. Returns False when the epoch/owner is no longer current."""
    result = await db.execute(
        _HEARTBEAT_SQL,
        {"id": execution_id, "owner": owner, "epoch": epoch, "ttl": float(ttl_seconds)},
    )
    ok = result.first() is not None
    await db.commit()
    return ok


async def release(db: AsyncSession, execution_id: uuid.UUID, owner: str, epoch: int) -> None:
    """Drop the lease if (and only if) the caller is still the current owner."""
    await db.execute(_RELEASE_SQL, {"id": execution_id, "owner": owner, "epoch": epoch})
    await db.commit()


async def assert_epoch(db: AsyncSession, execution_id: uuid.UUID, epoch: int) -> None:
    """Fence a write: lock the execution row and require that ``epoch`` is still current.

    Call this first inside the writing transaction; the row lock is held until commit, so a
    concurrent claim cannot interleave with the write that follows.
    """
    row = (
        await db.execute(
            text("SELECT run_epoch FROM workflow_executions WHERE id = :id FOR UPDATE"),
            {"id": execution_id},
        )
    ).first()
    if row is None:
        raise StaleWorkerError(f"Execution {execution_id} no longer exists")
    if int(row[0]) != epoch:
        raise StaleWorkerError(
            f"Execution {execution_id}: worker epoch {epoch} superseded by {int(row[0])}"
        )


async def run_with_lease[T](
    session_factory: Callable[[], Any],
    execution_id: uuid.UUID,
    owner: str,
    epoch: int,
    ttl_seconds: float,
    work: Callable[[], Awaitable[T]],
    heartbeat_interval: float | None = None,
) -> T:
    """Run ``work`` while a background task keeps the lease alive.

    If the heartbeat finds the epoch superseded, or cannot reach the database for longer than
    the lease TTL, ``work`` is cancelled and ``StaleWorkerError`` is raised: a worker that lost
    ownership stops doing new work instead of racing its successor.
    """
    interval = heartbeat_interval or max(0.2, ttl_seconds / 3)
    lost = asyncio.Event()
    reason: list[str] = []

    async def _beat() -> None:
        loop = asyncio.get_running_loop()
        last_ok = loop.time()
        while True:
            await asyncio.sleep(interval)
            try:
                async with session_factory() as session:
                    ok = await heartbeat(session, execution_id, owner, epoch, ttl_seconds)
                if not ok:
                    reason.append("epoch superseded")
                    lost.set()
                    return
                last_ok = loop.time()
            except Exception as exc:  # database unreachable: tolerate until the lease would lapse
                logger.warning("Lease heartbeat for %s failed: %s", execution_id, exc)
                if loop.time() - last_ok > ttl_seconds:
                    reason.append("lease lapsed (database unreachable)")
                    lost.set()
                    return

    work_task = asyncio.ensure_future(work())
    beat_task = asyncio.ensure_future(_beat())
    lost_task = asyncio.ensure_future(lost.wait())
    try:
        await asyncio.wait({work_task, lost_task}, return_when=asyncio.FIRST_COMPLETED)
        if lost.is_set() and not work_task.done():
            work_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await work_task
            raise StaleWorkerError(f"Execution {execution_id} lease lost: {', '.join(reason)}")
        return work_task.result()
    finally:
        for t in (beat_task, lost_task):
            t.cancel()
        for t in (beat_task, lost_task):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        if not work_task.done():
            work_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await work_task
