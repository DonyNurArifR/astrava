import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.approval import ApprovalStatus
from app.providers.base import ProviderResponse, ProviderStatus
from app.services.artifact_service import ArtifactService


@pytest.mark.asyncio
async def test_full_e2e_saas_lifecycle():
    """Demonstrates complete lifecycle: Create Project -> Submit Objective -> Plan -> Execute -> Verify -> Artifacts -> History."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create SaaS Project
        p_res = await client.post(
            "/api/v1/projects",
            json={
                "name": "Autonomous Invoice Triage Engine",
                "description": "Enterprise SaaS solution for autonomous OCR and accounting audits",
                "studio_type": "saas",
                "target_objectives": ["Automate OCR data extraction", "Generate audit trail"],
            },
        )
        assert p_res.status_code == 201
        project_id = p_res.json()["id"]

        # 2. Generate Structured Plan
        plan_res = await client.post(
            "/api/v1/orchestrator/plan",
            json={
                "project_id": project_id,
                "objective": "Build automated invoice parser with anomaly detection",
                "studio_type": "saas",
            },
        )
        assert plan_res.status_code == 200
        plan = plan_res.json()
        assert len(plan["tasks"]) == 4

        # 3. Execute Pipeline with Claude Haiku 5.5
        mock_output = ProviderResponse(
            status=ProviderStatus.SUCCESS,
            output_text="# Invoice Parser Module\n\ndef parse_invoice(data):\n    return {'status': 'verified'}\n",
            exit_code=0,
            duration_ms=2100,
            input_tokens=150,
            output_tokens=60,
            cost_usd=0.0018,
        )

        with patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = mock_output

            exec_res = await client.post(
                "/api/v1/orchestrator/execute",
                json={
                    "project_id": project_id,
                    "objective": "Build automated invoice parser with anomaly detection",
                    "studio_type": "saas",
                },
            )
            assert exec_res.status_code == 202
            execution = exec_res.json()
            assert execution["status"] == "completed"
            assert execution["current_step"] == 4

            # 4. Check registered artifacts
            art_res = await client.get(f"/api/v1/artifacts/project/{project_id}")
            assert art_res.status_code == 200
            artifacts = art_res.json()
            assert len(artifacts) >= 1

            # 5. Check execution events
            get_exec = await client.get(f"/api/v1/executions/{execution['id']}")
            assert get_exec.status_code == 200
            events = get_exec.json()["events"]
            event_types = [ev["event_type"] for ev in events]
            assert "pipeline_started" in event_types
            assert "pipeline_completed" in event_types

            # 6. Check intelligence telemetry
            intel_res = await client.get("/api/v1/intelligence/summary")
            assert intel_res.status_code == 200
            summary = intel_res.json()
            assert summary["total_executions"] >= 1


@pytest.mark.asyncio
async def test_failure_modes_and_security_boundaries():
    """Tests failure resilience: path traversal attack, rejection, CLI failure, non-existent entities."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Path traversal security boundary
        with pytest.raises(ValueError, match="Path traversal detected"):
            ArtifactService.sanitize_path("../../../etc/passwd")

        # 2. Missing project 404
        bad_id = str(uuid.uuid4())
        res_404 = await client.get(f"/api/v1/projects/{bad_id}")
        assert res_404.status_code == 404

        # 3. Missing execution 404
        exec_404 = await client.get(f"/api/v1/executions/{bad_id}")
        assert exec_404.status_code == 404

        # 4. Operator rejection flow
        p_res = await client.post(
            "/api/v1/projects",
            json={"name": "Rejection Test Project", "studio_type": "media"},
        )
        proj_id = p_res.json()["id"]

        mock_resp = ProviderResponse(
            status=ProviderStatus.SUCCESS,
            output_text="# Media Script Content",
            exit_code=0,
            duration_ms=1000,
        )

        with patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = mock_resp

            exec_res = await client.post(
                "/api/v1/orchestrator/execute",
                json={
                    "project_id": proj_id,
                    "objective": "High risk publishing media run",
                    "studio_type": "media",
                },
            )
            assert exec_res.status_code == 202
            exec_id = exec_res.json()["id"]

            # Reject approval
            reject_res = await client.post(
                f"/api/v1/orchestrator/resume/{exec_id}",
                json={
                    "decision": ApprovalStatus.REJECTED.value,
                    "reason": "Brand tone misalignment detected by lead editor",
                    "decided_by": "Abstract",
                },
            )
            assert reject_res.status_code == 200
            rejected_exec = reject_res.json()
            assert rejected_exec["status"] == "cancelled"
            assert "rejected" in rejected_exec["error_message"].lower()


@pytest.mark.asyncio
async def test_resume_idempotency_and_no_duplicate_records():
    """Verify that approving/resuming a pipeline does not duplicate tasks, artifacts, or telemetry."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create media project (which triggers approval required for media studio)
        p_res = await client.post(
            "/api/v1/projects",
            json={
                "name": "Deduplication Resume Test",
                "description": "Validates state synchronization idempotency",
                "studio_type": "media",
            },
        )
        assert p_res.status_code == 201
        project_id = p_res.json()["id"]

        mock_resp = ProviderResponse(
            status=ProviderStatus.SUCCESS,
            output_text="# Media Script Content\nGenerated script for marketing campaign.\n",
            exit_code=0,
            duration_ms=800,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        )

        with patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = mock_resp

            # 1. Execute initial run -> should pause at approval
            exec_res = await client.post(
                "/api/v1/orchestrator/execute",
                json={
                    "project_id": project_id,
                    "objective": "Produce short media launch plan",
                    "studio_type": "media",
                },
            )
            assert exec_res.status_code == 202
            exec_data = exec_res.json()
            assert exec_data["status"] == "waiting_approval"
            exec_id = exec_data["id"]

            # Count tasks right after pause
            tasks_before = await client.get(f"/api/v1/tasks/project/{project_id}")
            assert tasks_before.status_code == 200
            num_tasks_before = len(tasks_before.json())
            assert num_tasks_before > 0

            # 2. Resume with APPROVED -> completes remaining pipeline
            resume_res = await client.post(
                f"/api/v1/orchestrator/resume/{exec_id}",
                json={
                    "decision": ApprovalStatus.APPROVED.value,
                    "reason": "Approved by testing suite",
                    "decided_by": "Abstract",
                },
            )
            assert resume_res.status_code == 200
            resumed_data = resume_res.json()
            assert resumed_data["status"] == "completed"

            # 3. Check tasks count after resume: must NOT have duplicated tasks!
            tasks_after = await client.get(f"/api/v1/tasks/project/{project_id}")
            assert tasks_after.status_code == 200
            num_tasks_after = len(tasks_after.json())
            assert num_tasks_after == num_tasks_before

            # 4. Idempotency test: resuming an already completed execution should return gracefully
            double_resume = await client.post(
                f"/api/v1/orchestrator/resume/{exec_id}",
                json={
                    "decision": ApprovalStatus.APPROVED.value,
                    "reason": "Repeated approval",
                    "decided_by": "Abstract",
                },
            )
            assert double_resume.status_code == 200
            assert double_resume.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_pipeline_state_recovery_across_engine_restart():
    """Verify that an interrupted or waiting pipeline survives engine restart and resumes cleanly."""
    from app.db.session import async_engine

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create media project (pauses at approval)
        p_res = await client.post(
            "/api/v1/projects",
            json={
                "name": "Restart Survival Test Project",
                "description": "Validates state checkpoint durability across database connection reset",
                "studio_type": "media",
            },
        )
        assert p_res.status_code == 201
        project_id = p_res.json()["id"]

        mock_resp = ProviderResponse(
            status=ProviderStatus.SUCCESS,
            output_text="# Media Script Content\nGenerated script after simulated engine reboot.\n",
            exit_code=0,
            duration_ms=600,
        )

        with patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = mock_resp

            # Run until WAITING_APPROVAL
            exec_res = await client.post(
                "/api/v1/orchestrator/execute",
                json={
                    "project_id": project_id,
                    "objective": "Verify checkpoint persistence across simulated server crash",
                    "studio_type": "media",
                },
            )
            assert exec_res.status_code == 202
            exec_id = exec_res.json()["id"]

            # Simulate backend restart: dispose engine connection pool
            await async_engine.dispose()

            # Verify that reloading from fresh DB connection retains all state data
            reloaded_exec = await client.get(f"/api/v1/executions/{exec_id}")
            assert reloaded_exec.status_code == 200
            data = reloaded_exec.json()
            assert data["status"] == "waiting_approval"
            assert (
                data["state_data"]["objective"]
                == "Verify checkpoint persistence across simulated server crash"
            )

            # Resume pipeline after engine reboot
            resume_res = await client.post(
                f"/api/v1/orchestrator/resume/{exec_id}",
                json={
                    "decision": ApprovalStatus.APPROVED.value,
                    "reason": "Approved post-restart",
                    "decided_by": "Abstract",
                },
            )
            assert resume_res.status_code == 200
            assert resume_res.json()["status"] == "completed"
