import asyncio
import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.approval import ApprovalStatus
from app.models.artifact import ArtifactType
from app.models.budget import BudgetReservation, BudgetReservationStatus, BudgetStatus
from app.models.execution import ExecutionStatus, WorkflowExecution
from app.models.task import RiskLevel, TaskStatus
from app.models.usage import ModelExecutionStatus
from app.orchestrator.state import OrchestrationState
from app.orchestrator.workflow_graph import build_orchestrator_graph
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.artifact import ArtifactCreate
from app.schemas.execution import ExecutionCreate
from app.schemas.task import TaskCreate, TaskUpdate
from app.schemas.usage import ModelExecutionCreate
from app.schemas.workflow import WorkflowCreate
from app.services.agent_service import AgentService
from app.services.approval_service import ApprovalService
from app.services.artifact_service import ArtifactService
from app.services.budget_governor import BudgetGovernor
from app.services.execution_lease import (
    LeaseHeldError,
    StaleWorkerError,
    assert_epoch,
    claim,
    new_owner_id,
    release,
    run_with_lease,
)
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.services.usage_service import UsageService
from app.services.worker_run_service import WorkerReconcileError, WorkerRunService
from app.services.workflow_service import WorkflowService
from app.worker_runtime import WorkerRuntime, WorkerRuntimeError, get_worker_runtime
from app.workspace import GitWorktreeManager, RepoScanner
from app.workspace.path_security import (
    ExecutionSetupError,
    PathContainmentError,
    resolve_worktree_path,
    safe_join,
    validate_repo_path,
)

logger = logging.getLogger("astrava.orchestrator.runner")

# Concurrency semaphore enforcing MAX_CONCURRENT_EXECUTIONS
_execution_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_EXECUTIONS)


# Nodes after which the full state (tasks, artifacts, usage, terminal status) is synced.
_FULL_SYNC_NODES_START = frozenset(
    {"retrieve_knowledge", "plan", "artifact", "ingest_knowledge", "complete"}
)
_FULL_SYNC_NODES_RESUME = frozenset({"artifact", "ingest_knowledge", "complete"})
# Nodes after which only the state snapshot is persisted (status stays RUNNING). Their output
# resets tasks to a re-runnable state, so re-entering the graph from it is safe. dispatch_task
# and verify are deliberately NOT checkpointed: their result is rebuilt from settled reservations.
_CHECKPOINT_NODES = frozenset({"remediation", "replan"})

_MAX_OBSERVED_HASH_BYTES = 25 * 1024 * 1024


def _worktree_sha256(worktree_path: str, name: str) -> str | None:
    """SHA-256 of an artifact file inside the execution worktree, or None.

    Returns None silently when the file is absent, the path is unsafe, or it exceeds the size
    limit. The worktree is the file the agent produced; the storage copy is not consulted.
    """
    try:
        root = resolve_worktree_path(worktree_path)
        target = safe_join(root, name)
        if not target.is_file() or target.stat().st_size > _MAX_OBSERVED_HASH_BYTES:
            return None
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (PathContainmentError, OSError):
        return None


def _redact_host_paths(text: str, repo_path: str | None) -> str:
    """Keep host filesystem locations out of persisted setup-failure reasons."""
    replacements: list[tuple[str, str]] = [
        (str(settings.WORKTREE_STORAGE_PATH), "<worktree storage>"),
        (str(settings.ARTIFACT_STORAGE_PATH), "<artifact storage>"),
    ]
    if repo_path:
        replacements.append((repo_path, "<configured repository>"))
        replacements.append((str(Path(repo_path).resolve()), "<configured repository>"))
    redacted = text
    for raw, label in replacements:
        if raw:
            redacted = redacted.replace(raw, label)
    return redacted


class OrchestrationRunner:
    @staticmethod
    async def start_pipeline(
        db: AsyncSession,
        project_id: uuid.UUID,
        objective: str,
        studio_type: str = "saas",
        goal_id: uuid.UUID | None = None,
    ) -> WorkflowExecution:
        # The semaphore is taken BEFORE the execution is created or claimed, so a queued run never
        # holds an un-heartbeated lease while it waits.
        async with _execution_semaphore:
            return await OrchestrationRunner._start_pipeline_locked(
                db, project_id, objective, studio_type, goal_id
            )

    @staticmethod
    async def _start_pipeline_locked(
        db: AsyncSession,
        project_id: uuid.UUID,
        objective: str,
        studio_type: str,
        goal_id: uuid.UUID | None,
    ) -> WorkflowExecution:
        # 1. Create or retrieve active workflow
        wf_data = WorkflowCreate(
            project_id=project_id,
            name=f"{studio_type.upper()} Pipeline: {objective[:40]}...",
            studio_type=studio_type,
            step_definitions=[
                {"step": 1, "name": "Plan Formulation"},
                {"step": 2, "name": "Task Execution"},
                {"step": 3, "name": "Verification"},
                {"step": 4, "name": "Artifact Registration"},
            ],
        )
        workflow = await WorkflowService.create_workflow(db, wf_data)

        # 2. Create execution entry
        exec_init_state = {
            "objective": objective,
            "studio_type": studio_type,
        }
        if goal_id:
            exec_init_state["goal_id"] = str(goal_id)

        exec_data = ExecutionCreate(
            workflow_id=workflow.id,
            project_id=project_id,
            initial_state=exec_init_state,
        )
        execution = await WorkflowService.create_execution(db, exec_data)
        if goal_id:
            execution.goal_id = goal_id
            await db.flush()
        await WorkflowService.record_event(
            db,
            execution.id,
            "pipeline_started",
            {
                "objective": objective,
                "studio_type": studio_type,
                "goal_id": str(goal_id) if goal_id else None,
            },
        )

        # Take single-writer ownership (commits the execution as RUNNING with a live lease).
        owner = new_owner_id("run")
        # PENDING -> RUNNING and the lease are one atomic UPDATE, so the execution is never
        # visible as RUNNING-without-owner to a recoverer.
        epoch = await claim(
            db,
            execution.id,
            owner,
            settings.EXECUTION_LEASE_TTL_SECONDS,
            statuses=(ExecutionStatus.PENDING,),
            new_status=ExecutionStatus.RUNNING,
        )
        await WorkflowService.update_execution_status(db, execution.id, ExecutionStatus.RUNNING)

        # Setup Git Worktree Sandboxing & Repository Context if project is bound to a repo.
        # Fail closed: any setup failure ends the execution FAILED before a provider can run.
        project = await ProjectService.get_by_id(db, project_id)
        try:
            (
                repo_path_str,
                worktree_path,
                worktree_branch,
                repo_context_summary,
            ) = await OrchestrationRunner._setup_isolation(db, execution, project)
        except ExecutionSetupError as exc:
            failed = await OrchestrationRunner._fail_execution_setup(
                db, execution.id, str(exc), project.repo_path if project else None, epoch=epoch
            )
            await OrchestrationRunner._release_lease(execution.id, owner, epoch)
            return failed
        # Budget is initialized only after setup succeeds, so a failed setup leaves no ACTIVE
        # budget or reservation behind.
        await BudgetGovernor.initialize_budget(db, execution.id, project_id)

        # Capture immutable agent configuration snapshot for reproducible execution
        agents = await AgentService.list_agents(db)
        if not agents:
            await AgentService.seed_default_agents(db)
            agents = await AgentService.list_agents(db)
        agent_snapshots = {
            a.slug: {
                "name": a.name,
                "description": a.description,
                "instructions": a.instructions,
                "input_schema": a.input_schema,
                "output_schema": a.output_schema,
                "available_tools": a.available_tools,
                "model_config_data": a.model_config_data,
                "execution_config": a.execution_config,
                "verification_requirements": a.verification_requirements,
                "version": a.version,
            }
            for a in agents
        }

        # 3. Setup LangGraph initial state
        initial_state: OrchestrationState = {
            "execution_id": str(execution.id),
            "project_id": str(project_id),
            "objective": objective,
            "studio_type": studio_type,
            "goal_id": str(goal_id) if goal_id else None,
            "repo_path": repo_path_str,
            "worktree_path": worktree_path,
            "worktree_branch": worktree_branch,
            "agent_snapshots": agent_snapshots,
            "tasks": [],
            "completed_task_ids": [],
            "failed_task_ids": [],
            "current_task_index": 0,
            "is_paused": False,
            "status": "running",
            "verification_results": [],
            "artifacts": [],
            "usage_records": [],
            "task_db_ids": {},
            "synced_usage_count": 0,
        }
        if repo_context_summary:
            initial_state["retrieval_context"] = repo_context_summary

        # 4. Persist the complete initial state before any node runs, so a crash at any later point
        # leaves a recoverable execution (graph re-entry needs execution_id/project_id/snapshots).
        await OrchestrationRunner._checkpoint_state(db, execution.id, initial_state, epoch)

        # 5. Run the LangGraph graph under the concurrency semaphore and the execution lease.
        try:
            try:
                final_state = await OrchestrationRunner._drive_graph(
                    db,
                    execution.id,
                    project_id,
                    initial_state,
                    owner=owner,
                    epoch=epoch,
                    sync_nodes=_FULL_SYNC_NODES_START,
                )
            except ExecutionSetupError as exc:
                return await OrchestrationRunner._fail_execution_setup(
                    db, execution.id, str(exc), repo_path_str, epoch=epoch
                )

            # 6. Final synchronization back to Database
            await OrchestrationRunner._sync_state_to_db(
                db, execution.id, project_id, final_state, epoch=epoch
            )
        except StaleWorkerError:
            await OrchestrationRunner._safe_rollback(db)
            raise
        finally:
            await OrchestrationRunner._release_lease(execution.id, owner, epoch)
        reloaded = await WorkflowService.get_execution(db, execution.id)
        return reloaded or execution

    @staticmethod
    async def _drive_graph(
        db: AsyncSession,
        execution_id: uuid.UUID,
        project_id: uuid.UUID,
        state: dict[str, Any],
        *,
        owner: str,
        epoch: int,
        sync_nodes: frozenset[str],
    ) -> dict[str, Any]:
        """Stream the graph from ``state`` while the lease heartbeats; persist after each stage.

        Every write is fenced on ``epoch``. If the lease is lost the graph run is cancelled and
        StaleWorkerError is raised, so a superseded worker stops instead of racing its successor.
        """
        graph = build_orchestrator_graph()
        current_state: dict[str, Any] = dict(state)

        async def _work() -> dict[str, Any]:
            async for event in graph.astream(state):
                for node_name, node_output in event.items():
                    if node_output and isinstance(node_output, dict):
                        current_state.update(node_output)
                    if node_name in sync_nodes:
                        await OrchestrationRunner._sync_state_to_db(
                            db, execution_id, project_id, current_state, epoch=epoch
                        )
                    elif node_name in _CHECKPOINT_NODES:
                        await OrchestrationRunner._checkpoint_state(
                            db, execution_id, current_state, epoch
                        )
            return current_state

        return await run_with_lease(
            AsyncSessionLocal,
            execution_id,
            owner,
            epoch,
            settings.EXECUTION_LEASE_TTL_SECONDS,
            _work,
        )

    @staticmethod
    async def _checkpoint_state(
        db: AsyncSession, execution_id: uuid.UUID, state: dict[str, Any], epoch: int
    ) -> None:
        """Persist the state snapshot only (execution stays RUNNING). Fenced on ``epoch``."""
        await assert_epoch(db, execution_id, epoch)
        await WorkflowService.update_execution_status(
            db, execution_id, ExecutionStatus.RUNNING, state_data=state
        )
        await db.commit()

    @staticmethod
    async def _safe_rollback(db: AsyncSession) -> None:
        """Roll back after a cancelled graph run; the session may have been cancelled mid-query."""
        try:
            await db.rollback()
        except Exception:
            logger.warning("Rollback after lost lease failed; session discarded", exc_info=True)

    @staticmethod
    async def _release_lease(execution_id: uuid.UUID, owner: str, epoch: int) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await release(session, execution_id, owner, epoch)
        except Exception:
            logger.warning("Could not release lease for execution %s", execution_id, exc_info=True)

    @staticmethod
    async def resume_pipeline(
        db: AsyncSession,
        execution_id: uuid.UUID,
        decision_req: ApprovalDecisionRequest,
    ) -> WorkflowExecution:
        """Resume an execution that is WAITING_APPROVAL. Any other status is an idempotent no-op.

        The status change to RUNNING and the epoch increment are one atomic UPDATE, so of two
        simultaneous resumes exactly one proceeds, and a finished or running execution is never
        re-entered (a FAILED run cannot become successful through a repeated resume).
        """
        async with _execution_semaphore:
            execution = await WorkflowService.get_execution(db, execution_id)
            if not execution:
                raise ValueError(f"Execution {execution_id} not found")
            if execution.status != ExecutionStatus.WAITING_APPROVAL:
                return execution

            owner = new_owner_id("resume")
            try:
                epoch = await claim(
                    db,
                    execution_id,
                    owner,
                    settings.EXECUTION_LEASE_TTL_SECONDS,
                    statuses=(ExecutionStatus.WAITING_APPROVAL,),
                    new_status=ExecutionStatus.RUNNING,
                    ignore_lease=True,
                )
            except LeaseHeldError:
                await db.refresh(execution)
                return execution
            await db.refresh(execution)

            try:
                return await OrchestrationRunner._resume_claimed(
                    db, execution, decision_req, owner, epoch
                )
            except StaleWorkerError:
                await OrchestrationRunner._safe_rollback(db)
                raise
            finally:
                await OrchestrationRunner._release_lease(execution_id, owner, epoch)

    @staticmethod
    async def _resume_claimed(
        db: AsyncSession,
        execution: WorkflowExecution,
        decision_req: ApprovalDecisionRequest,
        owner: str,
        epoch: int,
    ) -> WorkflowExecution:
        execution_id = execution.id
        state: OrchestrationState = dict(execution.state_data)  # type: ignore

        # Mark approval records as decided in DB
        pending_approvals = await ApprovalService.list_pending(db)
        for appr in pending_approvals:
            if appr.execution_id == execution_id:
                await ApprovalService.decide(
                    db,
                    appr.id,
                    status=decision_req.decision,
                    reason=decision_req.reason,
                    decided_by=decision_req.decided_by,
                )

        if decision_req.decision == ApprovalStatus.REJECTED:
            # Rejection stops execution
            await assert_epoch(db, execution_id, epoch)
            await WorkflowService.update_execution_status(
                db,
                execution_id,
                ExecutionStatus.CANCELLED,
                error_message=f"Operator rejected: {decision_req.reason}",
            )
            await WorkflowService.record_event(
                db, execution_id, "pipeline_rejected", {"reason": decision_req.reason}
            )
            await db.commit()
            reloaded = await WorkflowService.get_execution(db, execution_id)
            return reloaded or execution

        # Approved -> Mark active task as approved in state
        tasks = state.get("tasks", [])
        active_task_id = state.get("active_approval_id")
        approved_title = "Approved Task"
        for t in tasks:
            if t.get("task_id") == active_task_id or (
                not active_task_id and t.get("requires_approval")
            ):
                t["approved"] = True
                t["requires_approval"] = False
                approved_title = t.get("title", approved_title)

        state["tasks"] = tasks
        state["status"] = "running"
        state["active_approval_id"] = None

        await assert_epoch(db, execution_id, epoch)
        await WorkflowService.update_execution_status(
            db, execution_id, ExecutionStatus.RUNNING, state_data=state
        )
        await WorkflowService.record_event(
            db, execution_id, "pipeline_resumed", {"approved_task": approved_title}
        )
        await db.commit()

        # The caller (resume_pipeline) already holds the execution semaphore.
        try:
            final_state = await OrchestrationRunner._drive_graph(
                db,
                execution_id,
                execution.project_id,
                state,
                owner=owner,
                epoch=epoch,
                sync_nodes=_FULL_SYNC_NODES_RESUME,
            )
        except ExecutionSetupError as exc:
            # e.g. the worktree directory was deleted before resume: no host-dir fallback.
            return await OrchestrationRunner._fail_execution_setup(
                db, execution_id, str(exc), state.get("repo_path"), epoch=epoch
            )

        await OrchestrationRunner._sync_state_to_db(
            db, execution_id, execution.project_id, final_state, epoch=epoch
        )
        reloaded = await WorkflowService.get_execution(db, execution_id)
        return reloaded or execution

    @staticmethod
    async def find_recoverable_executions(db: AsyncSession) -> list[uuid.UUID]:
        """RUNNING executions whose lease is free or expired (their runner is gone)."""
        rows = await db.execute(
            text(
                "SELECT id FROM workflow_executions WHERE status = 'RUNNING' "
                "AND (lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp()) "
                "ORDER BY created_at"
            )
        )
        return [r[0] for r in rows.all()]

    @staticmethod
    async def recover_execution(
        db: AsyncSession,
        execution_id: uuid.UUID,
        owner: str | None = None,
        worker_runtime: WorkerRuntime | None = None,
    ) -> WorkflowExecution:
        """Recover a RUNNING execution whose runner died, from persisted PostgreSQL state.

        Claims the lease (raises ``LeaseHeldError`` if a live owner holds it), force-settles the
        previous epoch's orphaned reservations, then re-enters the graph with the persisted
        state. Not RUNNING (finished, waiting for approval, paused) means nothing to recover:
        the execution is returned unchanged. Provider calls that never settled are repeated
        (at-least-once); see docs/V1_5_M1_5_1C_SPEC.md section 2.3.
        """
        execution = await WorkflowService.get_execution(db, execution_id)
        if not execution:
            raise ValueError(f"Execution {execution_id} not found")
        if execution.status != ExecutionStatus.RUNNING:
            return execution

        async with _execution_semaphore:
            return await OrchestrationRunner._recover_locked(db, execution, owner, worker_runtime)

    @staticmethod
    async def _recover_locked(
        db: AsyncSession,
        execution: WorkflowExecution,
        owner: str | None,
        worker_runtime: WorkerRuntime | None = None,
    ) -> WorkflowExecution:
        execution_id = execution.id
        owner = owner or new_owner_id("recover")
        epoch = await claim(
            db,
            execution_id,
            owner,
            settings.EXECUTION_LEASE_TTL_SECONDS,
            statuses=(ExecutionStatus.RUNNING,),
        )
        try:
            await db.refresh(execution)
            state: dict[str, Any] = dict(execution.state_data or {})

            # M1.5-2a ordering: stop and clean every stale-epoch worker BEFORE force-settling
            # reservations, so no live worker consumes a reservation that is being expired. Any
            # failure blocks recovery (fail closed); the lease is released and the execution stays
            # RUNNING for a later retry.
            await OrchestrationRunner._reconcile_workers(db, execution_id, epoch, worker_runtime)

            expired = await BudgetGovernor.expire_orphaned_reservations(db, execution_id, epoch)
            await WorkflowService.record_event(
                db,
                execution_id,
                "pipeline_recovered",
                {"epoch": epoch, "owner": owner, "expired_reservations": expired},
            )
            await db.commit()

            if not state.get("execution_id") or not state.get("project_id"):
                # Crash before the initial state was persisted: nothing ran; fail closed.
                return await OrchestrationRunner._fail_execution_setup(
                    db,
                    execution_id,
                    "Recovery impossible: execution state was never persisted",
                    None,
                    epoch=epoch,
                )

            try:
                final_state = await OrchestrationRunner._drive_graph(
                    db,
                    execution_id,
                    execution.project_id,
                    state,
                    owner=owner,
                    epoch=epoch,
                    sync_nodes=_FULL_SYNC_NODES_START,
                )
            except ExecutionSetupError as exc:
                return await OrchestrationRunner._fail_execution_setup(
                    db, execution_id, str(exc), state.get("repo_path"), epoch=epoch
                )
            await OrchestrationRunner._sync_state_to_db(
                db, execution_id, execution.project_id, final_state, epoch=epoch
            )
        except StaleWorkerError:
            await OrchestrationRunner._safe_rollback(db)
            raise
        finally:
            await OrchestrationRunner._release_lease(execution_id, owner, epoch)
        reloaded = await WorkflowService.get_execution(db, execution_id)
        return reloaded or execution

    @staticmethod
    async def _reconcile_workers(
        db: AsyncSession,
        execution_id: uuid.UUID,
        epoch: int,
        runtime: WorkerRuntime | None,
    ) -> None:
        owns_runtime = runtime is None
        try:
            if runtime is None:
                try:
                    runtime = get_worker_runtime()
                except WorkerRuntimeError as exc:
                    raise WorkerReconcileError(f"worker runtime misconfigured: {exc}") from exc
            try:
                report = await WorkerRunService.reconcile_for_recovery(
                    db, runtime, execution_id, epoch
                )
            except WorkerReconcileError as exc:
                await OrchestrationRunner._safe_rollback(db)
                await WorkflowService.record_event(
                    db, execution_id, "recovery_blocked", {"epoch": epoch, "reason": str(exc)[:300]}
                )
                await db.commit()
                raise
            await WorkflowService.record_event(
                db, execution_id, "workers_reconciled", {"epoch": epoch, **report.as_event()}
            )
            await db.commit()
        finally:
            if owns_runtime and runtime is not None:
                await runtime.aclose()

    @staticmethod
    async def _setup_isolation(
        db: AsyncSession,
        execution: WorkflowExecution,
        project: Any,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Validate the repository and create the execution worktree.

        Returns (repo_path, worktree_path, worktree_branch, repo_context_summary); all None for
        a project without repo_path. Raises ExecutionSetupError for any failure.
        """
        if not project or not project.repo_path:
            return None, None, None, None

        try:
            repo_root = validate_repo_path(project.repo_path)
        except PathContainmentError as exc:
            raise ExecutionSetupError(f"Repository rejected: {exc}") from exc

        repo_context_summary: str | None = None
        try:
            repo_context_summary = RepoScanner.scan(repo_root).context_summary
        except Exception as scan_err:
            # Context scanning is advisory; a scan failure never blocks execution.
            logger.warning("Repository scanning failed for %s: %s", repo_root, scan_err)

        try:
            wt_ctx = await GitWorktreeManager.create_worktree(
                repo_path=repo_root,
                execution_id=execution.id,
                base_branch=project.base_branch or "main",
            )
        except ExecutionSetupError:
            raise
        except Exception as wt_err:
            raise ExecutionSetupError(
                f"Worktree creation failed: {type(wt_err).__name__}"
            ) from wt_err

        execution.worktree_path = wt_ctx.worktree_path
        execution.worktree_branch = wt_ctx.branch_name
        await db.flush()
        return str(repo_root), wt_ctx.worktree_path, wt_ctx.branch_name, repo_context_summary

    @staticmethod
    async def _close_budget_after_setup_failure(db: AsyncSession, execution_id: uuid.UUID) -> None:
        """Release open reservations and move the budget to CANCELLED (terminal, not ACTIVE).

        Used when a setup failure happens after a budget exists (resume path). Initial-start
        failures have no budget and are unaffected.
        """
        budget = await BudgetGovernor.get_budget(db, execution_id)
        if budget is None:
            return
        open_reservations = (
            (
                await db.execute(
                    select(BudgetReservation).where(
                        BudgetReservation.budget_id == budget.id,
                        BudgetReservation.status == BudgetReservationStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        for reservation in open_reservations:
            await BudgetGovernor.release(db, reservation.id, reservation.fence_token)
        budget = await BudgetGovernor.get_budget(db, execution_id)
        if budget is not None and budget.status not in (
            BudgetStatus.COMPLETED,
            BudgetStatus.CANCELLED,
        ):
            budget.status = BudgetStatus.CANCELLED
        await db.flush()

    @staticmethod
    async def _fail_execution_setup(
        db: AsyncSession,
        execution_id: uuid.UUID,
        reason: str,
        repo_path: str | None,
        epoch: int | None = None,
    ) -> WorkflowExecution:
        """End the execution FAILED with an event; no task or provider has run."""
        if epoch is not None:
            await assert_epoch(db, execution_id, epoch)
        safe_reason = _redact_host_paths(reason, repo_path)
        await OrchestrationRunner._close_budget_after_setup_failure(db, execution_id)
        await WorkflowService.update_execution_status(
            db, execution_id, ExecutionStatus.FAILED, error_message=safe_reason
        )
        await WorkflowService.record_event(
            db, execution_id, "execution_setup_failed", {"reason": safe_reason}
        )
        await db.commit()
        reloaded = await WorkflowService.get_execution(db, execution_id)
        if reloaded is None:
            raise ValueError(f"Execution {execution_id} not found")
        return reloaded

    @staticmethod
    async def _sync_state_to_db(
        db: AsyncSession,
        execution_id: uuid.UUID,
        project_id: uuid.UUID,
        state: dict[str, Any],
        epoch: int | None = None,
    ) -> None:
        # Fence first: a superseded worker must not write tasks, artifacts, usage or status.
        if epoch is not None:
            await assert_epoch(db, execution_id, epoch)
        state_status = state.get("status", "running")

        # 1. Sync tasks to DB with ID mapping to prevent duplicate task creations
        tasks = state.get("tasks", [])
        task_db_ids = state.get("task_db_ids", {}) or {}
        completed_ids = set(state.get("completed_task_ids", []))
        failed_ids = set(state.get("failed_task_ids", []))

        # Re-sync with this execution's own task rows (matched on execution id + task key, never
        # on title: another execution of the project may use identical titles).
        existing_tasks = await TaskService.list_by_project(db, project_id)
        existing_by_key = {
            (et.input_data or {}).get("task_key"): str(et.id)
            for et in existing_tasks
            if (et.input_data or {}).get("execution_id") == str(execution_id)
        }
        for t in tasks:
            task_key = t.get("task_id", "")
            if task_key and task_key not in task_db_ids and task_key in existing_by_key:
                task_db_ids[task_key] = existing_by_key[task_key]

        for t in tasks:
            task_key = t.get("task_id", "")
            if task_key in task_db_ids:
                # Task already exists in DB; update status if completed or failed
                existing_db_id = uuid.UUID(task_db_ids[task_key])
                remed_hist = t.get("remediation_history_json")
                if task_key in completed_ids:
                    await TaskService.update(
                        db,
                        existing_db_id,
                        TaskUpdate(
                            status=TaskStatus.COMPLETED,
                            output_data={"result": t.get("output_text", "")},
                            remediation_history_json=remed_hist,
                        ),
                    )
                elif (
                    t.get("status") == "failed"
                    or t.get("exit_code", 0) != 0
                    or task_key in failed_ids
                ):
                    await TaskService.update(
                        db,
                        existing_db_id,
                        TaskUpdate(
                            status=TaskStatus.FAILED,
                            error_details=t.get("error_message", "Task execution failed"),
                            remediation_history_json=remed_hist,
                        ),
                    )
            else:
                # Create task in DB and track ID
                t_obj = await TaskService.create(
                    db,
                    TaskCreate(
                        project_id=project_id,
                        title=t.get("title", ""),
                        description=t.get("description", ""),
                        executor_type=t.get("executor_type", "claude_code"),
                        assigned_model=t.get("assigned_model", "claude-haiku-5-5"),
                        assigned_agent_slug=t.get("assigned_agent_slug"),
                        risk_level=t.get("risk_level", "low"),
                        priority=t.get("priority", 1),
                        dependency_ids=t.get("dependencies", []),
                        input_data={"execution_id": str(execution_id), "task_key": task_key},
                    ),
                )
                task_db_ids[task_key] = str(t_obj.id)
                if task_key in completed_ids:
                    await TaskService.update(
                        db,
                        t_obj.id,
                        TaskUpdate(
                            status=TaskStatus.COMPLETED,
                            output_data={"result": t.get("output_text", "")},
                        ),
                    )
                elif (
                    t.get("status") == "failed"
                    or t.get("exit_code", 0) != 0
                    or task_key in failed_ids
                ):
                    await TaskService.update(
                        db,
                        t_obj.id,
                        TaskUpdate(
                            status=TaskStatus.FAILED,
                            error_details=t.get("error_message", "Task execution failed"),
                        ),
                    )
        state["task_db_ids"] = task_db_ids

        # 2. Sync artifacts to DB (register_artifact handles deduplication). Task ids are checked
        # against the live state's task keys; provenance is server-written as "orchestrator".
        known_task_ids = {str(t.get("task_id")) for t in tasks if t.get("task_id")}
        isolated_worktree = state.get("worktree_path")
        for art in state.get("artifacts", []):
            # Isolated executions: hash the file the agent wrote inside the worktree (F-01).
            observed_sha = None
            location = "storage"
            if isolated_worktree:
                location = "worktree"
                observed_sha = _worktree_sha256(isolated_worktree, art.get("name", ""))
            try:
                await ArtifactService.register_artifact(
                    db,
                    ArtifactCreate(
                        project_id=project_id,
                        execution_id=execution_id,
                        task_id=art.get("task_id"),
                        name=art.get("name", "artifact.txt"),
                        file_path=art.get("file_path", ""),
                        artifact_type=ArtifactType.OTHER,
                        file_size_bytes=art.get("size_bytes", 0),
                    ),
                    source="orchestrator",
                    registered_by="orchestrator",
                    known_task_ids=known_task_ids,
                    producing_agent_slug=art.get("producing_agent_slug"),
                    observed_sha256=observed_sha,
                    location=location,
                )
            except Exception as e:
                logger.warning("Could not sync artifact %s: %s", art, e)

        # 3. Sync usage records to DB using slice offset to prevent duplicate inserts
        synced_usage_count = state.get("synced_usage_count", 0)
        usage_records = state.get("usage_records", [])

        for usage in usage_records[synced_usage_count:]:
            try:
                await UsageService.record_execution(
                    db,
                    ModelExecutionCreate(
                        execution_id=execution_id,
                        provider=usage.get("provider", "claude_code"),
                        model=usage.get("model", "claude-haiku-5-5"),
                        duration_ms=usage.get("duration_ms", 0),
                        input_tokens=usage.get("input_tokens", 0),
                        output_tokens=usage.get("output_tokens", 0),
                        cache_read_tokens=usage.get("cache_read_tokens", 0),
                        cache_creation_tokens=usage.get("cache_creation_tokens", 0),
                        cost_usd=usage.get("cost_usd", 0.0),
                        exit_code=usage.get("exit_code", 0),
                        status=ModelExecutionStatus.SUCCESS
                        if usage.get("status") == "success"
                        else ModelExecutionStatus.FAILED,
                    ),
                )
            except Exception as e:
                logger.warning("Could not sync usage record %s: %s", usage, e)

        state["synced_usage_count"] = len(usage_records)

        # Current progress step based on completed task count
        current_step = len(state.get("completed_task_ids", []))
        if state_status == "waiting_approval":
            active_task_id = state.get("active_approval_id")
            task_info = next((t for t in tasks if t.get("task_id") == active_task_id), {})
            if not task_info and tasks:
                task_info = tasks[0]
            approval = await ApprovalService.request_approval(
                db,
                execution_id=execution_id,
                action_type="high_risk_task_execution",
                description=f"Approval requested for task: {task_info.get('title')}",
                risk_level=RiskLevel.MEDIUM,
                context_data={"task": task_info},
            )
            await WorkflowService.update_execution_status(
                db,
                execution_id,
                ExecutionStatus.WAITING_APPROVAL,
                state_data=state,
                current_step=current_step,
            )
            await WorkflowService.record_event(
                db,
                execution_id,
                "approval_required",
                {"approval_id": str(approval.id), "task_id": active_task_id},
            )
        elif state_status == "completed":
            await WorkflowService.update_execution_status(
                db,
                execution_id,
                ExecutionStatus.COMPLETED,
                state_data=state,
                current_step=current_step,
            )
            await WorkflowService.record_event(
                db, execution_id, "pipeline_completed", {"tasks_count": len(tasks)}
            )
            if state.get("ingested_memory_ids") and not state.get("_memories_event_recorded"):
                await WorkflowService.record_event(
                    db,
                    execution_id,
                    "pipeline_memories_ingested",
                    {"count": len(state["ingested_memory_ids"])},
                )
                state["_memories_event_recorded"] = True
        elif state_status == "failed" or state.get("failed_task_ids"):
            await WorkflowService.update_execution_status(
                db,
                execution_id,
                ExecutionStatus.FAILED,
                state_data=state,
                current_step=current_step,
                error_message=state.get("error", "Task execution failed"),
            )
            await WorkflowService.record_event(
                db,
                execution_id,
                "pipeline_failed",
                {"error": state.get("error", "Task execution failed")},
            )
        else:
            await WorkflowService.update_execution_status(
                db,
                execution_id,
                ExecutionStatus.RUNNING,
                state_data=state,
                current_step=current_step,
            )

        # Explicitly commit transaction per execution wave to guarantee crash recovery
        await db.commit()
