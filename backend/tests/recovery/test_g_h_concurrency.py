"""Scenarios G and H plus retry/limit/terminal invariants, with real processes."""

import os
import signal
import time

from tests.recovery.harness import LEASE_TTL
from tests.recovery.scenarios import cfg_single, cfg_two_chain, task
from tests.recovery.test_00_baseline import seed


def _starts(renv):
    return [(i["title"], i["ordinal"]) for i in renv.invocations() if i["event"] == "start"]


def test_g_stale_worker_returns_after_newer_worker_took_over(renv):
    pid = seed(renv)
    release = renv.root / "release-old-worker"
    cfg = cfg_two_chain(
        project_id=pid,
        provider={"Task One": {"0": {"mode": "wait_file", "file": str(release)}}},
    )
    old = renv.spawn("start", cfg)
    assert renv.wait_marker("provider_wait.Task One.0")
    eid = renv.execution_id(pid)

    os.kill(old.pid, signal.SIGSTOP)  # frozen: no heartbeat, provider call still outstanding
    time.sleep(LEASE_TTL + 0.7)
    new = renv.spawn("recover", {**cfg, "execution_id": eid})
    assert renv.wait(new) == 0, new.result()
    assert new.result()["status"] == "completed"
    done = renv.snapshot(eid)
    assert done["execution"]["status"] == "COMPLETED" and done["execution"]["run_epoch"] == 2
    stale_token = next(
        r["fence_token"]
        for r in done["reservations"]
        if r["reservation_key"] == "task:t1:attempt:0"
    )
    assert stale_token  # the old worker still holds exactly this (now dead) token

    release.write_text("go")
    os.kill(old.pid, signal.SIGCONT)  # the stale worker wakes up and finishes its provider call
    assert renv.wait(old, timeout=60) == 4, old.stdout_path.read_text()[-2000:]
    assert "StaleWorkerError" in old.result()["error"]

    # Nothing the stale worker did changed the database.
    after = renv.snapshot(eid)
    for key in ("execution", "reservations", "tasks", "artifacts", "events", "model_executions"):
        assert after[key] == done[key], key
    assert after["budget"] == done["budget"]
    t1 = next(r for r in after["reservations"] if r["reservation_key"] == "task:t1:attempt:0")
    assert t1["status"] == "EXPIRED" and t1["fence_token"] == stale_token
    # The woken worker stopped itself (heartbeat saw the superseded epoch) before it could settle
    # or persist anything; the direct reservation-fence and epoch-fence rejections are covered
    # atomically in test_m1_5_1c_fencing.py.


def test_h_two_recoverers_exactly_one_wins(renv):
    pid = seed(renv)
    cfg = cfg_two_chain(project_id=pid, provider={"Task One": {"0": {"mode": "hang"}}})
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("provider_hang.Task One.0")
    eid = renv.execution_id(pid)
    renv.kill9(p1)
    time.sleep(LEASE_TTL + 0.5)

    barrier = renv.root / "go"
    rec = {**cfg, "execution_id": eid, "barrier_file": str(barrier)}
    a = renv.spawn("recover", rec)
    b = renv.spawn("recover", rec)
    time.sleep(3)  # both processes imported and are waiting at the barrier
    barrier.write_text("go")
    codes = sorted([renv.wait(a), renv.wait(b)])
    # one recovered; the other was refused (3) or found the work already finished (0)
    assert codes in ([0, 0], [0, 3]), (codes, a.result(), b.result())

    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "COMPLETED"
    assert after["execution"]["run_epoch"] == 2  # exactly one successful claim
    assert after["events"].count("pipeline_recovered") == 1
    assert sorted(t["title"] for t in after["tasks"]) == ["Task One", "Task Two"]
    assert len(after["artifacts"]) == 2
    assert len(after["reservations"]) == 3
    assert after["budget"]["total_agent_attempts"] == 3
    assert after["budget"]["active_reservations_count"] == 0
    assert _starts(renv) == [("Task One", 0), ("Task One", 1), ("Task Two", 0)]


def test_h_concurrent_and_repeated_approval_resume(renv):
    pid = seed(renv)
    gated = task("g1", "Gated Task", artifact="gated.txt")
    gated["requires_approval"] = True
    cfg = {"project_id": pid, "tasks": [gated]}
    code, res, _ = renv.run("start", cfg)
    assert code == 0 and res["status"] == "waiting_approval", res
    eid = renv.execution_id(pid)
    assert renv.snapshot(eid)["execution"]["lease_owner"] is None

    barrier = renv.root / "go"
    rec = {**cfg, "execution_id": eid, "barrier_file": str(barrier)}
    a = renv.spawn("resume", rec)
    b = renv.spawn("resume", rec)
    time.sleep(3)
    barrier.write_text("go")
    assert renv.wait(a) == 0 and renv.wait(b) == 0
    done = renv.snapshot(eid)
    assert done["execution"]["status"] == "COMPLETED"
    assert done["execution"]["run_epoch"] == 2  # start=1, exactly one resume claimed
    assert _starts(renv) == [("Gated Task", 0)]  # the task ran once
    assert done["events"].count("pipeline_resumed") == 1

    # Resuming a finished execution again changes nothing.
    code, res, _ = renv.run("resume", {**cfg, "execution_id": eid})
    assert code == 0 and res["status"] == "completed"
    again = renv.snapshot(eid)
    for key in ("execution", "reservations", "tasks", "artifacts", "events"):
        assert again[key] == done[key], key
    assert _starts(renv) == [("Gated Task", 0)]


def test_failed_execution_is_never_reopened_by_resume_or_recover(renv):
    pid = seed(renv)
    cfg = cfg_single(project_id=pid, provider={"Solo": {"default": {"mode": "fail"}}})
    code, res, _ = renv.run("start", cfg)
    assert code == 0 and res["status"] == "failed", res
    eid = renv.execution_id(pid)
    failed = renv.snapshot(eid)
    assert failed["execution"]["status"] == "FAILED"
    assert _starts(renv) == [("Solo", 0), ("Solo", 1)]  # max_retries + 1 attempts, no more

    for cmd in ("resume", "recover"):
        code, res, _ = renv.run(cmd, {**cfg, "execution_id": eid})
        assert code == 0 and res["status"] == "failed", (cmd, res)
    still = renv.snapshot(eid)
    for key in ("execution", "reservations", "tasks", "artifacts", "events"):
        assert still[key] == failed[key], key
    assert len(_starts(renv)) == 2


def test_retry_limit_and_budget_are_preserved_across_restart(renv):
    pid = seed(renv)
    # attempt 0 hangs (killed); after recovery only ONE attempt remains (max_retries=1 => 2 total)
    cfg = cfg_single(
        project_id=pid,
        provider={"Solo": {"0": {"mode": "hang"}, "default": {"mode": "fail"}}},
    )
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("provider_hang.Solo.0")
    eid = renv.execution_id(pid)
    renv.kill9(p1)
    time.sleep(LEASE_TTL + 0.5)
    p2 = renv.spawn("recover", {**cfg, "execution_id": eid})
    assert renv.wait(p2) == 0
    assert p2.result()["status"] == "failed"
    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "FAILED"  # a failing task never turns into success
    # total provider invocations for the task never exceed max_retries + 1 = 2
    assert _starts(renv) == [("Solo", 0), ("Solo", 1)]
    keys = {r["reservation_key"]: r["status"] for r in after["reservations"]}
    assert keys == {"task:s1:attempt:0": "EXPIRED", "task:s1:attempt:1": "RECONCILED"}
    assert after["budget"]["total_agent_attempts"] == 2
    assert after["budget"]["active_reservations_count"] == 0
    assert all(t["status"] == "FAILED" for t in after["tasks"])
    # the task failed because its recovered attempt really failed, not because of a bookkeeping
    # collision between the dispatcher's attempt number and the retry loop
    err = renv.rows(
        "SELECT error_details FROM tasks WHERE project_id=:p AND input_data->>'execution_id'=:e",
        p=pid,
        e=eid,
    )[0]["error_details"]
    assert "deterministic failure of Solo #1" in err, err


def test_remediation_state_survives_a_crash_and_is_not_recounted(renv):
    pid = seed(renv)
    cfg = cfg_single(
        project_id=pid,
        # first verification fails -> remediation (cycle 1); the remediation dispatch hangs
        semantic={"Solo": {"0": False}},
        provider={"Solo": {"1": {"mode": "hang"}}},
    )
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("provider_hang.Solo.1")
    eid = renv.execution_id(pid)
    mid = renv.snapshot(eid)
    assert mid["budget"]["remediation_turns_count"] == 1
    persisted = renv.rows("SELECT state_data FROM workflow_executions WHERE id=:e", e=eid)[0][
        "state_data"
    ]
    assert (
        persisted["tasks"][0]["remediation_cycles"] == 1
    )  # checkpointed after the remediation node
    renv.kill9(p1)

    time.sleep(LEASE_TTL + 0.5)
    p2 = renv.spawn("recover", {**cfg, "execution_id": eid})
    renv.wait(p2)
    after = renv.snapshot(eid)
    # the remediation turn already counted before the crash is not counted again
    assert after["budget"]["remediation_turns_count"] == 1
    assert after["budget"]["active_reservations_count"] == 0
    # attempt budget for the task (max_retries + 1 = 2) was consumed by attempt 0 and the lost
    # remediation attempt, so the task ends FAILED; it is never silently successful
    assert after["execution"]["status"] == "FAILED"
    assert len(_starts(renv)) == 2


def test_failed_reconciled_attempt_is_never_adopted_as_completion(renv):
    pid = seed(renv)
    # attempt 0: provider "succeeds" with a schema-violating output but writes the deliverable
    # (reconciled, success=False); attempt 1 hangs and the process is killed.
    cfg = cfg_single(
        project_id=pid,
        provider={"Solo": {"0": {"mode": "bad_schema"}, "1": {"mode": "hang"}}},
    )
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("provider_hang.Solo.1")
    eid = renv.execution_id(pid)
    mid = renv.snapshot(eid)
    first = next(r for r in mid["reservations"] if r["reservation_key"] == "task:s1:attempt:0")
    assert first["status"] == "RECONCILED" and first["metadata_json"]["success"] is False
    assert (renv.storage / pid / "solo.txt").exists()  # output AND deliverable are present
    renv.kill9(p1)

    time.sleep(LEASE_TTL + 0.5)
    p2 = renv.spawn("recover", {**cfg, "execution_id": eid})
    renv.wait(p2)
    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "FAILED"  # a failed attempt is not task completion
    assert all(t["status"] != "COMPLETED" for t in after["tasks"])
    assert len(_starts(renv)) == 2  # no further provider call: attempts are exhausted


def test_crash_before_first_sync_still_recovers_from_initial_checkpoint(renv):
    pid = seed(renv)
    cfg = cfg_two_chain(project_id=pid, failpoints=[{"name": "before_sync"}])
    p1 = renv.spawn("start", cfg)
    assert renv.wait_marker("before_sync")  # first sync = right after retrieve_knowledge
    eid = renv.execution_id(pid)
    state = renv.rows("SELECT state_data FROM workflow_executions WHERE id=:e", e=eid)[0][
        "state_data"
    ]
    assert state["execution_id"] == eid and state["agent_snapshots"] and "plan" not in state
    renv.kill9(p1)

    time.sleep(LEASE_TTL + 0.5)
    p2 = renv.spawn("recover", {**cfg, "failpoints": [], "execution_id": eid})
    assert renv.wait(p2) == 0
    after = renv.snapshot(eid)
    assert after["execution"]["status"] == "COMPLETED" and after["execution"]["run_epoch"] == 2
    assert len(after["tasks"]) == 2
