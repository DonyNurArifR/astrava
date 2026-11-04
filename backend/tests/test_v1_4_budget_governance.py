"""V1.4 M1.4-2: Execution budget governance against real PostgreSQL.

Covers the 20 requirements from Section 11 of M1.4-2:

Governor (BudgetGovernor, real DB via AsyncSessionLocal):
 1. Budget initialization is idempotent and applies defaults.
 2. Initial execution reservation creates an ACTIVE hold and updates reserved counters.
 3. Successful usage reconciliation settles the hold and charges consumption.
 4. Unused reservation release drops the hold without charging consumption.
 5. Budget exhaustion before dispatch raises BudgetExhaustedError.
 6. Ten concurrent reservations against capacity for three: exactly three succeed.
 7. Token usage accounting tracks input, output, and total tokens.
 8. Actual vs estimated cost is represented distinctly.
 9. Unknown provider cost (None) is charged at the estimate and marked estimated.
10. max_agent_attempts ceiling is enforced.
11. max_remediation_turns ceiling is enforced (budget exhausts, dispatch refused).
12. record_replan increments and blocks at max_replan_count.
13. Dispatch is blocked when projected duration exceeds max_runtime_seconds.
14. Budget and counters survive a simulated engine restart.
15. An expired ACTIVE reservation (crashed worker) is reclaimed with no orphaned hold.
16. A multi-task LangGraph wave consumes one shared execution budget.
17. Workflow halts at dispatch_task with budget_exhausted=True and status='failed'.
18. Subsequent dispatches on an exhausted execution are refused immediately.
19. Executions without a pre-existing budget initialize and run cleanly.
20. Operator increase_budget returns an EXHAUSTED execution to ACTIVE.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, update

from app.config import settings
from app.db.session import AsyncSessionLocal, async_engine
from app.models.budget import (
    BudgetReservation,
    BudgetReservationStatus,
    BudgetStatus,
    ExecutionBudget,
)
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.orchestrator.planner import PlannedTask, PlannerService, StructuredPlan
from app.orchestrator.workflow_graph import (
    build_orchestrator_graph,
    dispatch_task_node,
)
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.budget_governor import (
    BudgetExhaustedError,
    BudgetGovernor,
    BudgetLimitExceededError,
)
from app.services.workflow_service import WorkflowService

# ==============================================================================
# Helpers (each opens its own AsyncSessionLocal session, mirroring production)
# ==============================================================================


async def _seed_execution() -> tuple[uuid.UUID, uuid.UUID]:
    """Create workspace, project, workflow, and execution. Returns (project_id, execution_id)."""
    async with AsyncSessionLocal() as db:
        ws = Workspace(name="Budget WS", slug=f"ws-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        project = Project(
            name="Budget Project",
            slug=f"proj-{uuid.uuid4().hex[:8]}",
            workspace_id=ws.id,
            studio_type=StudioType.SAAS,
        )
        db.add(project)
        await db.commit()

        wf = await WorkflowService.create_workflow(
            db,
            WorkflowCreate(project_id=project.id, name="Budget WF", studio_type="saas"),
        )
        exec_row = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf.id, project_id=project.id)
        )
        await db.commit()
        return project.id, exec_row.id


async def _init_budget(
    project_id: uuid.UUID, execution_id: uuid.UUID, limits: dict | None = None
) -> None:
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id, limits)
        await db.commit()


async def _reserve(execution_id: uuid.UUID, key: str, **kwargs) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        reservation = await BudgetGovernor.reserve(db, execution_id, key, **kwargs)
        reservation_id = reservation.id
        await db.commit()
        return reservation_id


async def _reconcile(reservation_id: uuid.UUID, **kwargs) -> None:
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.reconcile(db, reservation_id, **kwargs)
        await db.commit()


async def _release(reservation_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.release(db, reservation_id)
        await db.commit()


async def _load_budget(execution_id: uuid.UUID) -> ExecutionBudget:
    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.get_budget(db, execution_id)
        assert budget is not None
        return budget


async def _load_reservations(execution_id: uuid.UUID) -> list[BudgetReservation]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BudgetReservation).where(BudgetReservation.execution_id == execution_id)
        )
        return list(result.scalars().all())


async def _count_budget_rows(execution_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExecutionBudget).where(ExecutionBudget.execution_id == execution_id)
        )
        return len(result.scalars().all())


def _plan(project_id: uuid.UUID, tasks: list[PlannedTask]) -> StructuredPlan:
    return StructuredPlan(
        project_id=str(project_id),
        objective="Budget governance integration objective",
        strategy_summary="test plan",
        tasks=tasks,
    )


def _usage(cost_usd: float | None = 0.01) -> dict:
    return {"input_tokens": 100, "output_tokens": 50, "duration_ms": 10, "cost_usd": cost_usd}


async def _noop_retrieve(state):  # replaces retrieval (no embeddings/network)
    return {}


async def _noop_ingest(state):  # replaces LLM knowledge extraction
    return {"ingestion_status": "skipped", "ingested_memory_ids": [], "ingestion_errors": []}


def _fake_verify_report():
    report = MagicMock()
    report.model_dump.return_value = {"passed": True}
    return report


async def _run_workflow(
    project_id: uuid.UUID,
    execution_id: uuid.UUID,
    tasks: list[PlannedTask],
    tmp_path,
    monkeypatch,
    cost_per_task: float | None = 0.01,
    cost_overrides: dict[str, float] | None = None,
) -> tuple[dict, list[str]]:
    """Run the real LangGraph workflow. Agent execution is faked; budget DB path is real."""
    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)
    dispatched: list[str] = []
    overrides = cost_overrides or {}

    async def fake_run_single_task(task, state, project_work_dir):
        dispatched.append(task["task_id"])
        cost = overrides.get(task["task_id"], cost_per_task)
        updated = {**task, "status": "completed", "output_text": "ok", "error_message": None}
        return updated, [_usage(cost)]

    initial_state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "objective": "Budget governance integration objective",
        "studio_type": "saas",
        "agent_snapshots": {},
        "tasks": [],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "current_task_index": 0,
        "is_paused": False,
        "status": "running",
        "verification_results": [],
        "artifacts": [],
        "usage_records": [],
        "retrieved_memories": [],
        "retrieved_artifacts": [],
        "retrieval_context": "",
        "knowledge_candidates": [],
        "ingested_memory_ids": [],
        "ingestion_errors": [],
    }

    with (
        patch(
            "app.orchestrator.workflow_graph.retrieve_knowledge_node",
            new=_noop_retrieve,
        ),
        patch(
            "app.orchestrator.workflow_graph.ingest_knowledge_node",
            new=_noop_ingest,
        ),
        patch(
            "app.orchestrator.workflow_graph.VerificationEngine.verify_task",
            new=AsyncMock(return_value=_fake_verify_report()),
        ),
        patch.object(
            PlannerService,
            "generate_plan",
            return_value=_plan(project_id, tasks),
        ),
        patch(
            "app.orchestrator.workflow_graph._run_single_task",
            new=fake_run_single_task,
        ),
    ):
        graph = build_orchestrator_graph()
        final_state = await graph.ainvoke(initial_state, {"recursion_limit": 50})
    return final_state, dispatched


# ==============================================================================
# Governor unit-level integration tests
# ==============================================================================


@pytest.mark.asyncio
async def test_budget_initialization(db_session):
    project_id, execution_id = await _seed_execution()

    async with AsyncSessionLocal() as db:
        first = await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        await db.commit()
        first_id = first.id
    async with AsyncSessionLocal() as db:
        # Second call with different limits must return the existing row unchanged.
        second = await BudgetGovernor.initialize_budget(
            db, execution_id, project_id, {"max_cost_usd": 99.0}
        )
        await db.commit()

    assert second.id == first_id
    assert await _count_budget_rows(execution_id) == 1

    budget = await _load_budget(execution_id)
    assert budget.status == BudgetStatus.ACTIVE
    assert budget.max_cost_usd == pytest.approx(1.0)
    assert budget.max_input_tokens == 250_000
    assert budget.max_output_tokens == 50_000
    assert budget.max_remediation_turns == 5
    assert budget.max_replan_count == 2
    assert budget.max_runtime_seconds == 600
    assert budget.consumed_total_tokens == 0
    assert budget.reserved_cost_usd == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_initial_execution_reservation(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id)

    reservation_id = await _reserve(
        execution_id,
        "task:initial",
        task_id="task-initial",
        estimated_input_tokens=4000,
        estimated_output_tokens=2000,
        estimated_cost_usd=0.02,
    )

    budget = await _load_budget(execution_id)
    assert budget.active_reservations_count == 1
    assert budget.reserved_input_tokens == 4000
    assert budget.reserved_output_tokens == 2000
    assert budget.reserved_cost_usd == pytest.approx(0.02)
    assert budget.consumed_total_tokens == 0

    reservations = await _load_reservations(execution_id)
    assert len(reservations) == 1
    assert reservations[0].id == reservation_id
    assert reservations[0].status == BudgetReservationStatus.ACTIVE
    assert reservations[0].expires_at is not None


@pytest.mark.asyncio
async def test_successful_usage_reconciliation(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id)
    reservation_id = await _reserve(
        execution_id, "task:ok", estimated_cost_usd=0.05, estimated_input_tokens=5000
    )

    await _reconcile(
        reservation_id,
        actual_input_tokens=3000,
        actual_output_tokens=1500,
        duration_ms=800,
        actual_cost_usd=0.02,
    )

    budget = await _load_budget(execution_id)
    # Hold released...
    assert budget.active_reservations_count == 0
    assert budget.reserved_input_tokens == 0
    assert budget.reserved_output_tokens == 0
    assert budget.reserved_cost_usd == pytest.approx(0.0)
    # ...and actual usage charged.
    assert budget.consumed_input_tokens == 3000
    assert budget.consumed_output_tokens == 1500
    assert budget.consumed_actual_cost_usd == pytest.approx(0.02)
    assert budget.consumed_runtime_ms == 800
    assert budget.total_agent_attempts == 1

    [reservation] = await _load_reservations(execution_id)
    assert reservation.status == BudgetReservationStatus.RECONCILED
    assert reservation.reconciled_cost_usd == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_unused_reservation_release(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id)
    reservation_id = await _reserve(execution_id, "task:unused", estimated_cost_usd=0.03)

    await _release(reservation_id)

    budget = await _load_budget(execution_id)
    assert budget.active_reservations_count == 0
    assert budget.reserved_cost_usd == pytest.approx(0.0)
    assert budget.reserved_input_tokens == 0
    # Nothing was consumed: a released hold is not charged.
    assert budget.consumed_actual_cost_usd == pytest.approx(0.0)
    assert budget.consumed_estimated_cost_usd == pytest.approx(0.0)
    assert budget.consumed_total_tokens == 0
    assert budget.total_agent_attempts == 0

    [reservation] = await _load_reservations(execution_id)
    assert reservation.status == BudgetReservationStatus.RELEASED


@pytest.mark.asyncio
async def test_budget_exhaustion_before_dispatch(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id, {"max_cost_usd": 0.05})

    first = await _reserve(execution_id, "task:spend", estimated_cost_usd=0.01)
    await _reconcile(
        first,
        actual_input_tokens=100,
        actual_output_tokens=50,
        duration_ms=10,
        actual_cost_usd=0.05,
    )
    assert (await _load_budget(execution_id)).status == BudgetStatus.EXHAUSTED

    async with AsyncSessionLocal() as db:
        with pytest.raises(BudgetExhaustedError) as excinfo:
            await BudgetGovernor.reserve(db, execution_id, "task:refused")
        await db.rollback()
    assert type(excinfo.value) is BudgetExhaustedError

    # The refused reservation must not have left a hold behind.
    budget = await _load_budget(execution_id)
    assert budget.active_reservations_count == 0
    assert len(await _load_reservations(execution_id)) == 1


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_over_reserve(db_session):
    project_id, execution_id = await _seed_execution()
    # Each reservation estimates $0.01; capacity $0.035 fits exactly three.
    await _init_budget(project_id, execution_id, {"max_cost_usd": 0.035})

    async def attempt(i: int) -> uuid.UUID:
        async with AsyncSessionLocal() as db:
            reservation = await BudgetGovernor.reserve(
                db, execution_id, f"concurrent:{i}", estimated_cost_usd=0.01
            )
            reservation_id = reservation.id
            await db.commit()
            return reservation_id

    results = await asyncio.gather(*(attempt(i) for i in range(10)), return_exceptions=True)

    successes = [r for r in results if isinstance(r, uuid.UUID)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 3
    assert len(failures) == 7
    assert all(type(f) is BudgetLimitExceededError for f in failures)

    budget = await _load_budget(execution_id)
    assert budget.active_reservations_count == 3
    assert budget.reserved_cost_usd == pytest.approx(0.03)
    assert len(await _load_reservations(execution_id)) == 3


@pytest.mark.asyncio
async def test_token_usage_accounting(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id)

    first = await _reserve(execution_id, "tokens:1", estimated_input_tokens=4000)
    second = await _reserve(execution_id, "tokens:2", estimated_input_tokens=4000)
    await _reconcile(first, actual_input_tokens=1200, actual_output_tokens=340, duration_ms=5)
    await _reconcile(second, actual_input_tokens=800, actual_output_tokens=60, duration_ms=5)

    budget = await _load_budget(execution_id)
    assert budget.consumed_input_tokens == 2000
    assert budget.consumed_output_tokens == 400
    assert budget.consumed_total_tokens == 2400
    assert budget.reserved_input_tokens == 0
    assert budget.reserved_output_tokens == 0


@pytest.mark.asyncio
async def test_actual_vs_estimated_cost_representation(db_session):
    # Actual cost (provider-reported, exact).
    project_a, exec_a = await _seed_execution()
    await _init_budget(project_a, exec_a)
    res_a = await _reserve(exec_a, "cost:actual", estimated_cost_usd=0.01)
    await _reconcile(
        res_a,
        actual_input_tokens=10,
        actual_output_tokens=10,
        duration_ms=1,
        actual_cost_usd=0.25,
    )
    budget_a = await _load_budget(exec_a)
    assert budget_a.consumed_actual_cost_usd == pytest.approx(0.25)
    assert budget_a.consumed_estimated_cost_usd == pytest.approx(0.0)
    assert budget_a.is_cost_estimated is False

    # Provider-reported cost that is itself an estimate.
    project_b, exec_b = await _seed_execution()
    await _init_budget(project_b, exec_b)
    res_b = await _reserve(exec_b, "cost:estimate", estimated_cost_usd=0.01)
    await _reconcile(
        res_b,
        actual_input_tokens=10,
        actual_output_tokens=10,
        duration_ms=1,
        actual_cost_usd=0.25,
        is_cost_estimated=True,
    )
    budget_b = await _load_budget(exec_b)
    assert budget_b.consumed_actual_cost_usd == pytest.approx(0.0)
    assert budget_b.consumed_estimated_cost_usd == pytest.approx(0.25)
    assert budget_b.is_cost_estimated is True


@pytest.mark.asyncio
async def test_unknown_provider_usage_representation(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id)
    reservation_id = await _reserve(execution_id, "cost:unknown", estimated_cost_usd=0.04)

    # Provider returned no cost (None): charge the reserved estimate and mark it estimated.
    await _reconcile(
        reservation_id,
        actual_input_tokens=100,
        actual_output_tokens=50,
        duration_ms=20,
        actual_cost_usd=None,
    )

    budget = await _load_budget(execution_id)
    assert budget.consumed_estimated_cost_usd == pytest.approx(0.04)
    assert budget.consumed_actual_cost_usd == pytest.approx(0.0)
    assert budget.is_cost_estimated is True

    [reservation] = await _load_reservations(execution_id)
    assert reservation.reconciled_cost_usd == pytest.approx(0.04)
    assert reservation.status == BudgetReservationStatus.RECONCILED


@pytest.mark.asyncio
async def test_maximum_agent_attempt_enforcement(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id, {"max_agent_attempts": 2})

    first = await _reserve(execution_id, "attempt:1")
    await _reserve(execution_id, "attempt:2")

    async with AsyncSessionLocal() as db:
        with pytest.raises(BudgetLimitExceededError, match="agent_attempts"):
            await BudgetGovernor.reserve(db, execution_id, "attempt:3")
        await db.rollback()

    # Settling one attempt still counts it toward the ceiling; a third is refused.
    await _reconcile(first, actual_input_tokens=1, actual_output_tokens=1, duration_ms=1)
    async with AsyncSessionLocal() as db:
        with pytest.raises(BudgetLimitExceededError, match="agent_attempts"):
            await BudgetGovernor.reserve(db, execution_id, "attempt:4")
        await db.rollback()

    budget = await _load_budget(execution_id)
    assert budget.total_agent_attempts == 1
    assert budget.active_reservations_count == 1


@pytest.mark.asyncio
async def test_maximum_remediation_turn_enforcement(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id, {"max_remediation_turns": 2})

    first = await _reserve(execution_id, "remediate:1")
    await _reconcile(
        first,
        actual_input_tokens=1,
        actual_output_tokens=1,
        duration_ms=1,
        is_remediation=True,
    )
    assert (await _load_budget(execution_id)).status == BudgetStatus.ACTIVE

    second = await _reserve(execution_id, "remediate:2")
    await _reconcile(
        second,
        actual_input_tokens=1,
        actual_output_tokens=1,
        duration_ms=1,
        is_remediation=True,
    )

    budget = await _load_budget(execution_id)
    assert budget.remediation_turns_count == 2
    assert budget.status == BudgetStatus.EXHAUSTED
    assert budget.exhaustion_reason == "budget_exhausted"

    async with AsyncSessionLocal() as db:
        with pytest.raises(BudgetExhaustedError):
            await BudgetGovernor.reserve(db, execution_id, "remediate:3")
        await db.rollback()


@pytest.mark.asyncio
async def test_maximum_replan_enforcement(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id, {"max_replan_count": 2})

    async with AsyncSessionLocal() as db:
        await BudgetGovernor.record_replan(db, execution_id)
        await db.commit()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.record_replan(db, execution_id)
        await db.commit()
    assert (await _load_budget(execution_id)).replan_count == 2

    async with AsyncSessionLocal() as db:
        with pytest.raises(BudgetLimitExceededError, match="Replan limit reached"):
            await BudgetGovernor.record_replan(db, execution_id)
        await db.rollback()

    assert (await _load_budget(execution_id)).replan_count == 2


@pytest.mark.asyncio
async def test_runtime_limit_enforcement(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id, {"max_runtime_seconds": 100})

    async with AsyncSessionLocal() as db:
        with pytest.raises(BudgetLimitExceededError, match="runtime_seconds"):
            # Projected attempt (120s) alone exceeds the 100s wall-time ceiling.
            await BudgetGovernor.reserve(db, execution_id, "runtime:long", timeout_seconds=120)
        await db.rollback()

    # A dispatch that fits is still allowed.
    await _reserve(execution_id, "runtime:short", timeout_seconds=60)
    assert (await _load_budget(execution_id)).active_reservations_count == 1


@pytest.mark.asyncio
async def test_resume_after_process_restart(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id)
    settled = await _reserve(execution_id, "restart:settled", estimated_cost_usd=0.02)
    await _reconcile(
        settled,
        actual_input_tokens=700,
        actual_output_tokens=300,
        duration_ms=50,
        actual_cost_usd=0.02,
    )
    await _reserve(execution_id, "restart:inflight", estimated_cost_usd=0.03)
    before = await _load_budget(execution_id)

    # Simulate process restart: drop every pooled connection and identity state.
    await async_engine.dispose()

    async with AsyncSessionLocal() as db:
        summary = await BudgetGovernor.get_summary(db, execution_id)

    assert summary["consumed"]["input_tokens"] == before.consumed_input_tokens == 700
    assert summary["consumed"]["output_tokens"] == before.consumed_output_tokens == 300
    assert summary["consumed"]["actual_cost_usd"] == pytest.approx(0.02)
    assert summary["reserved"]["active_reservations"] == 1
    assert summary["reserved"]["cost_usd"] == pytest.approx(0.03)
    assert summary["status"] == BudgetStatus.ACTIVE.value

    # Reloaded budget keeps enforcing: the in-flight hold can still be settled after restart.
    [inflight] = [
        r
        for r in await _load_reservations(execution_id)
        if r.status == BudgetReservationStatus.ACTIVE
    ]
    await _reconcile(
        inflight.id,
        actual_input_tokens=10,
        actual_output_tokens=10,
        duration_ms=5,
        actual_cost_usd=0.01,
    )
    after = await _load_budget(execution_id)
    assert after.active_reservations_count == 0
    assert after.consumed_actual_cost_usd == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_recovery_from_crash_after_reservation(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id)
    crashed = await _reserve(
        execution_id, "crash:worker", estimated_cost_usd=0.01, timeout_seconds=60
    )

    # The worker died; its hold's deadline is now in the past.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(BudgetReservation)
            .where(BudgetReservation.id == crashed)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await db.commit()

    # Next dispatch reclaims the stale hold before reserving.
    await _reserve(execution_id, "crash:recovery", estimated_cost_usd=0.02)

    budget = await _load_budget(execution_id)
    reservations = await _load_reservations(execution_id)
    by_id = {r.id: r for r in reservations}

    assert by_id[crashed].status == BudgetReservationStatus.EXPIRED
    assert by_id[crashed].resolved_at is not None
    # Expired estimate is charged (a stalled worker cannot free budget by timing out).
    assert budget.consumed_estimated_cost_usd == pytest.approx(0.01)
    assert budget.is_cost_estimated is True

    # No orphaned holds: only the new reservation remains ACTIVE, and counters agree.
    active = [r for r in reservations if r.status == BudgetReservationStatus.ACTIVE]
    assert len(active) == 1
    assert budget.active_reservations_count == 1
    assert budget.reserved_cost_usd == pytest.approx(0.02)

    async with AsyncSessionLocal() as db:
        assert await BudgetGovernor.reclaim_expired_reservations(db, budget.id) == 0
        await db.commit()


# ==============================================================================
# LangGraph workflow integration tests
# ==============================================================================


@pytest.mark.asyncio
async def test_parallel_workflow_waves_share_one_budget(tmp_path, monkeypatch, db_session):
    project_id, execution_id = await _seed_execution()
    tasks = [
        PlannedTask(task_id=f"wave-{i}", title=f"Wave {i}", description="parallel work")
        for i in range(3)
    ]

    final_state, dispatched = await _run_workflow(
        project_id, execution_id, tasks, tmp_path, monkeypatch, cost_per_task=0.01
    )

    assert final_state["status"] == "completed"
    assert sorted(dispatched) == ["wave-0", "wave-1", "wave-2"]

    # One shared budget row for the whole execution.
    assert await _count_budget_rows(execution_id) == 1
    budget = await _load_budget(execution_id)
    assert budget.total_agent_attempts == 3
    assert budget.consumed_input_tokens == 300
    assert budget.consumed_output_tokens == 150
    assert budget.consumed_total_tokens == 450
    assert budget.consumed_actual_cost_usd == pytest.approx(0.03)
    assert budget.reserved_cost_usd == pytest.approx(0.0)
    assert budget.active_reservations_count == 0

    reservations = await _load_reservations(execution_id)
    assert len(reservations) == 3
    assert all(r.status == BudgetReservationStatus.RECONCILED for r in reservations)


@pytest.mark.asyncio
async def test_budget_exhaustion_during_workflow(tmp_path, monkeypatch, db_session):
    project_id, execution_id = await _seed_execution()
    # Wave 1 spends the entire $1.00 default budget; wave 2 must never run.
    tasks = [
        PlannedTask(task_id="spend-a", title="Spend", description="expensive"),
        PlannedTask(
            task_id="spend-b",
            title="Blocked",
            description="depends on spend",
            dependencies=["spend-a"],
        ),
    ]

    final_state, dispatched = await _run_workflow(
        project_id,
        execution_id,
        tasks,
        tmp_path,
        monkeypatch,
        cost_overrides={"spend-a": 1.0},
    )

    assert final_state["budget_exhausted"] is True
    assert final_state["status"] == "failed"
    assert "Budget exhausted" in final_state["error"]
    assert dispatched == ["spend-a"]
    assert (await _load_budget(execution_id)).status == BudgetStatus.EXHAUSTED


@pytest.mark.asyncio
async def test_no_dispatch_after_exhaustion(tmp_path, monkeypatch, db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id, {"max_cost_usd": 0.05})
    spent = await _reserve(execution_id, "exhaust:seed", estimated_cost_usd=0.01)
    await _reconcile(
        spent, actual_input_tokens=1, actual_output_tokens=1, duration_ms=1, actual_cost_usd=0.05
    )
    reservations_before = len(await _load_reservations(execution_id))

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)
    run_calls: list[str] = []

    async def must_not_run(task, state, project_work_dir):
        run_calls.append(task["task_id"])
        raise AssertionError("agent execution must not start on an exhausted budget")

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [{"task_id": "late", "title": "Late", "assigned_agent_slug": "developer"}],
        "current_ready_task_ids": ["late"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }
    with patch(
        "app.orchestrator.workflow_graph._run_single_task",
        new=must_not_run,
    ):
        # Repeated dispatch attempts are each refused without touching the agent or the DB.
        for _ in range(2):
            result = await dispatch_task_node(state)
            assert result["budget_exhausted"] is True
            assert result["status"] == "failed"

    assert run_calls == []
    assert len(await _load_reservations(execution_id)) == reservations_before


@pytest.mark.asyncio
async def test_existing_execution_compatibility(tmp_path, monkeypatch, db_session):
    # Execution created before budget governance existed: no ExecutionBudget row.
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        assert await BudgetGovernor.get_budget(db, execution_id) is None

    tasks = [PlannedTask(task_id="legacy-1", title="Legacy", description="old execution")]
    final_state, dispatched = await _run_workflow(
        project_id, execution_id, tasks, tmp_path, monkeypatch
    )

    assert final_state["status"] == "completed"
    assert dispatched == ["legacy-1"]
    budget = await _load_budget(execution_id)
    assert budget.status == BudgetStatus.ACTIVE
    assert budget.max_cost_usd == pytest.approx(1.0)
    assert budget.total_agent_attempts == 1


@pytest.mark.asyncio
async def test_budget_increase_and_resumption(db_session):
    project_id, execution_id = await _seed_execution()
    await _init_budget(project_id, execution_id, {"max_cost_usd": 0.05})
    spent = await _reserve(execution_id, "resume:spend", estimated_cost_usd=0.01)
    await _reconcile(
        spent, actual_input_tokens=1, actual_output_tokens=1, duration_ms=1, actual_cost_usd=0.05
    )
    assert (await _load_budget(execution_id)).status == BudgetStatus.EXHAUSTED

    # Operator raises the ceiling.
    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.increase_budget(db, execution_id, {"max_cost_usd": 5.0})
        await db.commit()
        assert budget.status == BudgetStatus.ACTIVE
        assert budget.exhaustion_reason is None

    # Work resumes under the new limit.
    resumed = await _reserve(execution_id, "resume:after", estimated_cost_usd=0.01)
    budget = await _load_budget(execution_id)
    assert budget.status == BudgetStatus.ACTIVE
    assert budget.max_cost_usd == pytest.approx(5.0)
    assert budget.active_reservations_count == 1
    assert resumed is not None
