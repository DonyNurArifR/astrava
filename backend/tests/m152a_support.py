"""Shared builders for the M1.5-2a tests."""

import secrets
import time
import uuid
from pathlib import Path

from astrava_broker.backend import FakeBackend
from astrava_broker.config import BrokerConfig
from astrava_broker.contract import PROTOCOL_VERSION, sign_request
from astrava_broker.profiles import Profile
from astrava_broker.server import create_app
from astrava_broker.service import BrokerService
from astrava_broker.state import BrokerState

KEY = b"k" * 32 + b"-test-key-material"
SHA = "a" * 40


def make_config(tmp: Path, **kw) -> BrokerConfig:
    key_file = tmp / "key"
    if not key_file.exists():
        key_file.write_bytes(KEY)
        key_file.chmod(0o600)
    return BrokerConfig(
        socket_path=tmp / "run" / "broker.sock",
        key_file=key_file,
        state_dir=tmp / "state",
        **kw,
    )


class Clock:
    def __init__(self, t: float | None = None) -> None:
        self.t = t if t is not None else time.time()

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def make_service(tmp: Path, clock=None, **kw) -> BrokerService:
    cfg = make_config(tmp, **kw)
    state = BrokerState(cfg.state_dir)
    return BrokerService(cfg, KEY, FakeBackend(cfg.state_dir), state, clock=clock or time.time)


def make_app(service: BrokerService):
    return create_app(service)


def envelope(op: str, *, ts: float | None = None, key: bytes = KEY, **fields) -> dict:
    base = {
        "v": PROTOCOL_VERSION,
        "op": op,
        "request_id": str(uuid.uuid4()),
        "worker_run_id": None,
        "execution_id": None,
        "lease_epoch": None,
        "ts": ts if ts is not None else time.time(),
        "nonce": secrets.token_hex(16),
        "args": {},
    }
    base.update(fields)
    return sign_request(key, base)


def create_args(job: str = "{}", **over) -> dict:
    a = {
        "kind": "agent",
        "image_alias": "agent-base",
        "profile": Profile.AGENT_STANDARD.value,
        "repo_id": "repo-one",
        "base_ref": SHA,
        "task_id": str(uuid.uuid4()),
        "attempt": 0,
        "wall_timeout_s": 60,
        "job": job,
        "input_ref": None,
    }
    a.update(over)
    return a
