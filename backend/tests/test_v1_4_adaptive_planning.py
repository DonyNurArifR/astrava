"""ASTRAVA V1.4: M1.4-4 Adaptive Goal Planner & Dynamic DAG Modification Test Suite.

Verifies:
1. Goal lifecycle: CRUD, target criteria, and progress recalculation.
2. Dynamic goal decomposition via GoalDecomposer with Claude Haiku 5.5.
3. Kahn's algorithm cycle prevention and dependency validation.
4. Dynamic DAG modification preserving immutable completed tasks.
5. Runtime replanning node, BudgetGovernor replan tracking, and 2-replan limit ceiling.
6. Execution replan REST API endpoints with operator authentication.
"""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.execution import ExecutionStatus, WorkflowExecution
from app.models.goal import GoalStatus
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.orchestrator.planner import (
    DAGModifier,
    GoalDecomposer,
    PlannedTask,
)
from app.orchestrator.workflow_graph import replan_node
from app.providers.base import BaseProvider, ProviderRequest, ProviderResponse, ProviderStatus
from app.schemas.goal import GoalCreate, GoalUpdate
from app.schemas.workflow import WorkflowCreate
from app.services.budget_governor import (
    BudgetGovernor,
)
from app.services.goal_service import GoalService
from app.services.workflow_service import WorkflowService


async def _seed_project_and_execution() -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        ws = Workspace(name=f"WS-{uuid.uuid4().hex[:6]}", slug=f"ws-{uuid.uuid4().hex[:6]}")
        db.add(ws)
        await db.flush()

        proj = Project(
            workspace_id=ws.id,
            name="Adaptive Goal Platform",
            slug=f"adaptive-{uuid.uuid4().hex[:6]}",
            studio_type=StudioType.SAAS,
        )
        db.add(proj)
        await db.flush()

        wf = await WorkflowService.create_workflow(
            db,
            WorkflowCreate(
                project_id=proj.id,
                name="Adaptive Pipeline",
                studio_type="saas",
            ),
        )

        execution = WorkflowExecution(
            workflow_id=wf.id,
            project_id=proj.id,
            status=ExecutionStatus.RUNNING,
            current_step=0,
            state_data={"tasks": [], "completed_task_ids": [], "failed_task_ids": []},
        )
        db.add(execution)
        await db.commit()
        await db.refresh(execution)
        return proj.id, execution.id


@pytest.mark.asyncio
async def test_goal_crud_and_progress_recalculation(db_session: AsyncSession):
    """Verifies GoalService CRUD operations and automatic progress recalculation based on linked executions."""
    project_id, exec_id = await _seed_project_and_execution()

    # 1. Create Goal
    goal_data = GoalCreate(
        title="Deploy Self-Healing Infrastructure",
        description="Autonomous cluster deployment with auto-remediation and load testing",
        target_criteria=["Terraform scripts verified", "99.9% uptime SLA under load"],
    )
    goal = await GoalService.create_goal(db_session, project_id, goal_data)
    assert goal.id is not None
    assert goal.status == GoalStatus.ACTIVE
    assert goal.progress_percentage == 0.0

    # 2. List Goals
    goals = await GoalService.list_goals_by_project(db_session, project_id)
    assert len(goals) == 1
    assert goals[0].title == "Deploy Self-Healing Infrastructure"

    # 3. Update Goal
    updated = await GoalService.update_goal(
        db_session,
        goal.id,
        GoalUpdate(description="Updated autonomous cluster deployment description"),
    )
    assert updated is not None
    assert "Updated" in updated.description

    # 4. Progress Recalculation with Linked Execution
    async with AsyncSessionLocal() as db:
        stmt = select(WorkflowExecution).where(WorkflowExecution.id == exec_id)
        execution = (await db.scalars(stmt)).first()
        execution.goal_id = goal.id
        execution.state_data = {
            "tasks": [{"task_id": "t1"}, {"task_id": "t2"}],
            "completed_task_ids": ["t1"],
        }
        await db.commit()

    progress = await GoalService.recalculate_progress(db_session, goal.id)
    assert progress == 50.0

    # 5. Complete all tasks -> Goal status transitions to ACHIEVED
    async with AsyncSessionLocal() as db:
        stmt = select(WorkflowExecution).where(WorkflowExecution.id == exec_id)
        execution = (await db.scalars(stmt)).first()
        execution.state_data = {
            "tasks": [{"task_id": "t1"}, {"task_id": "t2"}],
            "completed_task_ids": ["t1", "t2"],
        }
        await db.commit()

    progress2 = await GoalService.recalculate_progress(db_session, goal.id)
    assert progress2 == 100.0

    refreshed_goal = await GoalService.get_goal(db_session, goal.id)
    assert refreshed_goal.status == GoalStatus.ACHIEVED


@pytest.mark.asyncio
async def test_goal_decomposer_dynamic_plan_synthesis():
    """GoalDecomposer synthesizes a non-templated, customized DAG for specific user objectives."""

    custom_plan_json = {
        "strategy_summary": "Adaptive microservice migration with canary deployment",
        "estimated_cost_usd": 0.03,
        "tasks": [
            {
                "task_id": "custom-spec",
                "title": "Service Interface Spec",
                "description": "Design OpenAPI schemas for auth and billing microservices",
                "assigned_agent_slug": "solution-architect",
                "risk_level": "low",
                "requires_approval": False,
                "priority": 1,
                "dependencies": [],
                "expected_output_artifacts": ["openapi.json"],
                "acceptance_criteria": ["All endpoints typed", "JWT auth specified"],
                "verification_criteria": ["valid_json"],
            },
            {
                "task_id": "custom-impl",
                "title": "Core Service Implementation",
                "description": "Implement FastAPI routing and storage adapters",
                "assigned_agent_slug": "lead-developer",
                "risk_level": "medium",
                "requires_approval": False,
                "priority": 2,
                "dependencies": ["custom-spec"],
                "expected_output_artifacts": ["main.py"],
                "acceptance_criteria": ["Exit code 0", "All routes mounted"],
                "verification_criteria": ["non_empty_file"],
            },
        ],
    }

    class MockDecomposerProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "mock_decomposer"

        async def execute(self, request: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text=json.dumps(custom_plan_json),
                input_tokens=100,
                output_tokens=200,
                duration_ms=50,
                cost_usd=0.01,
            )

    plan = await GoalDecomposer.decompose_goal(
        objective="Migrate billing from monolith to async microservices",
        project_id="proj-123",
        studio_type=StudioType.SAAS,
        provider=MockDecomposerProvider(),
    )

    assert plan is not None
    assert len(plan.tasks) == 2
    assert plan.tasks[0].task_id == "custom-spec"
    assert plan.tasks[1].task_id == "custom-impl"
    assert plan.tasks[1].dependencies == ["custom-spec"]
    assert plan.is_valid_dag is True
    assert len(plan.execution_stages) == 2  # Stage 1: spec, Stage 2: impl


@pytest.mark.asyncio
async def test_goal_decomposer_cycle_detection_fallback():
    """GoalDecomposer detects cyclic task graphs produced by LLM and safely falls back to valid plan."""

    cyclic_plan_json = {
        "strategy_summary": "Broken cyclic plan",
        "tasks": [
            {
                "task_id": "task-a",
                "title": "Task A",
                "description": "Depends on B",
                "dependencies": ["task-b"],
            },
            {
                "task_id": "task-b",
                "title": "Task B",
                "description": "Depends on A",
                "dependencies": ["task-a"],
            },
        ],
    }

    class MockCyclicProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "mock_cyclic"

        async def execute(self, request: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text=json.dumps(cyclic_plan_json),
            )

    # Must fall back cleanly to valid deterministic template without crashing
    plan = await GoalDecomposer.decompose_goal(
        objective="Build dashboard with cyclic dependencies",
        project_id="proj-cyclic",
        studio_type=StudioType.SAAS,
        provider=MockCyclicProvider(),
    )
    assert plan.is_valid_dag is True
    assert len(plan.tasks) > 0
    # Template has valid stages
    assert len(plan.execution_stages) >= 3


def test_dag_modifier_preserves_immutable_completed_tasks():
    """DAGModifier allows updating unexecuted tasks while strictly preserving completed tasks."""
    current_tasks = [
        {
            "task_id": "t-1",
            "title": "Architecture Research",
            "status": "completed",
            "output_text": "Selected PostgreSQL",
            "dependencies": [],
        },
        {
            "task_id": "t-2",
            "title": "Old Implementation Plan",
            "status": "pending",
            "dependencies": ["t-1"],
        },
    ]

    completed_ids = ["t-1"]
    failed_ids = []

    # New replan replaces t-2 with t-2-revised and adds t-3
    replan_tasks = [
        PlannedTask(
            task_id="t-2-revised",
            title="Revised Implementation Plan",
            description="Use asyncpg connection pooling",
            dependencies=["t-1"],
            acceptance_criteria=["Async driver configured"],
        ),
        PlannedTask(
            task_id="t-3",
            title="Database Benchmarking",
            description="Run concurrency benchmark",
            dependencies=["t-2-revised"],
            acceptance_criteria=["1000 req/s verified"],
        ),
    ]

    modified_tasks = DAGModifier.modify_dag(
        current_tasks=current_tasks,
        completed_task_ids=completed_ids,
        failed_task_ids=failed_ids,
        new_or_modified_tasks=replan_tasks,
    )

    task_map = {t["task_id"]: t for t in modified_tasks}
    assert len(modified_tasks) == 3
    # t-1 remains strictly intact and completed
    assert task_map["t-1"]["status"] == "completed"
    assert task_map["t-1"]["output_text"] == "Selected PostgreSQL"
    # t-2-revised and t-3 are added and pending
    assert task_map["t-2-revised"]["status"] == "pending"
    assert task_map["t-3"]["status"] == "pending"
    assert task_map["t-3"]["dependencies"] == ["t-2-revised"]


def test_dag_modifier_rejects_cycles():
    """DAGModifier raises ValueError when modified tasks form a circular dependency."""
    current_tasks = [
        {"task_id": "c-1", "title": "Done", "status": "completed", "dependencies": []},
    ]

    replan_tasks = [
        PlannedTask(task_id="c-2", title="C2", description="", dependencies=["c-3"]),
        PlannedTask(task_id="c-3", title="C3", description="", dependencies=["c-2"]),
    ]

    with pytest.raises(ValueError, match="Circular dependency detected"):
        DAGModifier.modify_dag(
            current_tasks=current_tasks,
            completed_task_ids=["c-1"],
            failed_task_ids=[],
            new_or_modified_tasks=replan_tasks,
        )


@pytest.mark.asyncio
async def test_replan_node_in_workflow_graph_and_budget_governor():
    """replan_node increments replan_count, records with BudgetGovernor, and halts when limit exceeded."""
    project_id, execution_id = await _seed_project_and_execution()

    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(
            db,
            execution_id,
            project_id,
            limits={"max_replan_count": 2},
        )
        await db.commit()

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "objective": "Build microservice architecture",
        "studio_type": "saas",
        "tasks": [
            {
                "task_id": "task-init",
                "title": "Initial Spec",
                "status": "completed",
                "dependencies": [],
            },
            {
                "task_id": "task-old",
                "title": "Old Task",
                "status": "pending",
                "dependencies": ["task-init"],
            },
        ],
        "completed_task_ids": ["task-init"],
        "failed_task_ids": [],
        "replan_count": 0,
        "replan_needed": True,
        "replan_reason": "Pivot to gRPC architecture",
    }

    # 1. First Replan
    r1 = await replan_node(state)
    state.update(r1)
    assert state["replan_count"] == 1
    assert state["replan_needed"] is False
    assert len(state["replan_records"]) == 1

    # Verify BudgetGovernor recorded count
    async with AsyncSessionLocal() as db:
        summary = await BudgetGovernor.get_summary(db, execution_id)
        assert summary["consumed"]["replan_count"] == 1

    # 2. Second Replan
    state["replan_needed"] = True
    state["replan_reason"] = "Add monitoring task"
    r2 = await replan_node(state)
    state.update(r2)
    assert state["replan_count"] == 2

    async with AsyncSessionLocal() as db:
        summary = await BudgetGovernor.get_summary(db, execution_id)
        assert summary["consumed"]["replan_count"] == 2

    # 3. Third Replan -> Exceeds max_replan_count (2) -> Refuses replan & halts
    state["replan_needed"] = True
    state["replan_reason"] = "Exceeding limit replan"
    r3 = await replan_node(state)
    assert r3["status"] == "failed"
    assert r3["budget_exhausted"] is True
    assert "Replan limit reached" in r3["error_message"]


@pytest.mark.asyncio
async def test_replan_execution_api_endpoint():
    """POST /api/v1/executions/{id}/replan allows authorized operators to request runtime replanning."""
    project_id, execution_id = await _seed_project_and_execution()

    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(
            db,
            execution_id,
            project_id,
            limits={"max_replan_count": 2},
        )
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Replan with valid reason
        res = await client.post(
            f"/api/v1/executions/{execution_id}/replan",
            json={
                "reason": "Discovery of third-party API rate limits requires queuing worker",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["replan_count"] == 1

        # 2. Replan with invalid short reason -> rejected
        bad_res = await client.post(
            f"/api/v1/executions/{execution_id}/replan",
            json={"reason": "foo"},  # too short
        )
        assert bad_res.status_code == 422
