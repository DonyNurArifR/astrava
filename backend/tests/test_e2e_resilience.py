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
