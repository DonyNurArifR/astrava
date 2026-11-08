"""Broker-local durable state: request ledger, per-execution epoch high-water marks, audit log.

SQLite (standard library) with synchronous=FULL. The broker has no database access to the
application's PostgreSQL and no secrets other than the MAC key.
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path


class BrokerState:
    def __init__(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(state_dir, 0o700)  # mkdir's mode is ignored for a pre-existing directory
        self.dir = state_dir
        self._lock = threading.Lock()
        self._db = sqlite3.connect(state_dir / "broker.sqlite3", check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger (nonce TEXT PRIMARY KEY, ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS epochs (execution_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL);
            """
        )
        self._db.commit()
        self.audit_path = state_dir / "audit.log"

    # ---- request ledger (persistent: replay protection survives a broker restart) ----------
    def seen_or_record(self, nonce: str, ts: float) -> bool:
        """True if the nonce was already used; otherwise records it and returns False."""
        with self._lock:
            try:
                with self._db:  # commits on success, ROLLS BACK on error (no dangling write lock)
                    self._db.execute("INSERT INTO ledger(nonce, ts) VALUES (?, ?)", (nonce, ts))
                return False
            except sqlite3.IntegrityError:
                return True

    def prune_ledger(self, older_than: float) -> None:
        with self._lock:
            self._db.execute("DELETE FROM ledger WHERE ts < ?", (older_than,))
            self._db.commit()

    # ---- epoch high-water marks -------------------------------------------------------------
    def epoch(self, execution_id: str) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT epoch FROM epochs WHERE execution_id = ?", (execution_id,)
            ).fetchone()
        return int(row[0]) if row else -1

    def raise_epoch(self, execution_id: str, epoch: int) -> int:
        """Monotonic: records max(current, epoch) and returns it."""
        with self._lock:
            self._db.execute(
                "INSERT INTO epochs(execution_id, epoch) VALUES (?, ?) "
                "ON CONFLICT(execution_id) DO UPDATE SET epoch = max(epoch, excluded.epoch)",
                (execution_id, epoch),
            )
            self._db.commit()
            row = self._db.execute(
                "SELECT epoch FROM epochs WHERE execution_id = ?", (execution_id,)
            ).fetchone()
        return int(row[0])

    # ---- audit (never contains job text, output or file contents) ---------------------------
    def audit(self, **fields: object) -> None:
        line = json.dumps({"t": time.time(), **fields}, default=str, sort_keys=True)
        with self._lock, self.audit_path.open("a") as fh:
            fh.write(line + "\n")
