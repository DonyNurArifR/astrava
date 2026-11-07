"""Scenario A: the orchestrator process is SIGKILLed while the provider call is in flight."""

import time

from tests.recovery.harness import LEASE_TTL
from tests.recovery.scenarios import cfg_two_chain
from tests.recovery.test_00_baseline import seed


def test_a_sigkill_during_provider_execution_then_recover(renv):
    pid = seed(renv)
    cfg = cfg_two_chain(
        project_id=pid,
        provider={"Task One": {"0": {"mode": "hang"}}},  # first invocation never returns
    )
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("provider_hang.Task One.0"), "provider never started"
    eid = renv.execution_id(pid)

    before = renv.snapshot(eid)
    assert before["execution"]["status"] == "RUNNING" and before["execution"]["run_epoch"] == 1
    assert before["execution"]["lease_owner"] is not None
    assert [r["status"] for r in before["reservations"]] == ["ACTIVE"]
    assert before["budget"]["active_reservations_count"] == 1
    assert len(before["tasks"]) == 2 and all(t["status"] == "PENDING" for t in before["tasks"])

    renv.kill9(p1)  # real SIGKILL
    assert p1.popen.returncode == -9

    # While the dead owner's lease is still live, a recoverer is refused (exit 3).
    code, res, _ = renv.run("recover", {**cfg, "execution_id": eid})
    assert code == 3 and "LeaseHeldError" in res["error"], res
    assert renv.snapshot(eid)["execution"]["run_epoch"] == 1  # refusal changed nothing

    time.sleep(LEASE_TTL + 0.5)  # lease expires; nobody heartbeats a dead process
    p2 = renv.spawn("recover", {**cfg, "execution_id": eid})
    assert renv.wait(p2) == 0, p2.result()
    assert p2.result()["status"] == "completed"
    assert p2.pid != p1.pid

    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "COMPLETED"
    assert after["execution"]["run_epoch"] == 2
    assert after["execution"]["lease_owner"] is None
    # no duplicate task rows, every task completed
    assert sorted(t["title"] for t in after["tasks"]) == ["Task One", "Task Two"]
    assert all(t["status"] == "COMPLETED" for t in after["tasks"])
    # reservation ledger: the orphan was expired exactly once, retry attempt 1 reconciled
    by_key = {r["reservation_key"]: r for r in after["reservations"]}
    assert by_key["task:t1:attempt:0"]["status"] == "EXPIRED"
    assert by_key["task:t1:attempt:0"]["metadata_json"]["recovery_expired"] is True
    assert by_key["task:t1:attempt:1"]["status"] == "RECONCILED"
    assert by_key["task:t2:attempt:0"]["status"] == "RECONCILED"
    assert len(after["reservations"]) == 3
    assert after["budget"]["active_reservations_count"] == 0
    assert after["budget"]["total_agent_attempts"] == 3  # 1 expired + 2 reconciled, no double count
    assert len(after["artifacts"]) == 2
    assert "pipeline_recovered" in after["events"]
    # provider invoked again for Task One (documented at-least-once), Task Two once
    starts = [(i["title"], i["ordinal"]) for i in renv.invocations() if i["event"] == "start"]
    assert starts == [("Task One", 0), ("Task One", 1), ("Task Two", 0)]

    # Repeated recovery of a finished execution is an idempotent no-op.
    code, res, _ = renv.run("recover", {**cfg, "execution_id": eid})
    assert code == 0 and res["status"] == "completed"
    final = renv.snapshot(eid)
    for key in ("execution", "reservations", "tasks", "artifacts", "events"):
        assert final[key] == after[key], key
    assert final["budget"] == after["budget"]
    assert len([i for i in renv.invocations() if i["event"] == "start"]) == 3
