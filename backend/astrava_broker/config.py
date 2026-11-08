"""Broker configuration from ``ASTRAVA_BROKER_*`` environment variables only.

Deliberately not pydantic-settings and no ``.env`` reading: the broker must not pick up the API's
database URL, provider keys or any other application secret.
"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path


class BrokerConfigError(Exception):
    pass


MIN_KEY_BYTES = 32


def load_key(path: Path) -> bytes:
    """Shared MAC key: a regular file, owned by the current user, mode 0600, >= 32 bytes."""
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise BrokerConfigError(f"key file unreadable: {exc.strerror}") from None
    if not stat.S_ISREG(st.st_mode):
        raise BrokerConfigError("key file must be a regular file (no symlinks)")
    if st.st_uid != os.geteuid():
        raise BrokerConfigError("key file must be owned by the current user")
    if st.st_mode & 0o077:
        raise BrokerConfigError("key file must not be accessible by group or others (mode 0600)")
    key = path.read_bytes().strip()
    if len(key) < MIN_KEY_BYTES:
        raise BrokerConfigError(f"key must be at least {MIN_KEY_BYTES} bytes")
    return key


@dataclass(frozen=True)
class BrokerConfig:
    socket_path: Path
    key_file: Path
    state_dir: Path
    backend: str = "fake"
    tier: str = "A"
    max_active_workers: int = 2
    reaper_interval_s: float = 1.0
    created_ttl_s: float = 300.0
    ledger_retention_s: float = 600.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "BrokerConfig":
        e = env if env is not None else dict(os.environ)

        def req(name: str) -> str:
            v = e.get(f"ASTRAVA_BROKER_{name}")
            if not v:
                raise BrokerConfigError(f"ASTRAVA_BROKER_{name} is required")
            return v

        backend = e.get("ASTRAVA_BROKER_BACKEND", "")
        if backend != "fake":
            # M1.5-2a ships no real backend. Anything else fails closed.
            raise BrokerConfigError("only ASTRAVA_BROKER_BACKEND=fake exists in M1.5-2a")
        tier = e.get("ASTRAVA_BROKER_TIER", "A")
        if tier not in ("A", "B"):
            raise BrokerConfigError("ASTRAVA_BROKER_TIER must be A or B")
        return cls(
            socket_path=Path(req("SOCKET")),
            key_file=Path(req("KEY_FILE")),
            state_dir=Path(req("STATE_DIR")),
            backend=backend,
            tier=tier,
            max_active_workers=int(e.get("ASTRAVA_BROKER_MAX_ACTIVE", "2")),
            reaper_interval_s=float(e.get("ASTRAVA_BROKER_REAPER_INTERVAL", "1.0")),
            created_ttl_s=float(e.get("ASTRAVA_BROKER_CREATED_TTL", "300")),
        )
