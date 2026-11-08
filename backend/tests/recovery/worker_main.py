"""Subprocess entry point for the M1.5-1c crash-recovery tests.

Runs the REAL OrchestrationRunner against the REAL PostgreSQL database named by the environment.
Only the external model boundary is replaced with deterministic test doubles (provider, planner,
semantic evaluator), and optional failpoints stop the process at an exact point so the parent test
can SIGKILL it. Nothing here is imported by production code.

Usage: python -m tests.recovery.worker_main <seed|start|recover|resume> <config.json>
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

CFG = json.loads(Path(sys.argv[2]).read_text())
CTL = Path(CFG["ctl_dir"])
INVOCATIONS = CTL / "invocations.log"


def marker(name: str) -> None:
    (CTL / f"fp.{name}").write_text(str(os.getpid()))


async def hang() -> None:
    await asyncio.sleep(10**6)


def log_invocation(title: str, ordinal: int, event: str) -> None:
    line = json.dumps(
        {"pid": os.getpid(), "title": title, "ordinal": ordinal, "event": event, "t": time.time()}
    )
    fd = os.open(INVOCATIONS, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)


def next_ordinal(title: str) -> int:
    if not INVOCATIONS.exists():
        return 0
    n = 0
    for raw in INVOCATIONS.read_text().splitlines():
        rec = json.loads(raw)
        if rec["title"] == title and rec["event"] == "start":
            n += 1
    return n


def install_doubles() -> None:
    from app.orchestrator.planner import GoalDecomposer, PlannedTask, StructuredPlan
    from app.providers.base import BaseProvider, ProviderResponse, ProviderStatus
    from app.providers.factory import ProviderFactory
    from app.verification.semantic_evaluator import SemanticEvaluationResult, SemanticEvaluator

    class FakeProvider(BaseProvider):
        @property
        def name(self) -> str:
            return "claude_code"

        async def execute(self, request):  # noqa: ANN001
            title = request.prompt.split("Your Assigned Task: ", 1)[1].split("\n", 1)[0].strip()
            ordinal = next_ordinal(title)
            log_invocation(title, ordinal, "start")
            plan = CFG.get("provider", {}).get(title, {})
            beh = plan.get(str(ordinal), plan.get("default", {"mode": "ok"}))
            mode = beh.get("mode", "ok")
            if mode == "hang":
                marker(f"provider_hang.{title}.{ordinal}")
                await hang()
            if mode == "wait_file":
                marker(f"provider_wait.{title}.{ordinal}")
                while not Path(beh["file"]).exists():
                    await asyncio.sleep(0.2)
            if mode == "sleep":
                await asyncio.sleep(float(beh.get("seconds", 1)))
            # A real agent writes its deliverables into the working directory itself.
            if mode not in ("fail", "no_deliverable"):  # bad_schema still writes files
                import ast

                try:
                    expected = ast.literal_eval(
                        request.prompt.split("Expected Deliverables: ", 1)[1].split("\n", 1)[0]
                    )
                except Exception:  # noqa: BLE001
                    expected = []
                for name in expected:
                    target = Path(request.working_directory) / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"deliverable of {title} #{ordinal} by pid {os.getpid()}")
            log_invocation(title, ordinal, "end")
            if mode == "fail":
                return ProviderResponse(
                    status=ProviderStatus.FAILED,
                    exit_code=1,
                    error_message=f"deterministic failure of {title} #{ordinal}",
                    duration_ms=5,
                )
            if mode == "bad_schema":  # provider "succeeds" but violates the agent output schema
                return ProviderResponse(
                    status=ProviderStatus.SUCCESS,
                    output_text=json.dumps({"other": "no summary field"}),
                    exit_code=0,
                    duration_ms=10,
                )
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                output_text=json.dumps({"summary": f"output of {title} #{ordinal}"}),
                exit_code=0,
                duration_ms=10,
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.001,
                canonical_model="claude-haiku-5-5",
            )

    fake = FakeProvider()
    ProviderFactory.get_provider = classmethod(lambda cls, name="claude_code": fake)

    async def fake_decompose(cls, objective, project_id, studio_type=None, **kw):  # noqa: ANN001
        return StructuredPlan(
            project_id=str(project_id),
            objective=objective,
            strategy_summary="deterministic recovery-test plan",
            tasks=[PlannedTask(**t) for t in CFG["tasks"]],
        )

    GoalDecomposer.decompose_goal = classmethod(fake_decompose)

    eval_log = CTL / "evaluations.log"

    async def fake_evaluate(**kw):  # noqa: ANN003
        title = kw.get("task_title", "")
        n = 0
        if eval_log.exists():
            n = sum(1 for raw in eval_log.read_text().splitlines() if raw == title)
        with eval_log.open("a") as fh:
            fh.write(title + "\n")
        verdict = CFG.get("semantic", {}).get(title, {}).get(str(n), True)
        return SemanticEvaluationResult(
            passed=bool(verdict),
            compliance_score=1.0 if verdict else 0.1,
            unmet_criteria=[] if verdict else ["scripted failure"],
            reasoning="scripted",
        )

    SemanticEvaluator.evaluate = staticmethod(fake_evaluate)


def install_failpoints() -> None:
    from app.orchestrator.runner import OrchestrationRunner
    from app.services.artifact_service import ArtifactService
    from app.services.budget_governor import BudgetGovernor

    fps = CFG.get("failpoints", [])
    fired: set[str] = set()

    def armed(name: str) -> dict | None:
        for fp in fps:
            if fp["name"] == name and name not in fired:
                return fp
        return None

    orig_reconcile = BudgetGovernor.reconcile

    async def reconcile(db, reservation_id, *a, **kw):  # noqa: ANN001
        from app.models.budget import BudgetReservation

        res = await db.get(BudgetReservation, reservation_id)
        key = f"{res.task_id}.{res.attempt_number}" if res else "?"
        fp_b = armed("before_reconcile")
        if fp_b and fp_b.get("match", key) == key:
            fired.add("before_reconcile")
            marker(f"before_reconcile.{key}")
            await hang()
        out = await orig_reconcile(db, reservation_id, *a, **kw)
        fp_a = armed("after_reconcile")
        if fp_a and fp_a.get("match", key) == key:
            # Commit happens in the caller right after we return; wait for it by hanging only
            # after a short delay so the reconcile is durable before the parent kills us.
            fired.add("after_reconcile")
            await db.commit()
            marker(f"after_reconcile.{key}")
            await hang()
        return out

    BudgetGovernor.reconcile = staticmethod(reconcile)

    orig_sync = OrchestrationRunner._sync_state_to_db

    async def sync(db, execution_id, project_id, state, epoch=None):  # noqa: ANN001
        fp = armed("before_sync")
        if (
            fp
            and len(state.get("artifacts", [])) >= fp.get("min_artifacts", 0)
            and (len(state.get("completed_task_ids", [])) >= fp.get("min_completed", 0))
        ):
            fired.add("before_sync")
            marker("before_sync")
            await hang()
        return await orig_sync(db, execution_id, project_id, state, epoch=epoch)

    OrchestrationRunner._sync_state_to_db = staticmethod(sync)

    orig_register = ArtifactService.register_artifact

    async def register(*a, **kw):  # noqa: ANN002, ANN003
        fp = armed("before_register_artifact")
        if fp:
            fired.add("before_register_artifact")
            marker("before_register_artifact")
            await hang()
        return await orig_register(*a, **kw)

    ArtifactService.register_artifact = staticmethod(register)


async def worker_side_task() -> None:
    """Stands in for graph dispatch (M1.5-2b+ wires real dispatch): once the execution is running
    and owned, ask the broker for workers through the REAL service, under the REAL epoch."""
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal
    from app.services.worker_run_service import WorkerRunService
    from app.worker_runtime import get_worker_runtime
    from astrava_broker.profiles import Profile

    side = CFG["worker_side"]
    async with AsyncSessionLocal() as db:
        while True:
            row = (
                await db.execute(
                    text(
                        "SELECT id, run_epoch FROM workflow_executions "
                        "WHERE project_id = :p AND run_epoch > 0"
                    ),
                    {"p": CFG["project_id"]},
                )
            ).first()
            if row:
                break
            await db.rollback()
            await asyncio.sleep(0.1)
        eid, epoch = row[0], int(row[1])
        runtime = get_worker_runtime()
        assert runtime is not None
        for _i in range(side.get("count", 1)):
            run = await WorkerRunService.launch(
                db,
                runtime,
                execution_id=eid,
                epoch=epoch,
                task_id=uuid.uuid4(),
                attempt=0,
                profile=Profile.AGENT_STANDARD,
                repo_id="repo-one",
                base_ref="a" * 40,
                wall_timeout_s=side.get("wall_timeout_s", 600),
                job=json.dumps({"fake": {"runtime_s": 100000}}),
            )
            await WorkerRunService.start(db, runtime, run, epoch)
        (CTL / "execution_id").write_text(str(eid))
        marker("workers_started")
    await hang()


async def amain() -> int:
    install_doubles()
    install_failpoints()
    from app.db.session import AsyncSessionLocal
    from app.orchestrator.runner import OrchestrationRunner
    from app.services.execution_lease import LeaseHeldError, StaleWorkerError

    cmd = sys.argv[1]
    result: dict = {"pid": os.getpid(), "cmd": cmd}
    if CFG.get("barrier_file"):
        # Lets the parent release several processes at the same instant.
        while not Path(CFG["barrier_file"]).exists():
            await asyncio.sleep(0.01)
    code = 0
    try:
        async with AsyncSessionLocal() as db:
            if cmd == "seed":
                from app.schemas.project import ProjectCreate
                from app.services.project_service import ProjectService

                project = await ProjectService.create(
                    db, ProjectCreate(name=f"recovery-{uuid.uuid4().hex[:6]}", base_branch="main")
                )
                await db.commit()
                result["project_id"] = str(project.id)
            elif cmd == "start":
                if CFG.get("worker_side"):
                    side_task = asyncio.ensure_future(worker_side_task())  # noqa: F841
                ex = await OrchestrationRunner.start_pipeline(
                    db, uuid.UUID(CFG["project_id"]), CFG.get("objective", "recovery test")
                )
                result["status"] = ex.status.value
            elif cmd == "stale_probe":
                # A superseded API process (old epoch) tries to create a worker both through the
                # control-plane service (DB fence) and directly at the broker (broker fence).
                from app.services.worker_run_service import WorkerRunService
                from app.worker_runtime import get_worker_runtime
                from app.worker_runtime.base import (
                    CreateWorkerRequest,
                    RuntimeConflictError,
                    WorkerRef,
                )
                from astrava_broker.profiles import ImageAlias, Profile, WorkerKind

                runtime = get_worker_runtime()
                eid, old = uuid.UUID(CFG["execution_id"]), int(CFG["epoch"])
                try:
                    await WorkerRunService.launch(
                        db, runtime, execution_id=eid, epoch=old, task_id=uuid.uuid4(),
                        attempt=0, profile=Profile.AGENT_STANDARD, repo_id="repo-one",
                        base_ref="a" * 40, wall_timeout_s=60, job="{}",
                    )  # fmt: skip
                    result["db_fence"] = "NOT FENCED"
                except StaleWorkerError:
                    result["db_fence"] = "StaleWorkerError"
                try:
                    await runtime.create_worker(
                        CreateWorkerRequest(
                            ref=WorkerRef(uuid.uuid4(), eid, old),
                            task_id=uuid.uuid4(),
                            attempt=0,
                            kind=WorkerKind.AGENT,
                            profile=Profile.AGENT_STANDARD,
                            image_alias=ImageAlias.AGENT_BASE,
                            repo_id="repo-one",
                            base_ref="a" * 40,
                            wall_timeout_s=60,
                            job="{}",
                        )  # fmt: skip
                    )
                    result["broker_fence"] = "NOT FENCED"
                except RuntimeConflictError:
                    result["broker_fence"] = "RuntimeConflictError"
            elif cmd == "recover":
                ex = await OrchestrationRunner.recover_execution(db, uuid.UUID(CFG["execution_id"]))
                result["status"] = ex.status.value
            elif cmd == "resume":
                from app.models.approval import ApprovalStatus
                from app.schemas.approval import ApprovalDecisionRequest

                ex = await OrchestrationRunner.resume_pipeline(
                    db,
                    uuid.UUID(CFG["execution_id"]),
                    ApprovalDecisionRequest(
                        decision=ApprovalStatus.APPROVED, reason="test", decided_by="test"
                    ),
                )
                result["status"] = ex.status.value
    except LeaseHeldError as exc:
        result["error"] = f"LeaseHeldError: {exc}"
        code = 3
    except StaleWorkerError as exc:
        result["error"] = f"StaleWorkerError: {exc}"
        code = 4
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    print("RESULT " + json.dumps(result), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
