from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.approval import ApprovalStatus
from app.models.project import StudioType
from app.orchestrator.planner import PlannerService
from app.providers.base import ProviderResponse, ProviderStatus


def test_saas_plan_generation():
    plan = PlannerService.generate_plan(
        project_id="test-proj-1",
        objective="Build an automated customer feedback triage platform",
        studio_type=StudioType.SAAS,
    )
    assert plan.project_id == "test-proj-1"
    assert len(plan.tasks) == 4
    assert plan.tasks[0].task_id == "task-1-prd"
    assert plan.tasks[1].task_id == "task-2-arch"
    assert plan.tasks[2].task_id == "task-3-implementation"
    assert plan.tasks[3].task_id == "task-4-qa"


def test_media_plan_generation():
    plan = PlannerService.generate_plan(
        project_id="test-proj-2",
        objective="Create a YouTube documentary about autonomous AI agents",
        studio_type=StudioType.MEDIA,
    )
    assert plan.project_id == "test-proj-2"
    assert len(plan.tasks) == 3
    assert plan.tasks[0].task_id == "task-1-content-strategy"
    assert plan.tasks[1].task_id == "task-2-scriptwriting"
    assert plan.tasks[2].task_id == "task-3-publishing-prep"
    assert plan.tasks[2].requires_approval is True


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
        assert len(plan["tasks"]) == 4


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

            # Execute pipeline
            exec_res = await client.post(
                "/api/v1/orchestrator/execute",
                json={
                    "project_id": project_id,
                    "objective": "Launch AI creator documentary series",
                    "studio_type": "media",
                },
            )
            assert exec_res.status_code == 202
            exec_data = exec_res.json()
            execution_id = exec_data["id"]

            # Verify it paused for approval because task 3 requires approval
            get_exec = await client.get(f"/api/v1/executions/{execution_id}")
            assert get_exec.status_code == 200
            current_status = get_exec.json()["status"]
            assert current_status == "waiting_approval"

            # Check pending approvals
            appr_res = await client.get("/api/v1/approvals?pending_only=true")
            assert appr_res.status_code == 200
            pending = appr_res.json()
            assert len(pending) >= 1

            # Resume with approval
            resume_res = await client.post(
                f"/api/v1/orchestrator/resume/{execution_id}",
                json={
                    "decision": ApprovalStatus.APPROVED.value,
                    "reason": "Content verified by lead producer",
                    "decided_by": "Abstract",
                },
            )
            assert resume_res.status_code == 200
            resumed_data = resume_res.json()
            assert resumed_data["status"] == "completed"
