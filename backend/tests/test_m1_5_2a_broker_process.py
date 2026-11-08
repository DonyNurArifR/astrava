"""M1.5-2a: the real broker process over a real Unix socket (fake backend, no Docker, no DB)."""

import os
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import pytest

from app.worker_runtime.base import RuntimeDeniedError, RuntimeUnavailableError
from app.worker_runtime.broker import BrokerWorkerRuntime
from astrava_broker import contract as c
from tests.m152a_support import KEY

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def broker_dir():
    d = Path(tempfile.mkdtemp(prefix="m152a-"))
    key = d / "key"
    key.write_bytes(KEY)
    key.chmod(0o600)
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


def _env(d: Path, **over) -> dict:
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(BACKEND),
        ASTRAVA_BROKER_SOCKET=str(d / "run" / "s"),
        ASTRAVA_BROKER_KEY_FILE=str(d / "key"),
        ASTRAVA_BROKER_STATE_DIR=str(d / "state"),
        ASTRAVA_BROKER_BACKEND="fake",
    )
    env.update(over)
    return env


def _spawn(d: Path, **over) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "astrava_broker"],
        cwd=BACKEND,
        env=_env(d, **over),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _wait_socket(d: Path, p: subprocess.Popen) -> Path:
    sock = d / "run" / "s"
    for _ in range(200):
        if sock.exists():
            return sock
        assert p.poll() is None, p.stdout.read().decode()
        time.sleep(0.1)
    raise TimeoutError


def test_socket_and_state_permissions_and_real_roundtrip(broker_dir):
    p = _spawn(broker_dir)
    try:
        sock = _wait_socket(broker_dir, p)
        assert stat.S_ISSOCK(sock.stat().st_mode)
        assert stat.S_IMODE(sock.stat().st_mode) == 0o600
        assert stat.S_IMODE(sock.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE((broker_dir / "state").stat().st_mode) == 0o700

        async def go():
            rt = BrokerWorkerRuntime(key=KEY, socket_path=sock)
            h = await rt.health()
            assert h.backend == "fake" and h.contract_digest == c.contract_digest()
            wrong = BrokerWorkerRuntime(key=b"w" * 40, socket_path=sock)
            with pytest.raises(RuntimeDeniedError):
                await wrong.health()
            await rt.aclose()
            await wrong.aclose()

        import asyncio

        asyncio.run(go())
    finally:
        p.kill()
        p.wait()


def test_http_layer_limits_over_the_real_socket(broker_dir):
    p = _spawn(broker_dir)
    try:
        sock = _wait_socket(broker_dir, p)

        async def go():
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(sock)), base_url="http://b"
            ) as cl:
                assert (await cl.get("/docs")).status_code == 404
                assert (await cl.get("/openapi.json")).status_code == 404
                big = b"x" * (c.MAX_REQUEST_BYTES + 100)
                r = await cl.post(
                    "/v1/call", content=big, headers={"content-type": "application/json"}
                )
                assert r.status_code == 413
                r = await cl.post(
                    "/v1/call", content=b"{}", headers={"content-type": "application/json"}
                )
                assert r.status_code == 403  # unauthenticated: denied before validation

        import asyncio

        asyncio.run(go())
    finally:
        p.kill()
        p.wait()


def test_unreachable_socket_fails_closed(broker_dir):
    async def go():
        rt = BrokerWorkerRuntime(key=KEY, socket_path=broker_dir / "nope")
        with pytest.raises(RuntimeUnavailableError):
            await rt.health()
        await rt.aclose()

    import asyncio

    asyncio.run(go())


@pytest.mark.parametrize(
    "over",
    [
        {"ASTRAVA_BROKER_BACKEND": "docker"},
        {"ASTRAVA_BROKER_BACKEND": ""},
        {"ASTRAVA_BROKER_TIER": "Z"},
    ],
)
def test_broker_refuses_to_start_with_bad_config(broker_dir, over):
    p = _spawn(broker_dir, **over)
    assert p.wait(timeout=30) != 0
    assert not (broker_dir / "run" / "s").exists()


def test_broker_refuses_group_readable_key(broker_dir):
    (broker_dir / "key").chmod(0o640)
    p = _spawn(broker_dir)
    assert p.wait(timeout=30) != 0
    assert not (broker_dir / "run" / "s").exists()


def test_broker_will_not_replace_a_regular_file_at_the_socket_path(broker_dir):
    (broker_dir / "run").mkdir()
    victim = broker_dir / "run" / "s"
    victim.write_text("precious")
    p = _spawn(broker_dir)
    assert p.wait(timeout=30) != 0
    assert victim.read_text() == "precious"


def test_broker_inherits_no_application_secrets(broker_dir):
    """The broker config reads only ASTRAVA_BROKER_* variables, never DATABASE_URL etc."""
    src = (BACKEND / "astrava_broker" / "config.py").read_text()
    for forbidden in (
        "DATABASE_URL",
        "OPERATOR_API_KEY",
        "ANTHROPIC",
        "CLAUDE",
        "load_dotenv",
        "env_file",
    ):
        assert forbidden not in src
    assert uuid.uuid4()  # keep imports honest


def test_preexisting_state_dir_is_tightened_to_0700(tmp_path):
    from astrava_broker.state import BrokerState

    d = tmp_path / "state"
    d.mkdir(mode=0o755)
    d.chmod(0o755)
    BrokerState(d)
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
