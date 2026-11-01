from app.providers.base import BaseProvider
from app.providers.claude_code import ClaudeCodeCLIProvider


class ProviderFactory:
    _providers: dict[str, BaseProvider] = {}

    @classmethod
    def get_provider(cls, name: str = "claude_code") -> BaseProvider:
        if name not in cls._providers:
            if name == "claude_code":
                cls._providers[name] = ClaudeCodeCLIProvider()
            else:
                raise ValueError(f"Unknown provider '{name}'")
        return cls._providers[name]
