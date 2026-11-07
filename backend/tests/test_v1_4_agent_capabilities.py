import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.project import Project, StudioType
from app.models.task import Task, TaskStatus
from app.models.usage import ModelExecution, ModelExecutionStatus
from app.models.workspace import Workspace
from app.orchestrator.planner import CapabilityMatcher, GoalDecomposer
from app.providers.base import BaseProvider, ProviderRequest, ProviderResponse, ProviderStatus
from app.services.agent_metrics_service import AgentMetricsService
from app.services.agent_service import DEFAULT_AGENTS, AgentService


def test_capability_matcher_selects_best_persona():
    """CapabilityMatcher maps required capability tags to the highest-scoring agent persona."""
    # Database migration & coding -> developer
    slug1 = CapabilityMatcher.match_agent(
        required_capabilities=["database_migrations", "code_implementation"],
        available_agents=DEFAULT_AGENTS,
        studio_type=StudioType.SAAS,
    )
    assert slug1 == "developer"

    # Automated testing & regression -> qa-engineer
    slug2 = CapabilityMatcher.match_agent(
        required_capabilities=["automated_testing", "regression_verification"],
        available_agents=DEFAULT_AGENTS,
        studio_type=StudioType.SAAS,
    )
    assert slug2 == "qa-engineer"

    # Competitor analysis -> competitor-analyst
    slug3 = CapabilityMatcher.match_agent(
        required_capabilities=["competitor_analysis", "feature_benchmarking"],
        available_agents=DEFAULT_AGENTS,
        studio_type=StudioType.SAAS,
    )
    assert slug3 == "competitor-analyst"

    # Topic research in media studio -> content-researcher
    slug4 = CapabilityMatcher.match_agent(
        required_capabilities=["topic_research", "reference_benchmarking"],
        available_agents=DEFAULT_AGENTS,
        studio_type=StudioType.MEDIA,
    )
    assert slug4 == "content-researcher"

    # Screenwriting in media studio -> scriptwriter
    slug5 = CapabilityMatcher.match_agent(
        required_capabilities=["screenwriting", "script_drafting"],
        available_agents=DEFAULT_AGENTS,
        studio_type=StudioType.MEDIA,
    )
    assert slug5 == "scriptwriter"


def test_capability_matcher_fallback_on_unmatched():
    """CapabilityMatcher returns fallback slug when capabilities cannot be matched or are empty."""
    slug_empty = CapabilityMatcher.match_agent(
        required_capabilities=[],
        available_agents=DEFAULT_AGENTS,
        studio_type=StudioType.SAAS,
        fallback_slug="custom-fallback",
    )
    assert slug_empty == "custom-fallback"

    slug_unknown = CapabilityMatcher.match_agent(
        required_capabilities=["teleportation", "quantum_telepathy"],
        available_agents=DEFAULT_AGENTS,
        studio_type=StudioType.SAAS,
        fallback_slug="default-persona",
    )
    assert slug_unknown == "default-persona"


@pytest.mark.asyncio
async def test_goal_decomposer_applies_capability_matching():
    """GoalDecomposer refines agent assignments using CapabilityMatcher when capabilities are generated."""
    mock_llm_json = """{
        "strategy_summary": "Capability matched test plan",
        "estimated_cost_usd": 0.02,
        "tasks": [
            {
                "task_id": "task-test-qa",
                "title": "Perform Automated Regression Suite",
                "description": "Run deterministic tests",
                "required_capabilities": ["automated_testing", "defect_analysis"],
                "dependencies": [],
                "expected_output_artifacts": ["test_report.json"]
            }
        ]
    }"""

    class MockCapabilityProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "mock_capability_provider"

        async def execute(self, request: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                output_text=mock_llm_json,
                exit_code=0,
                duration_ms=450,
                input_tokens=150,
                output_tokens=100,
                cost_usd=0.001,
            )

    plan = await GoalDecomposer.decompose_goal(
        objective="Run automated regression testing across SaaS microservices",
        project_id="proj-cap-test",
        studio_type=StudioType.SAAS,
        provider=MockCapabilityProvider(),
    )

    assert plan.is_valid_dag is True
    assert len(plan.tasks) == 1
    # Capability matching routed automated_testing to qa-engineer
    assert plan.tasks[0].assigned_agent_slug == "qa-engineer"


@pytest.mark.asyncio
async def test_agent_metrics_service_computes_accuracy():
    """AgentMetricsService aggregates task completion rates, remediations, tokens, and costs accurately."""
    test_slug = f"test-dev-{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        ws = Workspace(name="Metrics WS", slug=f"m-ws-{uuid.uuid4().hex[:6]}")
        db.add(ws)
        await db.flush()

        proj = Project(
            workspace_id=ws.id,
            name="Metrics Project",
            slug=f"m-proj-{uuid.uuid4().hex[:6]}",
            studio_type=StudioType.SAAS,
        )
        db.add(proj)
        await db.flush()

        # Seed 3 tasks: 2 completed (one with 2 remediation cycles), 1 failed
        t1 = Task(
            project_id=proj.id,
            title="Task 1",
            assigned_agent_slug=test_slug,
            status=TaskStatus.COMPLETED,
            remediation_history_json=[{"cycle": 1}, {"cycle": 2}],
        )
        t2 = Task(
            project_id=proj.id,
            title="Task 2",
            assigned_agent_slug=test_slug,
            status=TaskStatus.COMPLETED,
            remediation_history_json=[],
        )
        t3 = Task(
            project_id=proj.id,
            title="Task 3",
            assigned_agent_slug=test_slug,
            status=TaskStatus.FAILED,
            remediation_history_json=[],
        )
        db.add_all([t1, t2, t3])
        await db.flush()

        # Add usage records
        u1 = ModelExecution(
            task_id=t1.id,
            provider="claude_code",
            model="claude-haiku-5-5",
            duration_ms=1200,
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.005,
            status=ModelExecutionStatus.SUCCESS,
        )
        u2 = ModelExecution(
            task_id=t2.id,
            provider="claude_code",
            model="claude-haiku-5-5",
            duration_ms=800,
            input_tokens=300,
            output_tokens=150,
            cost_usd=0.003,
            status=ModelExecutionStatus.SUCCESS,
        )
        db.add_all([u1, u2])
        await db.flush()
        await db.commit()

        metrics = await AgentMetricsService.get_metrics_for_agent(db, test_slug)
        assert metrics is not None
        assert metrics.total_tasks_assigned == 3
        assert metrics.completed_tasks == 2
        assert metrics.failed_tasks == 1
        assert metrics.success_rate == 66.67
        assert metrics.total_remediations == 2
        assert metrics.total_tokens == 1150
        assert metrics.total_cost_usd == 0.008
        assert metrics.avg_duration_ms == 1000.0


@pytest.mark.asyncio
async def test_api_endpoints_agent_metrics():
    """REST API endpoints GET /api/v1/agents/metrics and GET /api/v1/agents/{slug}/metrics."""
    async with AsyncSessionLocal() as db:
        await AgentService.seed_default_agents(db)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test List all metrics
        resp_all = await client.get("/api/v1/agents/metrics")
        assert resp_all.status_code == 200
        metrics_all = resp_all.json()
        assert len(metrics_all) >= 16
        slugs = [m["agent_slug"] for m in metrics_all]
        assert "developer" in slugs
        assert "qa-engineer" in slugs

        # 2. Test Get specific agent metrics
        resp_dev = await client.get("/api/v1/agents/developer/metrics")
        assert resp_dev.status_code == 200
        dev_data = resp_dev.json()
        assert dev_data["agent_slug"] == "developer"
        assert "success_rate" in dev_data
        assert "total_remediations" in dev_data

        # 3. Test 404 for non-existent agent
        resp_404 = await client.get("/api/v1/agents/completely-fictional-agent/metrics")
        assert resp_404.status_code == 404
