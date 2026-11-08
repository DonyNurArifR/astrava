"""Parent-side helpers: isolated database, subprocess control, DB snapshots."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import psycopg2
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]
ADMIN = dict(host="localhost", port=5433, user="astrava", password="astrava_dev_password")
LEASE_TTL = 2.0


def _urls(db: str) -> tuple[str, str]:
    base = f"{ADMIN['user']}:{ADMIN['password']}@{ADMIN['host']}:{ADMIN['port']}/{db}"
    return f"postgresql+asyncpg://{base}", f"postgresql+psycopg2://{base}"


def create_database() -> str:
    name = f"astrava_m15_1c_{uuid.uuid4().hex[:8]}"
    conn = psycopg2.connect(dbname="postgres", **ADMIN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{name}"')
    conn.close()
    return name


def drop_database(name: str) -> None:
    conn = psycopg2.connect(dbname="postgres", **ADMIN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,)
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    conn.close()


@dataclass
class Proc:
    popen: subprocess.Popen
    name: str
    stdout_path: Path

    @property
    def pid(self) -> int:
        return self.popen.pid

    def result(self) -> dict | None:
        if not self.stdout_path.exists():
            return None
        for line in reversed(self.stdout_path.read_text().splitlines()):
            if line.startswith("RESULT "):
                return json.loads(line[7:])
        return None


@dataclass
class RecoveryEnv:
    db_name: str
    root: Path
    procs: list[Proc] = field(default_factory=list)
    extra_env: dict = field(default_factory=dict)
    broker: "Proc | None" = None

    def __post_init__(self) -> None:
        self.async_url, self.sync_url = _urls(self.db_name)
        self.storage = self.root / "storage"
        self.storage.mkdir(exist_ok=True)
        self.engine = create_engine(self.sync_url)

    # ---- subprocess control -------------------------------------------------------------
    def env(self) -> dict:
        env = dict(os.environ)
        env.update(
            APP_ENV="test",
            DATABASE_URL=self.async_url,
            DATABASE_URL_SYNC=self.sync_url.replace("+psycopg2", ""),
            ARTIFACT_STORAGE_PATH=str(self.storage),
            EXECUTION_LEASE_TTL_SECONDS=str(LEASE_TTL),
            PYTHONPATH=str(BACKEND),
        )
        env.update(self.extra_env)
        return env

    # ---- worker broker (M1.5-2a) ---------------------------------------------------------
    @property
    def broker_dir(self) -> Path:
        return self.root / "b"

    @property
    def broker_socket(self) -> Path:
        return self.broker_dir / "s"

    def configure_broker_client(self) -> None:
        """Point API-side subprocesses at the broker (WORKER_RUNTIME=broker)."""
        key = self.root / "broker.key"
        if not key.exists():
            key.write_bytes(b"process-level-test-key-0123456789abcdef")
            key.chmod(0o600)
        assert len(str(self.broker_socket)) < 100, "unix socket path too long"
        self.extra_env.update(
            WORKER_RUNTIME="broker",
            BROKER_SOCKET_PATH=str(self.broker_socket),
            BROKER_KEY_FILE=str(key),
            BROKER_REQUEST_TIMEOUT_SECONDS="5",
        )

    def spawn_broker(self, **extra: str) -> "Proc":
        self.configure_broker_client()
        out = self.root / f"broker-{len(self.procs)}.out"
        env = dict(os.environ)
        env.update(
            PYTHONPATH=str(BACKEND),
            ASTRAVA_BROKER_SOCKET=str(self.broker_socket),
            ASTRAVA_BROKER_KEY_FILE=str(self.root / "broker.key"),
            ASTRAVA_BROKER_STATE_DIR=str(self.broker_dir / "state"),
            ASTRAVA_BROKER_BACKEND="fake",
            ASTRAVA_BROKER_MAX_ACTIVE="8",
            ASTRAVA_BROKER_REAPER_INTERVAL="0.5",
            **extra,
        )
        popen = subprocess.Popen(
            [sys.executable, "-m", "astrava_broker"],
            cwd=BACKEND,
            env=env,
            stdout=out.open("w"),
            stderr=subprocess.STDOUT,
        )
        proc = Proc(popen, "broker", out)
        self.procs.append(proc)
        self.broker = proc
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.broker_socket.exists():
                return proc
            if popen.poll() is not None:
                raise RuntimeError(f"broker exited early: {out.read_text()}")
            time.sleep(0.1)
        raise TimeoutError("broker socket never appeared")

    def broker_workers(self) -> dict[str, dict]:
        """Read the broker's persisted worker records (the fake backend's 'container labels')."""
        import sqlite3

        path = self.broker_dir / "state" / "fake_workers.sqlite3"
        if not path.exists():
            return {}
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return {r[0]: json.loads(r[1]) for r in con.execute("SELECT id, data FROM workers")}
        finally:
            con.close()

    def broker_audit(self) -> list[dict]:
        path = self.broker_dir / "state" / "audit.log"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text().splitlines()]

    def migrate(self) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=self.env(),
            check=True,
            capture_output=True,
        )

    def spawn(self, cmd: str, cfg: dict, label: str | None = None) -> Proc:
        n = len(self.procs)
        ctl = self.root / "ctl"
        ctl.mkdir(exist_ok=True)
        cfg = {**cfg, "ctl_dir": str(ctl)}
        cfg_path = self.root / f"cfg-{n}.json"
        cfg_path.write_text(json.dumps(cfg))
        out = self.root / f"proc-{n}.out"
        popen = subprocess.Popen(
            [sys.executable, "-m", "tests.recovery.worker_main", cmd, str(cfg_path)],
            cwd=BACKEND,
            env=self.env(),
            stdout=out.open("w"),
            stderr=subprocess.STDOUT,
        )
        proc = Proc(popen, label or f"{cmd}-{n}", out)
        self.procs.append(proc)
        return proc

    def wait(self, proc: Proc, timeout: float = 90) -> int:
        return proc.popen.wait(timeout=timeout)

    def run(self, cmd: str, cfg: dict, timeout: float = 90) -> tuple[int, dict | None, Proc]:
        proc = self.spawn(cmd, cfg)
        code = self.wait(proc, timeout)
        return code, proc.result(), proc

    def wait_marker(self, name: str, timeout: float = 60) -> bool:
        path = self.root / "ctl" / f"fp.{name}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return True
            time.sleep(0.1)
        return False

    def kill9(self, proc: Proc) -> None:
        os.kill(proc.pid, signal.SIGKILL)
        proc.popen.wait(timeout=10)

    def cleanup(self) -> None:
        for p in self.procs:
            if p.popen.poll() is None:
                try:
                    os.kill(p.pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
                p.popen.kill()
                p.popen.wait(timeout=10)
        self.engine.dispose()

    # ---- database -----------------------------------------------------------------------
    def rows(self, sql: str, **params) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(text(sql), params)]

    def execution_id(self, project_id: str, timeout: float = 30) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.rows(
                "SELECT id FROM workflow_executions WHERE project_id = :p ORDER BY created_at",
                p=project_id,
            )
            if r:
                return str(r[0]["id"])
            time.sleep(0.1)
        raise TimeoutError("execution row never appeared")

    def snapshot(self, execution_id: str) -> dict:
        q = self.rows
        ex = q(
            "SELECT status, run_epoch, lease_owner, lease_expires_at, error_message "
            "FROM workflow_executions WHERE id = :e",
            e=execution_id,
        )[0]
        project_id = q("SELECT project_id FROM workflow_executions WHERE id=:e", e=execution_id)[0][
            "project_id"
        ]
        return {
            "execution": ex,
            "budget": (
                q("SELECT * FROM execution_budgets WHERE execution_id=:e", e=execution_id) or [None]
            )[0],
            "reservations": q(
                "SELECT reservation_key, task_id, attempt_number, status, fence_token, metadata_json "
                "FROM budget_reservations WHERE execution_id=:e ORDER BY created_at, reservation_key",
                e=execution_id,
            ),
            "tasks": q(
                "SELECT title, status, input_data FROM tasks WHERE project_id=:p "
                "AND input_data->>'execution_id' = :e ORDER BY title",
                p=project_id,
                e=execution_id,
            ),
            "artifacts": q(
                "SELECT file_path, name FROM artifacts WHERE execution_id=:e ORDER BY file_path",
                e=execution_id,
            ),
            "events": [
                r["event_type"]
                for r in q(
                    "SELECT event_type FROM execution_events WHERE execution_id=:e ORDER BY created_at",
                    e=execution_id,
                )
            ],
            "event_times": {
                r["event_type"]: r["created_at"].timestamp()
                for r in q(
                    "SELECT event_type, created_at FROM execution_events WHERE execution_id=:e "
                    "ORDER BY created_at",
                    e=execution_id,
                )
            },
            "worker_runs": q(
                "SELECT id::text AS id, state, lease_epoch, stop_reason, error FROM worker_runs "
                "WHERE execution_id=:e ORDER BY created_at",
                e=execution_id,
            ),
            "model_executions": q(
                "SELECT status FROM model_executions WHERE execution_id=:e", e=execution_id
            ),
        }

    def invocations(self) -> list[dict]:
        path = self.root / "ctl" / "invocations.log"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text().splitlines()]


def make_env() -> RecoveryEnv:
    root = Path(tempfile.mkdtemp(prefix="m151c-"))
    env = RecoveryEnv(create_database(), root)
    env.migrate()
    return env


def destroy_env(env: RecoveryEnv) -> None:
    env.cleanup()
    drop_database(env.db_name)
    shutil.rmtree(env.root, ignore_errors=True)
