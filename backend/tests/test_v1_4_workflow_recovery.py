"""ASTRAVA V1.4 M1.4-2.2.2: Workflow Recovery & Security Hardening Test Suite.

Verifies:
1. M1: Partial-wave task mapping (AUD-M2.2-01).
2. M2: Separation of reservation settlement from task completion (AUD-M2.2-02).
3. M3: Mandatory fencing token enforcement on reconcile and release (AUD-M2.2-03).
4. M4: Operator authentication on all execution mutation endpoints (AUD-M2.2-04).
5. M5: Real multi-process crash recovery across OS process boundaries (SIGKILL).
"""

import asyncio
import os
import signal
import uuid
from multiprocessing import Process, Queue

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.budget import (
    BudgetReservation,
    BudgetReservationStatus,
)
from app.models.execution import ExecutionEvent
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.orchestrator.workflow_graph import dispatch_task_node
from app.providers.base import ProviderRequest, ProviderResponse, ProviderStatus
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.budget_governor import (
    BudgetGovernor,
    FencingTokenMismatchError,
)
from app.services.workflow_service import WorkflowService

# ==============================================================================
# Helpers
# ==============================================================================


async def _seed_execution() -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        ws = Workspace(name="Recovery WS", slug=f"ws-rec-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        proj = Project(
            name="Recovery Proj",
            slug=f"proj-rec-{uuid.uuid4().hex[:8]}",
            workspace_id=ws.id,
            studio_type=StudioType.SAAS,
        )
        db.add(proj)
        await db.commit()

        wf = await WorkflowService.create_workflow(
            db,
            WorkflowCreate(project_id=proj.id, name="Recovery WF", studio_type="saas"),
        )
        exec_row = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf.id, project_id=proj.id)
        )
        await db.commit()
        return proj.id, exec_row.id


# ==============================================================================
# M1: Partial-Wave Task Mapping Regression Suite (AUD-M2.2-01)
# ==============================================================================


@pytest.mark.asyncio
async def test_partial_wave_first_task_already_completed(monkeypatch, db_session, tmp_path):
    """2-task wave where task 1 was already completed; task 2 runs and receives its own result.
    Task 1 must remain untouched with original output.
    """
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        # Pre-seed task 1 as successfully completed in prior run
        res1 = await BudgetGovernor.reserve(
            db,
            execution_id,
            "task:task-1:attempt:0",
            task_id="task-1",
            estimated_cost_usd=0.01,
        )
        await BudgetGovernor.reconcile(
            db,
            res1.id,
            actual_input_tokens=100,
            actual_output_tokens=50,
            duration_ms=10,
            fence_token=res1.fence_token,
            actual_cost_usd=0.01,
            attempt_metadata={
                "success": True,
                "provider_status": "success",
                "exit_code": 0,
                "has_output": True,
                "output_text": "Task 1 Original Deliverable",
            },
        )
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    # Provider mock that only returns output for task 2
    class MockProviderTask2Only:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text="Task 2 Fresh Deliverable",
                input_tokens=200,
                output_tokens=100,
                duration_ms=20,
                cost_usd=0.01,
            )

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: MockProviderTask2Only(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "task-1",
                "title": "Task 1 (Completed Prior)",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
            },
            {
                "task_id": "task-2",
                "title": "Task 2 (Needs Execution)",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
            },
        ],
        "current_ready_task_ids": ["task-1", "task-2"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }

    result = await dispatch_task_node(state)
    task_map = {t["task_id"]: t for t in result["tasks"]}

    # Task 1 must have its original deliverable adopted, NOT overwritten by task 2!
    assert task_map["task-1"]["status"] == "completed"
    assert task_map["task-1"]["output_text"] == "Task 1 Original Deliverable"

    # Task 2 must have its own deliverable!
    assert task_map["task-2"]["status"] == "completed"
    assert task_map["task-2"]["output_text"] == "Task 2 Fresh Deliverable"


@pytest.mark.asyncio
async def test_partial_wave_second_task_already_completed(monkeypatch, db_session, tmp_path):
    """2-task wave where task 2 was already completed; task 1 runs and receives its own result."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        # Pre-seed task 2 as completed
        res2 = await BudgetGovernor.reserve(
            db,
            execution_id,
            "task:task-2:attempt:0",
            task_id="task-2",
            estimated_cost_usd=0.01,
        )
        await BudgetGovernor.reconcile(
            db,
            res2.id,
            actual_input_tokens=150,
            actual_output_tokens=75,
            duration_ms=15,
            fence_token=res2.fence_token,
            actual_cost_usd=0.01,
            attempt_metadata={
                "success": True,
                "provider_status": "success",
                "exit_code": 0,
                "has_output": True,
                "output_text": "Task 2 Pre-Completed Deliverable",
            },
        )
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    class MockProviderTask1Only:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text="Task 1 Fresh Deliverable",
                input_tokens=220,
                output_tokens=110,
                duration_ms=25,
                cost_usd=0.01,
            )

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: MockProviderTask1Only(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "task-1",
                "title": "Task 1 (Needs Execution)",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
            },
            {
                "task_id": "task-2",
                "title": "Task 2 (Completed Prior)",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
            },
        ],
        "current_ready_task_ids": ["task-1", "task-2"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }

    result = await dispatch_task_node(state)
    task_map = {t["task_id"]: t for t in result["tasks"]}

    assert task_map["task-1"]["status"] == "completed"
    assert task_map["task-1"]["output_text"] == "Task 1 Fresh Deliverable"

    assert task_map["task-2"]["status"] == "completed"
    assert task_map["task-2"]["output_text"] == "Task 2 Pre-Completed Deliverable"


@pytest.mark.asyncio
async def test_three_parallel_tasks_with_sibling_failure_and_success(
    monkeypatch, db_session, tmp_path
):
    """3 parallel tasks in a single wave: task A succeeds, task B fails with exception, task C succeeds.
    Verifies that failure and success are mapped strictly by task identity.
    """
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    class MockMultiOutcomeProvider:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            if "Task B" in req.prompt:
                return ProviderResponse(
                    status=ProviderStatus.FAILED,
                    exit_code=1,
                    output_text="",
                    input_tokens=50,
                    output_tokens=10,
                    duration_ms=5,
                    cost_usd=0.005,
                    error_message="Task B Internal Failure",
                )
            if "Task A" in req.prompt:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    exit_code=0,
                    output_text="Deliverable A",
                    input_tokens=100,
                    output_tokens=50,
                    duration_ms=10,
                    cost_usd=0.01,
                )
            # Task C
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text="Deliverable C",
                input_tokens=120,
                output_tokens=60,
                duration_ms=12,
                cost_usd=0.01,
            )

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: MockMultiOutcomeProvider(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {"task_id": "task-A", "title": "Task A", "assigned_agent_slug": "developer"},
            {"task_id": "task-B", "title": "Task B", "assigned_agent_slug": "developer"},
            {"task_id": "task-C", "title": "Task C", "assigned_agent_slug": "developer"},
        ],
        "current_ready_task_ids": ["task-A", "task-B", "task-C"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }

    result = await dispatch_task_node(state)
    task_map = {t["task_id"]: t for t in result["tasks"]}

    assert task_map["task-A"]["status"] == "completed"
    assert task_map["task-A"]["output_text"] == "Deliverable A"

    assert task_map["task-B"]["status"] == "failed"
    assert "Task B Internal Failure" in task_map["task-B"]["error_message"]

    assert task_map["task-C"]["status"] == "completed"
    assert task_map["task-C"]["output_text"] == "Deliverable C"

    assert "task-B" in result["failed_task_ids"]
    assert "task-A" not in result["failed_task_ids"]
    assert "task-C" not in result["failed_task_ids"]


@pytest.mark.asyncio
async def test_multiple_completed_tasks_followed_by_pending_tasks(
    monkeypatch, db_session, tmp_path
):
    """4-task wave where tasks 1 & 2 were completed prior; tasks 3 & 4 are pending."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        for i in (1, 2):
            res = await BudgetGovernor.reserve(
                db,
                execution_id,
                f"task:t-{i}:attempt:0",
                task_id=f"t-{i}",
                estimated_cost_usd=0.01,
            )
            await BudgetGovernor.reconcile(
                db,
                res.id,
                actual_input_tokens=100,
                actual_output_tokens=50,
                duration_ms=10,
                fence_token=res.fence_token,
                actual_cost_usd=0.01,
                attempt_metadata={
                    "success": True,
                    "provider_status": "success",
                    "exit_code": 0,
                    "has_output": True,
                    "output_text": f"Output T{i}",
                },
            )
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    class MockPendingProvider:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            for i in (3, 4):
                if f"Task {i}" in req.prompt:
                    return ProviderResponse(
                        status=ProviderStatus.SUCCESS,
                        exit_code=0,
                        output_text=f"Fresh Output T{i}",
                        input_tokens=100,
                        output_tokens=50,
                        duration_ms=10,
                        cost_usd=0.01,
                    )
            return ProviderResponse(status=ProviderStatus.FAILED)

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: MockPendingProvider(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {"task_id": "t-1", "title": "Task 1", "assigned_agent_slug": "developer"},
            {"task_id": "t-2", "title": "Task 2", "assigned_agent_slug": "developer"},
            {"task_id": "t-3", "title": "Task 3", "assigned_agent_slug": "developer"},
            {"task_id": "t-4", "title": "Task 4", "assigned_agent_slug": "developer"},
        ],
        "current_ready_task_ids": ["t-1", "t-2", "t-3", "t-4"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }

    result = await dispatch_task_node(state)
    task_map = {t["task_id"]: t for t in result["tasks"]}

    assert task_map["t-1"]["output_text"] == "Output T1"
    assert task_map["t-2"]["output_text"] == "Output T2"
    assert task_map["t-3"]["output_text"] == "Fresh Output T3"
    assert task_map["t-4"]["output_text"] == "Fresh Output T4"
    assert all(t["status"] == "completed" for t in result["tasks"])


@pytest.mark.asyncio
async def test_asynchronous_out_of_order_completion(monkeypatch, db_session, tmp_path):
    """Tasks complete asynchronously out of order (Task 1 sleeps 0.05s while Task 2 completes instantly).
    Results must be mapped strictly by task identity, unaffected by completion timing.
    """
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    class MockAsyncDelayProvider:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            if "Slow Task" in req.prompt:
                await asyncio.sleep(0.05)
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    exit_code=0,
                    output_text="Slow Task Result",
                    input_tokens=100,
                    output_tokens=50,
                    duration_ms=50,
                    cost_usd=0.01,
                )
            if "Fast Task" in req.prompt:
                # Fast task returns immediately
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    exit_code=0,
                    output_text="Fast Task Result",
                    input_tokens=50,
                    output_tokens=25,
                    duration_ms=5,
                    cost_usd=0.005,
                )
            return ProviderResponse(status=ProviderStatus.FAILED)

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: MockAsyncDelayProvider(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {"task_id": "slow-t", "title": "Slow Task", "assigned_agent_slug": "developer"},
            {"task_id": "fast-t", "title": "Fast Task", "assigned_agent_slug": "developer"},
        ],
        "current_ready_task_ids": ["slow-t", "fast-t"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }

    result = await dispatch_task_node(state)
    task_map = {t["task_id"]: t for t in result["tasks"]}

    assert task_map["slow-t"]["output_text"] == "Slow Task Result"
    assert task_map["fast-t"]["output_text"] == "Fast Task Result"
    assert task_map["slow-t"]["status"] == "completed"
    assert task_map["fast-t"]["status"] == "completed"


# ==============================================================================
# M2: Separate Reservation Settlement from Task Completion (AUD-M2.2-02)
# ==============================================================================


@pytest.mark.asyncio
async def test_reconciled_failed_attempt_is_not_completed_on_resume(
    monkeypatch, db_session, tmp_path
):
    """If attempt 0 was reconciled but failed at the provider level, resumed execution
    must NOT blindly mark it completed (AUD-M2.2-02).
    """
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        # Pre-seed attempt 0 as reconciled but FAILED
        res0 = await BudgetGovernor.reserve(
            db,
            execution_id,
            "task:failed-task:attempt:0",
            task_id="failed-task",
            estimated_cost_usd=0.01,
        )
        await BudgetGovernor.reconcile(
            db,
            res0.id,
            actual_input_tokens=100,
            actual_output_tokens=20,
            duration_ms=10,
            fence_token=res0.fence_token,
            actual_cost_usd=0.01,
            attempt_metadata={
                "success": False,
                "provider_status": "failed",
                "exit_code": 1,
                "has_output": False,
                "output_text": "",
            },
        )
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    # Provider will succeed on the resumed retry attempt 1!
    attempt_called = 0

    class RetrySuccessProvider:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            nonlocal attempt_called
            attempt_called += 1
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text="Deliverable from Retry Attempt 1",
                input_tokens=150,
                output_tokens=80,
                duration_ms=15,
                cost_usd=0.01,
            )

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: RetrySuccessProvider(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "failed-task",
                "title": "Task That Failed Prior Attempt 0",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
            }
        ],
        "current_ready_task_ids": ["failed-task"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
        "agent_snapshots": {
            "developer": {
                "name": "Dev",
                "instructions": "Code",
                "execution_config": {"max_retries": 1},
            }
        },
    }

    result = await dispatch_task_node(state)
    # The task ran retry attempt 1 and completed with fresh deliverable!
    assert attempt_called == 1
    assert result["tasks"][0]["status"] == "completed"
    assert result["tasks"][0]["output_text"] == "Deliverable from Retry Attempt 1"


@pytest.mark.asyncio
async def test_reconciled_attempt_with_missing_deliverable_is_not_completed(
    monkeypatch, db_session, tmp_path
):
    """If attempt 0 was reconciled and claimed success, but required artifact file is
    missing on disk, recovery must NOT adopt it as completed!
    """
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        res0 = await BudgetGovernor.reserve(
            db,
            execution_id,
            "task:art-task:attempt:0",
            task_id="art-task",
            estimated_cost_usd=0.01,
        )
        await BudgetGovernor.reconcile(
            db,
            res0.id,
            actual_input_tokens=100,
            actual_output_tokens=50,
            duration_ms=10,
            fence_token=res0.fence_token,
            actual_cost_usd=0.01,
            attempt_metadata={
                "success": True,
                "provider_status": "success",
                "exit_code": 0,
                "has_output": True,
                "output_text": "Code output",
            },
        )
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)
    # Note: We do NOT create required_deliverable.json on disk!

    class ProviderCreatingArtifactOnRetry:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            # Create the artifact on disk during this retry run
            p_dir = tmp_path / str(project_id)
            p_dir.mkdir(parents=True, exist_ok=True)
            (p_dir / "required_deliverable.json").write_text('{"status": "ok"}')
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text="Re-created artifact deliverable",
                input_tokens=120,
                output_tokens=60,
                duration_ms=12,
                cost_usd=0.01,
            )

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: ProviderCreatingArtifactOnRetry(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "art-task",
                "title": "Artifact Dependent Task",
                "assigned_agent_slug": "developer",
                "expected_output_artifacts": ["required_deliverable.json"],
                "status": "pending",
                "output_text": "",
            }
        ],
        "current_ready_task_ids": ["art-task"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
        "agent_snapshots": {
            "developer": {
                "name": "Dev",
                "instructions": "Code",
                "execution_config": {"max_retries": 1},
            }
        },
    }

    result = await dispatch_task_node(state)
    assert result["tasks"][0]["status"] == "completed"
    assert result["tasks"][0]["output_text"] == "Re-created artifact deliverable"
    assert (tmp_path / str(project_id) / "required_deliverable.json").exists()


# ==============================================================================
# M3: Mandatory Fencing Token Enforcement (AUD-M2.2-03)
# ==============================================================================


@pytest.mark.asyncio
async def test_mandatory_fence_token_reconcile_and_release(db_session):
    """Reconcile and release must strictly reject empty or mismatched fence tokens."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        res = await BudgetGovernor.reserve(db, execution_id, "mandatory:fence")
        res_id = res.id
        valid_fence = res.fence_token
        await db.commit()

    # Empty token rejected
    async with AsyncSessionLocal() as db:
        with pytest.raises(FencingTokenMismatchError):
            await BudgetGovernor.reconcile(
                db,
                res_id,
                actual_input_tokens=10,
                actual_output_tokens=10,
                duration_ms=5,
                fence_token="",
            )
        await db.rollback()

    # Wrong token rejected
    async with AsyncSessionLocal() as db:
        with pytest.raises(FencingTokenMismatchError):
            await BudgetGovernor.reconcile(
                db,
                res_id,
                actual_input_tokens=10,
                actual_output_tokens=10,
                duration_ms=5,
                fence_token="wrong-token-abc",
            )
        await db.rollback()

    # Release with wrong token rejected
    async with AsyncSessionLocal() as db:
        with pytest.raises(FencingTokenMismatchError):
            await BudgetGovernor.release(db, res_id, fence_token="invalid-release-token")
        await db.rollback()

    # Settle with correct token succeeds
    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.reconcile(
            db,
            res_id,
            actual_input_tokens=10,
            actual_output_tokens=10,
            duration_ms=5,
            fence_token=valid_fence,
            actual_cost_usd=0.001,
        )
        await db.commit()
        assert budget.total_agent_attempts == 1


# ==============================================================================
# M4: Execution Mutation Endpoint Security (AUD-M2.2-04)
# ==============================================================================


@pytest.mark.asyncio
async def test_execution_mutation_endpoints_require_auth(monkeypatch, db_session):
    """POST /executions, POST /executions/{id}/pause, POST /executions/{id}/resume
    must strictly require operator credentials when OPERATOR_API_KEY is configured.
    """
    project_id, execution_id = await _seed_execution()

    # Configure operator API key requirement
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", "operator-secret-token")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. POST /executions - Unauthenticated -> 401
        res = await client.post(
            "/api/v1/executions",
            json={"workflow_id": str(uuid.uuid4()), "project_id": str(project_id)},
        )
        assert res.status_code == 401

        # 2. POST /executions/{id}/pause - Unauthenticated -> 401
        res = await client.post(f"/api/v1/executions/{execution_id}/pause")
        assert res.status_code == 401

        # 3. POST /executions/{id}/resume - Unauthenticated -> 401
        res = await client.post(f"/api/v1/executions/{execution_id}/resume")
        assert res.status_code == 401

        # 4. Valid credentials succeed
        auth_headers = {
            "X-ASTRAVA-OPERATOR-KEY": "operator-secret-token",
            "X-ASTRAVA-ACTOR-NAME": "LeadSecurityOfficer",
        }
        res_pause = await client.post(
            f"/api/v1/executions/{execution_id}/pause", headers=auth_headers
        )
        assert res_pause.status_code == 200
        assert res_pause.json()["status"] == "paused"

        res_resume = await client.post(
            f"/api/v1/executions/{execution_id}/resume", headers=auth_headers
        )
        assert res_resume.status_code == 200
        assert res_resume.json()["status"] == "running"

    # Verify audit event in DB captures authentic operator
    async with AsyncSessionLocal() as db:
        events = (
            (
                await db.execute(
                    select(ExecutionEvent)
                    .where(ExecutionEvent.execution_id == execution_id)
                    .order_by(ExecutionEvent.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        event_types = {e.event_type for e in events}
        assert "execution_paused" in event_types
        assert "execution_resumed" in event_types
        pause_event = next(e for e in events if e.event_type == "execution_paused")
        assert pause_event.payload["actor_id"] == "LeadSecurityOfficer"


# ==============================================================================
# M5: Real Multi-Process Crash Recovery Test (OS SIGKILL Boundary)
# ==============================================================================


def _worker_process_crash_during_wave(
    project_id_str: str,
    execution_id_str: str,
    queue: Queue,
    tmp_path_str: str,
):
    """Process 1: Dispatches a multi-task wave, completes Task A, and when Task B
    executes, sends SIGKILL to itself at a deterministic hook point.
    """

    async def _run():
        pid = os.getpid()
        proj_uuid = uuid.UUID(project_id_str)
        exec_uuid = uuid.UUID(execution_id_str)

        # Set storage path in this process
        from pathlib import Path

        settings.ARTIFACT_STORAGE_PATH = Path(tmp_path_str)

        class CrashingMultiTaskProvider:
            async def execute(self, req: ProviderRequest) -> ProviderResponse:
                if "Task A" in req.prompt:
                    # Task A finishes normally and produces output
                    p_dir = Path(tmp_path_str) / project_id_str
                    p_dir.mkdir(parents=True, exist_ok=True)
                    (p_dir / "deliverable_A.txt").write_text("Deliverable A Finished")
                    return ProviderResponse(
                        status=ProviderStatus.SUCCESS,
                        exit_code=0,
                        output_text="Deliverable A Finished",
                        input_tokens=100,
                        output_tokens=50,
                        duration_ms=10,
                        cost_usd=0.01,
                    )
                if "Task B" in req.prompt:
                    # Task B signals parent over Queue, then abruptly sends SIGKILL to itself
                    queue.put(
                        {
                            "event": "task_b_in_flight",
                            "pid": pid,
                            "task_id": "task-B",
                        }
                    )
                    print(
                        f"[Process 1 PID {pid}] Abruptly terminating via SIGKILL during Task B execution...",
                        flush=True,
                    )
                    os.kill(pid, signal.SIGKILL)
                    return ProviderResponse(status=ProviderStatus.FAILED)
                return ProviderResponse(status=ProviderStatus.FAILED)

        from unittest.mock import patch

        with patch(
            "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
            lambda _: CrashingMultiTaskProvider(),
        ):
            state = {
                "execution_id": str(exec_uuid),
                "project_id": str(proj_uuid),
                "tasks": [
                    {
                        "task_id": "task-A",
                        "title": "Task A",
                        "assigned_agent_slug": "developer",
                        "expected_output_artifacts": ["deliverable_A.txt"],
                        "status": "pending",
                        "output_text": "",
                    },
                    {
                        "task_id": "task-B",
                        "title": "Task B",
                        "assigned_agent_slug": "developer",
                        "status": "pending",
                        "output_text": "",
                    },
                ],
                "current_ready_task_ids": ["task-A", "task-B"],
                "completed_task_ids": [],
                "failed_task_ids": [],
                "usage_records": [],
                "agent_snapshots": {
                    "developer": {
                        "name": "Dev",
                        "instructions": "Code",
                        "execution_config": {"max_retries": 1},
                    }
                },
            }
            # Start dispatch_task_node which will trigger the crash
            await dispatch_task_node(state)

    try:
        asyncio.run(_run())
    except BaseException as exc:
        print(f"[Process 1 PID {os.getpid()}] Exited: {exc}", flush=True)


def _worker_process_resume_wave(
    project_id_str: str,
    execution_id_str: str,
    queue: Queue,
    tmp_path_str: str,
):
    """Process 2: Fresh OS process starts up, resumes the execution, verifies
    Task A is not re-executed, finishes Task B, and reports success.
    """

    async def _run():
        proj_uuid = uuid.UUID(project_id_str)
        exec_uuid = uuid.UUID(execution_id_str)
        from pathlib import Path

        settings.ARTIFACT_STORAGE_PATH = Path(tmp_path_str)

        task_a_recalled = False
        task_b_called = False

        class ResumingProvider:
            async def execute(self, req: ProviderRequest) -> ProviderResponse:
                nonlocal task_a_recalled, task_b_called
                if "Task A" in req.prompt:
                    task_a_recalled = True
                    return ProviderResponse(status=ProviderStatus.SUCCESS, exit_code=0)
                if "Task B" in req.prompt:
                    task_b_called = True
                    return ProviderResponse(
                        status=ProviderStatus.SUCCESS,
                        exit_code=0,
                        output_text="Deliverable B Recovered",
                        input_tokens=120,
                        output_tokens=60,
                        duration_ms=12,
                        cost_usd=0.01,
                    )
                return ProviderResponse(status=ProviderStatus.FAILED)

        from unittest.mock import patch

        with patch(
            "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
            lambda _: ResumingProvider(),
        ):
            # Check DB state
            async with AsyncSessionLocal() as session:
                budget = await BudgetGovernor.get_budget(session, exec_uuid)
                assert budget is not None

            state = {
                "execution_id": str(exec_uuid),
                "project_id": str(proj_uuid),
                "tasks": [
                    {
                        "task_id": "task-A",
                        "title": "Task A",
                        "assigned_agent_slug": "developer",
                        "expected_output_artifacts": ["deliverable_A.txt"],
                        "status": "pending",
                        "output_text": "",
                    },
                    {
                        "task_id": "task-B",
                        "title": "Task B",
                        "assigned_agent_slug": "developer",
                        "status": "pending",
                        "output_text": "",
                    },
                ],
                "current_ready_task_ids": ["task-A", "task-B"],
                "completed_task_ids": [],
                "failed_task_ids": [],
                "usage_records": [],
                "agent_snapshots": {
                    "developer": {
                        "name": "Dev",
                        "instructions": "Code",
                        "execution_config": {"max_retries": 1},
                    }
                },
            }

            result = await dispatch_task_node(state)
            task_map = {t["task_id"]: t for t in result["tasks"]}

            queue.put(
                {
                    "task_a_recalled": task_a_recalled,
                    "task_b_called": task_b_called,
                    "task_a_status": task_map["task-A"]["status"],
                    "task_b_status": task_map["task-B"]["status"],
                    "task_b_output": task_map["task-B"]["output_text"],
                }
            )

    asyncio.run(_run())


@pytest.mark.asyncio
async def test_real_multiprocess_orchestrator_crash_recovery(db_session, tmp_path):
    """Real OS Process Boundary Test:
    1. Process 1 starts execution, completes Task A and deliverable, and is killed with SIGKILL during Task B.
    2. Process 2 boots up in a fresh OS process, resumes execution, cleanly adopts Task A without re-running,
       completes Task B, and verifies no cross-task output corruption.
    """
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        # Pre-seed Task A as completed with deliverable on disk before Process 1
        p_dir = tmp_path / str(project_id)
        p_dir.mkdir(parents=True, exist_ok=True)
        (p_dir / "deliverable_A.txt").write_text("Deliverable A Valid Content")

        res_a = await BudgetGovernor.reserve(
            db,
            execution_id,
            "task:task-A:attempt:0",
            task_id="task-A",
            estimated_cost_usd=0.01,
        )
        await BudgetGovernor.reconcile(
            db,
            res_a.id,
            actual_input_tokens=100,
            actual_output_tokens=50,
            duration_ms=10,
            fence_token=res_a.fence_token,
            actual_cost_usd=0.01,
            attempt_metadata={
                "success": True,
                "provider_status": "success",
                "exit_code": 0,
                "has_output": True,
                "output_text": "Deliverable A Valid Content",
            },
        )
        await db.commit()

    q1 = Queue()
    proc1 = Process(
        target=_worker_process_crash_during_wave,
        args=(str(project_id), str(execution_id), q1, str(tmp_path)),
    )
    proc1.start()
    pid1 = proc1.pid

    # Wait for Process 1 to signal and kill itself via SIGKILL
    msg = q1.get(timeout=10)
    assert msg["event"] == "task_b_in_flight"

    proc1.join(timeout=5)
    # Confirm Process 1 was indeed terminated by real OS SIGKILL!
    assert proc1.exitcode == -signal.SIGKILL
    print(f"Verified: Process 1 (PID {pid1}) terminated with exitcode {-signal.SIGKILL}")

    # The crashed process left an active reservation. Simulate lease expiration so Process 2 reclaims it.
    from datetime import UTC, datetime, timedelta

    async with AsyncSessionLocal() as db:
        res_b = (
            await db.execute(
                select(BudgetReservation).where(
                    BudgetReservation.execution_id == execution_id,
                    BudgetReservation.task_id == "task-B",
                    BudgetReservation.status == BudgetReservationStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if res_b:
            res_b.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()

    # Now launch Process 2 in a fresh OS process
    q2 = Queue()
    proc2 = Process(
        target=_worker_process_resume_wave,
        args=(str(project_id), str(execution_id), q2, str(tmp_path)),
    )
    proc2.start()
    pid2 = proc2.pid

    res2_msg = q2.get(timeout=10)
    proc2.join(timeout=5)
    assert proc2.exitcode == 0
    print(f"Verified: Process 2 (PID {pid2}) finished successfully with exitcode 0")

    # Assertions across the process boundary:
    # 1. Task A was NOT recalled/re-executed
    assert res2_msg["task_a_recalled"] is False
    assert res2_msg["task_a_status"] == "completed"

    # 2. Task B was executed and completed
    assert res2_msg["task_b_called"] is True
    assert res2_msg["task_b_status"] == "completed"
    assert res2_msg["task_b_output"] == "Deliverable B Recovered"

    # 3. Verify PostgreSQL budget state
    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.get_budget(db, execution_id)
        assert budget.active_reservations_count == 0
        # 1 for Task A + 1 reclaimed for Task B attempt 0 + 1 for Task B retry = 3 attempts
        assert budget.total_agent_attempts == 3
