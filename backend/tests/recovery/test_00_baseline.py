from tests.recovery.scenarios import cfg_two_chain


def seed(renv) -> str:
    code, res, _ = renv.run("seed", {})
    assert code == 0, res
    return res["project_id"]


def test_uninterrupted_run_through_real_process_completes(renv):
    pid = seed(renv)
    code, res, _ = renv.run("start", {**cfg_two_chain(), "project_id": pid})
    assert code == 0 and res["status"] == "completed", res
    eid = renv.execution_id(pid)
    snap = renv.snapshot(eid)
    assert snap["execution"]["status"] == "COMPLETED"
    assert snap["execution"]["run_epoch"] == 1
    assert snap["execution"]["lease_owner"] is None  # lease released at the end
    assert len(snap["tasks"]) == 2 and all(t["status"] == "COMPLETED" for t in snap["tasks"])
    assert [r["status"] for r in snap["reservations"]] == ["RECONCILED", "RECONCILED"]
    assert snap["budget"]["active_reservations_count"] == 0
    assert len(snap["artifacts"]) == 2
    assert len(renv.invocations()) == 4  # 2 tasks x (start+end)
