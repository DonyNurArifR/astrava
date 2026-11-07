"""Scenarios B-F: SIGKILL at precise points between provider return, settlement and persistence."""

import time

from tests.recovery.harness import LEASE_TTL
from tests.recovery.scenarios import cfg_parallel, cfg_two_chain, task
from tests.recovery.test_00_baseline import seed


def _recover(renv, cfg, eid):
    time.sleep(LEASE_TTL + 0.5)
    p = renv.spawn("recover", {**cfg, "failpoints": [], "execution_id": eid})
    assert renv.wait(p) == 0, p.result()
    assert p.result()["status"] == "completed", p.result()
    return p


def _starts(renv):
    return [(i["title"], i["ordinal"]) for i in renv.invocations() if i["event"] == "start"]


def test_b_provider_finished_but_orchestrator_died_before_reconcile(renv):
    pid = seed(renv)
    cfg = cfg_two_chain(project_id=pid, failpoints=[{"name": "before_reconcile", "match": "t1.0"}])
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("before_reconcile.t1.0")
    eid = renv.execution_id(pid)
    # The provider call already returned (end logged) but nothing was settled or persisted.
    assert [(i["title"], i["event"]) for i in renv.invocations()] == [
        ("Task One", "start"),
        ("Task One", "end"),
    ]
    mid = renv.snapshot(eid)
    assert [r["status"] for r in mid["reservations"]] == ["ACTIVE"]
    assert mid["budget"]["total_agent_attempts"] == 0
    renv.kill9(p1)

    _recover(renv, cfg, eid)
    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "COMPLETED"
    # The unsettled result is NOT trusted: the attempt is expired (counted once, estimate charged)
    # and the provider is invoked again (documented at-least-once semantics).
    assert _starts(renv) == [("Task One", 0), ("Task One", 1), ("Task Two", 0)]
    by_key = {r["reservation_key"]: r["status"] for r in after["reservations"]}
    assert by_key == {
        "task:t1:attempt:0": "EXPIRED",
        "task:t1:attempt:1": "RECONCILED",
        "task:t2:attempt:0": "RECONCILED",
    }
    b = after["budget"]
    assert b["total_agent_attempts"] == 3 and b["active_reservations_count"] == 0
    # estimate (0.01) charged exactly once for the lost attempt; two real attempts at 0.001
    assert float(b["consumed_estimated_cost_usd"]) == 0.01
    assert abs(float(b["consumed_actual_cost_usd"]) - 0.002) < 1e-9
    t1 = next(t for t in after["tasks"] if t["title"] == "Task One")
    assert t1["status"] == "COMPLETED"


def test_c_failed_attempt_then_success_is_adopted_not_rerun(renv):
    pid = seed(renv)
    cfg = cfg_two_chain(
        project_id=pid,
        provider={"Task One": {"0": {"mode": "fail"}, "1": {"mode": "ok"}}},
        # state is lost at the sync that would persist Task One as completed
        failpoints=[{"name": "before_sync", "min_completed": 1}],
    )
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("before_sync")
    eid = renv.execution_id(pid)
    mid = renv.snapshot(eid)
    assert {r["reservation_key"]: r["status"] for r in mid["reservations"]} == {
        "task:t1:attempt:0": "RECONCILED",
        "task:t1:attempt:1": "RECONCILED",
    }
    assert [t["status"] for t in mid["tasks"]] == ["PENDING", "PENDING"]  # completion not persisted
    renv.kill9(p1)

    _recover(renv, cfg, eid)
    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "COMPLETED"
    # Task One is adopted from its SUCCESSFUL attempt 1 (the failed attempt 0 never counts as
    # completion) and is not run again; only Task Two is dispatched by the recoverer.
    assert _starts(renv) == [("Task One", 0), ("Task One", 1), ("Task Two", 0)]
    meta = {r["reservation_key"]: r["metadata_json"] for r in after["reservations"]}
    assert meta["task:t1:attempt:0"]["success"] is False
    assert meta["task:t1:attempt:1"]["success"] is True
    assert len(after["reservations"]) == 3  # no extra reservation for the adopted task
    t1 = next(t for t in after["tasks"] if t["title"] == "Task One")
    assert t1["status"] == "COMPLETED"
    assert after["budget"]["total_agent_attempts"] == 3
    assert after["budget"]["active_reservations_count"] == 0


def test_d_reconciled_without_deliverable_is_not_completion(renv):
    pid = seed(renv)
    cfg = {
        "project_id": pid,
        "tasks": [
            task("d1", "Needs File", artifact="needs.txt"),
            task("d2", "No File Needed"),
        ],
        # d1's provider reports success but never writes the deliverable on its first run;
        # the process is stopped right after d1's reservation is settled (artifact node not run).
        "provider": {"Needs File": {"0": {"mode": "no_deliverable"}}},
        "failpoints": [{"name": "after_reconcile", "match": "d1.0"}],
    }
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("after_reconcile.d1.0")
    eid = renv.execution_id(pid)
    deadline = time.time() + 20
    while time.time() < deadline:
        st = {r["task_id"]: r["status"] for r in renv.snapshot(eid)["reservations"]}
        if st.get("d1") == "RECONCILED" and st.get("d2") == "RECONCILED":
            break
        time.sleep(0.1)
    mid = renv.snapshot(eid)
    assert all(r["status"] == "RECONCILED" for r in mid["reservations"])  # both settled...
    assert all(t["status"] == "PENDING" for t in mid["tasks"])  # ...but nothing persisted done
    assert not (renv.storage / pid / "needs.txt").exists()
    renv.kill9(p1)

    _recover(renv, cfg, eid)
    after = renv.snapshot(eid)
    # "No File Needed" has no deliverable requirement: its reconciled success is adopted.
    # "Needs File" has a reconciled success but no deliverable on disk: a RECONCILED reservation
    # alone is NOT completion, so it is run again.
    starts = _starts(renv)
    assert ("No File Needed", 1) not in starts
    assert ("Needs File", 1) in starts
    keys = {r["reservation_key"]: r["status"] for r in after["reservations"]}
    assert keys["task:d1:attempt:0"] == "RECONCILED" and keys["task:d1:attempt:1"] == "RECONCILED"
    assert "task:d2:attempt:1" not in keys
    assert after["execution"]["status"] == "COMPLETED"
    assert (renv.storage / pid / "needs.txt").exists()
    assert after["budget"]["total_agent_attempts"] == 3


def test_e_parallel_wave_completed_siblings_survive(renv):
    pid = seed(renv)
    cfg = cfg_parallel(project_id=pid, provider={"Par Three": {"0": {"mode": "hang"}}})
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("provider_hang.Par Three.0")
    eid = renv.execution_id(pid)
    deadline = time.time() + 20
    while time.time() < deadline:
        st = {r["task_id"]: r["status"] for r in renv.snapshot(eid)["reservations"]}
        if st.get("p1") == "RECONCILED" and st.get("p2") == "RECONCILED":
            break
        time.sleep(0.1)
    mid = renv.snapshot(eid)
    assert {r["task_id"]: r["status"] for r in mid["reservations"]} == {
        "p1": "RECONCILED",
        "p2": "RECONCILED",
        "p3": "ACTIVE",
    }
    renv.kill9(p1)

    _recover(renv, cfg, eid)
    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "COMPLETED"
    starts = _starts(renv)
    # siblings p1/p2 ran once; only the unfinished p3 was invoked a second time
    assert starts.count(("Par One", 0)) == 1 and ("Par One", 1) not in starts
    assert starts.count(("Par Two", 0)) == 1 and ("Par Two", 1) not in starts
    assert ("Par Three", 0) in starts and ("Par Three", 1) in starts
    keys = {r["reservation_key"]: r["status"] for r in after["reservations"]}
    assert keys == {
        "task:p1:attempt:0": "RECONCILED",
        "task:p2:attempt:0": "RECONCILED",
        "task:p3:attempt:0": "EXPIRED",
        "task:p3:attempt:1": "RECONCILED",
    }
    assert sorted(t["title"] for t in after["tasks"]) == ["Par One", "Par Three", "Par Two"]
    assert all(t["status"] == "COMPLETED" for t in after["tasks"])
    assert len(after["artifacts"]) == 3
    assert after["budget"]["total_agent_attempts"] == 4
    assert after["budget"]["active_reservations_count"] == 0


def test_f_artifact_written_but_registration_interrupted(renv):
    pid = seed(renv)
    cfg = cfg_two_chain(project_id=pid, failpoints=[{"name": "before_register_artifact"}])
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("before_register_artifact")
    eid = renv.execution_id(pid)
    mid = renv.snapshot(eid)
    assert mid["artifacts"] == []  # registration never committed
    assert [t["status"] for t in mid["tasks"]] == ["PENDING", "PENDING"]
    assert (renv.storage / pid / "one.txt").exists()  # but the deliverable is on disk
    renv.kill9(p1)

    _recover(renv, cfg, eid)
    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "COMPLETED"
    # Task One is adopted from its settled attempt (file exists): no second provider call for it.
    assert _starts(renv) == [("Task One", 0), ("Task Two", 0)]
    paths = [a["file_path"] for a in after["artifacts"]]
    assert sorted(paths) == [f"{pid}/one.txt", f"{pid}/two.txt"]  # registered exactly once each
    assert all(t["status"] == "COMPLETED" for t in after["tasks"])
