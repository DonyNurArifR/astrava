import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.base import ProviderRequest, ProviderStatus
from app.providers.claude_code import ClaudeCodeCLIProvider, redact_secrets
from app.providers.factory import ProviderFactory


def test_secret_redaction():
    text = "User token: gho_1234567890abcdef1234567890abcdef1234 and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
    redacted = redact_secrets(text)
    assert "gho_" not in redacted
    assert "[REDACTED_CREDENTIAL]" in redacted


def test_provider_factory():
    provider = ProviderFactory.get_provider("claude_code")
    assert isinstance(provider, ClaudeCodeCLIProvider)
    assert provider.name == "claude_code"


@pytest.mark.asyncio
async def test_claude_provider_mock_execution(tmp_path: Path):
    provider = ClaudeCodeCLIProvider()

    sample_output = {
        "result": "Task completed successfully",
        "session_id": "test-session-123",
        "total_cost_usd": 0.0025,
        "is_error": False,
        "usage": {
            "input_tokens": 150,
            "output_tokens": 50,
            "cache_read_input_tokens": 500,
            "cache_creation_input_tokens": 200,
        },
    }

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        json.dumps(sample_output).encode("utf-8"),
        b"",
    )
    mock_proc.returncode = 0

    with patch("shutil.which", return_value="/mock/bin/claude"):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            req = ProviderRequest(
                prompt="Write a hello world function",
                working_directory=tmp_path,
                model="haiku",
            )
            resp = await provider.execute(req)

            assert resp.status == ProviderStatus.SUCCESS
            assert resp.output_text == "Task completed successfully"
            assert resp.session_id == "test-session-123"
            assert resp.cost_usd == 0.0025
            assert resp.input_tokens == 150
            assert resp.output_tokens == 50
            assert resp.cache_read_tokens == 500
            assert resp.cache_creation_tokens == 200


@pytest.mark.asyncio
async def test_claude_provider_timeout_handling(tmp_path: Path):
    provider = ClaudeCodeCLIProvider()

    mock_proc = AsyncMock()
    mock_proc.communicate.side_effect = TimeoutError()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("shutil.which", return_value="/mock/bin/claude"):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            req = ProviderRequest(
                prompt="Long running task",
                working_directory=tmp_path,
                model="haiku",
                timeout_seconds=1,
            )
            resp = await provider.execute(req)

            assert resp.status == ProviderStatus.TIMEOUT
            assert "timed out" in resp.error_message
            mock_proc.kill.assert_called_once()
