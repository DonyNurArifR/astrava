import asyncio
import json
import logging
import os
import re
import shutil
import time

from app.config import settings
from app.providers.base import (
    BaseProvider,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
)

logger = logging.getLogger("astrava.providers.claude_code")

SECRET_PATTERNS = [
    re.compile(r"gho_[A-Za-z0-9_]{36,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{36,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9_.-]{20,}", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"[REDACTED_CREDENTIAL]", redacted)
    return redacted


class ClaudeCodeCLIProvider(BaseProvider):
    def __init__(self, cli_path: str | None = None):
        self.cli_path = cli_path or settings.CLAUDE_CLI_PATH

    @property
    def name(self) -> str:
        return "claude_code"

    def _resolve_executable(self) -> str:
        exe = shutil.which(self.cli_path)
        if not exe:
            # Check common paths
            for path in ["/usr/local/bin/claude", "/opt/homebrew/bin/claude"]:
                if os.path.exists(path) and os.access(path, os.X_OK):
                    return path
            raise FileNotFoundError(f"Claude CLI executable not found at '{self.cli_path}'")
        return exe

    def _build_clean_environment(self, overrides: dict[str, str]) -> dict[str, str]:
        clean_env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"),
            "HOME": os.environ.get("HOME", ""),
            "USER": os.environ.get("USER", ""),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "TERM": "xterm-256color",
        }
        for k, v in overrides.items():
            clean_env[k] = v
        return clean_env

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        start_time = time.monotonic()
        try:
            executable = self._resolve_executable()
        except FileNotFoundError as e:
            logger.error("Claude CLI not found: %s", e)
            return ProviderResponse(
                status=ProviderStatus.FAILED,
                exit_code=-1,
                error_message=str(e),
            )

        cmd = [
            executable,
            "--model",
            request.model or settings.DEFAULT_CLAUDE_MODEL,
            "-p",
            "--output-format",
            "json",
        ]

        # Add relevant files if specified
        for file in request.relevant_files:
            cmd.extend(["--add-dir", file])

        # Append task prompt as the final positional argument
        cmd.append(request.prompt)

        work_dir = request.working_directory
        work_dir.mkdir(parents=True, exist_ok=True)
        env = self._build_clean_environment(request.env_overrides)

        logger.info(
            "Executing Claude CLI (model: %s, cwd: %s, timeout: %ss)",
            request.model,
            work_dir,
            request.timeout_seconds,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=request.timeout_seconds,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                duration_ms = int((time.monotonic() - start_time) * 1000)
                logger.warning("Claude CLI timed out after %s seconds", request.timeout_seconds)
                return ProviderResponse(
                    status=ProviderStatus.TIMEOUT,
                    exit_code=-1,
                    duration_ms=duration_ms,
                    error_message=f"Process timed out after {request.timeout_seconds}s",
                )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            stdout = redact_secrets(stdout_bytes.decode("utf-8", errors="replace"))
            stderr = redact_secrets(stderr_bytes.decode("utf-8", errors="replace"))
            exit_code = proc.returncode or 0

            # Parse JSON output from Claude CLI
            parsed_data: dict = {}
            output_text = ""
            session_id = None
            input_tokens = 0
            output_tokens = 0
            cache_read_tokens = 0
            cache_creation_tokens = 0
            cost_usd = 0.0

            if stdout.strip():
                try:
                    # Claude CLI prints a single JSON object when using --output-format json
                    parsed_data = json.loads(stdout.strip())
                    output_text = parsed_data.get("result", "")
                    session_id = parsed_data.get("session_id")
                    cost_usd = float(parsed_data.get("total_cost_usd", 0.0))

                    usage = parsed_data.get("usage", {})
                    input_tokens = int(usage.get("input_tokens", 0))
                    output_tokens = int(usage.get("output_tokens", 0))
                    cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))
                    cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0))

                    is_error = parsed_data.get("is_error", False)
                    if is_error or exit_code != 0:
                        status = ProviderStatus.FAILED
                    else:
                        status = ProviderStatus.SUCCESS

                except json.JSONDecodeError:
                    output_text = stdout
                    status = ProviderStatus.SUCCESS if exit_code == 0 else ProviderStatus.FAILED
            else:
                status = ProviderStatus.FAILED if exit_code != 0 else ProviderStatus.SUCCESS

            return ProviderResponse(
                status=status,
                output_text=output_text,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=duration_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cost_usd=cost_usd,
                session_id=session_id,
                raw_response=parsed_data,
                error_message=stderr if status == ProviderStatus.FAILED else None,
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.exception("Error during Claude CLI invocation: %s", e)
            return ProviderResponse(
                status=ProviderStatus.FAILED,
                exit_code=-1,
                duration_ms=duration_ms,
                error_message=str(e),
            )
