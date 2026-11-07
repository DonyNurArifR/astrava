from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.workspace.path_security import (
    ExecutionSetupError,
    PathContainmentError,
    resolve_worktree_path,
    validate_ref_name,
    validate_repo_path,
)

logger = logging.getLogger(__name__)

EXECUTION_BRANCH_PREFIX = "astrava/exec-"
_GIT_ENV_KEEP = frozenset({"PATH", "HOME", "USER", "LANG", "TMPDIR"})


def sanitized_git_env() -> dict[str, str]:
    """Environment for every git call made by ASTRAVA.

    Inherited GIT_* variables (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_SSH_COMMAND, ...)
    are dropped so ambient values cannot redirect an operation to another repository.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key in _GIT_ENV_KEEP or key.startswith("LC_")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def hardened_git_argv(args: list[str]) -> list[str]:
    """git argv with repository-controlled program hooks disabled.

    core.hooksPath=/dev/null stops hooks; core.fsmonitor=false stops a repository-configured
    fsmonitor program from running during status/diff. Command-line -c overrides the repo config.
    """
    return [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        *args,
    ]


@dataclass
class WorktreeContext:
    worktree_path: str
    branch_name: str
    repo_path: str
    base_branch: str
    execution_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "repo_path": self.repo_path,
            "base_branch": self.base_branch,
            "execution_id": self.execution_id,
        }


@dataclass
class GitDiffResult:
    files_changed: list[str]
    insertions: int
    deletions: int
    diff_text: str
    has_changes: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "diff_text": self.diff_text,
            "has_changes": self.has_changes,
        }


class GitWorktreeManager:
    """Manages ephemeral Git worktrees for isolated execution environments."""

    @staticmethod
    async def _run_git(
        args: list[str],
        cwd: Path | str,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        cmd = hardened_git_argv(args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                env=sanitized_git_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            code = proc.returncode or 0
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            return code, stdout_str, stderr_str
        except TimeoutError:
            logger.error("Git command timed out: %s in %s", args, cwd)
            return -1, "", "Git command timed out"
        except Exception as e:
            logger.error("Git execution failed: %s: %s", args, e)
            return -1, "", str(e)

    @classmethod
    async def is_git_repo(cls, path: Path | str) -> bool:
        p = Path(path).resolve()
        if not p.exists() or not p.is_dir():
            return False
        code, out, _ = await cls._run_git(["rev-parse", "--is-inside-work-tree"], cwd=p)
        return code == 0 and out.strip() == "true"

    @classmethod
    async def get_current_branch(cls, repo_path: Path | str) -> str:
        p = Path(repo_path).resolve()
        code, out, _ = await cls._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=p)
        if code == 0 and out.strip():
            return out.strip()
        return "main"

    @classmethod
    async def _commit_resolves(cls, repo_p: Path, ref: str) -> bool:
        code, _, _ = await cls._run_git(
            ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
            cwd=repo_p,
        )
        return code == 0

    @classmethod
    async def create_worktree(
        cls,
        repo_path: Path | str,
        execution_id: str | uuid.UUID,
        base_branch: str | None = None,
        worktree_dir: Path | str | None = None,
    ) -> WorktreeContext:
        """Create the execution worktree. Fails closed: no HEAD fallback, no uncontained path."""
        # Defense in depth: the repository must be allowlisted and a git work-tree top level.
        try:
            repo_p = validate_repo_path(repo_path)
        except PathContainmentError as exc:
            raise ExecutionSetupError(f"Repository rejected: {exc}") from exc
        if not await cls.is_git_repo(repo_p):
            raise ValueError(f"Target path is not a valid git repository: {repo_p}")

        exec_id_str = str(execution_id)
        try:
            branch_name = validate_ref_name(f"{EXECUTION_BRANCH_PREFIX}{exec_id_str}", "branch")
        except PathContainmentError as exc:
            raise ExecutionSetupError(f"Invalid execution branch name: {exc}") from exc

        base = base_branch or await cls.get_current_branch(repo_p)
        try:
            base = validate_ref_name(base, kind="base branch")
        except PathContainmentError as exc:
            raise ExecutionSetupError(str(exc)) from exc

        if not await cls._commit_resolves(repo_p, base):
            raise ExecutionSetupError(f"Base branch '{base}' does not resolve in the repository")

        try:
            if worktree_dir:
                wt_path = resolve_worktree_path(worktree_dir)
            else:
                settings.WORKTREE_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
                wt_path = resolve_worktree_path(settings.WORKTREE_STORAGE_PATH / exec_id_str)
        except PathContainmentError as exc:
            raise ExecutionSetupError(f"Invalid worktree directory: {exc}") from exc

        # Idempotency / cleanup leftovers from crashed executions (contained path only)
        if wt_path.exists():
            await cls._run_git(["worktree", "remove", "--force", str(wt_path)], cwd=repo_p)
            shutil.rmtree(wt_path, ignore_errors=True)

        await cls._run_git(["branch", "-D", branch_name], cwd=repo_p)
        await cls._run_git(["worktree", "prune"], cwd=repo_p)

        code, stdout, stderr = await cls._run_git(
            ["worktree", "add", "-b", branch_name, str(wt_path), base],
            cwd=repo_p,
        )
        if code != 0:
            error_msg = f"Failed to create git worktree: {stderr or stdout}"
            logger.error(error_msg)
            raise ExecutionSetupError(error_msg)

        logger.info(
            "Created git worktree for execution %s at %s on branch %s (base: %s)",
            exec_id_str,
            wt_path,
            branch_name,
            base,
        )

        return WorktreeContext(
            worktree_path=str(wt_path),
            branch_name=branch_name,
            repo_path=str(repo_p),
            base_branch=base,
            execution_id=exec_id_str,
        )

    @classmethod
    async def get_diff(
        cls,
        worktree_path: Path | str,
        base_branch: str | None = None,
    ) -> GitDiffResult:
        wt_p = resolve_worktree_path(worktree_path)
        target_base = validate_ref_name(base_branch or "main", kind="base branch")
        if not wt_p.exists():
            return GitDiffResult(
                files_changed=[],
                insertions=0,
                deletions=0,
                diff_text="",
                has_changes=False,
            )

        # Read-only display only: fall back to HEAD when the base ref does not exist.
        if not await cls._commit_resolves(wt_p, target_base):
            target_base = "HEAD"

        # Get unified diff against base branch (including staged and unstaged changes)
        # --no-ext-diff/--no-textconv: repository diff drivers never execute.
        code, diff_text, _ = await cls._run_git(
            ["diff", "--no-ext-diff", "--no-textconv", target_base], cwd=wt_p
        )
        if code != 0:
            # Fallback to diff against HEAD
            code, diff_text, _ = await cls._run_git(
                ["diff", "--no-ext-diff", "--no-textconv", "HEAD"], cwd=wt_p
            )

        # Get numstat for metrics
        code_stat, stat_text, _ = await cls._run_git(
            ["diff", "--no-ext-diff", "--no-textconv", "--numstat", target_base], cwd=wt_p
        )

        files_changed: list[str] = []
        insertions = 0
        deletions = 0

        if code_stat == 0 and stat_text.strip():
            for line in stat_text.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    ins_str, del_str, file_name = parts[0], parts[1], parts[2]
                    files_changed.append(file_name)
                    if ins_str.isdigit():
                        insertions += int(ins_str)
                    if del_str.isdigit():
                        deletions += int(del_str)

        # Also inspect untracked files
        _, untracked_out, _ = await cls._run_git(["status", "--porcelain", "-uall"], cwd=wt_p)
        for line in untracked_out.strip().splitlines():
            if line.startswith("?? "):
                untracked_file = line[3:].strip()
                if untracked_file not in files_changed:
                    files_changed.append(untracked_file)

        has_changes = bool(files_changed or diff_text.strip())

        return GitDiffResult(
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
            diff_text=diff_text,
            has_changes=has_changes,
        )

    @classmethod
    async def commit_changes(
        cls,
        worktree_path: Path | str,
        message: str,
        author_name: str = "Abstract",
        author_email: str = "61998277+DonyNurArifR@users.noreply.github.com",
    ) -> str | None:
        """Commit worktree changes. Raises PathContainmentError for a path outside storage."""
        wt_p = resolve_worktree_path(worktree_path)
        if not wt_p.exists():
            return None

        # Stage all changes
        await cls._run_git(["add", "-A"], cwd=wt_p)

        # Check if status is dirty
        code, status_out, _ = await cls._run_git(["status", "--porcelain"], cwd=wt_p)
        if not status_out.strip():
            return None  # Clean, nothing to commit

        # Commit
        author_arg = f"{author_name} <{author_email}>"
        code, stdout, stderr = await cls._run_git(
            ["commit", "-m", message, f"--author={author_arg}"],
            cwd=wt_p,
        )
        if code != 0:
            logger.warning(
                "Git commit in worktree %s returned non-zero: %s", wt_p, stderr or stdout
            )
            return None

        # Return commit SHA
        code_sha, sha_out, _ = await cls._run_git(["rev-parse", "HEAD"], cwd=wt_p)
        return sha_out.strip() if code_sha == 0 else None

    @classmethod
    async def merge_worktree(
        cls,
        repo_path: Path | str,
        branch_name: str,
        target_branch: str = "main",
    ) -> tuple[bool, str]:
        """Merge an execution branch into target_branch, which must be checked out.

        Every refusal returns (False, message) and leaves the repository untouched. The
        operator's checkout is never switched.
        """
        try:
            repo_p = validate_repo_path(repo_path)
            branch = validate_ref_name(branch_name, kind="branch")
            target = validate_ref_name(target_branch, kind="target branch")
        except PathContainmentError as exc:
            logger.warning("Merge refused: %s", exc)
            return False, f"Merge refused: {exc}"

        if not branch.startswith(EXECUTION_BRANCH_PREFIX):
            return False, "Merge refused: branch is not an execution branch"
        if not await cls._commit_resolves(repo_p, f"refs/heads/{branch}"):
            return False, "Merge refused: execution branch does not exist"
        if not await cls._commit_resolves(repo_p, f"refs/heads/{target}"):
            return False, f"Merge refused: merge target '{target}' does not exist"

        code, current_out, _ = await cls._run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo_p)
        if code != 0:
            return False, "Merge refused: repository HEAD is detached"
        current = current_out.strip()
        if current != target:
            return (
                False,
                f"Repository is on '{current}' but merge target is '{target}'; refusing to merge",
            )

        code, status_out, _ = await cls._run_git(
            ["status", "--porcelain", "--untracked-files=no"], cwd=repo_p
        )
        if code != 0:
            return False, "Merge refused: could not read repository status"
        if status_out.strip():
            return False, "Merge refused: repository has uncommitted tracked changes"

        message = f"Merge execution branch '{branch}' into '{target}'"
        code, stdout, stderr = await cls._run_git(
            ["merge", "--no-ff", "--no-edit", "-m", message, f"refs/heads/{branch}"],
            cwd=repo_p,
        )
        if code != 0:
            # Abort only our own failed merge attempt; the status check above proved the tree
            # was clean, so nothing the operator had in progress is discarded.
            await cls._run_git(["merge", "--abort"], cwd=repo_p)
            return False, stderr or stdout
        return True, stdout

    @classmethod
    async def cleanup_worktree(
        cls,
        repo_path: Path | str,
        worktree_path: Path | str,
        branch_name: str | None = None,
        delete_branch: bool = True,
    ) -> bool:
        """Remove a worktree and optionally its branch. Refuses any path outside storage."""
        try:
            wt_p = resolve_worktree_path(worktree_path)
        except PathContainmentError as exc:
            logger.error("Refusing worktree cleanup outside worktree storage: %s", exc)
            return False

        branch: str | None = None
        if delete_branch and branch_name:
            try:
                branch = validate_ref_name(branch_name, kind="branch")
            except PathContainmentError as exc:
                logger.error("Refusing worktree cleanup with invalid branch: %s", exc)
                return False

        repo_p = Path(repo_path).resolve()
        logger.info("Cleaning up git worktree %s (branch: %s)", wt_p, branch)

        if await cls.is_git_repo(repo_p):
            await cls._run_git(["worktree", "remove", "--force", str(wt_p)], cwd=repo_p)
            await cls._run_git(["worktree", "prune"], cwd=repo_p)

            if branch:
                await cls._run_git(["branch", "-D", branch], cwd=repo_p)

        if wt_p.exists():
            shutil.rmtree(wt_p, ignore_errors=True)

        return True
