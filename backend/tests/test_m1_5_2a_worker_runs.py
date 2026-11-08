"""M1.5-2a: worker_runs bookkeeping, epoch fencing and recovery reconciliation (PostgreSQL)."""

import uuid

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.session import AsyncSessionLocal
from app.models.worker_run import WorkerRun, WorkerRunState
from app.orchestrator.runner import OrchestrationRunner
from app.services import execution_lease as lease
from app.services.worker_run_service import WorkerReconcileError, WorkerRunService
from app.worker_runtime.base import (
    CreateWorkerRequest,
    RuntimeConflictError,
    WorkerRef,
)
from app.worker_runtime.broker import BrokerWorkerRuntime
from app.worker_runtime.fake import FakeWorkerRuntime
from astrava_broker.contract import ImageAlias, Profile, WorkerKind, WorkerState
from tests.m152a_support import KEY, SHA, make_app, make_service
from tests.test_m1_5_1c_fencing import _execution, _expire_lease, _project


@pytest.fixture(params=["fake", "broker"])
def runtime(request, tmp_path):
    if request.param == "fake":
        return FakeWorkerRuntime(capacity=5)
    service = make_service(tmp_path, max_active_workers=5)
    transport = httpx.ASGITransport(app=make_app(service), client=("127.0.0.1", 1))
    return BrokerWorkerRuntime(key=KEY, transport=transport)


async def _running_execution(db):
    pid = await _project(db)
    eid = await _execution(pid)
    async with AsyncSessionLocal() as s:
        epoch = await lease.claim(s, eid, "driver", 30)
    return eid, epoch


async def _launch(db, runtime, eid, epoch, attempt=0, task=None, **kw):
    return await WorkerRunService.launch(
        db,
        runtime,
        execution_id=eid,
        epoch=epoch,
        task_id=task or uuid.uuid4(),
        attempt=attempt,
        profile=Profile.AGENT_STANDARD,
        repo_id="repo-one",
        base_ref=SHA,
        wall_timeout_s=60,
        job='{"fake": {"runtime_s": 100000}}',
        **kw,
    )


async def _states(eid) -> dict[uuid.UUID, str]:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(WorkerRun).where(WorkerRun.execution_id == eid))).scalars()
        return {r.id: r.state for r in rows}


async def _events(eid) -> list[str]:
    async with AsyncSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT event_type FROM execution_events WHERE execution_id=:e ORDER BY created_at"
            ),
            {"e": eid},
        )
        return [x[0] for x in r.all()]


# ---- launch and fencing ---------------------------------------------------------------------
async def test_launch_persists_before_and_after_broker_call(db_session, runtime):
    eid, epoch = await _running_execution(db_session)
    run = await _launch(db_session, runtime, eid, epoch)
    assert run.state == WorkerRunState.CREATED.value and run.worker_id
    await WorkerRunService.start(db_session, runtime, run, epoch)
    assert (await _states(eid))[run.id] == "running"
    again = await _launch(db_session, runtime, eid, epoch, attempt=0, task=run.task_id)
    assert again.id == run.id  # idempotent on (execution, task, attempt, kind)


async def test_stale_api_process_cannot_record_or_create_workers(db_session, runtime):
    eid, epoch = await _running_execution(db_session)
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new_epoch = await lease.claim(s, eid, "recoverer", 30)
    assert new_epoch == epoch + 1
    with pytest.raises(lease.StaleWorkerError):
        await _launch(db_session, runtime, eid, epoch)  # the superseded owner
    await db_session.rollback()
    assert await _states(eid) == {}
    if isinstance(runtime, FakeWorkerRuntime):
        assert runtime.workers == {}  # the broker was never even called


async def test_state_never_moves_backwards_and_checks_hold(db_session, runtime):
    eid, epoch = await _running_execution(db_session)
    run = await _launch(db_session, runtime, eid, epoch)
    await WorkerRunService._advance(db_session, run, epoch, WorkerRunState.RUNNING)
    await WorkerRunService._advance(db_session, run, epoch, WorkerRunState.CREATED)  # ignored
    assert (await _states(eid))[run.id] == "running"
    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            await s.execute(text("UPDATE worker_runs SET state='bogus' WHERE id=:i"), {"i": run.id})
            await s.commit()


async def test_one_run_per_execution_task_attempt_kind(db_session, runtime):
    eid, epoch = await _running_execution(db_session)
    run = await _launch(db_session, runtime, eid, epoch)
    dup = WorkerRun(
        id=uuid.uuid4(), execution_id=eid, task_id=run.task_id, attempt=run.attempt, kind=run.kind,
        profile=run.profile, image_alias=run.image_alias, lease_epoch=epoch, state="requested",
        wall_timeout_s=60,
    )  # fmt: skip
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.commit()


# ---- recovery reconciliation ----------------------------------------------------------------
async def test_reconcile_stops_and_cleans_stale_workers_idempotently(db_session, runtime):
    eid, epoch = await _running_execution(db_session)
    r1 = await _launch(db_session, runtime, eid, epoch)
    r2 = await _launch(db_session, runtime, eid, epoch)
    await WorkerRunService.start(db_session, runtime, r1, epoch)  # r2 stays CREATED
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new_epoch = await lease.claim(s, eid, "recoverer", 30)

    async with AsyncSessionLocal() as s:
        report = await WorkerRunService.reconcile_for_recovery(s, runtime, eid, new_epoch)
    assert sorted(report.cleaned) == sorted([str(r1.id), str(r2.id)])
    assert set((await _states(eid)).values()) == {"cleaned"}
    listed = await runtime.list_workers(eid, new_epoch)
    assert listed == []  # nothing left alive at the runtime

    async with AsyncSessionLocal() as s:  # second pass: nothing to do
        again = await WorkerRunService.reconcile_for_recovery(s, runtime, eid, new_epoch)
    assert again.as_event() == {
        "terminated": [],
        "cleaned": [],
        "lost": [],
        "unknown_at_broker": [],
    }


async def test_crash_between_row_and_broker_create_leaves_reapable_state(db_session, runtime):
    """REQUESTED row + a worker that exists at the broker: the pre-persist crash window."""
    eid, epoch = await _running_execution(db_session)
    task = uuid.uuid4()
    run = WorkerRun(
        id=uuid.uuid4(), execution_id=eid, task_id=task, attempt=0, kind="agent",
        profile="agent-standard", image_alias="agent-base", lease_epoch=epoch,
        state="requested", wall_timeout_s=60,
    )  # fmt: skip
    db_session.add(run)
    await db_session.commit()
    await runtime.create_worker(  # the broker created it, then the API process died
        CreateWorkerRequest(
            ref=WorkerRef(run.id, eid, epoch), task_id=task, attempt=0, kind=WorkerKind.AGENT,
            profile=Profile.AGENT_STANDARD, image_alias=ImageAlias.AGENT_BASE, repo_id="repo-one",
            base_ref=SHA, wall_timeout_s=60, job="{}",
        )
    )  # fmt: skip
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new_epoch = await lease.claim(s, eid, "recoverer", 30)
        report = await WorkerRunService.reconcile_for_recovery(s, runtime, eid, new_epoch)
    assert report.cleaned == [str(run.id)]
    assert (await _states(eid))[run.id] == "cleaned"


async def test_row_absent_at_broker_is_settled_as_lost(db_session, runtime):
    eid, epoch = await _running_execution(db_session)
    run = WorkerRun(
        id=uuid.uuid4(), execution_id=eid, task_id=uuid.uuid4(), attempt=0, kind="agent",
        profile="agent-standard", image_alias="agent-base", lease_epoch=epoch,
        state="requested", wall_timeout_s=60,
    )  # fmt: skip
    db_session.add(run)
    await db_session.commit()
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new_epoch = await lease.claim(s, eid, "recoverer", 30)
        report = await WorkerRunService.reconcile_for_recovery(s, runtime, eid, new_epoch)
    assert report.lost == [str(run.id)]
    assert (await _states(eid))[run.id] == "cleaned"


async def test_worker_without_a_row_is_still_reaped(db_session, runtime):
    eid, epoch = await _running_execution(db_session)
    ghost = WorkerRef(uuid.uuid4(), eid, epoch)
    await runtime.create_worker(
        CreateWorkerRequest(
            ref=ghost, task_id=uuid.uuid4(), attempt=0, kind=WorkerKind.AGENT,
            profile=Profile.AGENT_STANDARD, image_alias=ImageAlias.AGENT_BASE, repo_id="repo-one",
            base_ref=SHA, wall_timeout_s=60, job='{"fake": {"runtime_s": 100000}}',
        )
    )  # fmt: skip
    await runtime.start_worker(ghost)
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new_epoch = await lease.claim(s, eid, "recoverer", 30)
        report = await WorkerRunService.reconcile_for_recovery(s, runtime, eid, new_epoch)
    assert report.unknown_at_broker == [str(ghost.worker_run_id)]
    assert await runtime.list_workers(eid, new_epoch) == []


async def test_runtime_unavailable_blocks_recovery_fail_closed(db_session):
    fake = FakeWorkerRuntime()
    eid, epoch = await _running_execution(db_session)
    await _launch(db_session, fake, eid, epoch)
    fake.unavailable = True
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new_epoch = await lease.claim(s, eid, "recoverer", 30)
        with pytest.raises(WorkerReconcileError):
            await WorkerRunService.reconcile_for_recovery(s, fake, eid, new_epoch)


async def test_no_runtime_configured_with_open_rows_blocks_but_empty_is_fine(db_session):
    fake = FakeWorkerRuntime()
    eid, epoch = await _running_execution(db_session)
    async with AsyncSessionLocal() as s:
        assert (
            await WorkerRunService.reconcile_for_recovery(s, None, eid, epoch + 1)
        ).cleaned == []
    await _launch(db_session, fake, eid, epoch)
    async with AsyncSessionLocal() as s:
        with pytest.raises(WorkerReconcileError):
            await WorkerRunService.reconcile_for_recovery(s, None, eid, epoch + 1)


async def test_cleanup_failure_is_recorded_and_retry_succeeds(db_session):
    fake = FakeWorkerRuntime()
    eid, epoch = await _running_execution(db_session)
    run = await _launch(db_session, fake, eid, epoch)
    await WorkerRunService.start(db_session, fake, run, epoch)
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new_epoch = await lease.claim(s, eid, "recoverer", 30)
    fake.fail_next["cleanup_worker"] = RuntimeConflictError("disk busy")
    async with AsyncSessionLocal() as s:
        with pytest.raises(WorkerReconcileError):
            await WorkerRunService.reconcile_for_recovery(s, fake, eid, new_epoch)
    assert (await _states(eid))[run.id] == "cleanup_failed"
    async with AsyncSessionLocal() as s:  # retry
        report = await WorkerRunService.reconcile_for_recovery(s, fake, eid, new_epoch)
    assert report.cleaned == [str(run.id)]
    assert (await _states(eid))[run.id] == "cleaned"


# ---- integration with OrchestrationRunner.recover_execution ---------------------------------
async def test_recover_execution_reconciles_workers_before_anything_else(db_session):
    fake = FakeWorkerRuntime()
    eid, epoch = await _running_execution(db_session)
    run = await _launch(db_session, fake, eid, epoch)
    await WorkerRunService.start(db_session, fake, run, epoch)
    await _expire_lease(eid)

    async with AsyncSessionLocal() as s:
        await OrchestrationRunner.recover_execution(s, eid, worker_runtime=fake)
    events = await _events(eid)
    assert events.index("workers_reconciled") < events.index("pipeline_recovered")
    assert (await _states(eid))[run.id] == "cleaned"
    assert all(w.summary.state == WorkerState.CLEANED for w in fake.workers.values())


async def test_recover_execution_blocked_when_runtime_down_keeps_execution_recoverable(db_session):
    fake = FakeWorkerRuntime()
    eid, epoch = await _running_execution(db_session)
    await _launch(db_session, fake, eid, epoch)
    fake.unavailable = True
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        with pytest.raises(WorkerReconcileError):
            await OrchestrationRunner.recover_execution(s, eid, worker_runtime=fake)
    events = await _events(eid)
    assert "recovery_blocked" in events and "pipeline_recovered" not in events
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text("SELECT status, lease_owner FROM workflow_executions WHERE id=:e"), {"e": eid}
            )
        ).one()
    assert row[0] == "RUNNING" and row[1] is None  # lease released, still recoverable
    async with AsyncSessionLocal() as s:
        assert eid in await OrchestrationRunner.find_recoverable_executions(s)
    # Runtime returns: the very same recovery now succeeds.
    fake.unavailable = False
    async with AsyncSessionLocal() as s:
        await OrchestrationRunner.recover_execution(s, eid, worker_runtime=fake)
    assert "workers_reconciled" in await _events(eid)


async def test_advance_is_fenced_on_its_own(db_session):
    fake = FakeWorkerRuntime()
    eid, epoch = await _running_execution(db_session)
    run = await _launch(db_session, fake, eid, epoch)
    run_id = run.id
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        await lease.claim(s, eid, "recoverer", 30)
    with pytest.raises(lease.StaleWorkerError):
        await WorkerRunService._advance(db_session, run, epoch, WorkerRunState.RUNNING)
    await db_session.rollback()
    assert (await _states(eid))[run_id] == "created"


async def test_reconcile_explicitly_terminates_every_stale_worker(db_session):
    fake = FakeWorkerRuntime()
    eid, epoch = await _running_execution(db_session)
    await _launch(db_session, fake, eid, epoch)
    await _launch(db_session, fake, eid, epoch)
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new_epoch = await lease.claim(s, eid, "recoverer", 30)
        await WorkerRunService.reconcile_for_recovery(s, fake, eid, new_epoch)
    assert [op for op, _ in fake.calls].count("terminate_worker") == 2


async def test_workers_are_already_cleaned_when_reservations_are_expired(db_session, monkeypatch):
    """Ordering: reconcile BEFORE expire_orphaned_reservations, observed at the moment of expiry."""
    from app.services.budget_governor import BudgetGovernor

    fake = FakeWorkerRuntime()
    eid, epoch = await _running_execution(db_session)
    run = await _launch(db_session, fake, eid, epoch)
    await WorkerRunService.start(db_session, fake, run, epoch)
    await _expire_lease(eid)
    seen: dict = {}
    real = BudgetGovernor.expire_orphaned_reservations

    async def spy(db, execution_id, new_epoch):
        seen["rows"] = await _states(execution_id)
        seen["broker"] = [w.summary.state for w in fake.workers.values()]
        return await real(db, execution_id, new_epoch)

    monkeypatch.setattr(BudgetGovernor, "expire_orphaned_reservations", staticmethod(spy))
    async with AsyncSessionLocal() as s:
        await OrchestrationRunner.recover_execution(s, eid, worker_runtime=fake)
    assert set(seen["rows"].values()) == {"cleaned"}
    assert seen["broker"] == [WorkerState.CLEANED]


async def test_misconfigured_runtime_blocks_recovery_even_without_rows(db_session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "WORKER_RUNTIME", "broker")
    monkeypatch.setattr(settings, "BROKER_SOCKET_PATH", None)
    eid, _ = await _running_execution(db_session)
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        with pytest.raises(WorkerReconcileError):
            await OrchestrationRunner.recover_execution(s, eid)
