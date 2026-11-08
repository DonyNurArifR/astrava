"""Worker backend interface and the FAKE backend (M1.5-2a). No container technology here.

``WorkerBackend`` is deliberately narrow and typed: it takes a validated ``WorkerRecord`` built by
the broker service from constants and enumerated profiles, never a free-form configuration.
M1.5-2b adds the Docker implementation behind this same interface.

The fake backend simulates a worker whose lifecycle is a pure function of persisted timestamps
(no threads), persisted in SQLite so a broker restart reconstructs it, the way the real backend
reconstructs from container labels.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from astrava_broker.contract import (
    MAX_RESULT_BYTES,
    ExportEntry,
    ExportManifest,
    StopReason,
    WorkerState,
    validate_relative_path,
)


@dataclass
class WorkerRecord:
    worker_run_id: str
    execution_id: str
    lease_epoch: int
    task_id: str
    attempt: int
    kind: str
    profile: str
    image_alias: str
    repo_id: str
    base_ref: str
    wall_timeout_s: int
    job_sha256: str
    input_ref: str | None
    worker_id: str
    state: str = WorkerState.CREATED.value
    exit_code: int | None = None
    reason: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    deadline: float | None = None
    # Fake-only simulation script, derived from the job text. Real backends have no such field.
    sim_exit_code: int = 0
    sim_runtime_s: float = 0.0
    sim_log: str = ""
    sim_files: dict[str, str] = field(default_factory=dict)


class WorkerBackend(Protocol):
    name: str

    def create(self, rec: WorkerRecord, job: str) -> None: ...
    def start(self, worker_run_id: str, now: float) -> WorkerRecord: ...
    def get(self, worker_run_id: str) -> WorkerRecord | None: ...
    def list_for_execution(self, execution_id: str) -> list[WorkerRecord]: ...
    def list_active(self) -> list[WorkerRecord]: ...
    def kill(self, worker_run_id: str, reason: StopReason, now: float) -> WorkerRecord: ...
    def resolve(self, worker_run_id: str, now: float) -> WorkerRecord | None: ...
    def remove(self, worker_run_id: str) -> WorkerRecord: ...
    def read_output(
        self, worker_run_id: str, max_bytes: int
    ) -> tuple[str, bool, str | None, bool]: ...
    def export(self, worker_run_id: str, max_files: int, max_bytes: int) -> ExportManifest: ...


class FakeBackend:
    """Deterministic simulation. Selected only via ASTRAVA_BROKER_BACKEND=fake."""

    name = "fake"

    def __init__(self, state_dir: Path) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(state_dir / "fake_workers.sqlite3", check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, execution_id TEXT NOT NULL, "
            "data TEXT NOT NULL)"
        )
        self._db.commit()

    # ---- persistence ----------------------------------------------------------------------
    def _save(self, rec: WorkerRecord) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO workers(id, execution_id, data) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (rec.worker_run_id, rec.execution_id, json.dumps(asdict(rec))),
            )

    def get(self, worker_run_id: str) -> WorkerRecord | None:
        with self._lock:
            row = self._db.execute(
                "SELECT data FROM workers WHERE id = ?", (worker_run_id,)
            ).fetchone()
        return WorkerRecord(**json.loads(row[0])) if row else None

    def list_for_execution(self, execution_id: str) -> list[WorkerRecord]:
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM workers WHERE execution_id = ?", (execution_id,)
            ).fetchall()
        return [WorkerRecord(**json.loads(r[0])) for r in rows]

    def list_active(self) -> list[WorkerRecord]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM workers").fetchall()
        recs = [WorkerRecord(**json.loads(r[0])) for r in rows]
        return [
            r for r in recs if r.state in (WorkerState.CREATED.value, WorkerState.RUNNING.value)
        ]

    # ---- lifecycle ------------------------------------------------------------------------
    def create(self, rec: WorkerRecord, job: str) -> None:
        sim = _parse_sim(job)
        rec.sim_exit_code = sim["exit_code"]
        rec.sim_runtime_s = sim["runtime_s"]
        rec.sim_log = sim["log"]
        rec.sim_files = sim["files"]
        with self._lock:
            self._save(rec)

    def start(self, worker_run_id: str, now: float) -> WorkerRecord:
        with self._lock:
            rec = self._load(worker_run_id)
            rec.state = WorkerState.RUNNING.value
            rec.started_at = now
            rec.deadline = now + rec.wall_timeout_s
            self._save(rec)
            return rec

    def _load(self, worker_run_id: str) -> WorkerRecord:
        row = self._db.execute("SELECT data FROM workers WHERE id = ?", (worker_run_id,)).fetchone()
        if not row:
            raise KeyError(worker_run_id)
        return WorkerRecord(**json.loads(row[0]))

    def resolve(self, worker_run_id: str, now: float) -> WorkerRecord | None:
        """Advance a RUNNING worker to its natural end (exit or deadline); persists."""
        with self._lock:
            try:
                rec = self._load(worker_run_id)
            except KeyError:
                return None
            if rec.state == WorkerState.RUNNING.value and rec.started_at is not None:
                natural_end = rec.started_at + rec.sim_runtime_s
                if rec.deadline is not None and now >= rec.deadline and natural_end > rec.deadline:
                    rec.state = WorkerState.TIMED_OUT.value
                    rec.reason = StopReason.DEADLINE.value
                    rec.finished_at = rec.deadline
                    rec.exit_code = None
                    self._save(rec)
                elif now >= natural_end:
                    rec.state = WorkerState.EXITED.value
                    rec.reason = StopReason.EXITED.value
                    rec.exit_code = rec.sim_exit_code
                    rec.finished_at = natural_end
                    self._save(rec)
            return rec

    def kill(self, worker_run_id: str, reason: StopReason, now: float) -> WorkerRecord:
        with self._lock:
            rec = self._load(worker_run_id)
            if rec.state in (WorkerState.CREATED.value, WorkerState.RUNNING.value):
                rec.state = (
                    WorkerState.TIMED_OUT.value
                    if reason == StopReason.DEADLINE
                    else WorkerState.KILLED.value
                )
                rec.reason = reason.value
                rec.finished_at = now
                self._save(rec)
            return rec

    def remove(self, worker_run_id: str) -> WorkerRecord:
        with self._lock:
            rec = self._load(worker_run_id)
            rec.state = WorkerState.CLEANED.value
            rec.sim_files = {}
            rec.sim_log = ""
            self._save(rec)
            return rec

    def read_output(self, worker_run_id: str, max_bytes: int) -> tuple[str, bool, str | None, bool]:
        rec = self.get(worker_run_id)
        assert rec is not None
        raw = rec.sim_log.encode("utf-8")
        truncated = len(raw) > max_bytes
        log = raw[:max_bytes].decode("utf-8", errors="ignore")
        result = rec.sim_files.get("result.json")
        res_trunc = False
        if result is not None and len(result.encode()) > MAX_RESULT_BYTES:
            result, res_trunc = result[:MAX_RESULT_BYTES], True
        return log, truncated, result, res_trunc

    def export(self, worker_run_id: str, max_files: int, max_bytes: int) -> ExportManifest:
        rec = self.get(worker_run_id)
        assert rec is not None
        entries: list[ExportEntry] = []
        total = 0
        truncated = False
        seen: set[str] = set()
        for path in sorted(rec.sim_files):
            if path == "result.json":
                continue
            try:
                validate_relative_path(path)
            except ValueError:
                continue  # the strict export filter drops it (real filter arrives in M1.5-2c)
            if path.casefold() in seen:
                continue
            seen.add(path.casefold())
            content = rec.sim_files[path].encode()
            if len(entries) >= max_files or total + len(content) > max_bytes:
                truncated = True
                break
            entries.append(
                ExportEntry(
                    path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest()
                )
            )
            total += len(content)
        return ExportManifest(entries=entries, total_bytes=total, truncated=truncated)


def _parse_sim(job: str) -> dict:
    """Fake-only: ``{"fake": {...}}`` in the job text scripts the simulated worker."""
    default: dict = {"exit_code": 0, "runtime_s": 0.0, "log": "", "files": {}}
    try:
        data = json.loads(job)
        sim = data.get("fake") if isinstance(data, dict) else None
        if not isinstance(sim, dict):
            return default
        return {
            "exit_code": int(sim.get("exit_code", 0)),
            "runtime_s": max(0.0, float(sim.get("runtime_s", 0.0))),
            "log": str(sim.get("log", ""))[:100_000],
            "files": {str(k): str(v) for k, v in dict(sim.get("files", {})).items()},
        }
    except (ValueError, TypeError, AttributeError):
        return default
