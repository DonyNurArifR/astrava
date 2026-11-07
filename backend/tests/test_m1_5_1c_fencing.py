"""M1.5-1c: atomic fencing, lease and terminal-state guarantees (in-process, PostgreSQL)."""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.budget import BudgetReservationStatus
from app.models.execution import ExecutionStatus, WorkflowExecution
from app.models.project import Project, StudioType
from app.models.task import Task
from app.models.workspace import Workspace
from app.orchestrator.runner import OrchestrationRunner
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services import execution_lease as lease
from app.services.budget_governor import (
    BudgetGovernor,
    FencingTokenMismatchError,
    ReservationNotFoundError,
)
from app.services.workflow_service import InvalidExecutionTransitionError, WorkflowService


async def _project(db) -> uuid.UUID:
    ws = Workspace(name="1C WS", slug=f"1c-ws-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    proj = Project(
        workspace_id=ws.id,
        name="1C Project",
        slug=f"1c-proj-{uuid.uuid4().hex[:8]}",
        studio_type=StudioType.SAAS,
        base_branch="main",
    )
    db.add(proj)
    await db.commit()
    return proj.id


async def _execution(project_id, status=ExecutionStatus.RUNNING, state=None) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        wf = await WorkflowService.create_workflow(
            db, WorkflowCreate(project_id=project_id, name="1C WF", studio_type="saas")
        )
        execution = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf.id, project_id=project_id)
        )
        await WorkflowService.update_execution_status(
            db, execution.id, status, state_data=state or {}
        )
        await db.commit()
        return execution.id


async def _expire_lease(execution_id) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE workflow_executions SET lease_expires_at = clock_timestamp() - interval '1 second' "
                "WHERE id = :i"
            ),
            {"i": execution_id},
        )
        await db.commit()


# ------------------------------------------------------------------ lease / epoch


@pytest.mark.asyncio
async def test_simultaneous_claims_have_exactly_one_winner(db_session):
    pid = await _project(db_session)
    eid = await _execution(pid)

    async def attempt(owner):
        async with AsyncSessionLocal() as s:
            try:
                return await lease.claim(s, eid, owner, 30)
            except lease.LeaseHeldError:
                return None

    results = await asyncio.gather(*[attempt(f"o{i}") for i in range(8)])
    winners = [r for r in results if r is not None]
    assert winners == [1]  # one claim, epoch 1; seven refused
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        assert row.run_epoch == 1


@pytest.mark.asyncio
async def test_claim_refused_while_lease_live_and_after_expiry_epoch_increments(db_session):
    pid = await _project(db_session)
    eid = await _execution(pid)
    async with AsyncSessionLocal() as s:
        assert await lease.claim(s, eid, "a", 30) == 1
    async with AsyncSessionLocal() as s:
        with pytest.raises(lease.LeaseHeldError):
            await lease.claim(s, eid, "b", 30)
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        assert await lease.claim(s, eid, "b", 30) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.WAITING_APPROVAL,
        ExecutionStatus.PAUSED,
    ],
)
async def test_claim_is_refused_for_non_running_status(db_session, status):
    pid = await _project(db_session)
    eid = await _execution(pid, status)
    async with AsyncSessionLocal() as s:
        with pytest.raises(lease.LeaseHeldError):
            await lease.claim(s, eid, "x", 30)


@pytest.mark.asyncio
async def test_stale_epoch_cannot_heartbeat_fence_a_write_or_release(db_session):
    pid = await _project(db_session)
    eid = await _execution(pid)
    async with AsyncSessionLocal() as s:
        old = await lease.claim(s, eid, "old", 30)
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        new = await lease.claim(s, eid, "new", 30)
    assert (old, new) == (1, 2)
    async with AsyncSessionLocal() as s:
        assert await lease.heartbeat(s, eid, "old", old, 30) is False
        assert await lease.heartbeat(s, eid, "new", new, 30) is True
    async with AsyncSessionLocal() as s:
        with pytest.raises(lease.StaleWorkerError):
            await lease.assert_epoch(s, eid, old)
        await s.rollback()
        await lease.assert_epoch(s, eid, new)  # current epoch passes
        await s.rollback()
    async with AsyncSessionLocal() as s:
        await lease.release(s, eid, "old", old)  # no-op: not the owner
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        assert row.lease_owner == "new"


@pytest.mark.asyncio
async def test_stale_worker_state_sync_is_rejected_and_writes_nothing(db_session):
    pid = await _project(db_session)
    eid = await _execution(pid)
    async with AsyncSessionLocal() as s:
        old = await lease.claim(s, eid, "old", 30)
    await _expire_lease(eid)
    async with AsyncSessionLocal() as s:
        await lease.claim(s, eid, "new", 30)

    state = {
        "tasks": [{"task_id": "t1", "title": "Stale Task", "status": "completed"}],
        "completed_task_ids": ["t1"],
        "status": "completed",
    }
    async with AsyncSessionLocal() as s:
        with pytest.raises(lease.StaleWorkerError):
            await OrchestrationRunner._sync_state_to_db(s, eid, pid, state, epoch=old)
        await s.rollback()
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        assert row.status == ExecutionStatus.RUNNING  # not COMPLETED
        tasks = (await s.execute(select(Task).where(Task.project_id == pid))).scalars().all()
        assert tasks == []


# ------------------------------------------------------------------ reservation fencing


async def _reserved(eid, pid, key="task:x:attempt:0", task_id="x"):
    async with AsyncSessionLocal() as s:
        await BudgetGovernor.initialize_budget(s, eid, pid)
        res = await BudgetGovernor.reserve(s, eid, key, task_id=task_id, timeout_seconds=300)
        await s.commit()
        return res.id, res.fence_token


@pytest.mark.asyncio
async def test_orphan_expiry_fences_out_the_old_token_and_is_idempotent(db_session):
    pid = await _project(db_session)
    eid = await _execution(pid)
    res_id, token = await _reserved(eid, pid)

    async with AsyncSessionLocal() as s:
        assert await BudgetGovernor.expire_orphaned_reservations(s, eid, recovered_by_epoch=2) == 1
        await s.commit()
    async with AsyncSessionLocal() as s:
        b = await BudgetGovernor.get_budget(s, eid)
        first = (b.active_reservations_count, b.total_agent_attempts, b.consumed_estimated_cost_usd)
        assert first[0] == 0 and first[1] == 1 and b.reserved_cost_usd == 0
    # old worker returns with its (previously valid) token: rejected atomically, nothing changes
    async with AsyncSessionLocal() as s:
        with pytest.raises(ReservationNotFoundError):
            await BudgetGovernor.reconcile(
                s, res_id, 10, 10, 5, fence_token=token, actual_cost_usd=0.5
            )
        await s.rollback()
    # a second recovery finds nothing left to expire: no double charge
    async with AsyncSessionLocal() as s:
        assert await BudgetGovernor.expire_orphaned_reservations(s, eid, recovered_by_epoch=3) == 0
        await s.commit()
    async with AsyncSessionLocal() as s:
        b = await BudgetGovernor.get_budget(s, eid)
        assert (
            b.active_reservations_count,
            b.total_agent_attempts,
            b.consumed_estimated_cost_usd,
        ) == first
        res = (
            await s.execute(
                text("SELECT status, metadata_json FROM budget_reservations WHERE id=:i"),
                {"i": res_id},
            )
        ).one()
        assert res[0] == BudgetReservationStatus.EXPIRED.name
        assert res[1]["recovery_expired"] is True and res[1]["recovered_by_epoch"] == 2


@pytest.mark.asyncio
async def test_wrong_fence_token_is_rejected_on_an_active_reservation(db_session):
    pid = await _project(db_session)
    eid = await _execution(pid)
    res_id, token = await _reserved(eid, pid)
    async with AsyncSessionLocal() as s:
        with pytest.raises(FencingTokenMismatchError):
            await BudgetGovernor.reconcile(s, res_id, 1, 1, 1, fence_token="not-the-token")
        await s.rollback()
    async with AsyncSessionLocal() as s:
        await BudgetGovernor.reconcile(s, res_id, 1, 1, 1, fence_token=token, actual_cost_usd=0.001)
        await s.commit()


@pytest.mark.asyncio
async def test_orphan_expiry_charges_actual_elapsed_runtime_not_the_full_timeout(db_session):
    pid = await _project(db_session)
    eid = await _execution(pid)
    await _reserved(eid, pid)  # timeout 300 s, created just now
    async with AsyncSessionLocal() as s:
        await BudgetGovernor.expire_orphaned_reservations(s, eid, 2)
        await s.commit()
    async with AsyncSessionLocal() as s:
        b = await BudgetGovernor.get_budget(s, eid)
        assert 0 <= b.consumed_runtime_ms < 60_000  # seconds elapsed, not 300_000
        assert b.consumed_input_tokens == 4000  # token/cost estimates still charged in full


# ------------------------------------------------------------------ terminal-state guard


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal", [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]
)
async def test_finished_execution_cannot_be_reopened_or_flipped(db_session, terminal):
    pid = await _project(db_session)
    eid = await _execution(pid, terminal)
    async with AsyncSessionLocal() as s:
        for target in (ExecutionStatus.RUNNING, ExecutionStatus.PAUSED, ExecutionStatus.COMPLETED):
            if target == terminal:
                continue
            with pytest.raises(InvalidExecutionTransitionError):
                await WorkflowService.update_execution_status(s, eid, target)
            await s.rollback()
        # same-status rewrite stays allowed (idempotent final sync)
        await WorkflowService.update_execution_status(s, eid, terminal, state_data={"k": 1})
        await s.commit()


@pytest.mark.asyncio
async def test_pause_and_resume_api_return_409_for_finished_execution(db_session, monkeypatch):
    pid = await _project(db_session)
    eid = await _execution(pid, ExecutionStatus.COMPLETED)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for verb in ("pause", "resume"):
            r = await c.post(f"/api/v1/executions/{eid}/{verb}")
            assert r.status_code == 409, (verb, r.text)


# ------------------------------------------------------------------ task identity


@pytest.mark.asyncio
async def test_same_titles_in_two_executions_never_share_task_rows(db_session):
    pid = await _project(db_session)
    e1, e2 = await _execution(pid), await _execution(pid)
    for eid in (e1, e2):
        state = {
            "tasks": [{"task_id": "t1", "title": "Same Title", "status": "pending"}],
            "completed_task_ids": [],
            "status": "running",
        }
        async with AsyncSessionLocal() as s:
            await OrchestrationRunner._sync_state_to_db(s, eid, pid, state, epoch=None)
    # complete only the first execution's task
    state1 = {
        "tasks": [
            {"task_id": "t1", "title": "Same Title", "status": "completed", "output_text": "x"}
        ],
        "completed_task_ids": ["t1"],
        "status": "running",
    }
    async with AsyncSessionLocal() as s:
        await OrchestrationRunner._sync_state_to_db(s, e1, pid, state1, epoch=None)
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Task).where(Task.project_id == pid))).scalars().all()
        by_exec = {r.input_data["execution_id"]: r for r in rows}
        assert len(rows) == 2 and set(by_exec) == {str(e1), str(e2)}
        assert by_exec[str(e1)].status.value == "completed"
        assert by_exec[str(e2)].status.value == "pending"  # untouched by e1's completion


# ------------------------------------------------------------------ recovery entry point


@pytest.mark.asyncio
async def test_recover_without_persisted_state_fails_closed_and_runs_no_provider(db_session):
    pid = await _project(db_session)
    eid = await _execution(pid, ExecutionStatus.RUNNING, state={})
    async with AsyncSessionLocal() as s:
        result = await OrchestrationRunner.recover_execution(s, eid)
        assert result.status == ExecutionStatus.FAILED
        assert "never persisted" in (result.error_message or "")


@pytest.mark.asyncio
async def test_recover_is_a_noop_for_non_running_executions(db_session):
    pid = await _project(db_session)
    for status in (
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.WAITING_APPROVAL,
    ):
        eid = await _execution(pid, status)
        async with AsyncSessionLocal() as s:
            result = await OrchestrationRunner.recover_execution(s, eid)
            assert result.status == status
            assert result.run_epoch == 0  # never claimed


@pytest.mark.asyncio
async def test_find_recoverable_executions_lists_only_orphaned_running(db_session):
    pid = await _project(db_session)
    orphan = await _execution(pid)  # RUNNING, no lease
    live = await _execution(pid)
    async with AsyncSessionLocal() as s:
        await lease.claim(s, live, "alive", 60)
    done = await _execution(pid, ExecutionStatus.COMPLETED)
    expired = await _execution(pid)
    async with AsyncSessionLocal() as s:
        await lease.claim(s, expired, "dead", 60)
    await _expire_lease(expired)
    async with AsyncSessionLocal() as s:
        found = set(await OrchestrationRunner.find_recoverable_executions(s))
    assert orphan in found and expired in found
    assert live not in found and done not in found


@pytest.mark.asyncio
async def test_resume_endpoint_only_unpauses_a_paused_execution(db_session):
    pid = await _project(db_session)
    waiting = await _execution(pid, ExecutionStatus.WAITING_APPROVAL)
    paused = await _execution(pid, ExecutionStatus.PAUSED)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/api/v1/executions/{waiting}/resume")
        assert r.status_code == 409  # cannot bypass the approval decision
        r = await c.post(f"/api/v1/executions/{paused}/resume")
        assert r.status_code == 200 and r.json()["status"] == "running"
