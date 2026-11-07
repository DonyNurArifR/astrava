"""M1.5-1b containment tests: path security, artifact ownership/provenance, secure defaults.

Test groups follow M1_5_1b_SPEC.md: 1 (path_security), 2 (artifacts API/service),
8 (secure defaults) and the artifact-related part of 8a. Settings are set per test through
explicit fixtures; there is no autouse fixture that relaxes ALLOWED_REPO_ROOTS.
"""

import hashlib
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings, settings
from app.core import security_config
from app.core.security_config import SecurityConfigurationError, validate_security_configuration
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.artifact import Artifact, ArtifactType
from app.models.project import Project, StudioType
from app.models.workspace import Workspace
from app.schemas.artifact import ArtifactCreate
from app.schemas.execution import ExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services import artifact_service as artifact_service_module
from app.services.artifact_service import (
    ArtifactNotFoundError,
    ArtifactOwnershipError,
    ArtifactService,
)
from app.services.workflow_service import WorkflowService
from app.workspace import path_security as ps
from app.workspace.path_security import (
    ExecutionSetupError,
    PathContainmentError,
    is_within,
    resolve_execution_work_dir,
    resolve_worktree_path,
    safe_join,
    validate_ref_name,
    validate_repo_path,
    write_bytes_contained,
    write_text_contained,
)

TASK_KEY = "task-1-slug"


# ---------------------------------------------------------------------------
# Fixtures (explicit, per test; never autouse)
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(monkeypatch, tmp_path: Path) -> Path:
    """Point artifact and worktree storage at isolated temporary directories."""
    artifacts = tmp_path / "artifacts"
    worktrees = tmp_path / "worktrees"
    artifacts.mkdir()
    worktrees.mkdir()
    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_PATH", artifacts)
    monkeypatch.setattr(settings, "WORKTREE_STORAGE_PATH", worktrees)
    return tmp_path


@pytest.fixture
def allowed_repos(monkeypatch, storage: Path) -> Path:
    """Allow repositories only under <tmp>/repos for this test."""
    repos = storage / "repos"
    repos.mkdir()
    monkeypatch.setattr(settings, "ALLOWED_REPO_ROOTS", [repos])
    return repos


def _fake_repo(path: Path) -> Path:
    """Create a directory that looks like a git work-tree top level (no git command run)."""
    (path / ".git").mkdir(parents=True)
    return path


async def _seed(task_keys: tuple[str, ...] = (TASK_KEY,)):
    """Create workspace, two projects and one execution per project (tasks set on p1's run)."""
    async with AsyncSessionLocal() as db:
        ws = Workspace(name="Containment WS", slug=f"ws-c-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        projects = []
        for label in ("p1", "p2"):
            proj = Project(
                name=f"Containment {label}",
                slug=f"proj-c-{uuid.uuid4().hex[:8]}",
                workspace_id=ws.id,
                studio_type=StudioType.SAAS,
            )
            db.add(proj)
            projects.append(proj)
        await db.commit()
        p1, p2 = projects
        wf = await WorkflowService.create_workflow(
            db, WorkflowCreate(project_id=p1.id, name="Containment WF", studio_type="saas")
        )
        e1 = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf.id, project_id=p1.id)
        )
        wf2 = await WorkflowService.create_workflow(
            db, WorkflowCreate(project_id=p2.id, name="Containment WF 2", studio_type="saas")
        )
        e2 = await WorkflowService.create_execution(
            db, ExecutionCreate(workflow_id=wf2.id, project_id=p2.id)
        )
        e1.state_data = {"tasks": [{"task_id": key} for key in task_keys]}
        await db.commit()
        return p1.id, e1.id, p2.id, e2.id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _write(path: Path, text: str = "content\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Group 1: path_security unit tests
# ---------------------------------------------------------------------------

REJECTED_RELATIVE = [
    "../x",
    "a/../../b",
    "a/..",
    "..",
    "/etc/passwd",
    "//server/share/x",
    "C:/x",
    "c:x",
    "a\\..\\b",
    "a\\b",
    "a\x00b",
    "a\nb",
    "a\x7fb",
    "a//b",
    "a/",
    "x" * 256,
    "a/" + "y" * 499,
    ".git",
    ".GIT/hooks/x",
    ".git./x",
    ".Git /x",
    ".git/config",
    "sub/.git",
    "a/.git/hooks/pre-merge-commit",
    "",
]


@pytest.mark.parametrize("relative", REJECTED_RELATIVE)
def test_safe_join_rejects_hostile_relative_paths(tmp_path: Path, relative: str):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(PathContainmentError):
        safe_join(root, relative)


@pytest.mark.parametrize("value", [None, 42, ["a"]])
def test_safe_join_rejects_non_string(tmp_path: Path, value):
    with pytest.raises(PathContainmentError):
        safe_join(tmp_path, value)


def test_safe_join_accepts_plain_and_missing_leaf(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    result = safe_join(root, "deep/new/file.md")
    assert result == (root.resolve() / "deep" / "new" / "file.md")
    assert is_within(result, root)


def test_safe_join_rejects_sibling_prefix_directory(tmp_path: Path):
    root = tmp_path / "proj"
    sibling = tmp_path / "proj_evil"
    root.mkdir()
    _write(sibling / "x")
    with pytest.raises(PathContainmentError):
        safe_join(root, "../proj_evil/x")


def test_safe_join_rejects_symlink_inside_root_pointing_outside(tmp_path: Path):
    root = tmp_path / "proj"
    outside = tmp_path / "outside.txt"
    root.mkdir()
    _write(outside)
    (root / "leak.txt").symlink_to(outside)
    with pytest.raises(PathContainmentError):
        safe_join(root, "leak.txt")


def test_safe_join_rejects_symlink_to_sibling_prefix_directory(tmp_path: Path):
    root = tmp_path / "proj"
    sibling = tmp_path / "proj_evil"
    root.mkdir()
    _write(sibling / "x")
    (root / "lnk").symlink_to(sibling)
    with pytest.raises(PathContainmentError):
        safe_join(root, "lnk/x")


def test_safe_join_rejects_symlink_to_another_project_directory(tmp_path: Path):
    projects = tmp_path / "projects"
    p1 = projects / "p1"
    p2 = projects / "p2"
    p1.mkdir(parents=True)
    _write(p2 / "secret.md")
    (p1 / "lnk").symlink_to(p2)
    with pytest.raises(PathContainmentError):
        safe_join(p1, "lnk/secret.md")


def test_safe_join_allows_symlink_that_stays_inside_root(tmp_path: Path):
    root = tmp_path / "proj"
    _write(root / "real" / "f.txt")
    (root / "inner").symlink_to(root / "real")
    assert safe_join(root, "inner/f.txt") == (root / "real" / "f.txt").resolve()


def test_safe_join_rejects_symlink_resolving_into_git_metadata(tmp_path: Path):
    root = tmp_path / "wt"
    _write(root / ".git" / "hooks" / "post-merge")
    (root / "alias").symlink_to(root / ".git" / "hooks")
    with pytest.raises(PathContainmentError):
        safe_join(root, "alias/post-merge")


def test_is_within_table(tmp_path: Path):
    root = tmp_path / "proj"
    sibling = tmp_path / "proj_evil"
    root.mkdir()
    sibling.mkdir()
    (root / "lnk").symlink_to(sibling)
    assert is_within(root, root)
    assert is_within(root / "a", root)
    assert not is_within(sibling / "x", root)
    assert not is_within(root / "lnk", root)
    assert not is_within(root / "a" / ".." / ".." / "x", root)


VALID_REF_NAMES = [
    "main",
    "feature/x-1",
    "astrava/exec-3f2a",
    "refs/heads/x",
    "release-1.2_3",
    "a" * 100,
]

INVALID_REF_NAMES = [
    "",
    "-x",
    "--upload-pack=x",
    "a b",
    "a..b",
    "a@{1}",
    "x.lock",
    "feature/x.lock",
    "a/",
    "a/.hidden",
    "a//b",
    "x~1",
    "x^",
    "x:y",
    "x?",
    "x*",
    "x[1]",
    "x\\y",
    "a\x00b",
    "a\nb",
    "tab\there",
    "a" * 101,
    ".hidden",
    "a.",
    "/abs",
    "x;rm",
]


@pytest.mark.parametrize("name", VALID_REF_NAMES)
def test_validate_ref_name_accepts_valid(name: str):
    assert validate_ref_name(name) == name


@pytest.mark.parametrize("name", INVALID_REF_NAMES)
def test_validate_ref_name_rejects_invalid(name: str):
    with pytest.raises(PathContainmentError):
        validate_ref_name(name)


def test_validate_repo_path_accepts_allowlisted_repo(allowed_repos: Path):
    repo = _fake_repo(allowed_repos / "proj")
    assert validate_repo_path(str(repo)) == repo.resolve()


def test_validate_repo_path_empty_allowlist_fails_closed(monkeypatch, storage: Path):
    repo = _fake_repo(storage / "repos" / "proj")
    monkeypatch.setattr(settings, "ALLOWED_REPO_ROOTS", [])
    with pytest.raises(PathContainmentError, match="ALLOWED_REPO_ROOTS"):
        validate_repo_path(str(repo))


def test_validate_repo_path_rejects_outside_allowlist(allowed_repos: Path, storage: Path):
    repo = _fake_repo(storage / "elsewhere" / "proj")
    with pytest.raises(PathContainmentError):
        validate_repo_path(str(repo))


def test_validate_repo_path_rejects_non_git_directory(allowed_repos: Path):
    plain = allowed_repos / "plain"
    plain.mkdir()
    with pytest.raises(PathContainmentError):
        validate_repo_path(str(plain))


def test_validate_repo_path_rejects_file(allowed_repos: Path):
    file_path = _write(allowed_repos / "file.txt")
    with pytest.raises(PathContainmentError):
        validate_repo_path(str(file_path))


def test_validate_repo_path_rejects_symlink_escaping_allowlist(allowed_repos: Path, storage: Path):
    outside = _fake_repo(storage / "elsewhere" / "proj")
    (allowed_repos / "lnk").symlink_to(outside)
    with pytest.raises(PathContainmentError):
        validate_repo_path(str(allowed_repos / "lnk"))


def test_validate_repo_path_returns_canonical_for_symlink_inside_allowlist(
    allowed_repos: Path,
):
    real = _fake_repo(allowed_repos / "real")
    (allowed_repos / "alias").symlink_to(real)
    assert validate_repo_path(str(allowed_repos / "alias")) == real.resolve()


def test_validate_repo_path_rejects_nested_subdirectory(allowed_repos: Path):
    repo = _fake_repo(allowed_repos / "proj")
    nested = repo / "sub"
    nested.mkdir()
    with pytest.raises(PathContainmentError):
        validate_repo_path(str(nested))


def test_validate_repo_path_rejects_relative_input(allowed_repos: Path, monkeypatch):
    _fake_repo(allowed_repos / "proj")
    monkeypatch.chdir(allowed_repos)
    with pytest.raises(PathContainmentError):
        validate_repo_path("proj")


def test_validate_repo_path_rejects_repo_inside_storage(monkeypatch, storage: Path):
    monkeypatch.setattr(settings, "ALLOWED_REPO_ROOTS", [storage])
    inside_artifacts = _fake_repo(storage / "artifacts" / "proj")
    inside_worktrees = _fake_repo(storage / "worktrees" / "proj")
    with pytest.raises(PathContainmentError):
        validate_repo_path(str(inside_artifacts))
    with pytest.raises(PathContainmentError):
        validate_repo_path(str(inside_worktrees))


def test_validate_repo_path_rejects_repo_containing_storage(monkeypatch, storage: Path):
    # The allowlisted repo is the parent of storage, so it would contain ASTRAVA's own data.
    monkeypatch.setattr(settings, "ALLOWED_REPO_ROOTS", [storage])
    containing = _fake_repo(storage)
    with pytest.raises(PathContainmentError):
        validate_repo_path(str(containing))


def test_resolve_worktree_path_accepts_inside_storage(storage: Path):
    wt = storage / "worktrees" / "exec-1"
    wt.mkdir()
    assert resolve_worktree_path(str(wt)) == wt.resolve()


def test_resolve_worktree_path_rejects_outside_sibling_relative_and_empty(storage: Path):
    (storage / "worktrees_evil").mkdir()
    for target in (
        str(storage / "outside"),
        str(storage / "worktrees_evil" / "x"),
        "relative/path",
        "",
    ):
        with pytest.raises(PathContainmentError):
            resolve_worktree_path(target)


def test_resolve_worktree_path_rejects_storage_root_and_symlink_escape(storage: Path):
    outside = storage / "outside"
    outside.mkdir()
    with pytest.raises(PathContainmentError):
        resolve_worktree_path(str(storage / "worktrees"))
    (storage / "worktrees" / "lnk").symlink_to(outside)
    with pytest.raises(PathContainmentError):
        resolve_worktree_path(str(storage / "worktrees" / "lnk"))


def test_write_text_contained_writes_inside_root(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    written = write_text_contained(root, "out/report.md", "hello")
    assert written.read_text(encoding="utf-8") == "hello"
    assert written.resolve().is_relative_to(root.resolve())


def test_write_bytes_contained_writes_inside_root(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    written = write_bytes_contained(root, "bin.dat", b"\x00\x01")
    assert written.read_bytes() == b"\x00\x01"


def test_write_text_contained_refuses_symlink_at_final_component(tmp_path: Path):
    root = tmp_path / "proj"
    outside = tmp_path / "outside.txt"
    root.mkdir()
    _write(outside, "original")
    (root / "target.txt").symlink_to(outside)
    with pytest.raises(PathContainmentError):
        write_text_contained(root, "target.txt", "attacker")
    assert outside.read_text(encoding="utf-8") == "original"


def test_write_text_contained_refuses_inside_symlink_at_final_component(tmp_path: Path):
    # The symlink points inside the root, so only the O_NOFOLLOW open can refuse it.
    root = tmp_path / "proj"
    root.mkdir()
    _write(root / "real.txt", "original")
    (root / "alias.txt").symlink_to(root / "real.txt")
    with pytest.raises(PathContainmentError):
        write_text_contained(root, "alias.txt", "attacker")
    assert (root / "real.txt").read_text(encoding="utf-8") == "original"


def test_write_text_contained_refuses_symlinked_parent_directory(tmp_path: Path):
    root = tmp_path / "proj"
    outside_dir = tmp_path / "outside_dir"
    root.mkdir()
    outside_dir.mkdir()
    (root / "d").symlink_to(outside_dir)
    with pytest.raises(PathContainmentError):
        write_text_contained(root, "d/x.txt", "attacker")
    assert not (outside_dir / "x.txt").exists()


@pytest.mark.parametrize("relative", ["../escape.txt", ".git/hooks/post-merge", ".GIT/x"])
def test_write_text_contained_writes_nothing_on_violation(tmp_path: Path, relative: str):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(PathContainmentError):
        write_text_contained(root, relative, "attacker")
    assert not (tmp_path / "escape.txt").exists()
    assert not (root / ".git").exists()


def test_execution_setup_error_is_a_runtime_error():
    assert issubclass(ExecutionSetupError, RuntimeError)
    assert issubclass(PathContainmentError, ValueError)
    assert ps.__all__ and "safe_join" in ps.__all__


# ---------------------------------------------------------------------------
# Group 2: artifact ownership, containment, provenance (service and API)
# ---------------------------------------------------------------------------


async def test_service_unknown_project_is_not_found(storage: Path):
    data = ArtifactCreate(
        project_id=uuid.uuid4(), name="a.md", file_path=f"{uuid.uuid4()}/a.md", metadata_json={}
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(ArtifactNotFoundError):
            await ArtifactService.register_artifact(db, data)


async def test_api_unknown_project_returns_404(storage: Path):
    payload = {"project_id": str(uuid.uuid4()), "name": "a.md", "file_path": "x/a.md"}
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 404


async def test_api_unknown_execution_returns_404(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    payload = {
        "project_id": str(p1),
        "execution_id": str(uuid.uuid4()),
        "name": "a.md",
        "file_path": f"{p1}/a.md",
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 404


async def test_api_cross_project_execution_returns_403(storage: Path):
    p1, _e1, _p2, e2 = await _seed()
    _write(storage / "artifacts" / str(p1) / "a.md")
    payload = {
        "project_id": str(p1),
        "execution_id": str(e2),
        "name": "a.md",
        "file_path": f"{p1}/a.md",
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 403


async def test_api_task_id_without_execution_returns_403(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    _write(storage / "artifacts" / str(p1) / "a.md")
    payload = {
        "project_id": str(p1),
        "task_id": TASK_KEY,
        "name": "a.md",
        "file_path": f"{p1}/a.md",
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 403


async def test_api_task_id_not_in_execution_returns_403(storage: Path):
    p1, e1, _p2, _e2 = await _seed()
    _write(storage / "artifacts" / str(p1) / "a.md")
    payload = {
        "project_id": str(p1),
        "execution_id": str(e1),
        "task_id": "task-unrelated",
        "name": "a.md",
        "file_path": f"{p1}/a.md",
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 403


async def test_api_valid_task_key_is_accepted(storage: Path):
    p1, e1, _p2, _e2 = await _seed()
    _write(storage / "artifacts" / str(p1) / "a.md")
    payload = {
        "project_id": str(p1),
        "execution_id": str(e1),
        "task_id": TASK_KEY,
        "name": "a.md",
        "file_path": f"{p1}/a.md",
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 201
    assert res.json()["task_id"] == TASK_KEY


async def test_api_file_of_another_project_returns_403(storage: Path):
    p1, _e1, p2, _e2 = await _seed()
    _write(storage / "artifacts" / str(p2) / "secret.md")
    payload = {"project_id": str(p1), "name": "s.md", "file_path": f"{p2}/secret.md"}
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 403


@pytest.mark.parametrize(
    "file_path_template",
    [
        "../x.md",
        "{p1}/../../x.md",
        "../artifacts_evil/x.md",
        "/etc/passwd",
        "{p1}/a\x00.md",
        "{p1}/back\\slash.md",
    ],
)
async def test_api_traversal_and_hostile_paths_return_400(storage: Path, file_path_template: str):
    p1, _e1, _p2, _e2 = await _seed()
    (storage / "artifacts_evil").mkdir()
    _write(storage / "artifacts_evil" / "x.md")
    payload = {
        "project_id": str(p1),
        "name": "x.md",
        "file_path": file_path_template.format(p1=p1),
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 400


async def test_api_symlink_pointing_outside_returns_400(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    outside = _write(storage / "outside.md")
    project_dir = storage / "artifacts" / str(p1)
    project_dir.mkdir(parents=True)
    (project_dir / "leak.md").symlink_to(outside)
    payload = {"project_id": str(p1), "name": "leak.md", "file_path": f"{p1}/leak.md"}
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 400


async def test_api_symlink_leaf_inside_project_returns_400(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    project_dir = storage / "artifacts" / str(p1)
    _write(project_dir / "real.md")
    (project_dir / "alias.md").symlink_to(project_dir / "real.md")
    payload = {"project_id": str(p1), "name": "alias.md", "file_path": f"{p1}/alias.md"}
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 400


@pytest.mark.parametrize("name", [".git", ".GIT", ".git."])
async def test_api_dot_git_names_return_400(storage: Path, name: str):
    p1, _e1, _p2, _e2 = await _seed()
    payload = {
        "project_id": str(p1),
        "name": "hook",
        "file_path": f"{p1}/{name}/hooks/post-merge",
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 400
    assert not (storage / "artifacts" / str(p1) / name).exists()


async def test_api_client_provenance_is_replaced_with_server_provenance(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    body = b"server-verified bytes\n"
    target = storage / "artifacts" / str(p1) / "a.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(body)
    payload = {
        "project_id": str(p1),
        "name": "a.txt",
        "file_path": f"{p1}/a.txt",
        "metadata_json": {
            "provenance": {
                "source": "orchestrator",
                "registered_by": "orchestrator",
                "sha256": "deadbeef",
                "producing_agent_slug": "forged",
            },
            "note": "kept",
        },
    }
    async with _client() as client:
        res = await client.post("/api/v1/artifacts", json=payload)
    assert res.status_code == 201
    metadata = res.json()["metadata_json"]
    assert metadata["note"] == "kept"
    provenance = metadata["provenance"]
    assert provenance["source"] == "api"
    assert provenance["registered_by"] == settings.DEFAULT_OPERATOR_NAME
    assert provenance["sha256"] == hashlib.sha256(body).hexdigest()
    assert provenance["size_bytes"] == len(body)
    assert "producing_agent_slug" not in provenance


async def test_api_preview_and_download_refuse_symlink_and_directory(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    project_dir = storage / "artifacts" / str(p1)
    _write(project_dir / "real.md", "real content")
    (project_dir / "link.md").symlink_to(project_dir / "real.md")
    (project_dir / "subdir").mkdir()

    async with AsyncSessionLocal() as db:
        link_row = Artifact(
            project_id=p1,
            name="link.md",
            file_path=f"{p1}/link.md",
            artifact_type=ArtifactType.OTHER,
            mime_type="text/markdown",
            file_size_bytes=1,
            metadata_json={},
        )
        dir_row = Artifact(
            project_id=p1,
            name="subdir",
            file_path=f"{p1}/subdir",
            artifact_type=ArtifactType.OTHER,
            mime_type="text/markdown",
            file_size_bytes=1,
            metadata_json={},
        )
        db.add_all([link_row, dir_row])
        await db.commit()
        link_id, dir_id = link_row.id, dir_row.id

    async with _client() as client:
        for artifact_id in (link_id, dir_id):
            preview = await client.get(f"/api/v1/artifacts/{artifact_id}/preview")
            download = await client.get(f"/api/v1/artifacts/{artifact_id}/download")
            assert preview.status_code == 404
            assert download.status_code == 404


async def test_service_orchestrator_source_accepts_known_task_ids(storage: Path):
    p1, e1, _p2, _e2 = await _seed(task_keys=("task-1-slug",))
    project_dir = storage / "artifacts" / str(p1)
    _write(project_dir / "out.md")
    data = ArtifactCreate(
        project_id=p1,
        execution_id=e1,
        task_id="task-9-live",
        name="out.md",
        file_path=f"{p1}/out.md",
    )
    async with AsyncSessionLocal() as db:
        artifact = await ArtifactService.register_artifact(
            db,
            data,
            source="orchestrator",
            registered_by="orchestrator",
            known_task_ids={"task-9-live"},
            producing_agent_slug="dev-agent",
        )
        await db.commit()
        provenance = artifact.metadata_json["provenance"]
    assert artifact.task_id == "task-9-live"
    assert provenance["source"] == "orchestrator"
    assert provenance["registered_by"] == "orchestrator"
    assert provenance["producing_agent_slug"] == "dev-agent"


async def test_service_orchestrator_unknown_task_still_rejected(storage: Path):
    p1, e1, _p2, _e2 = await _seed(task_keys=("task-1-slug",))
    _write(storage / "artifacts" / str(p1) / "out.md")
    data = ArtifactCreate(
        project_id=p1,
        execution_id=e1,
        task_id="task-unknown",
        name="out.md",
        file_path=f"{p1}/out.md",
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(ArtifactOwnershipError):
            await ArtifactService.register_artifact(
                db,
                data,
                source="orchestrator",
                known_task_ids={"task-9-live"},
            )


async def test_service_api_source_ignores_known_task_ids(storage: Path):
    p1, e1, _p2, _e2 = await _seed(task_keys=("task-1-slug",))
    _write(storage / "artifacts" / str(p1) / "out.md")
    data = ArtifactCreate(
        project_id=p1,
        execution_id=e1,
        task_id="task-9-live",
        name="out.md",
        file_path=f"{p1}/out.md",
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(ArtifactOwnershipError):
            await ArtifactService.register_artifact(db, data, known_task_ids={"task-9-live"})


async def test_service_default_call_stays_backward_compatible(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    _write(storage / "artifacts" / str(p1) / "legacy.md", "legacy")
    data = ArtifactCreate(project_id=p1, name="legacy.md", file_path=f"{p1}/legacy.md")
    async with AsyncSessionLocal() as db:
        artifact = await ArtifactService.register_artifact(db, data)
        await db.commit()
    assert artifact.metadata_json["provenance"]["source"] == "api"
    assert artifact.metadata_json["provenance"]["registered_by"] == "unknown"


async def test_service_hash_is_omitted_above_size_limit(storage: Path, monkeypatch):
    p1, _e1, _p2, _e2 = await _seed()
    _write(storage / "artifacts" / str(p1) / "big.md", "0123456789")
    monkeypatch.setattr(artifact_service_module, "MAX_HASH_BYTES", 4)
    data = ArtifactCreate(project_id=p1, name="big.md", file_path=f"{p1}/big.md")
    async with AsyncSessionLocal() as db:
        artifact = await ArtifactService.register_artifact(db, data)
        await db.commit()
    assert artifact.metadata_json["provenance"]["sha256"] is None
    assert artifact.metadata_json["provenance"]["size_bytes"] == 10


async def test_service_content_write_stays_inside_project(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    data = ArtifactCreate(project_id=p1, name="gen.md", file_path=f"{p1}/gen.md")
    async with AsyncSessionLocal() as db:
        artifact = await ArtifactService.register_artifact(db, data, content="generated")
        await db.commit()
    written = storage / "artifacts" / str(p1) / "gen.md"
    assert written.read_text(encoding="utf-8") == "generated"
    assert artifact.file_size_bytes == len(b"generated")


async def test_service_content_write_refuses_escape(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    data = ArtifactCreate(project_id=p1, name="gen.md", file_path=f"{p1}/../../gen.md")
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError):
            await ArtifactService.register_artifact(db, data, content="attacker")
    assert not (storage / "gen.md").exists()


async def test_list_by_project_still_returns_registered_rows(storage: Path):
    p1, _e1, _p2, _e2 = await _seed()
    _write(storage / "artifacts" / str(p1) / "row.md")
    data = ArtifactCreate(project_id=p1, name="row.md", file_path=f"{p1}/row.md")
    async with AsyncSessionLocal() as db:
        await ArtifactService.register_artifact(db, data)
        await db.commit()
        rows = (await db.execute(select(Artifact).where(Artifact.project_id == p1))).scalars().all()
    assert len(rows) == 1


def test_sanitize_path_keeps_traversal_message_and_value_error(storage: Path):
    with pytest.raises(ValueError, match="Path traversal detected"):
        ArtifactService.sanitize_path("../../../etc/passwd")


def test_servable_path_is_none_for_missing_file(storage: Path):
    assert ArtifactService.servable_path("nope/none.md") is None


# ---------------------------------------------------------------------------
# Group 8: secure defaults and configuration validation
# ---------------------------------------------------------------------------

LONG_KEY = "k" * 40


def test_settings_default_has_no_allowed_repo_roots(monkeypatch):
    monkeypatch.delenv("ALLOWED_REPO_ROOTS", raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.ALLOWED_REPO_ROOTS == []


def test_validation_accepts_absolute_allowlisted_root(tmp_path: Path):
    config = Settings(_env_file=None, ALLOWED_REPO_ROOTS=[tmp_path])
    validate_security_configuration(config)


def test_validation_rejects_relative_root():
    config = Settings(_env_file=None, ALLOWED_REPO_ROOTS=[Path("relative/root")])
    with pytest.raises(SecurityConfigurationError, match="absolute"):
        validate_security_configuration(config)


def test_validation_rejects_filesystem_root():
    config = Settings(_env_file=None, ALLOWED_REPO_ROOTS=[Path("/")])
    with pytest.raises(SecurityConfigurationError, match="filesystem root"):
        validate_security_configuration(config)


def test_validation_rejects_home_directory():
    config = Settings(_env_file=None, ALLOWED_REPO_ROOTS=[Path.home()])
    with pytest.raises(SecurityConfigurationError, match="home directory"):
        validate_security_configuration(config)


def test_validation_error_does_not_echo_configured_root(tmp_path: Path):
    secret_like = "relative/secret-looking-root"
    config = Settings(_env_file=None, ALLOWED_REPO_ROOTS=[Path(secret_like)])
    with pytest.raises(SecurityConfigurationError) as excinfo:
        validate_security_configuration(config)
    assert secret_like not in str(excinfo.value)


def test_validation_tolerates_config_without_the_setting():
    class Partial:
        APP_HOST = "127.0.0.1"
        DEBUG = False
        OPERATOR_API_KEY = None
        CORS_ORIGINS = []
        ALLOWED_HOSTS = ["localhost"]
        COOKIE_SECURE = None

    security_config.validate_security_configuration(Partial())


# ---------------------------------------------------------------------------
# Work-dir helper (part of section A; behaviour covered by later B-tasks)
# ---------------------------------------------------------------------------


def test_resolve_execution_work_dir_repo_without_worktree_fails_closed(storage: Path):
    with pytest.raises(ExecutionSetupError):
        resolve_execution_work_dir({"project_id": "p", "repo_path": str(storage)})


# ---------------------------------------------------------------------------
# B4: invisible/format Unicode and fullwidth lookalikes (CVE-2014-9390 class)
# ---------------------------------------------------------------------------

HOSTILE_UNICODE_NAMES = [
    ".g‌it/hooks/x",  # zero-width non-joiner inside .git
    ".git​/x",  # zero-width space after .git
    "﻿.git/x",  # byte-order mark before .git
    "a‮b.md",  # right-to-left override in a name
    "‮",  # bidi override alone
    "．．/x",  # fullwidth full stops normalize to '..'
    "．git/x",  # fullwidth full stop + git normalizes to '.git'
    "a／b",  # fullwidth solidus normalizes to '/'
    "a b.md",  # line separator (Zl)
    "a b.md",  # paragraph separator (Zp)
    "ab.md",  # private-use character
    "a͸b.md",  # unassigned code point
]

ORDINARY_UNICODE_NAMES = [
    "laporan_é.md",
    "文档.md",
    "plain.md",
    "nested/dir/ok.txt",
    "café/résumé.pdf",
]


@pytest.mark.parametrize("name", HOSTILE_UNICODE_NAMES)
def test_safe_join_rejects_unicode_lookalikes(tmp_path: Path, name: str):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(PathContainmentError):
        safe_join(root, name)


@pytest.mark.parametrize("name", ORDINARY_UNICODE_NAMES)
def test_safe_join_accepts_ordinary_unicode(tmp_path: Path, name: str):
    root = tmp_path / "proj"
    root.mkdir()
    assert is_within(safe_join(root, name), root)


@pytest.mark.parametrize("name", HOSTILE_UNICODE_NAMES)
def test_write_text_contained_rejects_unicode_lookalikes(tmp_path: Path, name: str):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(PathContainmentError):
        write_text_contained(root, name, "attacker")
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("name", ORDINARY_UNICODE_NAMES)
def test_write_text_contained_accepts_ordinary_unicode(tmp_path: Path, name: str):
    root = tmp_path / "proj"
    root.mkdir()
    written = write_text_contained(root, name, "ok")
    assert written.read_text(encoding="utf-8") == "ok"


@pytest.mark.parametrize("name", HOSTILE_UNICODE_NAMES)
def test_planned_task_rejects_unicode_lookalikes(name: str):
    from pydantic import ValidationError

    from app.orchestrator.planner import PlannedTask

    with pytest.raises(ValidationError):
        PlannedTask(task_id="t", title="T", description="d", expected_output_artifacts=[name])


@pytest.mark.parametrize("name", ORDINARY_UNICODE_NAMES)
def test_planned_task_accepts_ordinary_unicode(name: str):
    from app.orchestrator.planner import PlannedTask

    task = PlannedTask(task_id="t", title="T", description="d", expected_output_artifacts=[name])
    assert task.expected_output_artifacts == [name]


@pytest.mark.parametrize("name", HOSTILE_UNICODE_NAMES)
def test_sanitize_path_rejects_unicode_lookalikes(storage: Path, name: str):
    with pytest.raises(PathContainmentError):
        ArtifactService.sanitize_path(name)


@pytest.mark.parametrize("name", ORDINARY_UNICODE_NAMES)
def test_sanitize_path_accepts_ordinary_unicode(storage: Path, name: str):
    resolved = ArtifactService.sanitize_path(name)
    assert resolved.is_relative_to((storage / "artifacts").resolve())
