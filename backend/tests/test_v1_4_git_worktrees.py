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
from app.workspace import GitWorktreeManager, RepoScanner


@pytest.fixture
def git_sandbox(monkeypatch, tmp_path: Path) -> Path:
    """Explicit containment settings for these tests (M1.5-1b): repos live under tmp/repos,
    worktrees under tmp/worktrees. Not autouse, so the default stays fail-closed."""
    repos = tmp_path / "repos"
    worktrees = tmp_path / "worktrees"
    repos.mkdir()
    worktrees.mkdir()
    monkeypatch.setattr(settings, "ALLOWED_REPO_ROOTS", [repos])
    monkeypatch.setattr(settings, "WORKTREE_STORAGE_PATH", worktrees)
    return tmp_path


def _init_git_repo(repo_dir: Path) -> None:
    """Helper to initialize a real git repository with an initial commit on main."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test Runner"], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@astrava.local"], cwd=str(repo_dir), check=True
    )

    # Create initial files
    (repo_dir / "README.md").write_text("# Test Repo\nInitial content\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )


async def _seed_test_project_and_execution(repo_dir: Path) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        ws = Workspace(name="Worktree WS", slug=f"wt-ws-{uuid.uuid4().hex[:6]}")
        db.add(ws)
        await db.flush()

        proj = Project(
            workspace_id=ws.id,
            name="Worktree Project",
            slug=f"wt-proj-{uuid.uuid4().hex[:6]}",
            studio_type=StudioType.SAAS,
            repo_path=str(repo_dir),
            base_branch="main",
        )
        db.add(proj)
        await db.flush()

        wf = await WorkflowService.create_workflow(
            db,
            WorkflowCreate(
                name="Worktree Workflow",
                project_id=proj.id,
                template_type="saas",
            ),
        )

        exec_obj = WorkflowExecution(
            workflow_id=wf.id,
            project_id=proj.id,
            status=ExecutionStatus.RUNNING,
            current_step=0,
            state_data={},
        )
        db.add(exec_obj)
        await db.flush()
        await db.commit()
        return proj.id, exec_obj.id


def test_repo_scanner_on_synthetic_repo(tmp_path: Path):
    """RepoScanner scans file hierarchy, detects language manifests, entrypoints, and test suites."""
    repo_dir = tmp_path / "sample_app"
    _init_git_repo(repo_dir)

    # Add python and node files
    (repo_dir / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (repo_dir / "package.json").write_text('{"name": "demo-ui"}\n', encoding="utf-8")
    (repo_dir / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")

    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('hello')\n", encoding="utf-8")

    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text("def test_ok(): assert True\n", encoding="utf-8")

    scan_result = RepoScanner.scan(repo_dir)

    assert "python" in scan_result.toolchains
    assert "node" in scan_result.toolchains
    assert "docker" in scan_result.toolchains
    assert any("main.py" in ep for ep in scan_result.entry_points)
    assert any("tests" in td for td in scan_result.test_directories)
    assert "pyproject.toml" in scan_result.file_tree
    assert scan_result.total_files_scanned >= 4
    assert "Repository Architecture & Structure Context" in scan_result.context_summary
    assert len(scan_result.context_summary) <= 6000


def test_repo_scanner_rejects_invalid_path(tmp_path: Path):
    """RepoScanner raises appropriate exceptions for non-existent paths or files."""
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        RepoScanner.scan(missing)

    a_file = tmp_path / "file.txt"
    a_file.write_text("hello", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        RepoScanner.scan(a_file)


@pytest.mark.asyncio
@pytest.mark.usefixtures("git_sandbox")
async def test_git_worktree_manager_create_and_isolation(tmp_path: Path):
    """GitWorktreeManager creates isolated branch & worktree; changes do not taint main workspace."""
    repo_dir = tmp_path / "repos" / "main_repo"
    _init_git_repo(repo_dir)

    exec_id = str(uuid.uuid4())
    wt_dir = tmp_path / "worktrees" / exec_id

    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo_dir,
        execution_id=exec_id,
        base_branch="main",
        worktree_dir=wt_dir,
    )

    assert Path(ctx.worktree_path).exists()
    assert ctx.branch_name == f"astrava/exec-{exec_id}"
    assert await GitWorktreeManager.is_git_repo(ctx.worktree_path)

    # Modify file inside worktree
    wt_file = Path(ctx.worktree_path) / "feature.txt"
    wt_file.write_text("New worktree feature\n", encoding="utf-8")

    # Verify main repo is NOT contaminated
    main_file = repo_dir / "feature.txt"
    assert not main_file.exists()


@pytest.mark.asyncio
@pytest.mark.usefixtures("git_sandbox")
async def test_git_worktree_diff_and_commit(tmp_path: Path):
    """GitWorktreeManager generates accurate unified diffs and commits changes."""
    repo_dir = tmp_path / "repos" / "main_repo"
    _init_git_repo(repo_dir)

    exec_id = str(uuid.uuid4())
    wt_dir = tmp_path / "worktrees" / exec_id

    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo_dir,
        execution_id=exec_id,
        base_branch="main",
        worktree_dir=wt_dir,
    )

    # Add a new file
    (Path(ctx.worktree_path) / "service.py").write_text("class Service: pass\n", encoding="utf-8")

    # Get diff before commit (untracked/staged)
    diff_before = await GitWorktreeManager.get_diff(ctx.worktree_path, base_branch="main")
    assert diff_before.has_changes is True
    assert any("service.py" in f for f in diff_before.files_changed)

    # Commit changes
    commit_sha = await GitWorktreeManager.commit_changes(
        ctx.worktree_path,
        message="feat: add service class",
    )
    assert commit_sha is not None
    assert len(commit_sha) >= 7

    # Get diff after commit against main
    diff_after = await GitWorktreeManager.get_diff(ctx.worktree_path, base_branch="main")
    assert diff_after.has_changes is True
    assert diff_after.insertions >= 1
    assert "class Service: pass" in diff_after.diff_text


@pytest.mark.asyncio
@pytest.mark.usefixtures("git_sandbox")
async def test_git_worktree_cleanup(tmp_path: Path):
    """GitWorktreeManager cleans up worktree path and deletes the execution branch."""
    repo_dir = tmp_path / "repos" / "main_repo"
    _init_git_repo(repo_dir)

    exec_id = str(uuid.uuid4())
    wt_dir = tmp_path / "worktrees" / exec_id

    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo_dir,
        execution_id=exec_id,
        base_branch="main",
        worktree_dir=wt_dir,
    )
    assert Path(ctx.worktree_path).exists()

    success = await GitWorktreeManager.cleanup_worktree(
        repo_path=repo_dir,
        worktree_path=ctx.worktree_path,
        branch_name=ctx.branch_name,
        delete_branch=True,
    )
    assert success is True
    assert not Path(ctx.worktree_path).exists()

    # Check branch deleted in main repo
    res = subprocess.run(
        ["git", "branch", "--list", ctx.branch_name],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
    )
    assert ctx.branch_name not in res.stdout


@pytest.mark.asyncio
@pytest.mark.usefixtures("git_sandbox")
async def test_git_worktree_merge_into_base(tmp_path: Path):
    """GitWorktreeManager merges the execution branch back into target base branch."""
    repo_dir = tmp_path / "repos" / "main_repo"
    _init_git_repo(repo_dir)

    exec_id = str(uuid.uuid4())
    wt_dir = tmp_path / "worktrees" / exec_id

    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo_dir,
        execution_id=exec_id,
        base_branch="main",
        worktree_dir=wt_dir,
    )

    # Make and commit changes in worktree
    (Path(ctx.worktree_path) / "merged_module.py").write_text("x = 42\n", encoding="utf-8")
    await GitWorktreeManager.commit_changes(ctx.worktree_path, message="Add merged_module")

    # Clean up worktree directory before merging to avoid branch checkout collisions
    await GitWorktreeManager.cleanup_worktree(
        repo_path=repo_dir,
        worktree_path=ctx.worktree_path,
        branch_name=ctx.branch_name,
        delete_branch=False,  # preserve branch for merging
    )

    # Merge branch into main
    merge_ok, log = await GitWorktreeManager.merge_worktree(
        repo_path=repo_dir,
        branch_name=ctx.branch_name,
        target_branch="main",
    )
    assert merge_ok is True

    # Main repository now has the merged file!
    assert (repo_dir / "merged_module.py").exists()
    assert (repo_dir / "merged_module.py").read_text(encoding="utf-8") == "x = 42\n"


@pytest.mark.asyncio
@pytest.mark.usefixtures("git_sandbox")
async def test_api_endpoints_diff_merge_and_scan(tmp_path: Path):
    """REST API endpoints /projects/{id}/scan, /executions/{id}/diff, /executions/{id}/merge."""
    repo_dir = tmp_path / "repos" / "api_repo"
    _init_git_repo(repo_dir)
    (repo_dir / "pyproject.toml").write_text('[project]\nname = "api-test"\n', encoding="utf-8")

    project_id, execution_id = await _seed_test_project_and_execution(repo_dir)

    # Create worktree for this execution
    wt_dir = tmp_path / "worktrees" / str(execution_id)
    ctx = await GitWorktreeManager.create_worktree(
        repo_path=repo_dir,
        execution_id=execution_id,
        base_branch="main",
        worktree_dir=wt_dir,
    )

    # Attach worktree info to execution in DB
    async with AsyncSessionLocal() as db:
        exec_db = await WorkflowService.get_execution(db, execution_id)
        assert exec_db is not None
        exec_db.worktree_path = ctx.worktree_path
        exec_db.worktree_branch = ctx.branch_name
        await db.commit()

    # Modify a file in worktree
    (Path(ctx.worktree_path) / "api_artifact.txt").write_text(
        "Artifact from agent\n", encoding="utf-8"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test Project Scan API
        scan_resp = await client.get(f"/api/v1/projects/{project_id}/scan")
        assert scan_resp.status_code == 200
        scan_data = scan_resp.json()
        assert "python" in scan_data["toolchains"]
        assert scan_data["total_files_scanned"] >= 1

        # 2. Test Execution Diff API
        diff_resp = await client.get(f"/api/v1/executions/{execution_id}/diff")
        assert diff_resp.status_code == 200
        diff_data = diff_resp.json()
        assert diff_data["has_changes"] is True
        assert any("api_artifact.txt" in f for f in diff_data["files_changed"])

        # Commit changes in worktree
        await GitWorktreeManager.commit_changes(ctx.worktree_path, message="Add api_artifact")

        # Cleanup worktree directory so merge can execute cleanly
        await GitWorktreeManager.cleanup_worktree(
            repo_path=repo_dir,
            worktree_path=ctx.worktree_path,
            branch_name=ctx.branch_name,
            delete_branch=False,
        )

        # 3. Test Execution Merge API (Protected with operator context)
        merge_resp = await client.post(
            f"/api/v1/executions/{execution_id}/merge",
            headers={"X-ASTRAVA-ACTOR-NAME": "LeadArchitect"},
        )
        assert merge_resp.status_code == 200
        merge_data = merge_resp.json()
        assert merge_data["success"] is True
        assert merge_data["branch"] == ctx.branch_name

        # Verify file is merged into main repo
        assert (repo_dir / "api_artifact.txt").exists()
