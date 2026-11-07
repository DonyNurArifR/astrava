"""ASTRAVA V1.4 M1.4-3: Semantic Evaluator & Automated Remediation Test Suite.

Verifies:
1. VerificationEngine structured diagnostic extraction (file, line number, bounded summary).
2. SemanticEvaluator acceptance criteria compliance scoring and unmet criteria identification.
3. Closed-loop remediation self-correction: deliberate syntax error diagnosed and resolved on retry.
4. Hard boundary: maximum 3 remediation cycles per task enforced without infinite loops.
5. BudgetGovernor remediation turn cap enforcement and graceful execution halting.
6. REST API: GET /api/v1/executions/{id}/remediations returns complete cycle history and diagnostics.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.execution import WorkflowExecution
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.orchestrator.workflow_graph import (
    dispatch_task_node,
    remediation_node,
    verify_node,
)
from app.providers.base import ProviderRequest, ProviderResponse, ProviderStatus
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.budget_governor import (
    BudgetGovernor,
)
from app.services.workflow_service import WorkflowService
from app.verification.engine import VerificationEngine
from app.verification.semantic_evaluator import (
    SemanticEvaluator,
)

# ==============================================================================
# Helpers
# ==============================================================================


async def _seed_execution() -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        ws = Workspace(name="Remediation WS", slug=f"ws-rem-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        proj = Project(
            name="Remediation Proj",
            slug=f"proj-rem-{uuid.uuid4().hex[:8]}",
            workspace_id=ws.id,
            studio_type=StudioType.SAAS,
        )
        db.add(proj)
        await db.commit()

        wf = await WorkflowService.create_workflow(
            db,
            WorkflowCreate(project_id=proj.id, name="Remediation WF", studio_type="saas"),
        )
        exec_row = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf.id, project_id=proj.id)
        )
        await db.commit()
        return proj.id, exec_row.id


# ==============================================================================
# 1. Structured Diagnostics Extraction
# ==============================================================================


@pytest.mark.asyncio
async def test_structured_diagnostics_extraction(tmp_path):
    """VerificationEngine must extract structured error summaries including file and line numbers,
    bounded to 2,500 characters.
    """
    broken_py = tmp_path / "broken_script.py"
    broken_py.write_text("def broken_syntax(:\n    pass\n")

    report = await VerificationEngine.verify_task(tmp_path, run_lint=True, run_tests=False)
    assert report.overall_passed is False
    assert len(report.diagnostics) >= 1

    syntax_diag = next(d for d in report.diagnostics if d.error_type == "syntax")
    assert syntax_diag.line_number == 1
    assert "broken_script.py" in (syntax_diag.file_path or "")
    assert len(report.diagnostic_summary) <= 2500
    assert (
        "broken_syntax" in report.diagnostic_summary
        or "invalid syntax" in report.diagnostic_summary.lower()
    )


# ==============================================================================
# 2. Semantic Evaluation
# ==============================================================================


@pytest.mark.asyncio
async def test_semantic_evaluator_no_criteria_passes():
    """When no criteria declared, SemanticEvaluator returns immediate pass."""
    res = await SemanticEvaluator.evaluate(
        deliverable_text="Some deliverable",
        acceptance_criteria=[],
        task_title="No Criteria Task",
    )
    assert res.passed is True
    assert res.compliance_score == 1.0
    assert len(res.unmet_criteria) == 0


@pytest.mark.asyncio
async def test_semantic_evaluator_with_mock_provider():
    """SemanticEvaluator parses compliance score and unmet criteria from provider response."""

    class MockEvaluatorProvider:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            mock_json = """
            {
              "passed": false,
              "compliance_score": 0.5,
              "unmet_criteria": ["Must include error handling for HTTP 404"],
              "reasoning": "404 handler was missing from router.",
              "suggestions": ["Add @app.exception_handler(404)"]
            }
            """
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text=mock_json,
            )

    res = await SemanticEvaluator.evaluate(
        deliverable_text="def router(): return 200",
        acceptance_criteria=[
            "Must return HTTP 200 on success",
            "Must include error handling for HTTP 404",
        ],
        task_title="Build Router",
        provider=MockEvaluatorProvider(),
    )
    assert res.passed is False
    assert res.compliance_score == 0.5
    assert "Must include error handling for HTTP 404" in res.unmet_criteria
    assert len(res.suggestions) == 1


# ==============================================================================
# 3. Closed-Loop Remediation Self-Correction
# ==============================================================================


@pytest.mark.asyncio
async def test_remediation_cycle_fixes_syntax_error(monkeypatch, db_session, tmp_path):
    """An agent that generates code with a deliberate syntax error on cycle 0 receives
    compiler diagnostics, fixes the error on remediation cycle 1, and passes verification.
    """
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)
    p_dir = tmp_path / str(project_id)
    p_dir.mkdir(parents=True, exist_ok=True)

    calls = 0

    class SelfCorrectingProvider:
        async def execute(self, req: ProviderRequest) -> ProviderResponse:
            nonlocal calls
            calls += 1
            code_file = p_dir / "calculator.py"

            if "REMEDIATION REQUIRED" in req.prompt:
                # Cycle 1: Agent sees the diagnostics and fixes the code!
                code_file.write_text("def add(a, b):\n    return a + b\n")
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    exit_code=0,
                    output_text="def add(a, b):\n    return a + b\n",
                    input_tokens=150,
                    output_tokens=60,
                    duration_ms=15,
                    cost_usd=0.01,
                )
            else:
                # Cycle 0: Deliberate syntax error!
                code_file.write_text("def add(a, b:\n    return a + b\n")
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    exit_code=0,
                    output_text="def add(a, b:\n    return a + b\n",
                    input_tokens=100,
                    output_tokens=40,
                    duration_ms=10,
                    cost_usd=0.01,
                )

    monkeypatch.setattr(
        "app.orchestrator.workflow_graph.ProviderFactory.get_provider",
        lambda _: SelfCorrectingProvider(),
    )

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "calc-task",
                "title": "Build Calculator",
                "description": "Create calculator module",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
            }
        ],
        "current_ready_task_ids": ["calc-task"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }

    # Step 1: Initial dispatch generates buggy code
    d_res1 = await dispatch_task_node(state)
    state.update(d_res1)

    # Step 2: Verification runs and detects the syntax error!
    v_res1 = await verify_node(state)
    state.update(v_res1)

    assert state["remediation_needed"] is True
    assert "calc-task" in state["remediation_task_ids"]

    # Step 3: Remediation node formats diagnostic prompt and increments turn
    r_res1 = await remediation_node(state)
    state.update(r_res1)

    rem_task = state["tasks"][0]
    assert rem_task["remediation_cycles"] == 1
    assert "REMEDIATION REQUIRED (Cycle 1/3)" in rem_task["description"]
    assert rem_task["status"] == "pending"

    # Step 4: Dispatch runs again with remediation prompt
    d_res2 = await dispatch_task_node(state)
    state.update(d_res2)

    # Step 5: Verification runs on fixed code -> PASSES!
    v_res2 = await verify_node(state)
    state.update(v_res2)

    assert state["remediation_needed"] is False
    assert "calc-task" not in state["failed_task_ids"]
    assert calls == 2


# ==============================================================================
# 4. Remediation Cycle Cap (Max 3)
# ==============================================================================


@pytest.mark.asyncio
async def test_remediation_cycle_limit_halts_after_3_attempts(monkeypatch, db_session, tmp_path):
    """Tasks exceeding 3 remediation cycles halt without infinite looping and are marked failed."""
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        await db.commit()

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", tmp_path)
    p_dir = tmp_path / str(project_id)
    p_dir.mkdir(parents=True, exist_ok=True)
    (p_dir / "stub.py").write_text("def broken(\n")

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "unfixable-task",
                "title": "Unfixable Task",
                "description": "Broken task",
                "assigned_agent_slug": "developer",
                "status": "completed",
                "output_text": "broken",
                "remediation_cycles": 3,  # Already at limit
            }
        ],
        "current_ready_task_ids": ["unfixable-task"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
    }

    v_res = await verify_node(state)
    assert v_res["remediation_needed"] is False
    assert "unfixable-task" in v_res["failed_task_ids"]
    assert v_res["tasks"][0]["status"] == "failed"
    assert "exceeded maximum remediation cycles" in v_res["tasks"][0]["error_message"]


# ==============================================================================
# 5. BudgetGovernor Remediation Cap Exhaustion
# ==============================================================================


@pytest.mark.asyncio
async def test_remediation_budget_governor_exhaustion_halts(monkeypatch, db_session, tmp_path):
    """When BudgetGovernor.max_remediation_turns is reached, remediation_node halts
    cleanly with budget_exhausted=True and status=failed.
    """
    project_id, execution_id = await _seed_execution()
    async with AsyncSessionLocal() as db:
        budget = await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        # Artificially set max_remediation_turns to 1 and consumed to 1
        budget.max_remediation_turns = 1
        budget.remediation_turns_count = 1
        await db.commit()

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "task-budget-exhaust",
                "title": "Budget Task",
                "description": "Task",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
                "_remediation_meta": {"diagnostic_summary": "Failed"},
            }
        ],
        "current_ready_task_ids": ["task-budget-exhaust"],
        "remediation_task_ids": ["task-budget-exhaust"],
        "failed_task_ids": [],
        "remediation_records": [],
    }

    r_res = await remediation_node(state)
    assert r_res["budget_exhausted"] is True
    assert r_res["status"] == "failed"
    assert "task-budget-exhaust" in r_res["failed_task_ids"]


# ==============================================================================
# 6. REST API: GET /api/v1/executions/{id}/remediations
# ==============================================================================


@pytest.mark.asyncio
async def test_get_execution_remediations_endpoint(monkeypatch, db_session):
    """GET /executions/{id}/remediations returns cycle history and diagnostics."""
    project_id, execution_id = await _seed_execution()

    async with AsyncSessionLocal() as db:
        exec_row = await db.get(WorkflowExecution, execution_id)
        exec_row.remediation_count = 2
        await WorkflowService.record_event(
            db,
            execution_id,
            "task_remediation_cycle",
            {
                "cycle": 1,
                "task_id": "t-1",
                "diagnostics": "Syntax error at line 4",
                "unmet_criteria": ["Return int"],
            },
        )
        await WorkflowService.record_event(
            db,
            execution_id,
            "task_remediation_cycle",
            {
                "cycle": 2,
                "task_id": "t-1",
                "diagnostics": "Assertion error in test_add",
                "unmet_criteria": [],
            },
        )
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/v1/executions/{execution_id}/remediations")
        assert res.status_code == 200
        data = res.json()
        assert data["execution_id"] == str(execution_id)
        assert data["total_remediations"] == 2
        assert "t-1" in data["tasks_affected"]
        assert len(data["cycles"]) == 2
        assert data["cycles"][0]["cycle"] == 1
        assert "Syntax error" in data["cycles"][0]["diagnostics"]
