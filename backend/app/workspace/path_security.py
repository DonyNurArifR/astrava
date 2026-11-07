"""Path, ref and repository containment helpers (M1.5-1b, spec section A).

Every filesystem location that originates from an API client, a planner/LLM output or a
stored database value is validated here before ASTRAVA reads, writes, merges or deletes it.

Rules of thumb:
- containment is decided on canonical paths (``resolve()``), never on string prefixes;
- a symlink that leaves its root is rejected, including symlinks that point to a sibling
  directory sharing the root's name prefix;
- ``.git`` components are never writable through an artifact name.

Residual risk (recorded, not closed here): an agent running on the host can still race an
intermediate directory between the check and the write (TOCTOU). ``write_text_contained``
narrows that window and refuses a symlink at the final component, but only sandboxing
(M1.5-4) closes it.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from app.config import settings

MAX_COMPONENT_LENGTH = 255
MAX_RELATIVE_LENGTH = 500
MAX_REF_LENGTH = 100
_REF_ALLOWED = re.compile(r"^[A-Za-z0-9._/-]+$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class PathContainmentError(ValueError):
    """A path, ref or repository location violates the containment rules."""


class ExecutionSetupError(RuntimeError):
    """Fail-closed signal: an execution cannot be set up safely and must not run."""


def is_within(path: str | Path, root: str | Path) -> bool:
    """True when ``path`` resolves to ``root`` or a location below it (symlinks followed)."""
    resolved_path = Path(path).resolve()
    resolved_root = Path(root).resolve()
    return resolved_path.is_relative_to(resolved_root)


def _is_git_component(part: str) -> bool:
    # ".git", ".GIT", ".git.", ".git " all name the metadata directory on common filesystems.
    return part.strip().rstrip(". ").lower() == ".git"


def _has_control_chars(value: str) -> bool:
    """True for any Unicode control, format, surrogate, private-use or unassigned character.

    Also rejects line/paragraph separators (Zl/Zp). Invisible format characters (ZWJ, BOM,
    bidi overrides) can make a name look like '.git' or '..' to a human or a filesystem.
    """
    for ch in value:
        category = unicodedata.category(ch)
        if category.startswith("C") or category in ("Zl", "Zp"):
            return True
    return False


def _component_is_unsafe(part: str) -> bool:
    """Check a path component as written AND after NFKC normalization.

    Fullwidth lookalikes (for example U+FF0E for '.' or U+FF0F for '/') normalize to ASCII
    separators or dot names on some filesystems, so the normalized form is checked too.
    """
    for form in {part, unicodedata.normalize("NFKC", part)}:
        if form in ("", ".", ".."):
            return True
        if "/" in form or "\\" in form:
            return True
        if _is_git_component(form):
            return True
    return False


def safe_join(root: str | Path, relative: str) -> Path:
    """Join ``relative`` under ``root`` and return the canonical result, or raise.

    The leaf may be missing (a file about to be created), but every existing ancestor is
    resolved. The result must be strictly below the resolved root, and no component may
    be ``.git``, even when it is reached through a symlink.
    """
    if not isinstance(relative, str) or not relative:
        raise PathContainmentError("Path must be a non-empty string")
    if len(relative) > MAX_RELATIVE_LENGTH:
        raise PathContainmentError("Path is too long")
    if "\x00" in relative or _has_control_chars(relative):
        raise PathContainmentError("Path contains control characters")
    if "\\" in relative:
        raise PathContainmentError("Path must not contain backslashes")
    if relative.startswith("/") or _WINDOWS_DRIVE.match(relative):
        raise PathContainmentError("Path must be relative")

    for part in relative.split("/"):
        if part in ("", ".."):
            raise PathContainmentError("Path contains an empty or parent component")
        if len(part) > MAX_COMPONENT_LENGTH:
            raise PathContainmentError("Path component is too long")
        if _component_is_unsafe(part):
            raise PathContainmentError("Path component is not a safe plain name")

    resolved_root = Path(root).resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root) or resolved == resolved_root:
        raise PathContainmentError("Path escapes its containment root")

    # A symlink inside the root may point at another location of the root (for example a
    # .git directory). Check the resolved components too, not only the written name.
    for part in resolved.relative_to(resolved_root).parts:
        if _is_git_component(part):
            raise PathContainmentError("Path must not reference .git metadata")
    return resolved


def validate_ref_name(name: str, kind: str = "branch") -> str:
    """Validate a git ref name against a strict allowlist; return it unchanged or raise."""
    if not isinstance(name, str) or not name:
        raise PathContainmentError(f"{kind} name must be a non-empty string")
    if len(name) > MAX_REF_LENGTH:
        raise PathContainmentError(f"{kind} name is too long")
    if name.startswith("-"):
        raise PathContainmentError(f"{kind} name must not start with '-'")
    if not _REF_ALLOWED.match(name):
        raise PathContainmentError(f"{kind} name contains characters that are not allowed")
    if ".." in name or "@{" in name or "//" in name:
        raise PathContainmentError(f"{kind} name contains a forbidden sequence")
    if name.startswith("/") or name.endswith("/") or name.endswith(".") or name.endswith(".lock"):
        raise PathContainmentError(f"{kind} name has a forbidden prefix or suffix")
    for component in name.split("/"):
        if component.startswith(".") or component.endswith(".lock"):
            raise PathContainmentError(f"{kind} name has a forbidden component")
    return name


def _resolved_roots(roots: list[Path]) -> list[Path]:
    return [Path(root).resolve() for root in roots]


def validate_repo_path(raw: str | Path) -> Path:
    """Return the canonical path of an allowlisted git work-tree top level, or raise."""
    allowed = _resolved_roots(list(settings.ALLOWED_REPO_ROOTS))
    if not allowed:
        raise PathContainmentError(
            "Repositories are not allowed until ALLOWED_REPO_ROOTS is configured"
        )
    if not isinstance(raw, str | Path) or not str(raw).strip():
        raise PathContainmentError("Repository path must be a non-empty string")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise PathContainmentError("Repository path must be absolute")

    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise PathContainmentError("Repository path is not an existing directory")
    if not (resolved / ".git").exists():
        raise PathContainmentError("Repository path is not the top level of a git work tree")
    if not any(resolved.is_relative_to(root) for root in allowed):
        raise PathContainmentError("Repository path is outside ALLOWED_REPO_ROOTS")

    for storage in (settings.ARTIFACT_STORAGE_PATH, settings.WORKTREE_STORAGE_PATH):
        storage_root = Path(storage).resolve()
        if is_within(resolved, storage_root) or is_within(storage_root, resolved):
            raise PathContainmentError(
                "Repository path must not overlap ASTRAVA storage directories"
            )
    return resolved


def resolve_worktree_path(raw: str | Path) -> Path:
    """Return the canonical worktree path, which must lie strictly inside worktree storage."""
    if not isinstance(raw, str | Path) or not str(raw).strip():
        raise PathContainmentError("Worktree path must be a non-empty string")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise PathContainmentError("Worktree path must be absolute")
    storage_root = Path(settings.WORKTREE_STORAGE_PATH).resolve()
    resolved = candidate.resolve()
    if resolved == storage_root or not resolved.is_relative_to(storage_root):
        raise PathContainmentError("Worktree path is outside WORKTREE_STORAGE_PATH")
    return resolved


def resolve_execution_work_dir(state: dict) -> Path:
    """Return the directory an execution node may write to. Never falls back silently.

    - ``worktree_path`` set: it must be a contained, existing directory, else setup fails.
    - ``repo_path`` set without a worktree: setup fails (isolation was expected).
    - neither: the project's artifact directory (created when missing).
    """
    try:
        project_dir = safe_join(
            settings.ARTIFACT_STORAGE_PATH, str(state.get("project_id", "default"))
        )
    except PathContainmentError as exc:
        raise ExecutionSetupError("Invalid project identifier for work directory") from exc

    worktree_raw = state.get("worktree_path")
    if worktree_raw:
        try:
            worktree = resolve_worktree_path(worktree_raw)
        except PathContainmentError as exc:
            raise ExecutionSetupError("Execution worktree is outside worktree storage") from exc
        if not worktree.is_dir():
            raise ExecutionSetupError("Execution worktree directory is missing")
        return worktree

    if state.get("repo_path"):
        raise ExecutionSetupError("Execution has a repository but no isolated worktree")

    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _open_contained_leaf(parent: Path, name: str) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    return os.open(parent / name, flags, 0o644)


def _contained_parent(root: str | Path, relative: str) -> tuple[Path, str]:
    """Validate ``relative`` and return (canonical parent directory, final name)."""
    # Full validation first: traversal, .git, symlink escape. Raises on any violation.
    safe_join(root, relative)
    parts = relative.split("/")
    name = parts[-1]
    parent_rel = "/".join(parts[:-1])
    resolved_root = Path(root).resolve()
    parent = safe_join(resolved_root, parent_rel) if parent_rel else resolved_root
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PathContainmentError("Cannot create parent directory for path") from exc
    if not parent.resolve().is_relative_to(resolved_root):
        raise PathContainmentError("Parent directory escapes its containment root")
    return parent, name


def write_text_contained(root: str | Path, relative: str, text: str) -> Path:
    """Write ``text`` to ``root/relative``, refusing any escape and any symlink leaf.

    Re-validates the path immediately before writing, resolves the parent directory and
    opens the final component with O_NOFOLLOW (a planted symlink there fails the open).
    """
    return _write_bytes(root, relative, text.encode("utf-8"))


def write_bytes_contained(root: str | Path, relative: str, data: bytes) -> Path:
    """Byte-oriented variant of :func:`write_text_contained` with the same guarantees."""
    return _write_bytes(root, relative, data)


def _write_bytes(root: str | Path, relative: str, data: bytes) -> Path:
    parent, name = _contained_parent(root, relative)
    try:
        fd = _open_contained_leaf(parent, name)
    except OSError as exc:
        # ELOOP here means the final component is a symlink (O_NOFOLLOW refused it).
        raise PathContainmentError("Refusing to write through a symbolic link") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return parent / name


__all__ = [
    "ExecutionSetupError",
    "PathContainmentError",
    "is_within",
    "resolve_execution_work_dir",
    "resolve_worktree_path",
    "safe_join",
    "validate_ref_name",
    "validate_repo_path",
    "write_bytes_contained",
    "write_text_contained",
]
