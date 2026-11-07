from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


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
        cmd = ["git"] + args
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            code = proc.returncode or 0
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            return code, stdout_str, stderr_str
        except TimeoutError:
            logger.error("Git command timed out: %s in %s", cmd, cwd)
            return -1, "", "Git command timed out"
        except Exception as e:
            logger.error("Git execution failed: %s: %s", cmd, e)
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
    async def create_worktree(
        cls,
        repo_path: Path | str,
        execution_id: str | uuid.UUID,
        base_branch: str | None = None,
        worktree_dir: Path | str | None = None,
    ) -> WorktreeContext:
        repo_p = Path(repo_path).resolve()
        if not await cls.is_git_repo(repo_p):
            raise ValueError(f"Target path is not a valid git repository: {repo_p}")

        exec_id_str = str(execution_id)
        branch_name = f"astrava/exec-{exec_id_str}"

        # Resolve base branch
        if not base_branch:
            base_branch = await cls.get_current_branch(repo_p)
        else:
            # Check if base branch exists, fallback to HEAD if not found
            code, _, _ = await cls._run_git(["rev-parse", "--verify", base_branch], cwd=repo_p)
            if code != 0:
                logger.warning("Base branch '%s' not found, falling back to HEAD", base_branch)
                base_branch = "HEAD"

        if worktree_dir:
            wt_path = Path(worktree_dir).resolve()
        else:
            settings.WORKTREE_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
            wt_path = (settings.WORKTREE_STORAGE_PATH / exec_id_str).resolve()

        # Idempotency / Cleanup leftovers from crashed executions
        if wt_path.exists():
            await cls._run_git(["worktree", "remove", "--force", str(wt_path)], cwd=repo_p)
            shutil.rmtree(wt_path, ignore_errors=True)

        await cls._run_git(["branch", "-D", branch_name], cwd=repo_p)
        await cls._run_git(["worktree", "prune"], cwd=repo_p)

        # Create worktree with new branch
        code, stdout, stderr = await cls._run_git(
            ["worktree", "add", "-b", branch_name, str(wt_path), base_branch],
            cwd=repo_p,
        )

        if code != 0:
            error_msg = f"Failed to create git worktree: {stderr or stdout}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        logger.info(
            "Created git worktree for execution %s at %s on branch %s (base: %s)",
            exec_id_str,
            wt_path,
            branch_name,
            base_branch,
        )

        return WorktreeContext(
            worktree_path=str(wt_path),
            branch_name=branch_name,
            repo_path=str(repo_p),
            base_branch=base_branch,
            execution_id=exec_id_str,
        )

    @classmethod
    async def get_diff(
        cls,
        worktree_path: Path | str,
        base_branch: str | None = None,
    ) -> GitDiffResult:
        wt_p = Path(worktree_path).resolve()
        if not wt_p.exists():
            return GitDiffResult(
                files_changed=[],
                insertions=0,
                deletions=0,
                diff_text="",
                has_changes=False,
            )

        target_base = base_branch or "main"

        # Check if base branch exists in repo, fallback to HEAD if needed
        code_check, _, _ = await cls._run_git(["rev-parse", "--verify", target_base], cwd=wt_p)
        if code_check != 0:
            target_base = "HEAD"

        # Get unified diff against base branch (including staged and unstaged changes)
        code, diff_text, _ = await cls._run_git(["diff", target_base], cwd=wt_p)
        if code != 0:
            # Fallback to diff against HEAD
            code, diff_text, _ = await cls._run_git(["diff", "HEAD"], cwd=wt_p)

        # Get numstat for metrics
        code_stat, stat_text, _ = await cls._run_git(["diff", "--numstat", target_base], cwd=wt_p)

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
        wt_p = Path(worktree_path).resolve()
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
        repo_p = Path(repo_path).resolve()
        logger.info("Merging execution branch %s into %s in %s", branch_name, target_branch, repo_p)

        # Check if target branch exists
        code, stdout, stderr = await cls._run_git(
            ["merge", "--no-ff", branch_name, "-m", f"Merge execution branch '{branch_name}'"],
            cwd=repo_p,
        )
        success = code == 0
        output = stdout if success else (stderr or stdout)
        return success, output

    @classmethod
    async def cleanup_worktree(
        cls,
        repo_path: Path | str,
        worktree_path: Path | str,
        branch_name: str | None = None,
        delete_branch: bool = True,
    ) -> bool:
        repo_p = Path(repo_path).resolve()
        wt_p = Path(worktree_path).resolve()

        logger.info("Cleaning up git worktree %s (branch: %s)", wt_p, branch_name)

        if await cls.is_git_repo(repo_p):
            await cls._run_git(["worktree", "remove", "--force", str(wt_p)], cwd=repo_p)
            await cls._run_git(["worktree", "prune"], cwd=repo_p)

            if delete_branch and branch_name:
                await cls._run_git(["branch", "-D", branch_name], cwd=repo_p)

        if wt_p.exists():
            shutil.rmtree(wt_p, ignore_errors=True)

        return True
