from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ProviderStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ProviderRequest(BaseModel):
    prompt: str
    working_directory: Path = Field(default_factory=Path.cwd)
    model: str = "haiku"
    timeout_seconds: int = 180
    env_overrides: dict[str, str] = Field(default_factory=dict)
    relevant_files: list[str] = Field(default_factory=list)


class ProviderResponse(BaseModel):
    status: ProviderStatus
    output_text: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    model: str | None = None
    canonical_model: str | None = None
    session_id: str | None = None
    raw_response: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class BaseProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g. claude_code, antigravity)."""
        pass

    @abstractmethod
    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Executes a task request safely in a sandboxed subprocess."""
        pass
