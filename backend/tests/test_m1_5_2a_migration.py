"""M1.5-2a: the worker_runs migration upgrades, downgrades and matches the model (throw-away DB)."""

import subprocess
import sys

from sqlalchemy import create_engine, inspect

from tests.recovery.harness import BACKEND, destroy_env, make_env


def _alembic(env, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env.env(),
        capture_output=True,
        text=True,
    )


def test_upgrade_downgrade_upgrade_and_model_match():
    env = make_env()  # already at head (includes worker_runs)
    try:
        insp = inspect(create_engine(env.sync_url))
        cols = {c["name"] for c in insp.get_columns("worker_runs")}
        assert {"id", "execution_id", "task_id", "attempt", "kind", "profile", "state",
                "lease_epoch", "reservation_id", "fence_token_sha256", "wall_timeout_s"} <= cols  # fmt: skip
        down = _alembic(env, "downgrade", "b7c1d2e3f4a5")
        assert down.returncode == 0, down.stderr
        assert "worker_runs" not in inspect(create_engine(env.sync_url)).get_table_names()
        up = _alembic(env, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        check = _alembic(env, "check")  # no drift between models and migrations
        assert check.returncode == 0, check.stdout + check.stderr
    finally:
        destroy_env(env)
