"""M1.5-1b fail-closed execution tests (spec groups 3 and 4, remaining 8a items).

Settings are applied per test through the explicit ``fc_storage`` fixture (not autouse). Real
temporary git repositories are used. Provider calls are mocked and asserted to be absent where
a setup failure must prevent any execution.
"""

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.approval import ApprovalStatus
from app.models.artifact import Artifact
from app.models.execution import ExecutionEvent, ExecutionStatus
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.orchestrator.planner import GoalDecomposer, PlannedTask, PlannerService
from app.orchestrator.runner import OrchestrationRunner
from app.orchestrator.workflow_graph import artifact_node, dispatch_task_node
from app.providers.base import ProviderResponse, ProviderStatus
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.budget_governor import BudgetGovernor
from app.services.workflow_service import WorkflowService
from app.workspace import ExecutionSetupError, GitWorktreeManager
from app.workspace.path_security import resolve_execution_work_dir


@pytest.fixture
def fc_storage(monkeypatch, tmp_path: Path) -> Path:
    artifacts = tmp_path / "artifacts"
    worktrees = tmp_path / "worktrees"
    repos = tmp_path / "repos"
    for directory in (artifacts, worktrees, repos):
        directory.mkdir()
    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", artifacts)
    monkeypatch.setattr(settings, "WORKTREE_STORAGE_PATH", worktrees)
    monkeypatch.setattr(settings, "ALLOWED_REPO_ROOTS", [repos])
    return tmp_path


def _git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test Runner")
    _git(repo, "config", "user.email", "test@astrava.local")
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Initial commit")
    return repo


async def _seed_project(db, repo_path: str | None, base_branch: str = "main") -> uuid.UUID:
    ws = Workspace(name="FC WS", slug=f"fc-ws-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    proj = Project(
        workspace_id=ws.id,
        name="FC Project",
        slug=f"fc-proj-{uuid.uuid4().hex[:8]}",
        studio_type=StudioType.SAAS,
        repo_path=repo_path,
        base_branch=base_branch,
    )
    db.add(proj)
    await db.commit()
    return proj.id


async def _seed_bare_execution(project_id: uuid.UUID) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        wf = await WorkflowService.create_workflow(
            db, WorkflowCreate(project_id=project_id, name="FC WF", studio_type="saas")
        )
        execution = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf.id, project_id=project_id)
        )
        await db.commit()
        return execution.id


async def _event_types(db, execution_id: uuid.UUID) -> list[str]:
    stmt = select(ExecutionEvent.event_type).where(ExecutionEvent.execution_id == execution_id)
    return list((await db.execute(stmt)).scalars().all())


def _success_response() -> ProviderResponse:
    return ProviderResponse(
        status=ProviderStatus.SUCCESS,
        output_text="Deliverable content meeting approval criteria.\n",
        exit_code=0,
        duration_ms=1000,
        input_tokens=50,
        output_tokens=25,
        cost_usd=0.0005,
    )


def _provider_mock(response: ProviderResponse | None = None) -> MagicMock:
    provider = MagicMock()
    provider.execute = AsyncMock(return_value=response or _success_response())
    return provider


# ---------------------------------------------------------------------------
# Group 3: planner output names and artifact_node / adoption containment
# ---------------------------------------------------------------------------

UNSAFE_OUTPUT_NAMES = [
    "../../x",
    "/etc/x",
    ".git/hooks/x",
    ".GIT/x",
    ".git./x",
    "a\x00b.md",
    "sub\\..\\x",
    "",
]


@pytest.mark.parametrize("name", UNSAFE_OUTPUT_NAMES)
def test_planned_task_rejects_unsafe_output_names(name: str):
    with pytest.raises(ValidationError):
        PlannedTask(
            task_id="t-1",
            title="T",
            description="d",
            expected_output_artifacts=[name],
        )


def test_planned_task_accepts_safe_output_names():
    task = PlannedTask(
        task_id="t-1",
        title="T",
        description="d",
        expected_output_artifacts=["research_findings.md", "out/report.json"],
    )
    assert task.expected_output_artifacts == ["research_findings.md", "out/report.json"]


class _UnsafePlanProvider:
    """Provider stub returning a plan whose artifact names are hostile."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    async def execute(self, request):
        payload = {
            "strategy_summary": "hostile",
            "tasks": [
                {
                    "task_id": "task-hostile",
                    "title": "Hostile",
                    "description": "Write outside the work dir",
                    "expected_output_artifacts": self._names,
                }
            ],
        }
        return ProviderResponse(
            status=ProviderStatus.SUCCESS,
            output_text=json.dumps(payload),
            exit_code=0,
            duration_ms=1,
        )


@pytest.mark.asyncio
async def test_plan_with_unsafe_artifact_name_falls_back_to_template():
    project_id = str(uuid.uuid4())
    template = PlannerService.generate_plan(
        project_id=project_id,
        objective="Build a parser",
        studio_type=StudioType.SAAS,
        retrieval_context=None,
    )
    plan = await GoalDecomposer.decompose_goal(
        objective="Build a parser",
        project_id=project_id,
        studio_type=StudioType.SAAS,
        provider=_UnsafePlanProvider(["../../escape.md"]),
    )
    assert [t.task_id for t in plan.tasks] == [t.task_id for t in template.tasks]
    assert "task-hostile" not in [t.task_id for t in plan.tasks]


@pytest.mark.asyncio
async def test_artifact_node_writes_nothing_outside_work_dir(fc_storage: Path):
    project_id = uuid.uuid4()
    hostile_abs = f"/tmp/astrava-hostile-{uuid.uuid4().hex}.md"
    hostile_names = [
        "../escape.md",
        "sub/../../escape2.md",
        hostile_abs,
        ".git/hooks/post-merge",
        ".GIT/hooks/x",
        ".git./x",
    ]
    state = {
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "t1",
                "status": "completed",
                "output_text": "hello",
                "assigned_agent_slug": "developer",
                "expected_output_artifacts": [*hostile_names, "ok.md"],
            }
        ],
        "current_ready_task_ids": ["t1"],
        "completed_task_ids": [],
        "artifacts": [],
    }

    result = await artifact_node(state)

    assert [a["name"] for a in result["artifacts"]] == ["ok.md"]
    work_dir = fc_storage / "artifacts" / str(project_id)
    assert sorted(os.listdir(work_dir)) == ["ok.md"]
    assert not (fc_storage / "escape.md").exists()
    assert not (fc_storage / "escape2.md").exists()
    assert not Path(hostile_abs).exists()


@pytest.mark.asyncio
async def test_artifact_node_refuses_symlink_at_artifact_path(fc_storage: Path):
    project_id = uuid.uuid4()
    work_dir = fc_storage / "artifacts" / str(project_id)
    work_dir.mkdir(parents=True)
    victim = fc_storage / "victim.md"
    (work_dir / "ok.md").symlink_to(victim)
    state = {
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "t1",
                "status": "completed",
                "output_text": "payload",
                "assigned_agent_slug": "developer",
                "expected_output_artifacts": ["ok.md"],
            }
        ],
        "current_ready_task_ids": ["t1"],
        "completed_task_ids": [],
        "artifacts": [],
    }

    result = await artifact_node(state)

    assert result["artifacts"] == []
    assert not victim.exists()


@pytest.mark.asyncio
async def test_adoption_ignores_hostile_artifact_name(fc_storage: Path, db_session):
    project_id = await _seed_project(db_session, None)
    execution_id = await _seed_bare_execution(project_id)

    # A fresh file OUTSIDE the work dir must not satisfy the hostile artifact name.
    outside = fc_storage / "escape.md"
    outside.write_text("planted outside the work dir\n", encoding="utf-8")

    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        res0 = await BudgetGovernor.reserve(
            db,
            execution_id,
            "task:hostile-task:attempt:0",
            task_id="hostile-task",
            estimated_cost_usd=0.01,
            attempt_number=0,
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
                "output_text": "Adopted output that must not be used",
            },
        )
        await db.commit()

    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "hostile-task",
                "title": "Hostile",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
                "expected_output_artifacts": ["../escape.md"],
            }
        ],
        "current_ready_task_ids": ["hostile-task"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
        "agent_snapshots": {"developer": {"name": "Dev", "execution_config": {"max_retries": 1}}},
    }

    provider = _provider_mock(
        ProviderResponse(status=ProviderStatus.FAILED, output_text="", exit_code=1, duration_ms=1)
    )
    with patch("app.providers.factory.ProviderFactory.get_provider", return_value=provider):
        result = await dispatch_task_node(state)

    task_res = result["tasks"][0]
    assert task_res["output_text"] != "Adopted output that must not be used"
    assert task_res["status"] != "completed"
    assert provider.execute.await_count >= 1


# ---------------------------------------------------------------------------
# Group 4: resolve_execution_work_dir and create_worktree containment
# ---------------------------------------------------------------------------


def test_resolve_work_dir_returns_project_dir_for_repo_less_state(fc_storage: Path):
    project_id = str(uuid.uuid4())
    result = resolve_execution_work_dir({"project_id": project_id})
    assert result == (fc_storage / "artifacts" / project_id).resolve()
    assert result.is_dir()


def test_resolve_work_dir_returns_existing_contained_worktree(fc_storage: Path):
    wt = fc_storage / "worktrees" / "exec-ok"
    wt.mkdir()
    result = resolve_execution_work_dir({"project_id": "p", "worktree_path": str(wt)})
    assert result == wt.resolve()


def test_resolve_work_dir_raises_for_missing_worktree_dir(fc_storage: Path):
    missing = fc_storage / "worktrees" / "gone"
    with pytest.raises(ExecutionSetupError):
        resolve_execution_work_dir({"project_id": "p", "worktree_path": str(missing)})


def test_resolve_work_dir_raises_for_worktree_outside_storage(fc_storage: Path):
    outside = fc_storage / "elsewhere"
    outside.mkdir()
    with pytest.raises(ExecutionSetupError):
        resolve_execution_work_dir({"project_id": "p", "worktree_path": str(outside)})


def test_resolve_work_dir_raises_for_repo_without_worktree(fc_storage: Path):
    with pytest.raises(ExecutionSetupError):
        resolve_execution_work_dir({"project_id": "p", "repo_path": str(fc_storage / "repos")})


@pytest.mark.asyncio
async def test_artifact_node_fails_closed_when_worktree_missing(fc_storage: Path):
    state = {
        "project_id": str(uuid.uuid4()),
        "worktree_path": str(fc_storage / "worktrees" / "deleted"),
        "tasks": [],
        "current_ready_task_ids": [],
        "artifacts": [],
    }
    with pytest.raises(ExecutionSetupError):
        await artifact_node(state)


@pytest.mark.asyncio
async def test_create_worktree_refuses_repo_outside_allowlist(fc_storage: Path):
    outside = _init_repo(fc_storage / "elsewhere" / "proj")
    wt_dir = fc_storage / "worktrees" / "exec-x"
    with pytest.raises(ExecutionSetupError):
        await GitWorktreeManager.create_worktree(
            repo_path=outside,
            execution_id="exec-x",
            base_branch="main",
            worktree_dir=wt_dir,
        )
    assert not wt_dir.exists()


# ---------------------------------------------------------------------------
# Group 3/4: runner fail-closed setup and resume
# ---------------------------------------------------------------------------


async def _start_saas(db, project_id, *, extra_patch=None):
    """Start a repo-backed pipeline and return (execution, provider factory mock, execute mock)."""
    with (
        patch(
            "app.providers.factory.ProviderFactory.get_provider",
            new=MagicMock(return_value=_provider_mock()),
        ) as factory,
        patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
            new_callable=AsyncMock,
        ) as execute,
    ):
        execute.return_value = _success_response()
        if extra_patch is not None:
            extra_patch()
        execution = await OrchestrationRunner.start_pipeline(
            db=db,
            project_id=project_id,
            objective="Build a parser",
            studio_type="saas",
        )
    return execution, factory, execute


@pytest.mark.asyncio
async def test_setup_failure_when_create_worktree_raises(fc_storage: Path, db_session, monkeypatch):
    repo = _init_repo(fc_storage / "repos" / "proj")
    project_id = await _seed_project(db_session, str(repo))
    monkeypatch.setattr(
        GitWorktreeManager, "create_worktree", AsyncMock(side_effect=RuntimeError("boom"))
    )

    execution, factory, execute = await _start_saas(db_session, project_id)

    assert execution.status == ExecutionStatus.FAILED
    assert factory.call_count == 0
    assert execute.await_count == 0
    assert "execution_setup_failed" in await _event_types(db_session, execution.id)
    assert await BudgetGovernor.get_budget(db_session, execution.id) is None


@pytest.mark.asyncio
async def test_setup_failure_when_repo_directory_missing(fc_storage: Path, db_session):
    project_id = await _seed_project(db_session, str(fc_storage / "repos" / "gone"))

    execution, factory, execute = await _start_saas(db_session, project_id)

    assert execution.status == ExecutionStatus.FAILED
    assert factory.call_count == 0 and execute.await_count == 0
    assert "execution_setup_failed" in await _event_types(db_session, execution.id)


@pytest.mark.asyncio
async def test_setup_failure_when_repo_outside_allowlist(fc_storage: Path, db_session):
    repo = _init_repo(fc_storage / "elsewhere" / "proj")
    project_id = await _seed_project(db_session, str(repo))

    execution, factory, execute = await _start_saas(db_session, project_id)

    assert execution.status == ExecutionStatus.FAILED
    assert factory.call_count == 0 and execute.await_count == 0
    reasons = [
        e.payload.get("reason")
        for e in (await WorkflowService.list_events(db_session, execution.id))
        if e.event_type == "execution_setup_failed"
    ]
    assert reasons and "ALLOWED_REPO_ROOTS" in reasons[0]


@pytest.mark.asyncio
async def test_setup_failure_for_missing_base_branch_has_no_head_fallback(
    fc_storage: Path, db_session
):
    repo = _init_repo(fc_storage / "repos" / "proj")
    project_id = await _seed_project(db_session, str(repo), base_branch="no-such-branch")

    execution, factory, execute = await _start_saas(db_session, project_id)

    assert execution.status == ExecutionStatus.FAILED
    assert factory.call_count == 0 and execute.await_count == 0
    assert "astrava/exec-" not in _git(repo, "branch", "--list")
    reasons = [
        e.payload.get("reason")
        for e in (await WorkflowService.list_events(db_session, execution.id))
        if e.event_type == "execution_setup_failed"
    ]
    assert reasons
    # Persisted reason must not expose host locations.
    for path in (str(repo), str(fc_storage)):
        assert path not in reasons[0]
    assert execution.error_message and str(fc_storage) not in execution.error_message


@pytest.mark.asyncio
async def test_setup_failure_budget_endpoint_reports_no_active_budget(fc_storage: Path, db_session):
    repo = _init_repo(fc_storage / "repos" / "proj")
    project_id = await _seed_project(db_session, str(repo), base_branch="missing-base")
    execution, _factory, _execute = await _start_saas(db_session, project_id)
    assert execution.status == ExecutionStatus.FAILED

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/api/v1/executions/{execution.id}/budget")

    assert res.status_code == 404
    assert res.json()["detail"] == "Budget not found for execution"
    assert await BudgetGovernor.get_budget(db_session, execution.id) is None


@pytest.mark.asyncio
async def test_repo_scan_failure_stays_non_fatal(fc_storage: Path, db_session):
    repo = _init_repo(fc_storage / "repos" / "proj")
    project_id = await _seed_project(db_session, str(repo))

    with patch("app.orchestrator.runner.RepoScanner.scan", side_effect=RuntimeError("scan broke")):
        execution, _factory, _execute = await _start_saas(db_session, project_id)

    assert execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.WAITING_APPROVAL)
    assert execution.worktree_path is not None
    assert "execution_setup_failed" not in await _event_types(db_session, execution.id)


@pytest.mark.asyncio
async def test_resume_after_worktree_deleted_fails_closed(fc_storage: Path, db_session):
    repo = _init_repo(fc_storage / "repos" / "proj")
    project_id = await _seed_project(db_session, str(repo))

    # Media studio pipeline: the run stops at the approval gate with a live worktree.
    with (
        patch(
            "app.providers.factory.ProviderFactory.get_provider",
            new=MagicMock(return_value=_provider_mock()),
        ),
        patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
            new_callable=AsyncMock,
        ) as execute,
    ):
        execute.return_value = _success_response()
        execution = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project_id,
            objective="Produce video documentary episode using AV1 codec",
            studio_type="media",
        )
    assert execution.status == ExecutionStatus.WAITING_APPROVAL
    wt = Path(execution.worktree_path)
    assert wt.is_dir()
    shutil.rmtree(wt)
    calls_before = execute.await_count

    with (
        patch(
            "app.providers.factory.ProviderFactory.get_provider",
            new=MagicMock(return_value=_provider_mock()),
        ) as factory,
        patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
            new_callable=AsyncMock,
        ) as resume_execute,
    ):
        resume_execute.return_value = _success_response()
        resumed = await OrchestrationRunner.resume_pipeline(
            db=db_session,
            execution_id=execution.id,
            decision_req=ApprovalDecisionRequest(
                decision=ApprovalStatus.APPROVED,
                reason="Approve after worktree loss",
                decided_by="operator-1",
            ),
        )

    assert resumed.status == ExecutionStatus.FAILED
    assert "execution_setup_failed" in await _event_types(db_session, execution.id)
    assert factory.call_count == 0
    assert resume_execute.await_count == 0
    assert execute.await_count == calls_before
    assert not wt.exists()


@pytest.mark.asyncio
async def test_project_without_repo_path_still_completes_and_registers_provenance(
    fc_storage: Path, db_session
):
    project_id = await _seed_project(db_session, None)

    with (
        patch(
            "app.providers.factory.ProviderFactory.get_provider",
            new=MagicMock(return_value=_provider_mock()),
        ),
        patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
            new_callable=AsyncMock,
        ) as execute,
    ):
        execute.return_value = _success_response()
        execution = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project_id,
            objective="Produce video documentary episode using AV1 codec",
            studio_type="media",
        )
        assert execution.status == ExecutionStatus.WAITING_APPROVAL
        assert execution.worktree_path is None
        resumed = await OrchestrationRunner.resume_pipeline(
            db=db_session,
            execution_id=execution.id,
            decision_req=ApprovalDecisionRequest(
                decision=ApprovalStatus.APPROVED,
                reason="Approved",
                decided_by="operator-1",
            ),
        )

    assert resumed.status == ExecutionStatus.COMPLETED
    assert "execution_setup_failed" not in await _event_types(db_session, execution.id)

    rows = (
        (await db_session.execute(select(Artifact).where(Artifact.execution_id == execution.id)))
        .scalars()
        .all()
    )
    assert rows, "expected orchestrator-registered artifacts"
    for row in rows:
        provenance = row.metadata_json["provenance"]
        assert provenance["source"] == "orchestrator"
        assert provenance["registered_by"] == "orchestrator"
        assert provenance.get("producing_agent_slug")
        assert row.task_id is not None


@pytest.mark.asyncio
async def test_task_level_setup_error_propagates_through_dispatch_gather(
    fc_storage: Path, db_session
):
    """A setup error raised inside a task must not be recorded as an ordinary task failure."""
    project_id = await _seed_project(db_session, None)
    execution_id = await _seed_bare_execution(project_id)
    async with AsyncSessionLocal() as db:
        await BudgetGovernor.initialize_budget(db, execution_id, project_id)
        await db.commit()
    state = {
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        "tasks": [
            {
                "task_id": "t1",
                "title": "T",
                "assigned_agent_slug": "developer",
                "status": "pending",
                "output_text": "",
                "expected_output_artifacts": [],
            }
        ],
        "current_ready_task_ids": ["t1"],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "usage_records": [],
        "agent_snapshots": {},
    }
    with (
        patch(
            "app.orchestrator.workflow_graph._execute_single_task",
            new=AsyncMock(side_effect=ExecutionSetupError("worktree vanished")),
        ),
    ):
        with pytest.raises(ExecutionSetupError):
            await dispatch_task_node(state)
