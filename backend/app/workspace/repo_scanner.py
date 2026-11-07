from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DetectedToolchain:
    name: str
    manifest_files: list[str]
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RepoScanResult:
    repo_path: str
    toolchains: list[str]
    entry_points: list[str]
    test_directories: list[str]
    file_tree: list[str]
    total_files_scanned: int
    context_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_path": self.repo_path,
            "toolchains": self.toolchains,
            "entry_points": self.entry_points,
            "test_directories": self.test_directories,
            "file_tree": self.file_tree,
            "total_files_scanned": self.total_files_scanned,
            "context_summary": self.context_summary,
        }


class RepoScanner:
    """Scans repository structure, identifies toolchains, and generates compact context for planning."""

    EXCLUDED_DIRS: set[str] = {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "coverage",
        ".next",
        ".turbo",
        ".idea",
        ".vscode",
        "storage",
        ".gemini",
    }

    TOOLCHAIN_MANIFESTS: dict[str, list[str]] = {
        "python": ["pyproject.toml", "requirements.txt", "Pipfile", "setup.py", "uv.lock"],
        "node": [
            "package.json",
            "tsconfig.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "package-lock.json",
        ],
        "rust": ["Cargo.toml", "Cargo.lock"],
        "go": ["go.mod", "go.sum"],
        "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
    }

    ENTRYPOINT_PATTERNS: list[str] = [
        "main.py",
        "app.py",
        "app/main.py",
        "backend/app/main.py",
        "src/main.ts",
        "src/main.tsx",
        "src/index.ts",
        "src/index.tsx",
        "src/App.tsx",
        "index.js",
        "src/lib.rs",
        "src/main.rs",
    ]

    TEST_DIR_NAMES: set[str] = {
        "tests",
        "__tests__",
        "test",
        "spec",
        "specs",
    }

    @classmethod
    def scan(
        cls,
        repo_path: str | Path,
        max_depth: int = 4,
        max_files: int = 250,
    ) -> RepoScanResult:
        path = Path(repo_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Repository path does not exist: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"Repository path is not a directory: {path}")

        files_scanned = 0
        tree_entries: list[str] = []
        detected_toolchains: dict[str, list[str]] = {}
        detected_entrypoints: list[str] = []
        detected_test_dirs: set[str] = set()

        def _traverse(current_dir: Path, current_depth: int) -> None:
            nonlocal files_scanned
            if current_depth > max_depth or files_scanned >= max_files:
                return

            try:
                entries = sorted(list(current_dir.iterdir()), key=lambda e: (e.is_file(), e.name))
            except PermissionError:
                return

            for entry in entries:
                if files_scanned >= max_files:
                    break

                rel_path = entry.relative_to(path).as_posix()

                if entry.is_dir():
                    if entry.name in cls.EXCLUDED_DIRS:
                        continue
                    if entry.name.lower() in cls.TEST_DIR_NAMES:
                        detected_test_dirs.add(rel_path)
                    tree_entries.append(f"{rel_path}/")
                    _traverse(entry, current_depth + 1)
                elif entry.is_file():
                    files_scanned += 1
                    tree_entries.append(rel_path)

                    # Check toolchains
                    filename = entry.name
                    for tc, manifests in cls.TOOLCHAIN_MANIFESTS.items():
                        if filename in manifests:
                            detected_toolchains.setdefault(tc, []).append(rel_path)

                    # Check entry points
                    for pattern in cls.ENTRYPOINT_PATTERNS:
                        if rel_path == pattern or rel_path.endswith(f"/{pattern}"):
                            if rel_path not in detected_entrypoints:
                                detected_entrypoints.append(rel_path)

        _traverse(path, current_depth=1)

        toolchains_list = sorted(list(detected_toolchains.keys()))
        test_dirs_list = sorted(list(detected_test_dirs))

        # Generate compact context summary (bounded to <= 1500 tokens / ~6000 chars)
        summary_lines = [
            "### Repository Architecture & Structure Context",
            f"- **Root Path**: `{path.as_posix()}`",
            f"- **Detected Toolchains**: {', '.join(toolchains_list) if toolchains_list else 'Generic / None'}",
        ]

        if toolchains_list:
            summary_lines.append("- **Manifest Files**:")
            for tc in toolchains_list:
                manifest_str = ", ".join(detected_toolchains[tc][:5])
                summary_lines.append(f"  - *{tc}*: `{manifest_str}`")

        if detected_entrypoints:
            summary_lines.append(f"- **Key Entrypoints**: {', '.join(detected_entrypoints[:6])}")

        if test_dirs_list:
            summary_lines.append(f"- **Test Suites**: {', '.join(test_dirs_list)}")

        summary_lines.append("- **Directory Tree Overview**:")
        display_tree = tree_entries[:80]
        for item in display_tree:
            indent = "  " * item.count("/")
            summary_lines.append(f"  {indent}- {item}")
        if len(tree_entries) > 80:
            summary_lines.append(f"  ... ({len(tree_entries) - 80} additional files truncated)")

        context_summary = "\n".join(summary_lines)
        if len(context_summary) > 6000:
            context_summary = context_summary[:5950] + "\n... [repository context truncated]"

        return RepoScanResult(
            repo_path=str(path),
            toolchains=toolchains_list,
            entry_points=detected_entrypoints,
            test_directories=test_dirs_list,
            file_tree=tree_entries,
            total_files_scanned=files_scanned,
            context_summary=context_summary,
        )
