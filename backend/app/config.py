from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "ASTRAVA"
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    APP_HOST: str = "0.0.0.0"
    DEBUG: bool = True
    BRAND_TAGLINE: str = "From vision to execution."

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Database URLs
    DATABASE_URL: str = "postgresql+asyncpg://astrava:astrava_dev_password@localhost:5433/astrava"
    DATABASE_URL_SYNC: str = "postgresql://astrava:astrava_dev_password@localhost:5433/astrava"

    # Storage paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    ARTIFACT_STORAGE_PATH: Path = BASE_DIR / "storage" / "artifacts"
    WORKTREE_STORAGE_PATH: Path = BASE_DIR / "storage" / "worktrees"

    # Provider & Model Settings
    CLAUDE_CLI_PATH: str = "claude"
    DEFAULT_CLAUDE_MODEL: str = "haiku"
    CLAUDE_EXECUTION_TIMEOUT_SECONDS: int = 180
    MAX_CONCURRENT_EXECUTIONS: int = 1

    # Security & Approvals
    REQUIRE_APPROVAL_FOR_DESTRUCTIVE: bool = True
    REQUIRE_APPROVAL_FOR_DEPLOYMENT: bool = True

    # Trusted operator identity (V1.4 M1.4-1).
    # When OPERATOR_API_KEY is None, the server runs in local development mode and
    # trusts the X-ASTRAVA-ACTOR-NAME header (defaulting to DEFAULT_OPERATOR_NAME).
    DEFAULT_OPERATOR_NAME: str = "Abstract"
    OPERATOR_API_KEY: str | None = None


settings = Settings()
