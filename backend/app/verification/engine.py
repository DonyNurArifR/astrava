import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.workspace.worktree_manager import hardened_git_argv, sanitized_git_env


class CheckResult(BaseModel):
    name: str
    passed: bool
    duration_ms: int
    output: str = ""
    error: str = ""


class StructuredDiagnostic(BaseModel):
    check_name: str
    error_type: str  # "syntax", "test_failure", "json_malformed", "timeout", "general"
    summary: str
    details: str = ""
    file_path: str | None = None
    line_number: int | None = None


class VerificationReport(BaseModel):
    overall_passed: bool
    total_duration_ms: int
    checks: list[CheckResult] = Field(default_factory=list)
    diagnostics: list[StructuredDiagnostic] = Field(default_factory=list)
    diagnostic_summary: str = ""
    git_diff: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationEngine:
    @staticmethod
    async def run_command_check(
        name: str,
        cmd: list[str],
        cwd: Path,
        timeout_seconds: int = 60,
    ) -> CheckResult:
        start = time.monotonic()
        # Verify executable exists
        executable = shutil.which(cmd[0])
        if not executable:
            return CheckResult(
                name=name,
                passed=False,
                duration_ms=0,
                error=f"Executable '{cmd[0]}' not found in PATH",
            )

        full_cmd = [executable] + cmd[1:]
        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            passed = proc.returncode == 0
            return CheckResult(
                name=name,
                passed=passed,
                duration_ms=duration_ms,
                output=stdout.decode("utf-8", errors="replace"),
                error=stderr.decode("utf-8", errors="replace") if not passed else "",
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            duration_ms = int((time.monotonic() - start) * 1000)
            return CheckResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                error=f"Check timed out after {timeout_seconds}s",
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return CheckResult(
                name=name,
                passed=False,
                duration_ms=duration_ms,
                error=str(e),
            )

    @staticmethod
    async def collect_git_diff(cwd: Path) -> str:
        """Captures local uncommitted git changes in the workspace."""
        if not (cwd / ".git").exists() and not Path(cwd).resolve().is_dir():
            return ""
        try:
            proc = await asyncio.create_subprocess_exec(
                *hardened_git_argv(["diff", "--no-ext-diff", "--no-textconv"]),
                cwd=str(cwd),
                env=sanitized_git_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode("utf-8", errors="replace")
        except Exception:
            return ""

    @classmethod
    async def verify_task(
        cls,
        working_directory: Path,
        run_tests: bool = True,
        run_lint: bool = True,
    ) -> VerificationReport:
        start = time.monotonic()
        checks: list[CheckResult] = []

        # 1. Deterministic Python syntax check if python files exist
        py_files = list(working_directory.glob("**/*.py"))
        if py_files and run_lint:
            syntax_check = await cls.run_command_check(
                name="Python Syntax Check",
                cmd=["python3", "-m", "py_compile"] + [str(p) for p in py_files[:10]],
                cwd=working_directory,
            )
            checks.append(syntax_check)

        # 2. Automated Test Execution if test files exist
        test_files = list(working_directory.glob("**/test_*.py")) + list(
            working_directory.glob("**/*_test.py")
        )
        if test_files and run_tests:
            test_check = await cls.run_command_check(
                name="Automated Test Suite (pytest)",
                cmd=["pytest", "-v"] + [str(p) for p in test_files[:5]],
                cwd=working_directory,
                timeout_seconds=30,
            )
            checks.append(test_check)

        # 3. JSON Output Validation
        json_files = list(working_directory.glob("**/*.json"))
        for jf in json_files[:5]:
            try:
                content = jf.read_text(encoding="utf-8")
                if content.strip():
                    json.loads(content)
                    checks.append(
                        CheckResult(name=f"JSON Validation: {jf.name}", passed=True, duration_ms=1)
                    )
            except Exception as e:
                checks.append(
                    CheckResult(
                        name=f"JSON Validation: {jf.name}",
                        passed=False,
                        duration_ms=1,
                        error=f"Malformed JSON: {e}",
                    )
                )

        # 4. Collect Git diff
        git_diff = await cls.collect_git_diff(working_directory)

        # 5. Extract structured diagnostics for automated remediation (M1.4-3)
        diagnostics: list[StructuredDiagnostic] = []
        diag_lines: list[str] = []

        import re

        for c in checks:
            if not c.passed:
                raw_err = (c.error or c.output or "").strip()
                err_type = "general"
                file_path = None
                line_no = None

                if "syntax" in c.name.lower() or "py_compile" in c.name.lower():
                    err_type = "syntax"
                    match = re.search(r'File "([^"]+)", line (\d+)', raw_err)
                    if match:
                        file_path = match.group(1)
                        line_no = int(match.group(2))
                elif "test" in c.name.lower() or "pytest" in c.name.lower():
                    err_type = "test_failure"
                elif "json" in c.name.lower():
                    err_type = "json_malformed"

                summary = raw_err.split("\n")[-1] if raw_err else f"{c.name} failed"
                if len(summary) > 200:
                    summary = summary[:197] + "..."

                diag = StructuredDiagnostic(
                    check_name=c.name,
                    error_type=err_type,
                    summary=summary,
                    details=raw_err[:1500],
                    file_path=file_path,
                    line_number=line_no,
                )
                diagnostics.append(diag)
                loc_str = f" at {file_path}:{line_no}" if file_path and line_no else ""
                diag_lines.append(f"- [{err_type.upper()}]{loc_str} {c.name}: {summary}")
                if raw_err:
                    snippet = raw_err[:400].strip()
                    diag_lines.append(f"  Details: {snippet}")

        diagnostic_summary = "\n".join(diag_lines)[:2500]

        # 6. Overall pass evaluation
        overall_passed = all(c.passed for c in checks) if checks else True
        total_duration = int((time.monotonic() - start) * 1000)

        return VerificationReport(
            overall_passed=overall_passed,
            total_duration_ms=total_duration,
            checks=checks,
            diagnostics=diagnostics,
            diagnostic_summary=diagnostic_summary,
            git_diff=git_diff,
            metadata={
                "files_checked": len(py_files),
                "tests_executed": len(test_files),
                "json_artifacts_verified": len(json_files),
            },
        )
