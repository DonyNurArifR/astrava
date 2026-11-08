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
    APP_HOST: str = "127.0.0.1"
    DEBUG: bool = False
    BRAND_TAGLINE: str = "From vision to execution."

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Host header allowlist (hostnames only; port stripped, IPv6 bracketed).
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "[::1]", "::1"]

    # Database URLs
    # Execution ownership lease (M1.5-1c): a runner heartbeats at ttl/3; a lease that has not been
    # renewed for EXECUTION_LEASE_TTL_SECONDS may be claimed by a recovering runner.
    EXECUTION_LEASE_TTL_SECONDS: float = 60.0
    # Worker runtime (M1.5-2a). "disabled" (default) = no workers. "broker" = the privilege-
    # separated worker broker over a Unix socket. The API never talks to Docker.
    WORKER_RUNTIME: str = "disabled"
    BROKER_SOCKET_PATH: Path | None = None
    BROKER_KEY_FILE: Path | None = None
    BROKER_REQUEST_TIMEOUT_SECONDS: float = 10.0
    DATABASE_URL: str = "postgresql+asyncpg://astrava:astrava_dev_password@localhost:5433/astrava"
    DATABASE_URL_SYNC: str = "postgresql://astrava:astrava_dev_password@localhost:5433/astrava"

    # Storage paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    ARTIFACT_STORAGE_PATH: Path = BASE_DIR / "storage" / "artifacts"
    WORKTREE_STORAGE_PATH: Path = BASE_DIR / "storage" / "worktrees"
    # Repositories an execution may use must sit under one of these roots (M1.5-1b).
    # Empty = fail closed: no repository can be registered or executed.
    ALLOWED_REPO_ROOTS: list[Path] = []

    # Provider & Model Settings
    CLAUDE_CLI_PATH: str = "claude"
    DEFAULT_CLAUDE_MODEL: str = "haiku"
    CLAUDE_EXECUTION_TIMEOUT_SECONDS: int = 180
    MAX_CONCURRENT_EXECUTIONS: int = 1

    # Security & Approvals
    REQUIRE_APPROVAL_FOR_DESTRUCTIVE: bool = True
    REQUIRE_APPROVAL_FOR_DEPLOYMENT: bool = True

    # Operator authentication (M1.5-1a).
    # OPERATOR_API_KEY None = local development mode: only loopback clients with an
    # allowed Host and no forwarding headers are served. Identity is always the
    # server-side DEFAULT_OPERATOR_NAME; client-supplied identity headers are ignored.
    DEFAULT_OPERATOR_NAME: str = "Abstract"
    OPERATOR_API_KEY: str | None = None
    SESSION_TTL_SECONDS: int = 28800
    COOKIE_SECURE: bool | None = None
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_WINDOW_SECONDS: int = 300


settings = Settings()
