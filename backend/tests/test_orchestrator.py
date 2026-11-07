from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.approval import ApprovalStatus
from app.models.project import StudioType
from app.orchestrator.planner import PlannedTask, PlannerService
from app.providers.base import ProviderResponse, ProviderStatus


def test_saas_plan_generation():
    plan = PlannerService.generate_plan(
        project_id="test-proj-1",
        objective="Build an automated customer feedback triage platform",
        studio_type=StudioType.SAAS,
    )
    assert plan.project_id == "test-proj-1"
    assert len(plan.tasks) == 7
    assert plan.tasks[0].task_id == "task-1-market-research"
    assert plan.tasks[0].assigned_agent_slug == "product-researcher"
    assert plan.tasks[1].task_id == "task-2-competitor-analysis"
    assert plan.tasks[1].assigned_agent_slug == "competitor-analyst"
    assert plan.tasks[2].task_id == "task-3-product-strategy"
    assert plan.tasks[3].task_id == "task-4-prd"
    assert plan.tasks[4].task_id == "task-5-architecture"
    assert plan.tasks[5].task_id == "task-6-implementation"
    assert plan.tasks[6].task_id == "task-7-qa"
    assert plan.is_valid_dag is True
    assert len(plan.execution_stages) == 6


def test_media_plan_generation():
    plan = PlannerService.generate_plan(
        project_id="test-proj-2",
        objective="Create a YouTube documentary about autonomous AI agents",
        studio_type=StudioType.MEDIA,
    )
    assert plan.project_id == "test-proj-2"
    assert len(plan.tasks) == 8
    assert plan.tasks[0].task_id == "task-1-content-research"
    assert plan.tasks[1].task_id == "task-2-audience-analysis"
    assert plan.tasks[7].task_id == "task-8-quality-review"
    assert plan.tasks[7].requires_approval is True
    assert plan.is_valid_dag is True
    assert len(plan.execution_stages) == 6


def test_dag_cycle_detection():
    t1 = PlannedTask(task_id="t1", title="Task 1", description="", dependencies=["t2"])
    t2 = PlannedTask(task_id="t2", title="Task 2", description="", dependencies=["t1"])
    with pytest.raises(ValueError, match="Circular dependency detected"):
        PlannerService.validate_and_compute_stages([t1, t2])


@pytest.mark.asyncio
async def test_orchestrator_plan_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create project
        p_res = await client.post(
            "/api/v1/projects",
            json={"name": "Plan Test Project", "studio_type": "saas"},
        )
        project_id = p_res.json()["id"]

        # Request plan
        plan_res = await client.post(
            "/api/v1/orchestrator/plan",
            json={
                "project_id": project_id,
                "objective": "Design an enterprise AI orchestrator",
                "studio_type": "saas",
            },
        )
        assert plan_res.status_code == 200
        plan = plan_res.json()
        assert plan["project_id"] == project_id
        assert len(plan["tasks"]) == 7
        assert len(plan["execution_stages"]) == 6
        assert plan["is_valid_dag"] is True


@pytest.mark.asyncio
async def test_orchestrator_understand_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/orchestrator/understand",
            json={
                "objective": "Build automated invoice parser with anomaly detection",
                "studio_type": "saas",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["studio"] == "saas"
        assert len(data["required_capabilities"]) > 0
        assert len(data["expected_deliverables"]) > 0


@pytest.mark.asyncio
async def test_orchestrator_execution_and_approval_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create project for media studio (which has an approval required task)
        p_res = await client.post(
            "/api/v1/projects",
            json={"name": "Media Orchestrator Project", "studio_type": "media"},
        )
        project_id = p_res.json()["id"]

        mock_resp = ProviderResponse(
            status=ProviderStatus.SUCCESS,
            output_text="# Output content\nVerified autonomous execution.",
            exit_code=0,
            duration_ms=1200,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        )

        with patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = mock_resp

            # Trigger execution
            exec_res = await client.post(
                "/api/v1/orchestrator/execute",
                json={
                    "project_id": project_id,
                    "objective": "High risk content campaign",
                    "studio_type": "media",
                },
            )
            assert exec_res.status_code in (200, 202)
            execution = exec_res.json()
            exec_id = execution["id"]

            # Must pause on approval required task (task-8-quality-review)
            assert execution["status"] == "waiting_approval"

            # Check pending approval list
            appr_res = await client.get("/api/v1/approvals/pending")
            assert appr_res.status_code == 200
            pending = appr_res.json()
            assert len(pending) >= 1

            # Resume by approving
            resume_res = await client.post(
                f"/api/v1/orchestrator/executions/{exec_id}/resume",
                json={
                    "decision": ApprovalStatus.APPROVED,
                    "reason": "Authorized release",
                },
            )
            assert resume_res.status_code == 200
            resumed = resume_res.json()
            assert resumed["status"] == "completed"
