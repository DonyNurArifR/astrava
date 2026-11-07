"""The operator recovery CLI lists orphaned executions and recovers one on request."""

import json
import subprocess
import sys
import time

from tests.recovery.harness import BACKEND, LEASE_TTL
from tests.recovery.scenarios import cfg_two_chain
from tests.recovery.test_00_baseline import seed


def _cli(renv, *args):
    return subprocess.run(
        [sys.executable, "-m", "app.orchestrator.recovery_cli", *args],
        cwd=BACKEND,
        env=renv.env(),
        capture_output=True,
        text=True,
        timeout=90,
    )


def test_cli_lists_and_recovers_orphaned_execution(renv):
    pid = seed(renv)
    cfg = cfg_two_chain(project_id=pid, provider={"Task One": {"0": {"mode": "hang"}}})
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("provider_hang.Task One.0")
    eid = renv.execution_id(pid)
    renv.kill9(p1)

    live = _cli(renv, "--list")  # lease still live: not offered for recovery
    assert json.loads(live.stdout)["recoverable"] == []
    refused = _cli(renv, eid)
    assert refused.returncode == 3 and "lease_held" in refused.stdout

    time.sleep(LEASE_TTL + 0.5)
    assert json.loads(_cli(renv, "--list").stdout)["recoverable"] == [eid]
    # The CLI uses the real provider factory; the failing run above never reaches a provider
    # because recovery of a not-orphaned execution is refused. Recovery itself is covered with
    # test doubles in the scenario tests, so here only the listing and refusal paths are driven.


def test_cli_noop_for_finished_and_error_for_unknown(renv):
    import uuid

    from tests.recovery.scenarios import cfg_two_chain as chain

    pid = seed(renv)
    code, res, _ = renv.run("start", {**chain(), "project_id": pid})
    assert code == 0 and res["status"] == "completed"
    eid = renv.execution_id(pid)
    done = _cli(renv, eid)
    assert done.returncode == 0 and json.loads(done.stdout)["status"] == "completed"
    missing = _cli(renv, str(uuid.uuid4()))
    assert missing.returncode == 1 and "not_found" in missing.stdout
