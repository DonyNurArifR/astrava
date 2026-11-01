from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.task import TaskStatus
from app.orchestrator.planner import PlannedTask, PlannerService
from app.orchestrator.workflow_graph import _execute_single_task
from app.providers.base import ProviderRequest, ProviderResponse, ProviderStatus


def test_duplicate_task_id_rejection():
    t1 = PlannedTask(
        task_id="dup-task-1",
        title="Task A",
        description="",
    )
    t2 = PlannedTask(
        task_id="dup-task-1",
        title="Task B",
        description="",
    )
    with pytest.raises(ValueError, match="Duplicate task identifier detected: 'dup-task-1'"):
        PlannerService.validate_and_compute_stages([t1, t2])


def test_missing_dependency_rejection():
    t1 = PlannedTask(
        task_id="task-1",
        title="Task 1",
        description="",
        dependencies=["non-existent-task-id"],
    )
    with pytest.raises(ValueError, match="depends on non-existent task 'non-existent-task-id'"):
        PlannerService.validate_and_compute_stages([t1])


def test_circular_dependency_rejection():
    t1 = PlannedTask(task_id="task-1", title="1", description="", dependencies=["task-3"])
    t2 = PlannedTask(task_id="task-2", title="2", description="", dependencies=["task-1"])
    t3 = PlannedTask(task_id="task-3", title="3", description="", dependencies=["task-2"])
    with pytest.raises(ValueError, match="Circular dependency detected"):
        PlannerService.validate_and_compute_stages([t1, t2, t3])


@pytest.mark.asyncio
async def test_bounded_retry_on_transient_failure(tmp_path):
    task = {
        "task_id": "test-retry-task",
        "title": "Retryable Analysis",
        "description": "Perform analysis",
        "assigned_agent_slug": "product-researcher",
        "assigned_model": "claude-haiku-5-5",
        "dependencies": [],
        "expected_output_artifacts": ["analysis.md"],
    }
    state = {
        "agent_snapshots": {
            "product-researcher": {
                "name": "Product Researcher",
                "instructions": "Research carefully",
                "execution_config": {"max_retries": 1, "timeout_seconds": 30},
                "output_schema": {},
            }
        },
        "tasks": [task],
        "completed_task_ids": [],
    }

    fail_resp = ProviderResponse(
        status=ProviderStatus.FAILED,
        output_text="",
        exit_code=1,
        error_message="Transient process crash",
    )
    success_resp = ProviderResponse(
        status=ProviderStatus.SUCCESS,
        output_text="# Research Complete\nAll market criteria satisfied.",
        exit_code=0,
    )

    with patch(
        "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
        new_callable=AsyncMock,
    ) as mock_exec:
        # First call fails, second call succeeds
        mock_exec.side_effect = [fail_resp, success_resp]

        updated_task, usage_records = await _execute_single_task(task, state, tmp_path)

        assert updated_task["status"] == "completed"
        assert updated_task["retry_count"] == 1
        assert len(usage_records) == 2
        assert mock_exec.call_count == 2


@pytest.mark.asyncio
async def test_context_traceability_and_failed_dependency_exclusion(tmp_path):
    t1 = {
        "task_id": "t1-success",
        "title": "Market Research",
        "assigned_agent_slug": "product-researcher",
        "output_text": "# Market Research Deliverable",
        "status": "completed",
    }
    t2 = {
        "task_id": "t2-failed",
        "title": "Faulty Prerequisite",
        "assigned_agent_slug": "competitor-analyst",
        "output_text": "Error: Corrupted output data",
        "status": "failed",
    }
    t3 = {
        "task_id": "t3-downstream",
        "title": "Product Strategy",
        "description": "Synthesize strategy",
        "assigned_agent_slug": "product-strategist",
        "dependencies": ["t1-success", "t2-failed"],
        "expected_output_artifacts": ["strategy.md"],
    }

    state = {
        "tasks": [t1, t2, t3],
        "completed_task_ids": ["t1-success"],  # t2-failed is NOT in completed_task_ids
        "agent_snapshots": {
            "product-strategist": {
                "name": "Product Strategist",
                "instructions": "Synthesize inputs",
                "execution_config": {"max_retries": 0},
            }
        },
    }

    success_resp = ProviderResponse(
        status=ProviderStatus.SUCCESS,
        output_text="# Product Strategy Formulated",
        exit_code=0,
    )

    with patch(
        "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = success_resp

        updated_task, _ = await _execute_single_task(t3, state, tmp_path)

        assert updated_task["status"] == "completed"
        # Verify only completed task is in used_context_sources
        sources = updated_task.get("used_context_sources", [])
        assert len(sources) == 1
        assert sources[0]["task_id"] == "t1-success"
        assert sources[0]["agent_slug"] == "product-researcher"

        # Verify prompt passed to provider contained t1 and NOT t2
        called_req: ProviderRequest = mock_exec.call_args[0][0]
        assert "Market Research Deliverable" in called_req.prompt
        assert "Corrupted output data" not in called_req.prompt


@pytest.mark.asyncio
async def test_parallel_stage_partial_failure_preserves_sibling_completion():
    """
    Verifies that in a concurrent wave [task-1, task-2], if task-2 fails and task-1 succeeds:
    - Task-1 is marked completed and has its artifacts registered.
    - Task-2 is marked failed.
    - Execution state transitions to FAILED without discarding task-1's completed work.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create project
        p_res = await client.post(
            "/api/v1/projects",
            json={
                "name": "Partial Wave Failure Project",
                "studio_type": "saas",
            },
        )
        project_id = p_res.json()["id"]

        # Stage 1 of SaaS pipeline runs task-1-market-research and task-2-competitor-analysis concurrently
        # Mock task-1 succeeding and task-2 failing
        def mock_side_effect(req):
            if "market-research" in req.prompt or "Product Researcher" in req.prompt:
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    output_text="# Market Research Succeeded",
                    exit_code=0,
                )
            else:
                return ProviderResponse(
                    status=ProviderStatus.FAILED,
                    output_text="",
                    exit_code=1,
                    error_message="Competitor scraper timed out",
                )

        with patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.side_effect = mock_side_effect

            exec_res = await client.post(
                "/api/v1/orchestrator/execute",
                json={
                    "project_id": project_id,
                    "objective": "Build invoicing pipeline with robust error boundaries",
                    "studio_type": "saas",
                },
            )
            assert exec_res.status_code == 202
            execution = exec_res.json()

            # Pipeline overall must be failed
            assert execution["status"] == "failed"

            # Task 1 must be completed and recorded in completed_task_ids
            completed_ids = execution["state_data"].get("completed_task_ids", [])
            assert "task-1-market-research" in completed_ids
            assert "task-2-competitor-analysis" not in completed_ids

            # Sibling Task 1's artifact must be registered in DB!
            art_res = await client.get(f"/api/v1/artifacts/project/{project_id}")
            assert art_res.status_code == 200
            artifacts = art_res.json()
            artifact_names = [a["name"] for a in artifacts]
            assert "research_findings.md" in artifact_names

            # Task records in DB: Task 1 COMPLETED, Task 2 FAILED
            tasks_res = await client.get(f"/api/v1/tasks/project/{project_id}")
            assert tasks_res.status_code == 200
            db_tasks = {t["title"]: t["status"] for t in tasks_res.json()}
            assert (
                db_tasks.get("Conduct Product & Market Opportunity Research")
                == TaskStatus.COMPLETED.value
            )
            assert (
                db_tasks.get("Execute Competitor Benchmarking & Gap Analysis")
                == TaskStatus.FAILED.value
            )
