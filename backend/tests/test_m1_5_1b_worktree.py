"""M1.5-1b worktree and projects/executions containment tests (spec groups 5, 6, 8a git parts).

Real temporary git repositories are used. Repositories live under <tmp>/repos and worktrees
under <tmp>/worktrees through the explicit ``git_sandbox`` fixture (not autouse). Test git
commands run with an explicit committer identity configured inside each temporary repo.
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.execution import ExecutionStatus, WorkflowExecution
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.schemas.workflow import WorkflowCreate
from app.services.workflow_service import WorkflowService
from app.workspace import ExecutionSetupError, GitWorktreeManager, PathContainmentError
from app.workspace.path_security import validate_repo_path

EXEC_ID = "3f2a9c10-0000-4000-8000-000000000001"


@pytest.fixture
def git_sandbox(monkeypatch, tmp_path: Path) -> Path:
    repos = tmp_path / "repos"
    worktrees = tmp_path / "worktrees"
    repos.mkdir()
    worktrees.mkdir()
    monkeypatch.setattr(settings, "ALLOWED_REPO_ROOTS", [repos])
    monkeypatch.setattr(settings, "WORKTREE_STORAGE_PATH", worktrees)
    return tmp_path


def _git(repo: Path, *args: str) -> str:
    # Test helper ignores ambient GIT_* so monkeypatched decoy variables cannot leak into asserts.
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


def _rev(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


async def _execution_branch(repo: Path, storage: Path, exec_id: str = EXEC_ID):
    """Create an execution worktree, commit one file on its branch, and remove the worktree."""
    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo,
        execution_id=exec_id,
        base_branch="main",
        worktree_dir=storage / "worktrees" / exec_id,
    )
    (Path(ctx.worktree_path) / "feature.txt").write_text("feature\n", encoding="utf-8")
    sha = await GitWorktreeManager.commit_changes(ctx.worktree_path, message="Add feature")
    assert sha is not None
    await GitWorktreeManager.cleanup_worktree(
        repo_path=repo,
        worktree_path=ctx.worktree_path,
        branch_name=ctx.branch_name,
        delete_branch=False,
    )
    return ctx


# ---------------------------------------------------------------------------
# Group 5: worktree manager (real temporary git repositories)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_refused_when_repo_is_on_another_branch(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await _execution_branch(repo, git_sandbox)
    _git(repo, "checkout", "-b", "side")
    main_before = _rev(repo, "main")
    side_before = _rev(repo, "side")
    exec_before = _rev(repo, ctx.branch_name)

    ok, message = await GitWorktreeManager.merge_worktree(repo, ctx.branch_name, "main")

    assert ok is False
    assert "Repository is on 'side' but merge target is 'main'" in message
    assert _rev(repo, "main") == main_before
    assert _rev(repo, "side") == side_before
    assert _rev(repo, ctx.branch_name) == exec_before
    assert _git(repo, "symbolic-ref", "--short", "HEAD") == "side"


@pytest.mark.asyncio
async def test_merge_refused_for_dirty_tracked_file(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await _execution_branch(repo, git_sandbox)
    (repo / "README.md").write_text("local uncommitted edit\n", encoding="utf-8")
    main_before = _rev(repo, "main")

    ok, message = await GitWorktreeManager.merge_worktree(repo, ctx.branch_name, "main")

    assert ok is False
    assert "uncommitted tracked changes" in message
    assert _rev(repo, "main") == main_before
    assert (repo / "README.md").read_text(encoding="utf-8") == "local uncommitted edit\n"


@pytest.mark.asyncio
async def test_merge_ignores_untracked_files(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await _execution_branch(repo, git_sandbox)
    (repo / "scratch.txt").write_text("untracked\n", encoding="utf-8")

    ok, _ = await GitWorktreeManager.merge_worktree(repo, ctx.branch_name, "main")

    assert ok is True
    assert (repo / "feature.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["does-not-exist", "-x", "../main", "main..x", "x y"])
async def test_merge_refused_for_missing_or_invalid_target(git_sandbox: Path, target: str):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await _execution_branch(repo, git_sandbox)
    main_before = _rev(repo, "main")

    ok, message = await GitWorktreeManager.merge_worktree(repo, ctx.branch_name, target)

    assert ok is False
    assert message
    assert _rev(repo, "main") == main_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "branch", ["feature/other", "main", "astrava/exec-missing", "-x", "astrava/../main"]
)
async def test_merge_refused_for_branch_outside_execution_namespace(git_sandbox: Path, branch: str):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    _git(repo, "branch", "feature/other")
    main_before = _rev(repo, "main")

    ok, _ = await GitWorktreeManager.merge_worktree(repo, branch, "main")

    assert ok is False
    assert _rev(repo, "main") == main_before


@pytest.mark.asyncio
async def test_merge_lands_exactly_on_target_branch(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await _execution_branch(repo, git_sandbox)
    _git(repo, "branch", "other")
    other_before = _rev(repo, "other")
    exec_tip = _rev(repo, ctx.branch_name)
    main_before = _rev(repo, "main")

    ok, output = await GitWorktreeManager.merge_worktree(repo, ctx.branch_name, "main")

    assert ok is True, output
    merge_commit = _rev(repo, "main")
    assert merge_commit != main_before
    parents = _git(repo, "rev-list", "--parents", "-n", "1", "main").split()[1:]
    assert parents == [main_before, exec_tip]
    assert _rev(repo, "other") == other_before
    assert _git(repo, "symbolic-ref", "--short", "HEAD") == "main"
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "feature\n"


@pytest.mark.asyncio
async def test_merge_does_not_run_repository_hooks(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await _execution_branch(repo, git_sandbox)
    marker_dir = git_sandbox / "markers"
    marker_dir.mkdir()
    for hook in ("pre-merge-commit", "post-merge"):
        hook_path = repo / ".git" / "hooks" / hook
        hook_path.write_text(
            f"#!/bin/sh\ntouch '{marker_dir / hook}'\n",
            encoding="utf-8",
        )
        hook_path.chmod(0o755)

    ok, _ = await GitWorktreeManager.merge_worktree(repo, ctx.branch_name, "main")

    assert ok is True
    assert list(marker_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_hook_control_proves_hooks_fire_without_hardening(git_sandbox: Path):
    """Control: the same hook DOES fire under plain git, so the test above is meaningful."""
    repo = _init_repo(git_sandbox / "repos" / "control")
    marker = git_sandbox / "control-marker"
    hook_path = repo / ".git" / "hooks" / "pre-commit"
    hook_path.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
    hook_path.chmod(0o755)
    (repo / "x.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-m", "control")
    assert marker.exists()


@pytest.mark.asyncio
async def test_create_worktree_refuses_dash_prefixed_and_missing_base(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    wt_dir = git_sandbox / "worktrees" / "exec-a"

    for base in ("--upload-pack=touch", "-b", "no-such-branch"):
        with pytest.raises(ExecutionSetupError):
            await GitWorktreeManager.create_worktree(
                repo_path=repo,
                execution_id="exec-a",
                base_branch=base,
                worktree_dir=wt_dir,
            )
        assert not wt_dir.exists()
    assert "astrava/exec-exec-a" not in _git(repo, "branch", "--list")


@pytest.mark.asyncio
async def test_create_worktree_refuses_directory_outside_storage(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    outside = git_sandbox / "outside-wt"

    with pytest.raises(ExecutionSetupError):
        await GitWorktreeManager.create_worktree(
            repo_path=repo,
            execution_id="exec-b",
            base_branch="main",
            worktree_dir=outside,
        )
    assert not outside.exists()


@pytest.mark.asyncio
async def test_cleanup_refuses_path_outside_storage_and_keeps_it(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    outside = git_sandbox / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("do not delete\n", encoding="utf-8")

    result = await GitWorktreeManager.cleanup_worktree(
        repo_path=repo,
        worktree_path=outside,
        branch_name=None,
        delete_branch=False,
    )

    assert result is False
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "do not delete\n"


@pytest.mark.asyncio
async def test_cleanup_refuses_invalid_branch_name(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await _execution_branch(repo, git_sandbox)

    result = await GitWorktreeManager.cleanup_worktree(
        repo_path=repo,
        worktree_path=ctx.worktree_path,
        branch_name="-D",
        delete_branch=True,
    )

    assert result is False
    assert ctx.branch_name in _git(repo, "branch", "--list", ctx.branch_name)


@pytest.mark.asyncio
async def test_commit_changes_rejects_worktree_outside_storage(git_sandbox: Path):
    outside = git_sandbox / "not-storage"
    outside.mkdir()
    (outside / "f.txt").write_text("x\n", encoding="utf-8")

    with pytest.raises(PathContainmentError):
        await GitWorktreeManager.commit_changes(outside, message="must not run")


@pytest.mark.asyncio
async def test_get_diff_rejects_worktree_outside_storage_and_invalid_base(git_sandbox: Path):
    outside = git_sandbox / "not-storage"
    outside.mkdir()
    with pytest.raises(PathContainmentError):
        await GitWorktreeManager.get_diff(outside, base_branch="main")

    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await _execution_branch(repo, git_sandbox)
    with pytest.raises(PathContainmentError):
        await GitWorktreeManager.get_diff(ctx.worktree_path, base_branch="-x")


@pytest.mark.asyncio
async def test_get_diff_falls_back_to_head_for_display_only(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo,
        execution_id=EXEC_ID,
        base_branch="main",
        worktree_dir=git_sandbox / "worktrees" / EXEC_ID,
    )
    (Path(ctx.worktree_path) / "scratch.txt").write_text("new\n", encoding="utf-8")

    diff = await GitWorktreeManager.get_diff(ctx.worktree_path, base_branch="no-such-base")

    assert diff.has_changes is True
    assert any("scratch.txt" in f for f in diff.files_changed)


@pytest.mark.asyncio
async def test_ambient_git_environment_cannot_redirect_operations(git_sandbox: Path, monkeypatch):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    decoy = _init_repo(git_sandbox / "decoy")
    _git(decoy, "branch", "decoy-branch")
    decoy_head = _rev(decoy, "HEAD")
    decoy_index = decoy / ".git" / "index"
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy_index))

    assert await GitWorktreeManager.get_current_branch(repo) == "main"
    ctx = await _execution_branch(repo, git_sandbox)
    main_before = _rev(repo, "main")
    ok, _ = await GitWorktreeManager.merge_worktree(repo, ctx.branch_name, "main")

    assert ok is True
    assert _rev(repo, "main") != main_before
    assert _rev(decoy, "HEAD") == decoy_head
    assert not (decoy / "feature.txt").exists()


def test_validate_repo_path_accepts_test_repo(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    assert validate_repo_path(str(repo)) == repo.resolve()


# ---------------------------------------------------------------------------
# Group 6: projects and executions APIs
# ---------------------------------------------------------------------------


async def _seed_project(repo_path: str | None = None) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        ws = Workspace(name="WT WS", slug=f"wt-ws-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        proj = Project(
            workspace_id=ws.id,
            name="WT Project",
            slug=f"wt-proj-{uuid.uuid4().hex[:8]}",
            studio_type=StudioType.SAAS,
            repo_path=repo_path,
            base_branch="main",
        )
        db.add(proj)
        await db.commit()
        return proj.id


async def _seed_execution(
    project_id: uuid.UUID, worktree_path: str | None, branch: str = "astrava/exec-seeded"
) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        wf = await WorkflowService.create_workflow(
            db, WorkflowCreate(project_id=project_id, name="WT WF", studio_type="saas")
        )
        execution = WorkflowExecution(
            workflow_id=wf.id,
            project_id=project_id,
            status=ExecutionStatus.RUNNING,
            current_step=0,
            state_data={},
            worktree_path=worktree_path,
            worktree_branch=branch,
        )
        db.add(execution)
        await db.commit()
        return execution.id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_create_project_rejects_repo_outside_allowlist(git_sandbox: Path):
    outside = _init_repo(git_sandbox / "elsewhere" / "proj")
    async with _client() as client:
        res = await client.post(
            "/api/v1/projects",
            json={"name": "Outside", "studio_type": "saas", "repo_path": str(outside)},
        )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_project_stores_canonical_path_for_symlink_input(git_sandbox: Path):
    real = _init_repo(git_sandbox / "repos" / "real")
    alias = git_sandbox / "repos" / "alias"
    alias.symlink_to(real)
    async with _client() as client:
        res = await client.post(
            "/api/v1/projects",
            json={
                "name": "Canonical",
                "studio_type": "saas",
                "repo_path": str(alias),
                "base_branch": "main",
            },
        )
    assert res.status_code == 201, res.text
    assert res.json()["repo_path"] == str(real.resolve())


@pytest.mark.asyncio
async def test_create_project_rejects_symlink_escaping_allowlist(git_sandbox: Path):
    outside = _init_repo(git_sandbox / "elsewhere" / "proj")
    (git_sandbox / "repos" / "escape").symlink_to(outside)
    async with _client() as client:
        res = await client.post(
            "/api/v1/projects",
            json={
                "name": "Escape",
                "studio_type": "saas",
                "repo_path": str(git_sandbox / "repos" / "escape"),
            },
        )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_project_rejects_non_git_directory(git_sandbox: Path):
    plain = git_sandbox / "repos" / "plain"
    plain.mkdir()
    async with _client() as client:
        res = await client.post(
            "/api/v1/projects",
            json={"name": "Plain", "studio_type": "saas", "repo_path": str(plain)},
        )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_project_rejects_invalid_base_branch(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    async with _client() as client:
        res = await client.post(
            "/api/v1/projects",
            json={
                "name": "Bad Base",
                "studio_type": "saas",
                "repo_path": str(repo),
                "base_branch": "--upload-pack=x",
            },
        )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_project_validates_then_null_clears_repo_path(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "proj")
    project_id = await _seed_project(str(repo))
    outside = _init_repo(git_sandbox / "elsewhere" / "proj")

    async with _client() as client:
        bad = await client.patch(f"/api/v1/projects/{project_id}", json={"repo_path": str(outside)})
        assert bad.status_code == 422

        bad_base = await client.patch(f"/api/v1/projects/{project_id}", json={"base_branch": "a b"})
        assert bad_base.status_code == 422

        cleared = await client.patch(f"/api/v1/projects/{project_id}", json={"repo_path": None})
    assert cleared.status_code == 200
    assert cleared.json()["repo_path"] is None


@pytest.mark.asyncio
async def test_scan_revalidates_legacy_repo_path_outside_allowlist(git_sandbox: Path):
    outside = _init_repo(git_sandbox / "elsewhere" / "legacy")
    project_id = await _seed_project(str(outside))

    async with _client() as client:
        res = await client.get(f"/api/v1/projects/{project_id}/scan")

    assert res.status_code == 422


@pytest.mark.asyncio
async def test_scan_succeeds_for_allowlisted_repo(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "scan-me")
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    project_id = await _seed_project(str(repo))

    async with _client() as client:
        res = await client.get(f"/api/v1/projects/{project_id}/scan")

    assert res.status_code == 200
    assert "python" in res.json()["toolchains"]


@pytest.mark.asyncio
async def test_execution_diff_rejects_worktree_outside_storage(git_sandbox: Path):
    project_id = await _seed_project(None)
    outside = git_sandbox / "outside-worktree"
    outside.mkdir()
    execution_id = await _seed_execution(project_id, str(outside))

    async with _client() as client:
        res = await client.get(f"/api/v1/executions/{execution_id}/diff")

    assert res.status_code == 400


@pytest.mark.asyncio
async def test_execution_merge_rejects_worktree_outside_storage(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "merge-api")
    project_id = await _seed_project(str(repo))
    outside = git_sandbox / "outside-worktree"
    outside.mkdir()
    execution_id = await _seed_execution(project_id, str(outside))

    async with _client() as client:
        res = await client.post(f"/api/v1/executions/{execution_id}/merge")

    assert res.status_code == 400


@pytest.mark.asyncio
async def test_execution_merge_refusal_maps_to_422(git_sandbox: Path):
    repo = _init_repo(git_sandbox / "repos" / "merge-refused")
    ctx = await _execution_branch(repo, git_sandbox)
    _git(repo, "checkout", "-b", "side")
    project_id = await _seed_project(str(repo))
    execution_id = await _seed_execution(project_id, None, branch=ctx.branch_name)

    async with _client() as client:
        res = await client.post(f"/api/v1/executions/{execution_id}/merge")

    assert res.status_code == 422
    assert "merge target" in res.json()["detail"]


def test_execution_setup_error_is_runtime_error_for_legacy_catches():
    assert issubclass(ExecutionSetupError, RuntimeError)
