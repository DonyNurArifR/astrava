"""M1.5-2a process-level worker recovery: real broker process, real runner, real SIGKILL.

The broker runs its FAKE backend (no Docker exists in 2a); everything else is the production
path: the real OrchestrationRunner recovery, the real BrokerWorkerRuntime over a Unix socket with
HMAC authentication, real PostgreSQL, real lease/epoch fencing.
"""

import os
import signal
import time

import pytest

from tests.recovery.harness import LEASE_TTL
from tests.recovery.scenarios import cfg_single
from tests.recovery.test_00_baseline import seed


def _start_with_workers(renv, count=2, hang=True, **extra):
    pid = seed(renv)
    renv.spawn_broker()
    provider = {"Solo": {"0": {"mode": "hang"}}} if hang else {}
    cfg = cfg_single(project_id=pid, provider=provider, worker_side={"count": count}, **extra)
    proc = renv.spawn("start", cfg)
    assert renv.wait_marker("workers_started", 60), proc.stdout_path.read_text()
    if hang:
        assert renv.wait_marker("provider_hang.Solo.0", 60)
    return pid, proc, renv.execution_id(pid)


def _recover_cfg(eid):
    return {"execution_id": eid, "tasks": cfg_single()["tasks"]}


def test_api_sigkill_mid_worker_recovers_reaps_and_is_idempotent(renv):
    pid, proc, eid = _start_with_workers(renv, count=2)
    before = renv.snapshot(eid)
    assert sorted(r["state"] for r in before["worker_runs"]) == ["running", "running"]
    assert [w["state"] for w in renv.broker_workers().values()] == ["running", "running"]
    assert [r["status"] for r in before["reservations"]] == ["ACTIVE"]

    renv.kill9(proc)
    time.sleep(LEASE_TTL + 0.6)
    code, res, _ = renv.run("recover", _recover_cfg(eid))
    assert code == 0 and res["status"] == "completed", res

    snap = renv.snapshot(eid)
    # Workers: stopped and cleaned at the broker AND recorded as cleaned in PostgreSQL.
    assert [r["state"] for r in snap["worker_runs"]] == ["cleaned", "cleaned"]
    assert all(r["lease_epoch"] == 1 for r in snap["worker_runs"])  # created under the dead epoch
    broker = renv.broker_workers()
    assert [w["state"] for w in broker.values()] == ["cleaned", "cleaned"]
    # Either the explicit terminate or the broker's own stale-epoch reaper got there first.
    assert all(w["reason"] in ("terminated", "stale_epoch") for w in broker.values())
    # Recovery order: workers reaped BEFORE the orphaned reservation is force-settled.
    ev = snap["events"]
    assert ev.index("workers_reconciled") < ev.index("pipeline_recovered")
    terminate_ts = max(a["t"] for a in renv.broker_audit() if a.get("op") == "terminate_worker")
    assert terminate_ts < snap["event_times"]["pipeline_recovered"]
    # The M1.5-1c guarantees are intact: reservation expired once, task completed, new epoch.
    assert snap["execution"]["status"] == "COMPLETED" and snap["execution"]["run_epoch"] == 2
    assert sorted(r["status"] for r in snap["reservations"]) == ["EXPIRED", "RECONCILED"]
    assert snap["budget"]["active_reservations_count"] == 0

    # Idempotent: recovering a finished execution touches neither the broker nor the rows.
    audit_n = len(renv.broker_audit())
    code2, res2, _ = renv.run("recover", _recover_cfg(eid))
    assert code2 == 0 and res2["status"] == "completed"
    assert len(renv.broker_audit()) == audit_n
    assert renv.snapshot(eid)["worker_runs"] == snap["worker_runs"]


def test_broker_sigkill_blocks_recovery_closed_then_restart_completes(renv):
    pid, proc, eid = _start_with_workers(renv, count=1)
    renv.kill9(proc)
    renv.kill9(renv.broker)
    time.sleep(LEASE_TTL + 0.6)

    code, res, _ = renv.run("recover", _recover_cfg(eid))
    assert code == 1 and "WorkerReconcileError" in res["error"], res
    snap = renv.snapshot(eid)
    assert snap["execution"]["status"] == "RUNNING" and snap["execution"]["lease_owner"] is None
    assert [r["status"] for r in snap["reservations"]] == ["ACTIVE"]  # NOT force-settled
    assert "recovery_blocked" in snap["events"] and "pipeline_recovered" not in snap["events"]
    assert len(renv.invocations()) == 1  # only the original (hung) start: no re-run happened
    assert [r["state"] for r in snap["worker_runs"]] == ["running"]

    # The same operator action works once the broker is back, from its persisted state.
    renv.spawn_broker()
    assert [w["state"] for w in renv.broker_workers().values()] == ["running"]
    code, res, _ = renv.run("recover", _recover_cfg(eid))
    assert code == 0 and res["status"] == "completed", res
    snap = renv.snapshot(eid)
    assert [r["state"] for r in snap["worker_runs"]] == ["cleaned"]
    assert [w["state"] for w in renv.broker_workers().values()] == ["cleaned"]


def test_stale_api_process_is_fenced_everywhere_after_recovery(renv):
    pid, proc, eid = _start_with_workers(renv, count=1)
    os.kill(proc.pid, signal.SIGSTOP)  # frozen, not dead: it cannot heartbeat
    time.sleep(LEASE_TTL + 0.6)
    code, res, _ = renv.run("recover", _recover_cfg(eid))
    assert code == 0 and res["status"] == "completed", res
    done = renv.snapshot(eid)
    workers_before = renv.broker_workers()

    os.kill(proc.pid, signal.SIGCONT)  # the stale owner wakes up
    code = renv.wait(proc, timeout=60)
    res = proc.result()
    assert code == 4 and "StaleWorkerError" in res["error"], res  # stops; does not race

    # Direct attempts by the stale epoch are refused by BOTH layers.
    code, res, _ = renv.run("stale_probe", {"execution_id": eid, "epoch": 1})
    assert code == 0, res
    assert res["db_fence"] == "StaleWorkerError"
    assert res["broker_fence"] == "RuntimeConflictError"

    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "COMPLETED"
    assert after["worker_runs"] == done["worker_runs"]
    assert renv.broker_workers().keys() == workers_before.keys()
    assert after["tasks"] == done["tasks"] and after["artifacts"] == done["artifacts"]


@pytest.mark.parametrize("count", [3])
def test_many_workers_all_reaped_exactly_once(renv, count):
    pid, proc, eid = _start_with_workers(renv, count=count)
    renv.kill9(proc)
    time.sleep(LEASE_TTL + 0.6)
    code, res, _ = renv.run("recover", _recover_cfg(eid))
    assert code == 0, res
    terminates = [a for a in renv.broker_audit() if a.get("op") == "terminate_worker"]
    cleanups = [a for a in renv.broker_audit() if a.get("op") == "cleanup_worker"]
    assert len(terminates) == count and len(cleanups) == count
    assert {r["state"] for r in renv.snapshot(eid)["worker_runs"]} == {"cleaned"}
