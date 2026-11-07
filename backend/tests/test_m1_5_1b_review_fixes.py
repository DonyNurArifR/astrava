"""M1.5-1b review fixes B5: budget close on setup failure, artifact file requirements,
worktree provenance, and repository-controlled git program hardening.

Real temporary git repositories are used. Each git-hardening test first proves the marker WOULD
be written by plain git in the same repository (a control), then asserts it is NOT written by
ASTRAVA's own operations.
"""

import hashlib
import os
import stat
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.approval import ApprovalStatus
from app.models.artifact import Artifact
from app.models.budget import BudgetReservation, BudgetReservationStatus, BudgetStatus
from app.models.execution import ExecutionStatus
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.orchestrator.runner import OrchestrationRunner
from app.providers.base import ProviderResponse, ProviderStatus
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.artifact import ArtifactCreate
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.artifact_service import ArtifactService
from app.services.budget_governor import BudgetGovernor
from app.services.workflow_service import WorkflowService
from app.verification.engine import VerificationEngine
from app.workspace import GitWorktreeManager


@pytest.fixture
def b5_storage(monkeypatch, tmp_path: Path) -> Path:
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
    (repo / "README.md").write_text("# Repo\nInitial\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Initial commit")
    return repo


def _write_hook_script(path: Path, marker: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


async def _seed_project(db, repo_path: str | None) -> uuid.UUID:
    ws = Workspace(name="B5 WS", slug=f"b5-ws-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    proj = Project(
        workspace_id=ws.id,
        name="B5 Project",
        slug=f"b5-proj-{uuid.uuid4().hex[:8]}",
        studio_type=StudioType.SAAS,
        repo_path=repo_path,
        base_branch="main",
    )
    db.add(proj)
    await db.commit()
    return proj.id


async def _seed_bare_execution(project_id: uuid.UUID) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        wf = await WorkflowService.create_workflow(
            db, WorkflowCreate(project_id=project_id, name="B5 WF", studio_type="saas")
        )
        execution = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf.id, project_id=project_id)
        )
        await db.commit()
        return execution.id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


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


# ---------------------------------------------------------------------------
# F-02: setup failure after a budget exists closes it and releases reservations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_setup_failure_closes_budget_and_releases_reservation(
    b5_storage: Path, db_session
):
    repo = _init_repo(b5_storage / "repos" / "proj")
    project_id = await _seed_project(db_session, str(repo))

    with (
        patch(
            "app.providers.factory.ProviderFactory.get_provider",
            new=MagicMock(
                return_value=MagicMock(execute=AsyncMock(return_value=_success_response()))
            ),
        ),
        patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
            new_callable=AsyncMock,
            return_value=_success_response(),
        ),
    ):
        execution = await OrchestrationRunner.start_pipeline(
            db=db_session,
            project_id=project_id,
            objective="Produce video documentary episode using AV1 codec",
            studio_type="media",
        )
    assert execution.status == ExecutionStatus.WAITING_APPROVAL
    wt = Path(execution.worktree_path)

    budget = await BudgetGovernor.get_budget(db_session, execution.id)
    assert budget.status != BudgetStatus.CANCELLED
    reserved_before = budget.reserved_cost_usd

    # An open reservation exists when the operator approves after the worktree was lost.
    await BudgetGovernor.reserve(
        db_session,
        execution.id,
        "task:open-task:attempt:0",
        task_id="open-task",
        estimated_cost_usd=0.01,
        attempt_number=0,
    )
    await db_session.commit()
    budget = await BudgetGovernor.get_budget(db_session, execution.id)
    assert budget.active_reservations_count >= 1

    import shutil

    shutil.rmtree(wt)
    with (
        patch(
            "app.providers.factory.ProviderFactory.get_provider",
            new=MagicMock(
                return_value=MagicMock(execute=AsyncMock(return_value=_success_response()))
            ),
        ),
        patch(
            "app.providers.claude_code.ClaudeCodeCLIProvider.execute",
            new_callable=AsyncMock,
            return_value=_success_response(),
        ),
    ):
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

    await db_session.commit()
    budget = await BudgetGovernor.get_budget(db_session, execution.id)
    assert budget.status == BudgetStatus.CANCELLED
    open_rows = (
        (
            await db_session.execute(
                select(BudgetReservation).where(
                    BudgetReservation.budget_id == budget.id,
                    BudgetReservation.status == BudgetReservationStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert open_rows == []
    assert budget.reserved_cost_usd == reserved_before

    async with _client() as client:
        res = await client.get(f"/api/v1/executions/{execution.id}/budget")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# F-03: API artifacts must exist on disk; client size and hash are ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_rejects_registration_of_missing_file(b5_storage: Path, db_session):
    project_id = await _seed_project(db_session, None)
    payload = {
        "project_id": str(project_id),
        "name": "missing.md",
        "file_path": f"{project_id}/missing.md",
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 400
    assert res.json()["detail"] == "Artifact file does not exist"


@pytest.mark.asyncio
async def test_api_ignores_client_size_and_hashes_the_file_on_disk(b5_storage: Path, db_session):
    project_id = await _seed_project(db_session, None)
    body = b"hello"
    target = b5_storage / "artifacts" / str(project_id) / "greet.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(body)
    payload = {
        "project_id": str(project_id),
        "name": "greet.txt",
        "file_path": f"{project_id}/greet.txt",
        "file_size_bytes": 999,
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["file_size_bytes"] == len(body)
    assert data["metadata_json"]["provenance"]["size_bytes"] == len(body)
    assert data["metadata_json"]["provenance"]["sha256"] == hashlib.sha256(body).hexdigest()


@pytest.mark.asyncio
async def test_orchestrator_still_accepts_missing_worktree_file_with_caller_size(
    b5_storage: Path, db_session
):
    project_id = await _seed_project(db_session, None)
    execution_id = await _seed_bare_execution(project_id)
    data = ArtifactCreate(
        project_id=project_id,
        execution_id=execution_id,
        name="later.md",
        file_path=f"{project_id}/later.md",
        file_size_bytes=42,
    )
    artifact = await ArtifactService.register_artifact(
        db_session, data, source="orchestrator", registered_by="orchestrator"
    )
    await db_session.commit()
    assert artifact.file_size_bytes == 42
    assert artifact.metadata_json["provenance"]["source"] == "orchestrator"


# ---------------------------------------------------------------------------
# F-01: worktree artifacts record the worktree file's hash and location
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worktree_artifact_provenance_uses_worktree_file(b5_storage: Path, db_session):
    project_id = await _seed_project(db_session, None)
    execution_id = await _seed_bare_execution(project_id)
    worktree = b5_storage / "worktrees" / str(execution_id)
    worktree.mkdir()
    (worktree / "out.md").write_text("worktree content", encoding="utf-8")
    storage_dir = b5_storage / "artifacts" / str(project_id)
    storage_dir.mkdir(parents=True)
    (storage_dir / "out.md").write_text("storage content differs", encoding="utf-8")

    state = {
        "worktree_path": str(worktree),
        "tasks": [],
        "artifacts": [
            {
                "name": "out.md",
                "file_path": f"{project_id}/out.md",
                "size_bytes": 16,
                "producing_agent_slug": "developer",
            }
        ],
    }
    await OrchestrationRunner._sync_state_to_db(db_session, execution_id, project_id, state)
    await db_session.commit()

    rows = (
        (await db_session.execute(select(Artifact).where(Artifact.execution_id == execution_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    provenance = rows[0].metadata_json["provenance"]
    assert provenance["location"] == "worktree"
    assert provenance["source"] == "orchestrator"
    assert provenance["sha256"] == hashlib.sha256(b"worktree content").hexdigest()


@pytest.mark.asyncio
async def test_worktree_artifact_missing_in_worktree_has_no_hash(b5_storage: Path, db_session):
    project_id = await _seed_project(db_session, None)
    execution_id = await _seed_bare_execution(project_id)
    worktree = b5_storage / "worktrees" / str(execution_id)
    worktree.mkdir()
    storage_dir = b5_storage / "artifacts" / str(project_id)
    storage_dir.mkdir(parents=True)
    (storage_dir / "gone.md").write_text("stale storage copy", encoding="utf-8")
    state = {
        "worktree_path": str(worktree),
        "tasks": [],
        "artifacts": [{"name": "gone.md", "file_path": f"{project_id}/gone.md", "size_bytes": 3}],
    }
    await OrchestrationRunner._sync_state_to_db(db_session, execution_id, project_id, state)
    await db_session.commit()
    rows = (
        (await db_session.execute(select(Artifact).where(Artifact.execution_id == execution_id)))
        .scalars()
        .all()
    )
    provenance = rows[0].metadata_json["provenance"]
    assert provenance["location"] == "worktree"
    assert provenance["sha256"] is None


@pytest.mark.asyncio
async def test_api_artifact_records_storage_location(b5_storage: Path, db_session):
    project_id = await _seed_project(db_session, None)
    target = b5_storage / "artifacts" / str(project_id) / "api.txt"
    target.parent.mkdir(parents=True)
    target.write_text("api content", encoding="utf-8")
    payload = {
        "project_id": str(project_id),
        "name": "api.txt",
        "file_path": f"{project_id}/api.txt",
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 201, res.text
    provenance = res.json()["metadata_json"]["provenance"]
    assert provenance["location"] == "storage"
    assert provenance["sha256"] == hashlib.sha256(b"api content").hexdigest()


@pytest.mark.asyncio
async def test_api_source_ignores_observed_hash_and_worktree_location(b5_storage: Path, db_session):
    project_id = await _seed_project(db_session, None)
    target = b5_storage / "artifacts" / str(project_id) / "api2.txt"
    target.parent.mkdir(parents=True)
    target.write_text("disk content", encoding="utf-8")
    data = ArtifactCreate(
        project_id=project_id, name="api2.txt", file_path=f"{project_id}/api2.txt"
    )
    artifact = await ArtifactService.register_artifact(
        db_session, data, observed_sha256="deadbeef", location="worktree"
    )
    await db_session.commit()
    provenance = artifact.metadata_json["provenance"]
    assert provenance["location"] == "storage"
    assert provenance["sha256"] == hashlib.sha256(b"disk content").hexdigest()


# ---------------------------------------------------------------------------
# Git hardening: repository-controlled fsmonitor and diff drivers never run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_fsmonitor_program_never_runs_during_hardened_operations(b5_storage: Path):
    repo = _init_repo(b5_storage / "repos" / "fsmon")
    marker = b5_storage / "fsmonitor-marker"
    script = _write_hook_script(b5_storage / "bin" / "fsmon.sh", marker)
    _git(repo, "config", "core.fsmonitor", str(script))

    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo,
        execution_id="fsmon-exec",
        base_branch="main",
        worktree_dir=b5_storage / "worktrees" / "fsmon-exec",
    )
    wt = Path(ctx.worktree_path)
    (wt / "README.md").write_text("changed\n", encoding="utf-8")

    # Control: plain git in the same repository DOES run the configured program.
    _git(wt, "status", "--porcelain")
    assert marker.exists(), "control failed: plain git did not run core.fsmonitor"
    marker.unlink()

    await GitWorktreeManager.get_diff(wt, base_branch="main")
    assert not marker.exists()

    sha = await GitWorktreeManager.commit_changes(wt, message="change")
    assert sha is not None
    assert not marker.exists()

    await GitWorktreeManager.cleanup_worktree(
        repo_path=repo, worktree_path=wt, branch_name=ctx.branch_name, delete_branch=False
    )
    ok, _ = await GitWorktreeManager.merge_worktree(repo, ctx.branch_name, "main")
    assert ok is True
    assert not marker.exists()


@pytest.mark.asyncio
async def test_repo_diff_driver_never_runs_during_hardened_operations(b5_storage: Path):
    repo = _init_repo(b5_storage / "repos" / "difftool")
    marker = b5_storage / "diff-driver-marker"
    script = _write_hook_script(b5_storage / "bin" / "diff-driver.sh", marker)
    _git(repo, "config", "diff.external", str(script))

    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo,
        execution_id="difftool-exec",
        base_branch="main",
        worktree_dir=b5_storage / "worktrees" / "difftool-exec",
    )
    wt = Path(ctx.worktree_path)
    (wt / "README.md").write_text("changed for diff\n", encoding="utf-8")

    # Control: plain `git diff` in the same repository DOES run the external diff driver.
    _git(wt, "diff")
    assert marker.exists(), "control failed: plain git diff did not run diff.external"
    marker.unlink()

    diff = await GitWorktreeManager.get_diff(wt, base_branch="main")
    assert diff.has_changes is True
    assert not marker.exists()

    report_diff = await VerificationEngine.collect_git_diff(wt)
    assert "changed for diff" in report_diff
    assert not marker.exists()

    await GitWorktreeManager.commit_changes(wt, message="change")
    assert not marker.exists()
