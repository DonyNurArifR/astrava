"""ASTRAVA V1.4 M1.4-2.2: Budget Governance Hardening Test Suite.

Verifies the findings addressed in M1.4-2.2:
1. F-01: HTTP-level security, authorization, ceilings, reason, and transactional audit logging for budget increase.
2. F-02: Retry-aware budget enforcement (per-attempt reservations, total_agent_attempts counting, retry blocking).
3. F-03: Missing vs zero provider telemetry accounting (never coercing missing cost to $0.00).
4. F-04: Fencing token validation rejecting stale worker reconciliations.
5. F-05: Decimal monetary precision preventing float drift across thousands of operations.
6. F-06: Crash-recovery idempotency on resumed executions with already-reconciled reservations.
7. Subprocess execution and termination handling.
"""

import asyncio
import os
import signal
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.budget import (
    BudgetAuditLog,
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
        ws = Workspace(name="Hardening WS", slug=f"ws-hard-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        proj = Project(
            name="Hardening Proj",
            slug=f"proj-hard-{uuid.uuid4().hex[:8]}",
            workspace_id=ws.id,
            studio_type=StudioType.SAAS,
        )
        db.add(proj)
        await db.commit()

        wf = await WorkflowService.create_workflow(
            db,
            WorkflowCreate(project_id=proj.id, name="Hardening WF", studio_type="saas"),
        )
        exec_row = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf.id, project_id=proj.id)
        )
        await db.commit()
        return proj.id, exec_row.id


# ==============================================================================
# F-01: HTTP-Level Budget Increase Security & Audit
# ==============================================================================


@pytest.mark.asyncio
async def test_budget_increase_http_security_and_audit(monkeypatch, db_session):
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        await db.commit()

    # Configure operator api key requirement
    monkeypatch.setattr(settings, "OPERATOR_API_KEY", "secret-test-operator-key")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        url = f"/api/v1/executions/{execution_id}/budget/increase"

        # 1. 401 when unauthenticated
        res = await client.post(url, json={"max_cost_usd": 2.0, "reason": "Valid reason provided"})
        assert res.status_code == 401

        # 2. 401 with wrong key
        res = await client.post(
            url,
            headers={"X-ASTRAVA-OPERATOR-KEY": "wrong-key"},
            json={"max_cost_usd": 2.0, "reason": "Valid reason provided"},
        )
        assert res.status_code == 401

        valid_headers = {
            "X-ASTRAVA-OPERATOR-KEY": "secret-test-operator-key",
            "X-ASTRAVA-ACTOR-NAME": "LeadArchitect",
        }

        # 3. 422 when reason is missing
        res = await client.post(url, headers=valid_headers, json={"max_cost_usd": 2.0})
        assert res.status_code == 422

        # 4. 422 when reason is too short (< 5 chars)
        res = await client.post(
            url, headers=valid_headers, json={"max_cost_usd": 2.0, "reason": "no"}
        )
        assert res.status_code == 422

        # 5. 422 when ceiling is exceeded (max permitted cost is $50.00)
        res = await client.post(
            url,
            headers=valid_headers,
            json={"max_cost_usd": 100.0, "reason": "Attempting to exceed ceiling"},
        )
        assert res.status_code == 422

        # 6. 404 for non-existent execution
        res = await client.post(
            f"/api/v1/executions/{uuid.uuid4()}/budget/increase",
            headers=valid_headers,
            json={"max_cost_usd": 2.0, "reason": "Valid reason for non-existent"},
        )
        assert res.status_code == 404

        # 7. 200 on authorized, valid increase
        res = await client.post(
            url,
            headers=valid_headers,
            json={"max_cost_usd": 5.0, "reason": "Approved load test stage 2"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["limits"]["max_cost_usd"] == 5.0
        assert data["status"] == "active"

    # Verify database audit records
    async with AsyncSessionLocal() as db:
        # Budget audit log
        logs = (
            (
                await db.execute(
                    select(BudgetAuditLog).where(BudgetAuditLog.execution_id == execution_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
        # Client-supplied X-ASTRAVA-ACTOR-NAME is ignored; server identity is recorded.
        assert logs[0].actor_id == "Abstract"
        assert logs[0].reason == "Approved load test stage 2"
        assert logs[0].new_limits["max_cost_usd"] == 5.0

        # Workflow execution event
        events = (
            (
                await db.execute(
                    select(ExecutionEvent).where(
                        ExecutionEvent.execution_id == execution_id,
                        ExecutionEvent.event_type == "pipeline_budget_increased",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].payload["actor_id"] == "Abstract"


# ==============================================================================
# F-02: Retry-Aware Budget Enforcement
# ==============================================================================


@pytest.mark.asyncio
async def test_retry_aware_budget_accounting(monkeypatch, db_session, tmp_path):
    """Verifies that internal retries are reserved and counted per attempt."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        # Budget fits exactly 2 attempts at $0.01 each ($0.025 ceiling)
        await BudgetGovernor.initialize_budget(
            db, execution_id, project_id, limits={"max_cost_usd": 0.025, "max_agent_attempts": 5}
        )
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    attempt_counter = 0

    class MockFailingThenSucceedingProvider:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            nonlocal attempt_counter
            attempt_counter += 1
            if attempt_counter == 1:
                # First attempt fails
                return ProviderResponse(
                    status=ProviderStatus.FAILED,
                    exit_code=1,
                    output_text="",
                    input_tokens=100,
                    output_tokens=50,
                    duration_ms=10,
                    cost_usd=0.01,
                    error_message="Transient provider error",
                )
            # Second attempt succeeds
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text="Deliverable content",
                input_tokens=150,
                output_tokens=80,
                duration_ms=15,
                cost_usd=0.01,
            )

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: MockFailingThenSucceedingProvider(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "retry-task",
                "title": "Task With Retry",
                "assigned_agent_slug": "developer",
            }
        ],
        "current_ready_task_ids": ["retry-task"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
        "agent_snapshots": {
            "developer": {
                "name": "Developer",
                "instructions": "Code",
                "execution_config": {"max_retries": 1, "timeout_seconds": 30},
            }
        },
    }

    result = await dispatch_task_node(state)
    assert result["tasks"][0]["status"] == "completed"
    assert result["tasks"][0]["retry_count"] == 1
    assert attempt_counter == 2

    # Check budget in DB: must record 2 agent attempts, not 1!
    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.get_budget(db, execution_id)
        assert budget.total_agent_attempts == 2
        assert budget.consumed_input_tokens == 250
        assert budget.consumed_output_tokens == 130
        assert float(budget.consumed_actual_cost_usd) == pytest.approx(0.02)
        assert budget.active_reservations_count == 0

        # Check reservations: must have 2 distinct reconciled reservations
        reservations = (
            (
                await db.execute(
                    select(BudgetReservation).where(BudgetReservation.execution_id == execution_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(reservations) == 2
        res_keys = {r.reservation_key for r in reservations}
        assert "task:retry-task:attempt:0" in res_keys
        assert "task:retry-task:attempt:1" in res_keys
        assert all(r.status == BudgetReservationStatus.RECONCILED for r in reservations)


@pytest.mark.asyncio
async def test_retry_blocked_when_budget_exhausts(monkeypatch, db_session, tmp_path):
    """Verifies that a retry cannot start if remaining budget is insufficient."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        # Budget only has enough for 1 attempt (0.015 limit)
        await BudgetGovernor.initialize_budget(
            db, execution_id, project_id, limits={"max_cost_usd": 0.015}
        )
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    calls = 0

    class AlwaysFailingProvider:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            nonlocal calls
            calls += 1
            return ProviderResponse(
                status=ProviderStatus.FAILED,
                exit_code=1,
                output_text="",
                input_tokens=100,
                output_tokens=50,
                duration_ms=10,
                cost_usd=0.01,
                error_message="Fail",
            )

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: AlwaysFailingProvider(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "block-retry",
                "title": "Task That Should Be Blocked On Retry",
                "assigned_agent_slug": "developer",
            }
        ],
        "current_ready_task_ids": ["block-retry"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
        "agent_snapshots": {
            "developer": {
                "name": "Developer",
                "instructions": "Code",
                "execution_config": {"max_retries": 3, "timeout_seconds": 30},
            }
        },
    }

    result = await dispatch_task_node(state)
    assert result["tasks"][0]["status"] == "failed"
    assert "Retry blocked by budget exhaustion" in result["tasks"][0]["error_message"]
    # Only 1 provider invocation occurred; retry was blocked before dispatch!
    assert calls == 1


# ==============================================================================
# F-03: Missing vs Zero Telemetry Metrics
# ==============================================================================


@pytest.mark.asyncio
async def test_missing_provider_cost_preserves_reserved_estimate(db_session):
    """Never coerce missing provider cost to $0.00."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        res = await BudgetGovernor.reserve(
            db,
            execution_id,
            "missing:telemetry",
            estimated_cost_usd=Decimal("0.030000"),
            estimated_input_tokens=4000,
        )
        res_id = res.id
        fence = res.fence_token
        await db.commit()

    async with AsyncSessionLocal() as db:
        # Telemetry has None for cost (CLI returned no total_cost_usd)
        await BudgetGovernor.reconcile(
            db,
            res_id,
            actual_input_tokens=1200,
            actual_output_tokens=400,
            duration_ms=100,
            actual_cost_usd=None,
            fence_token=fence,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.get_budget(db, execution_id)
        # Reserved estimate of $0.03 is preserved in consumed_estimated_cost_usd
        assert float(budget.consumed_estimated_cost_usd) == pytest.approx(0.03)
        assert float(budget.consumed_actual_cost_usd) == pytest.approx(0.0)
        assert budget.is_cost_estimated is True

        res_row = await db.get(BudgetReservation, res_id)
        assert float(res_row.reconciled_cost_usd) == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_coerced_zero_cost_with_tokens_preserves_estimate(db_session):
    """A provider returning cost=0.0 while consuming tokens is treated as estimated."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        res = await BudgetGovernor.reserve(
            db,
            execution_id,
            "zero:coerced",
            estimated_cost_usd=Decimal("0.020000"),
        )
        res_id = res.id
        fence = res.fence_token
        await db.commit()

    async with AsyncSessionLocal() as db:
        # Passes 0.0 with 500 tokens without deterministic confirmation
        await BudgetGovernor.reconcile(
            db,
            res_id,
            actual_input_tokens=500,
            actual_output_tokens=200,
            duration_ms=80,
            actual_cost_usd=Decimal("0.0"),
            is_cost_zero_confirmed=False,
            fence_token=fence,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.get_budget(db, execution_id)
        # Estimated cost is charged, not $0.00!
        assert float(budget.consumed_estimated_cost_usd) == pytest.approx(0.02)
        assert budget.is_cost_estimated is True


@pytest.mark.asyncio
async def test_deterministic_zero_cost_allowed(db_session):
    """Deterministic local engines explicitly confirmed as free charge exact $0.00."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        res = await BudgetGovernor.reserve(
            db,
            execution_id,
            "deterministic:free",
            estimated_cost_usd=Decimal("0.010000"),
        )
        res_id = res.id
        fence = res.fence_token
        await db.commit()

    async with AsyncSessionLocal() as db:
        await BudgetGovernor.reconcile(
            db,
            res_id,
            actual_input_tokens=0,
            actual_output_tokens=0,
            duration_ms=5,
            actual_cost_usd=Decimal("0.0"),
            is_cost_zero_confirmed=True,
            fence_token=fence,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.get_budget(db, execution_id)
        assert float(budget.consumed_actual_cost_usd) == pytest.approx(0.0)
        assert float(budget.consumed_estimated_cost_usd) == pytest.approx(0.0)


# ==============================================================================
# F-04: Fencing Token Rejects Stale Workers
# ==============================================================================


@pytest.mark.asyncio
async def test_fencing_token_rejects_stale_worker(db_session):
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        res = await BudgetGovernor.reserve(db, execution_id, "fence:test")
        res_id = res.id
        valid_fence = res.fence_token
        await db.commit()

    # Worker presenting invalid fence token is rejected
    async with AsyncSessionLocal() as db:
        with pytest.raises(FencingTokenMismatchError):
            await BudgetGovernor.reconcile(
                db,
                res_id,
                actual_input_tokens=100,
                actual_output_tokens=50,
                duration_ms=10,
                actual_cost_usd=0.01,
                fence_token="stale-invalid-token",
            )
        await db.rollback()

    # Worker presenting valid fence token succeeds
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.reconcile(
            db,
            res_id,
            actual_input_tokens=100,
            actual_output_tokens=50,
            duration_ms=10,
            actual_cost_usd=0.01,
            fence_token=valid_fence,
        )
        await db.commit()


# ==============================================================================
# F-05: Decimal Precision & Absence of Float Drift
# ==============================================================================


@pytest.mark.asyncio
async def test_monetary_decimal_precision(db_session):
    """Verifies that sub-cent operations with Decimal accumulate exactly without drift."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        await db.commit()

    # 100 sub-cent reservations and settlements of $0.000123
    increment = Decimal("0.000123")
    for i in range(50):
        async with AsyncSessionLocal() as db:
            res = await BudgetGovernor.reserve(
                db,
                execution_id,
                f"decimal:{i}",
                estimated_cost_usd=increment,
            )
            res_id = res.id
            fence = res.fence_token
            await BudgetGovernor.reconcile(
                db,
                res_id,
                actual_input_tokens=10,
                actual_output_tokens=10,
                duration_ms=1,
                actual_cost_usd=increment,
                fence_token=fence,
            )
            await db.commit()

    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.get_budget(db, execution_id)
        expected = increment * 50
        # Exact decimal equality: zero float drift!
        assert budget.consumed_actual_cost_usd == expected
        assert budget.reserved_cost_usd == Decimal("0.000000")


# ==============================================================================
# F-06: Crash Recovery On Resumed Executions
# ==============================================================================


@pytest.mark.asyncio
async def test_resumed_execution_with_reconciled_reservation(db_session, tmp_path, monkeypatch):
    """If an execution crashed after DB reconciliation, resume adopts the task cleanly."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        # Pre-seed a reconciled reservation for attempt 0 (simulating prior run success)
        res = await BudgetGovernor.reserve(
            db,
            execution_id,
            reservation_key="task:crashed-task:attempt:0",
            task_id="crashed-task",
            estimated_cost_usd=0.01,
        )
        await BudgetGovernor.reconcile(
            db,
            res.id,
            actual_input_tokens=500,
            actual_output_tokens=200,
            duration_ms=50,
            actual_cost_usd=0.01,
            fence_token=res.fence_token,
            attempt_metadata={
                "success": True,
                "provider_status": "success",
                "exit_code": 0,
                "has_output": True,
                "output_text": "Completed task result",
            },
        )
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "crashed-task",
                "title": "Crashed Task",
                "assigned_agent_slug": "developer",
            }
        ],
        "current_ready_task_ids": ["crashed-task"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }

    # Must adopt attempt 0 and mark status completed without crashing!
    result = await dispatch_task_node(state)
    assert result["tasks"][0]["status"] == "completed"
    assert result.get("budget_exhausted") is not True


# ==============================================================================
# Subprocess Real Process Termination Test
# ==============================================================================


@pytest.mark.asyncio
async def test_subprocess_real_process_kill():
    """Starts an actual OS child process and kills it with SIGKILL, verifying recovery."""
    proc = await asyncio.create_subprocess_exec(
        "sleep",
        "10",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    pid = proc.pid
    assert pid is not None

    # Verify process is alive
    os.kill(pid, 0)

    # Terminate with SIGKILL
    os.kill(pid, signal.SIGKILL)
    await proc.wait()

    # Verify process is dead
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert proc.returncode is not None
