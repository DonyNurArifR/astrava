import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.budget import BudgetReservation, BudgetReservationStatus
from app.models.execution import WorkflowExecution
from app.models.memory import IngestionOperation, IngestionOperationStatus, ProjectMemory
from app.models.project import StudioType
from app.models.task import ExecutorType
from app.orchestrator.knowledge_extraction import (
    KnowledgeExtractor,
    compute_candidate_fingerprint,
)
from app.orchestrator.planner import DAGModifier, GoalDecomposer
from app.orchestrator.state import OrchestrationState
from app.providers.base import ProviderRequest, ProviderStatus
from app.providers.factory import ProviderFactory
from app.services.agent_service import DEFAULT_AGENTS
from app.services.budget_governor import (
    BudgetExhaustedError,
    BudgetGovernor,
    BudgetLimitExceededError,
    FencingTokenMismatchError,
    ReservationNotFoundError,
)
from app.services.memory_service import MemoryService
from app.services.retrieval.schemas import RetrievalQuery
from app.services.retrieval.service import RetrievalService
from app.services.workflow_service import WorkflowService
from app.verification.engine import VerificationEngine
from app.verification.semantic_evaluator import SemanticEvaluator
from app.workspace import GitWorktreeManager

logger = logging.getLogger("astrava.orchestrator")

AGENT_MAP = {a["slug"]: a for a in DEFAULT_AGENTS}


def _extract_json_dict(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


async def retrieve_knowledge_node(state: OrchestrationState) -> dict[str, Any]:
    """Retrieves relevant project memories and artifacts before planning."""
    # If plan already exists (e.g. on resume), preserve existing state and do not re-query
    if state.get("plan"):
        logger.info("Preserving existing retrieval context on pipeline resume.")
        return {}

    project_id_str = state.get("project_id", "")
    objective = state.get("objective", "")

    try:
        project_uuid = uuid.UUID(project_id_str)
    except (ValueError, TypeError):
        logger.info(
            "Project ID '%s' is not a valid UUID; skipping database knowledge retrieval.",
            project_id_str,
        )
        return {
            "retrieved_memories": [],
            "retrieved_artifacts": [],
            "retrieval_context": "_No project knowledge available for non-UUID project._",
            "retrieval_metadata": {"skipped": True, "reason": "non_uuid_project"},
            "retrieval_error": None,
        }

    try:
        async with AsyncSessionLocal() as session:
            query = RetrievalQuery(
                project_id=project_uuid,
                query_text=objective,
                context_budget_chars=4000,
                top_k_memories=15,
                top_k_artifacts=5,
            )
            result = await RetrievalService.search(session, query)

        serialized_memories = [
            {
                "id": str(m.id),
                "summary": m.summary,
                "category": m.category.value,
                "provenance_type": m.provenance_type.value,
                "is_verified": m.is_verified,
                "composite_score": m.composite_score,
            }
            for m in result.memories
        ]
        serialized_artifacts = [
            {
                "id": str(a.id),
                "name": a.name,
                "version": a.version,
                "verification_status": a.verification_status.value,
            }
            for a in result.artifacts
        ]

        logger.info(
            "Retrieved %d memories and %d artifacts for project %s (context chars: %d)",
            len(serialized_memories),
            len(serialized_artifacts),
            project_id_str,
            len(result.context_package),
        )

        return {
            "retrieved_memories": serialized_memories,
            "retrieved_artifacts": serialized_artifacts,
            "retrieval_context": result.context_package,
            "retrieval_metadata": result.trace_metadata,
            "retrieval_error": None,
        }
    except Exception as e:
        logger.warning("Knowledge retrieval encountered recoverable error: %s", e)
        return {
            "retrieved_memories": [],
            "retrieved_artifacts": [],
            "retrieval_context": "_No relevant project knowledge retrieved (retrieval skipped)._",
            "retrieval_metadata": {"skipped": True, "reason": "error"},
            "retrieval_error": str(e),
        }


async def _record_replan(state: OrchestrationState) -> None:
    """Count one replanning iteration against the execution budget. Raises BudgetExhaustedError."""
    execution_id = uuid.UUID(state["execution_id"])
    async with AsyncSessionLocal() as session:
        await BudgetGovernor.initialize_budget(
            session, execution_id, uuid.UUID(state["project_id"])
        )
        await BudgetGovernor.record_replan(session, execution_id)
        await session.commit()


async def plan_node(state: OrchestrationState) -> dict[str, Any]:
    # If plan already exists in state (e.g. on resume), preserve existing plan and tasks
    if state.get("plan"):
        logger.info("Preserving existing plan on pipeline resume.")
        return {}

    if state.get("replanning") or (state.get("replan_count") or 0) > 0:
        try:
            await _record_replan(state)
        except BudgetExhaustedError as exc:
            message = f"Budget exhausted: {exc}"
            logger.warning("Replan refused for execution %s: %s", state.get("execution_id"), exc)
            return {
                "status": "failed",
                "error": message,
                "error_message": message,
                "budget_exhausted": True,
            }

    logger.info("Executing plan_node for objective: %s", state.get("objective"))
    studio_type_str = state.get("studio_type", "saas")
    studio_type = StudioType.MEDIA if studio_type_str == "media" else StudioType.SAAS

    plan = await GoalDecomposer.decompose_goal(
        objective=state.get("objective", ""),
        project_id=state.get("project_id", "default"),
        studio_type=studio_type,
        retrieval_context=state.get("retrieval_context"),
    )
    tasks = [t.model_dump() for t in plan.tasks]

    # Ensure agent snapshots are initialized
    agent_snapshots = state.get("agent_snapshots", {})
    if not agent_snapshots:
        agent_snapshots = {slug: dict(info) for slug, info in AGENT_MAP.items()}

    return {
        "plan": plan.model_dump(),
        "tasks": tasks,
        "agent_snapshots": agent_snapshots,
        "completed_task_ids": [],
        "failed_task_ids": [],
        "current_ready_task_ids": [],
        "current_task_index": 0,
        "status": "running",
    }


async def approval_check_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    completed_ids = set(state.get("completed_task_ids", []))
    failed_ids = set(state.get("failed_task_ids", []))

    # All tasks completed
    if len(completed_ids) == len(tasks) and len(tasks) > 0:
        return {"status": "completed"}

    # Find tasks whose dependencies are fully met in completed_ids, not yet run, and not failed
    ready_tasks = [
        t
        for t in tasks
        if t["task_id"] not in completed_ids
        and t["task_id"] not in failed_ids
        and t.get("status") not in ("completed", "failed")
        and all(dep in completed_ids for dep in t.get("dependencies", []))
    ]

    if not ready_tasks:
        if failed_ids or state.get("status") == "failed":
            return {"status": "failed"}
        if len(completed_ids) == len(tasks):
            return {"status": "completed"}
        # If tasks remain but cannot run because prerequisites failed, mark blocked/failed
        return {
            "status": "failed",
            "error": "Downstream tasks blocked due to upstream dependency failures.",
        }

    # Check if ANY ready task requires human approval and has not been approved
    for t in ready_tasks:
        if t.get("requires_approval", False) and not t.get("approved", False):
            logger.info("Task '%s' requires human approval. Pausing execution.", t["title"])
            return {
                "status": "waiting_approval",
                "active_approval_id": t["task_id"],
                "current_ready_task_ids": [t["task_id"]],
            }

    # Ready to execute ready tasks in parallel
    ready_ids = [t["task_id"] for t in ready_tasks]
    logger.info("Execution wave ready with %d task(s): %s", len(ready_ids), ready_ids)
    return {
        "status": "running",
        "current_ready_task_ids": ready_ids,
    }


def _reservation_timeout_seconds(task: dict[str, Any], state: OrchestrationState) -> int:
    """Projected runtime for a task's reservation: one attempt's timeout.

    The governor checks consumed runtime + this value against max_runtime_seconds, so
    multiplying by retries would refuse every wave after the first under default limits.
    """
    snapshots = state.get("agent_snapshots", {}) or {}
    agent_slug = task.get("assigned_agent_slug", "developer")
    agent_info = snapshots.get(agent_slug) or AGENT_MAP.get(agent_slug, {})
    exec_config = agent_info.get("execution_config", {}) or {}
    per_attempt = exec_config.get("timeout_seconds", settings.CLAUDE_EXECUTION_TIMEOUT_SECONDS)
    return max(1, int(per_attempt))


async def _settle_reservation(
    reservation_id: uuid.UUID,
    usage_records: list[dict[str, Any]] | None,
    fence_token: str,
) -> None:
    """Reconcile a reservation with actual usage, or release it when usage is None (aborted)."""
    try:
        async with AsyncSessionLocal() as session:
            if usage_records is None:
                await BudgetGovernor.release(session, reservation_id, fence_token=fence_token)
            else:
                total_in = sum(int(r.get("input_tokens") or 0) for r in usage_records)
                total_out = sum(int(r.get("output_tokens") or 0) for r in usage_records)
                total_dur = sum(int(r.get("duration_ms") or 0) for r in usage_records)
                costs = [r.get("cost_usd") for r in usage_records if r.get("cost_usd") is not None]
                actual_cost = Decimal(str(sum(costs))) if costs else None
                await BudgetGovernor.reconcile(
                    session,
                    reservation_id,
                    actual_input_tokens=total_in,
                    actual_output_tokens=total_out,
                    duration_ms=total_dur,
                    actual_cost_usd=actual_cost,
                    fence_token=fence_token,
                )
            await session.commit()
    except (ReservationNotFoundError, FencingTokenMismatchError) as err:
        logger.warning("Budget reservation %s settlement note: %s", reservation_id, err)


async def _execute_single_task(
    task: dict[str, Any],
    state: OrchestrationState,
    project_work_dir: Path,
    reservation_info: tuple[uuid.UUID, str] | uuid.UUID | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run a task with per-attempt budget reservations and safe fencing."""
    import inspect

    res_id = reservation_info[0] if isinstance(reservation_info, tuple) else reservation_info
    fence = reservation_info[1] if isinstance(reservation_info, tuple) else None

    sig = inspect.signature(_run_single_task)
    if len(sig.parameters) <= 3:
        try:
            updated_task, usage_records = await _run_single_task(task, state, project_work_dir)
        except BaseException:
            if res_id and fence:
                try:
                    await _settle_reservation(res_id, None, fence_token=fence)
                except Exception:
                    pass
            raise
        if res_id and fence:
            await _settle_reservation(res_id, usage_records, fence_token=fence)
        return updated_task, usage_records

    return await _run_single_task(task, state, project_work_dir, reservation_info)


async def _run_single_task(
    task: dict[str, Any],
    state: OrchestrationState,
    project_work_dir: Path,
    reservation_info: tuple[uuid.UUID, str] | uuid.UUID | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Executes a single task using its assigned agent instructions,
    structured upstream context from completed dependencies, bounded retries,
    per-attempt budget reservation/reconciliation, and output schema validation.
    """
    init_res_id: uuid.UUID | None = None
    init_fence_token: str | None = None
    if isinstance(reservation_info, tuple):
        init_res_id, init_fence_token = reservation_info
    elif isinstance(reservation_info, uuid.UUID):
        init_res_id = reservation_info

    execution_uuid: uuid.UUID | None = None
    if state.get("execution_id"):
        try:
            execution_uuid = uuid.UUID(state["execution_id"])
        except (ValueError, TypeError):
            pass

    agent_slug = task.get("assigned_agent_slug", "developer")
    snapshots = state.get("agent_snapshots", {})
    agent_info = snapshots.get(agent_slug) or AGENT_MAP.get(agent_slug, {})

    agent_name = agent_info.get("name", agent_slug)
    agent_instructions = agent_info.get("instructions", "Execute the task meeting all criteria.")
    exec_config = agent_info.get("execution_config", {})
    max_retries = exec_config.get("max_retries", 1)
    timeout_seconds = exec_config.get("timeout_seconds", settings.CLAUDE_EXECUTION_TIMEOUT_SECONDS)

    # 1. Structure upstream context from completed prerequisites only
    completed_ids = set(state.get("completed_task_ids", []))
    task_lookup = {t["task_id"]: t for t in state.get("tasks", [])}
    upstream_context_blocks = []
    used_context_sources = []

    for dep_id in task.get("dependencies", []):
        if dep_id in completed_ids:
            dep_task = task_lookup.get(dep_id, {})
            dep_title = dep_task.get("title", dep_id)
            dep_slug = dep_task.get("assigned_agent_slug", "unknown")
            dep_out = dep_task.get("output_text", "")
            if dep_out:
                bounded_out = dep_out.strip()
                if len(bounded_out) > 3500:
                    bounded_out = (
                        bounded_out[:3500]
                        + "\n[... deliverable truncated for context length; full artifact on disk ...]"
                    )
                upstream_context_blocks.append(
                    f"=== Deliverable from [{dep_title}] (@{dep_slug}) ===\n{bounded_out}"
                )
                used_context_sources.append(
                    {
                        "task_id": dep_id,
                        "title": dep_title,
                        "agent_slug": dep_slug,
                    }
                )

    upstream_text = (
        "\n\n".join(upstream_context_blocks)
        if upstream_context_blocks
        else "None (Initial stage; no prerequisites)."
    )
    task["used_context_sources"] = used_context_sources

    usage_records: list[dict[str, Any]] = []

    # If state provides an isolated git worktree, route execution and verification into it
    effective_work_dir = project_work_dir
    if state.get("worktree_path"):
        wt_p = Path(state["worktree_path"]).resolve()
        if wt_p.exists() and wt_p.is_dir():
            effective_work_dir = wt_p

    # 2. Deterministic task execution (e.g. QA engineer)
    if task.get("executor_type") == ExecutorType.DETERMINISTIC:
        report = await VerificationEngine.verify_task(effective_work_dir)
        output_text = json.dumps(report.model_dump(), indent=2)
        task["output_text"] = output_text
        task["status"] = "completed" if report.overall_passed else "failed"
        task["exit_code"] = 0 if report.overall_passed else 1
        task["retry_count"] = 0

        u_rec = {
            "task_id": task["task_id"],
            "provider": "deterministic",
            "model": "deterministic-engine",
            "duration_ms": report.total_duration_ms,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_usd": 0.0,
            "status": "success" if report.overall_passed else "failed",
            "exit_code": task["exit_code"],
        }
        usage_records.append(u_rec)
        if init_res_id is not None and init_fence_token is not None:
            try:
                async with AsyncSessionLocal() as session:
                    await BudgetGovernor.reconcile(
                        session,
                        init_res_id,
                        actual_input_tokens=0,
                        actual_output_tokens=0,
                        duration_ms=report.total_duration_ms,
                        fence_token=init_fence_token,
                        actual_cost_usd=Decimal("0.0"),
                        is_cost_estimated=False,
                        is_cost_zero_confirmed=True,
                        attempt_metadata={
                            "success": report.overall_passed,
                            "provider_status": "success" if report.overall_passed else "failed",
                            "exit_code": task["exit_code"],
                            "has_output": True,
                            "output_text": output_text,
                        },
                    )
                    await session.commit()
            except (ReservationNotFoundError, FencingTokenMismatchError) as err:
                logger.warning("Deterministic reservation %s settlement note: %s", init_res_id, err)
        return task, usage_records

    # 3. Claude Code CLI execution with bounded retries and per-attempt budget governance
    retrieval_context = state.get("retrieval_context", "")
    if retrieval_context and not retrieval_context.startswith("_No"):
        project_context_section = f"Project Knowledge & Architecture Decisions (Persistent Memory):\n{retrieval_context}\n\n"
    else:
        project_context_section = ""

    prompt = f"""You are an autonomous AI Agent in the ASTRAVA platform.
Agent Identity: {agent_name} (@{agent_slug})
Agent Responsibilities & Directives:
{agent_instructions}

{project_context_section}Upstream Prerequisite Deliverables (Verified Context):
{upstream_text}

Your Assigned Task: {task.get("title", "")}
Task Description: {task.get("description", "")}
Acceptance Criteria: {task.get("acceptance_criteria", [])}
Expected Deliverables: {task.get("expected_output_artifacts", [])}

Produce the complete deliverable meeting all criteria directly."""

    provider = ProviderFactory.get_provider("claude_code")
    p_req = ProviderRequest(
        prompt=prompt,
        working_directory=effective_work_dir,
        model=task.get("assigned_model", "haiku"),
        timeout_seconds=timeout_seconds,
    )

    success = False
    last_error = "Task execution failed"

    for attempt in range(max_retries + 1):
        if attempt == 0:
            current_res_id = init_res_id
            current_fence = init_fence_token
        else:
            # RETRY: Reserve attempt capacity BEFORE launching subprocess!
            current_res_id = None
            current_fence = None
            if execution_uuid is not None:
                try:
                    async with AsyncSessionLocal() as session:
                        retry_res = await BudgetGovernor.reserve(
                            session,
                            execution_uuid,
                            reservation_key=f"task:{task['task_id']}:attempt:{attempt}",
                            task_id=task["task_id"],
                            agent_slug=agent_slug,
                            purpose="agent_retry",
                            attempt_number=attempt,
                            timeout_seconds=timeout_seconds,
                        )
                        await session.commit()
                        current_res_id = retry_res.id
                        current_fence = retry_res.fence_token
                except BudgetExhaustedError as exc:
                    logger.warning(
                        "Task %s retry %d refused by budget governor: %s",
                        task["task_id"],
                        attempt,
                        exc,
                    )
                    last_error = f"Retry blocked by budget exhaustion: {exc}"
                    break

        try:
            resp = await provider.execute(p_req)
        except BaseException:
            if current_res_id is not None:
                try:
                    async with AsyncSessionLocal() as session:
                        await BudgetGovernor.release(
                            session, current_res_id, fence_token=current_fence
                        )
                        await session.commit()
                except Exception:
                    logger.exception("Failed to release reservation %s on abort", current_res_id)
            raise

        u_rec = {
            "task_id": task["task_id"],
            "provider": "claude_code",
            "model": resp.canonical_model or task.get("assigned_model", "claude-haiku-5-5"),
            "duration_ms": resp.duration_ms,
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "cache_read_tokens": resp.cache_read_tokens,
            "cache_creation_tokens": resp.cache_creation_tokens,
            "cost_usd": resp.cost_usd,
            "status": resp.status.value,
            "exit_code": resp.exit_code,
        }
        usage_records.append(u_rec)

        # Determine if attempt succeeded at provider and schema/deliverable levels
        attempt_is_success = False
        if resp.status in (ProviderStatus.FAILED, ProviderStatus.TIMEOUT):
            last_error = resp.error_message or f"Provider returned status {resp.status.value}"
        elif not resp.output_text.strip():
            last_error = "Agent produced empty deliverable"
        else:
            # Check schema validation if required fields specified
            output_schema = agent_info.get("output_schema", {})
            required_fields = output_schema.get("required", [])
            schema_valid = True
            if required_fields:
                parsed_dict = _extract_json_dict(resp.output_text)
                if parsed_dict:
                    missing = [f for f in required_fields if f not in parsed_dict]
                    if missing:
                        schema_valid = False
                        last_error = f"Deliverable missing required schema fields: {missing}"

            if schema_valid:
                attempt_is_success = True
                success = True

        # Settle this attempt immediately with BudgetGovernor
        if current_res_id is not None and current_fence is not None:
            actual_cost = (
                Decimal(str(resp.cost_usd))
                if (resp.cost_usd is not None and not resp.cost_unavailable)
                else None
            )
            try:
                async with AsyncSessionLocal() as session:
                    await BudgetGovernor.reconcile(
                        session,
                        current_res_id,
                        actual_input_tokens=resp.input_tokens,
                        actual_output_tokens=resp.output_tokens,
                        duration_ms=resp.duration_ms,
                        fence_token=current_fence,
                        actual_cost_usd=actual_cost,
                        is_cost_estimated=resp.is_cost_estimated or actual_cost is None,
                        attempt_metadata={
                            "success": attempt_is_success,
                            "remediation_cycle": task.get("remediation_cycles", 0),
                            "provider_status": resp.status.value,
                            "exit_code": resp.exit_code,
                            "has_output": bool(resp.output_text.strip()),
                            "output_text": resp.output_text[:4000],
                        },
                    )
                    await session.commit()
            except (ReservationNotFoundError, FencingTokenMismatchError) as settle_err:
                logger.warning(
                    "Attempt %d reservation %s settlement note: %s",
                    attempt,
                    current_res_id,
                    settle_err,
                )

        task["output_text"] = resp.output_text
        task["exit_code"] = resp.exit_code
        task["retry_count"] = attempt

        if success:
            break

        if not success and attempt < max_retries:
            logger.warning(
                "Task '%s' failed on attempt %d/%d (%s). Retrying...",
                task["task_id"],
                attempt + 1,
                max_retries,
                last_error,
            )
            await asyncio.sleep(1)

    if success:
        task["status"] = "completed"
        task["error_message"] = None
    else:
        task["status"] = "failed"
        task["error_message"] = last_error

    return task, usage_records


async def dispatch_task_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    ready_ids = state.get("current_ready_task_ids", [])
    project_id = state.get("project_id", "default")
    project_work_dir = (settings.ARTIFACT_STORAGE_PATH / project_id).resolve()
    if state.get("worktree_path"):
        wt_p = Path(state["worktree_path"]).resolve()
        if wt_p.exists() and wt_p.is_dir():
            project_work_dir = wt_p
    project_work_dir.mkdir(parents=True, exist_ok=True)

    task_map = {t["task_id"]: t for t in tasks}
    ready_tasks = [task_map[tid] for tid in ready_ids if tid in task_map]

    logger.info("Dispatching %d task(s) concurrently in this stage", len(ready_tasks))

    # Reserve budget for the whole wave atomically: any refusal rolls back every
    # reservation in this wave and nothing is dispatched.
    execution_id = uuid.UUID(state["execution_id"])
    reservations: dict[str, tuple[uuid.UUID, str]] = {}
    tasks_to_dispatch: list[dict[str, Any]] = []
    failed_ids = list(state.get("failed_task_ids", []))

    try:
        async with AsyncSessionLocal() as session:
            budget = await BudgetGovernor.initialize_budget(
                session, execution_id, uuid.UUID(state["project_id"])
            )
            for t in ready_tasks:
                task_id = t["task_id"]
                # Query how many attempts have already been accounted for this task
                attempt_statuses = (
                    BudgetReservationStatus.ACTIVE,
                    BudgetReservationStatus.RECONCILED,
                    BudgetReservationStatus.EXPIRED,
                )
                stmt = select(func.count(BudgetReservation.id)).where(
                    BudgetReservation.budget_id == budget.id,
                    BudgetReservation.task_id == task_id,
                    BudgetReservation.status.in_(attempt_statuses),
                )
                attempts_used = (await session.scalar(stmt)) or 0

                # Query all reconciled reservations for this task, ordered by latest attempt first (AUD-M2.2.2-01)
                stmt_reconciled = (
                    select(BudgetReservation)
                    .where(
                        BudgetReservation.budget_id == budget.id,
                        BudgetReservation.task_id == task_id,
                        BudgetReservation.status == BudgetReservationStatus.RECONCILED,
                    )
                    .order_by(BudgetReservation.attempt_number.desc())
                )
                reconciled_attempts = (await session.scalars(stmt_reconciled)).all()

                # Separate reservation settlement from task completion (AUD-M2.2-02 / AUD-M2.2.2-01)
                # A RECONCILED reservation alone NEVER establishes task completion.
                # Valid completion requires:
                # 1. Attempt succeeded at provider/verification level (rec_res.metadata_json["success"] is True)
                # 2. Output text is non-empty
                # 3. All expected deliverables exist, are non-empty, and belong to this attempt/execution (AUD-M2.2.2-02)
                adopted_successful_attempt = None
                current_remediation_cycle = t.get("remediation_cycles", 0)
                for rec_res in reconciled_attempts:
                    rec_cycle = rec_res.metadata_json.get("remediation_cycle", 0)
                    if rec_cycle < current_remediation_cycle:
                        # Attempt was settled during an earlier cycle that failed verification
                        continue

                    attempt_success = rec_res.metadata_json.get("success") is True
                    output_text = rec_res.metadata_json.get("output_text") or t.get(
                        "output_text", ""
                    )
                    has_output = bool(output_text and str(output_text).strip())

                    expected_artifacts = t.get("expected_output_artifacts", [])
                    artifacts_present = True
                    if expected_artifacts:
                        for art_name in expected_artifacts:
                            art_file = project_work_dir / art_name
                            if not art_file.exists() or art_file.stat().st_size == 0:
                                artifacts_present = False
                                break
                            # Verify artifact ownership and recency (AUD-M2.2.2-02):
                            # The deliverable must have been created/modified during or after this reservation attempt,
                            # not leftover from an older run or prior execution.
                            res_created_ts = (
                                rec_res.created_at.timestamp() if rec_res.created_at else 0.0
                            )
                            file_mtime = art_file.stat().st_mtime
                            if file_mtime < (res_created_ts - 5.0):  # 5s clock skew buffer
                                logger.warning(
                                    "Artifact %s for task %s has stale mtime (%s < %s); rejecting adoption",
                                    art_name,
                                    task_id,
                                    file_mtime,
                                    res_created_ts,
                                )
                                artifacts_present = False
                                break

                    if attempt_success and has_output and artifacts_present:
                        adopted_successful_attempt = (rec_res, output_text)
                        break
                    else:
                        logger.warning(
                            "Task %s attempt %d reconciled but incomplete/failed (success=%s, output=%s, artifacts=%s)",
                            task_id,
                            rec_res.attempt_number,
                            attempt_success,
                            has_output,
                            artifacts_present,
                        )

                if adopted_successful_attempt is not None:
                    rec_res, output_text = adopted_successful_attempt
                    logger.info(
                        "Task %s attempt %d completed and verified in prior run; adopting result",
                        task_id,
                        rec_res.attempt_number,
                    )
                    t["status"] = "completed"
                    t["output_text"] = output_text
                    t["error_message"] = None
                    continue

                # If attempts have already been used, determine if retries allow another attempt
                agent_slug = t.get("assigned_agent_slug", "developer")
                snapshots = state.get("agent_snapshots", {}) or {}
                agent_info = snapshots.get(agent_slug) or AGENT_MAP.get(agent_slug, {})
                exec_config = agent_info.get("execution_config", {})
                max_retries = exec_config.get("max_retries", 1)
                max_allowed_attempts = max_retries + 1

                if attempts_used >= max_allowed_attempts:
                    logger.warning(
                        "Task %s retry limit exhausted across prior attempts (%d/%d)",
                        task_id,
                        attempts_used,
                        max_allowed_attempts,
                    )
                    t["status"] = "failed"
                    t["error_message"] = (
                        f"Task failed: maximum attempts ({max_allowed_attempts}) exhausted"
                    )
                    failed_ids.append(task_id)
                    continue

                attempt_to_reserve = attempts_used
                res_key = f"task:{task_id}:attempt:{attempt_to_reserve}"

                reservation = await BudgetGovernor.reserve(
                    session,
                    execution_id,
                    reservation_key=res_key,
                    task_id=task_id,
                    agent_slug=agent_slug,
                    purpose="agent_dispatch" if attempt_to_reserve == 0 else "agent_retry",
                    attempt_number=attempt_to_reserve,
                    timeout_seconds=_reservation_timeout_seconds(t, state),
                )
                reservations[task_id] = (reservation.id, reservation.fence_token)
                tasks_to_dispatch.append(t)
            await session.commit()
    except BudgetExhaustedError as exc:
        message = f"Budget exhausted: {exc}"
        logger.warning("Dispatch halted for execution %s: %s", execution_id, exc)
        return {
            "status": "failed",
            "error": message,
            "error_message": message,
            "budget_exhausted": True,
        }

    # Execute independent tasks concurrently via asyncio.gather
    results = await asyncio.gather(
        *[
            _execute_single_task(t, state, project_work_dir, reservations.get(t["task_id"]))
            for t in tasks_to_dispatch
        ],
        return_exceptions=True,
    )

    usage_list = list(state.get("usage_records", []))
    any_failed = bool(failed_ids)
    error_msg = None

    # AUD-M2.2-01: Explicit 1-to-1 task identity result pairing
    for task_dispatched, res in zip(tasks_to_dispatch, results, strict=True):
        task_id = task_dispatched["task_id"]
        target_task = task_map.get(task_id, task_dispatched)
        if isinstance(res, Exception):
            logger.error("Task %s raised unhandled exception: %s", task_id, res)
            target_task["status"] = "failed"
            target_task["error_message"] = str(res)
            failed_ids.append(task_id)
            any_failed = True
            error_msg = str(res)
        else:
            updated_task, u_records = res
            target_task.update(updated_task)
            usage_list.extend(u_records)
            if target_task.get("status") == "failed":
                failed_ids.append(task_id)
                any_failed = True
                error_msg = target_task.get("error_message", "Task failed")

    return {
        "tasks": tasks,
        "usage_records": usage_list,
        "failed_task_ids": list(set(failed_ids)),
        # Do not abort before verify/artifact processing; route_after_artifact handles termination
        "status": "failed" if any_failed else "running",
        "error": error_msg,
    }


async def verify_node(state: OrchestrationState) -> dict[str, Any]:
    ready_ids = state.get("current_ready_task_ids", [])
    tasks = state.get("tasks", [])
    task_map = {t["task_id"]: t for t in tasks}
    project_id = state.get("project_id", "default")
    project_work_dir = (settings.ARTIFACT_STORAGE_PATH / project_id).resolve()
    if state.get("worktree_path"):
        wt_p = Path(state["worktree_path"]).resolve()
        if wt_p.exists() and wt_p.is_dir():
            project_work_dir = wt_p

    logger.info("Running deterministic & semantic verification for batch: %s", ready_ids)
    report = await VerificationEngine.verify_task(project_work_dir)

    results = list(state.get("verification_results", []))
    remediation_needed_tasks: list[dict[str, Any]] = []
    failed_ids = list(state.get("failed_task_ids", []))

    for tid in ready_ids:
        task = task_map.get(tid)
        if not task:
            continue

        if task.get("status") != "completed":
            failed_ids.append(tid)
            continue

        # Tier 2 Semantic Evaluation
        acceptance_criteria = task.get("acceptance_criteria", [])
        semantic_result = await SemanticEvaluator.evaluate(
            deliverable_text=task.get("output_text", ""),
            acceptance_criteria=acceptance_criteria,
            task_title=task.get("title", ""),
            task_description=task.get("description", ""),
        )

        task_passed = (
            report.overall_passed
            and semantic_result.passed
            and task.get("status") == "completed"
            and task.get("exit_code", 0) == 0
        )

        task_ver_record = {
            "task_id": tid,
            "report": report.model_dump(),
            "semantic_evaluation": semantic_result.model_dump(),
            "passed": task_passed,
        }
        results.append(task_ver_record)

        if not task_passed:
            current_cycle = task.get("remediation_cycles", 0)
            if current_cycle < 3:
                # Task is eligible for automated remediation
                task["_remediation_meta"] = {
                    "diagnostic_summary": report.diagnostic_summary
                    or task.get("error_message")
                    or "Task deliverable failed verification",
                    "unmet_criteria": semantic_result.unmet_criteria,
                    "reasoning": semantic_result.reasoning,
                    "suggestions": semantic_result.suggestions,
                }
                remediation_needed_tasks.append(task)
            else:
                logger.warning("Task %s exceeded maximum remediation cycles (3)", tid)
                task["status"] = "failed"
                task["error_message"] = (
                    f"Task exceeded maximum remediation cycles ({current_cycle}): "
                    + (
                        report.diagnostic_summary
                        or task.get("error_message")
                        or "Verification failed"
                    )
                )
                failed_ids.append(tid)

    remediation_needed = bool(remediation_needed_tasks)

    return {
        "tasks": tasks,
        "verification_results": results,
        "failed_task_ids": list(set(failed_ids)),
        "remediation_needed": remediation_needed,
        "remediation_task_ids": [t["task_id"] for t in remediation_needed_tasks],
    }


async def remediation_node(state: OrchestrationState) -> dict[str, Any]:
    remediation_ids = state.get("remediation_task_ids", [])
    tasks = state.get("tasks", [])
    task_map = {t["task_id"]: t for t in tasks}
    execution_id = uuid.UUID(state["execution_id"])
    remediation_records = list(state.get("remediation_records", []))
    failed_ids = list(state.get("failed_task_ids", []))
    tasks_to_remediate: list[str] = []

    try:
        async with AsyncSessionLocal() as session:
            # Count remediation turn against execution budget
            await BudgetGovernor.record_remediation_turn(session, execution_id)
            exec_row = await session.get(WorkflowExecution, execution_id)
            if exec_row:
                exec_row.remediation_count += 1
            await session.commit()
    except (BudgetExhaustedError, Exception) as exc:
        logger.warning("Remediation turn halted by budget governor: %s", exc)
        for tid in remediation_ids:
            t = task_map.get(tid)
            if t:
                t["status"] = "failed"
                t["error_message"] = f"Remediation halted: {exc}"
                failed_ids.append(tid)
        return {
            "tasks": tasks,
            "failed_task_ids": list(set(failed_ids)),
            "remediation_needed": False,
            "remediation_task_ids": [],
            "status": "failed",
            "budget_exhausted": True,
        }

    for tid in remediation_ids:
        task = task_map.get(tid)
        if not task:
            continue

        meta = task.pop("_remediation_meta", {})
        cycle = task.get("remediation_cycles", 0) + 1
        task["remediation_cycles"] = cycle

        diag = meta.get("diagnostic_summary", "")
        unmet = meta.get("unmet_criteria", [])
        reasoning = meta.get("reasoning", "")
        suggestions = meta.get("suggestions", [])

        unmet_text = "\n".join(f"- {c}" for c in unmet) if unmet else "None"
        sugg_text = "\n".join(f"- {s}" for s in suggestions) if suggestions else "None"

        remediation_prompt = (
            f"\n\n======================================================\n"
            f"REMEDIATION REQUIRED (Cycle {cycle}/3)\n"
            f"Your previous deliverable failed verification. Fix the following issues:\n\n"
            f"### Diagnostics & Failures:\n{diag}\n\n"
            f"### Unmet Acceptance Criteria:\n{unmet_text}\n\n"
            f"### Suggestions:\n{sugg_text}\n"
            f"======================================================\n"
        )

        original_prompt = task.get("original_description") or task.get("description", "")
        task["original_description"] = original_prompt
        task["description"] = original_prompt + remediation_prompt
        # Reset task status to pending so it runs in dispatch_task
        task["status"] = "pending"
        task["error_message"] = None

        history = list(task.get("remediation_history_json", []))
        rec = {
            "cycle": cycle,
            "task_id": tid,
            "diagnostics": diag,
            "unmet_criteria": unmet,
            "reasoning": reasoning,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        history.append(rec)
        task["remediation_history_json"] = history
        remediation_records.append(rec)
        tasks_to_remediate.append(tid)

        try:
            async with AsyncSessionLocal() as session:
                await WorkflowService.record_event(
                    session,
                    execution_id,
                    "task_remediation_cycle",
                    rec,
                )
                await session.commit()
        except Exception:
            pass

    return {
        "tasks": tasks,
        "current_ready_task_ids": tasks_to_remediate,
        "remediation_needed": False,
        "remediation_task_ids": [],
        "remediation_records": remediation_records,
    }


async def replan_node(state: OrchestrationState) -> dict[str, Any]:
    execution_id_str = state.get("execution_id")
    current_replan_count = state.get("replan_count", 0)
    replan_reason = (
        state.get("replan_reason") or "Adaptive DAG replanning triggered by evaluation findings."
    )
    logger.info(
        "Executing replan_node (iteration %d) for execution %s: %s",
        current_replan_count + 1,
        execution_id_str,
        replan_reason,
    )

    # 1. Budget Governor replan turn check and enforcement
    if execution_id_str:
        try:
            exec_uuid = uuid.UUID(execution_id_str)
            async with AsyncSessionLocal() as session:
                await BudgetGovernor.record_replan(session, exec_uuid)
                await session.commit()
        except (BudgetExhaustedError, BudgetLimitExceededError) as exc:
            msg = f"Replanning halted: {exc}"
            logger.warning("Replan refused for execution %s: %s", execution_id_str, exc)
            return {
                "status": "failed",
                "error": msg,
                "error_message": msg,
                "budget_exhausted": True,
                "replan_needed": False,
            }

    # 2. Replan remaining unexecuted tasks using DAGModifier
    current_tasks = state.get("tasks", [])
    completed_ids = state.get("completed_task_ids", [])
    failed_ids = state.get("failed_task_ids", [])

    new_tasks = state.get("new_tasks_for_replan")
    if not new_tasks:
        studio_type_str = state.get("studio_type", "saas")
        studio_type = StudioType.MEDIA if studio_type_str == "media" else StudioType.SAAS
        adapted_plan = await GoalDecomposer.decompose_goal(
            objective=f"{state.get('objective', '')} (Replanning note: {replan_reason})",
            project_id=state.get("project_id", "default"),
            studio_type=studio_type,
            retrieval_context=state.get("retrieval_context"),
        )
        new_tasks = [t.model_dump() for t in adapted_plan.tasks]

    try:
        updated_tasks = DAGModifier.modify_dag(
            current_tasks=current_tasks,
            completed_task_ids=completed_ids,
            failed_task_ids=failed_ids,
            new_or_modified_tasks=new_tasks,
        )
    except Exception as exc:
        logger.error("DAG modification failed: %s", exc)
        return {
            "status": "failed",
            "error": f"Invalid replan DAG: {exc}",
            "error_message": f"Invalid replan DAG: {exc}",
            "replan_needed": False,
        }

    # Record telemetry event
    replan_record = {
        "replan_count": current_replan_count + 1,
        "reason": replan_reason,
        "completed_task_count": len(completed_ids),
        "total_task_count": len(updated_tasks),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    replan_records = list(state.get("replan_records", []))
    replan_records.append(replan_record)

    if execution_id_str:
        try:
            exec_uuid = uuid.UUID(execution_id_str)
            async with AsyncSessionLocal() as session:
                await WorkflowService.record_event(
                    session,
                    exec_uuid,
                    "execution_replan",
                    replan_record,
                )
                execution = await WorkflowService.get_execution(session, exec_uuid)
                if execution:
                    execution.replan_count = current_replan_count + 1
                await session.commit()
        except Exception:
            pass

    return {
        "tasks": updated_tasks,
        "replan_count": current_replan_count + 1,
        "replan_needed": False,
        "replan_reason": None,
        "replan_records": replan_records,
        "status": "running",
    }


async def artifact_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    ready_ids = state.get("current_ready_task_ids", [])
    project_id = state.get("project_id", "default")
    project_work_dir = (settings.ARTIFACT_STORAGE_PATH / project_id).resolve()
    if state.get("worktree_path"):
        wt_p = Path(state["worktree_path"]).resolve()
        if wt_p.exists() and wt_p.is_dir():
            project_work_dir = wt_p

    artifacts = list(state.get("artifacts", []))
    completed_ids = list(state.get("completed_task_ids", []))
    task_map = {t["task_id"]: t for t in tasks}

    for tid in ready_ids:
        task = task_map.get(tid)
        # Sibling tasks that completed successfully in this wave get artifacts registered
        if not task or task.get("status") != "completed":
            continue

        output_text = task.get("output_text", "")
        agent_slug = task.get("assigned_agent_slug", "unknown")

        for filename in task.get("expected_output_artifacts", []):
            file_path = project_work_dir / filename
            if output_text and not file_path.exists():
                if filename.endswith(".json"):
                    try:
                        json.loads(output_text)
                        file_path.write_text(output_text, encoding="utf-8")
                    except Exception:
                        file_path.write_text(json.dumps({"content": output_text}), encoding="utf-8")
                else:
                    file_path.write_text(output_text, encoding="utf-8")

            artifacts.append(
                {
                    "task_id": tid,
                    "name": filename,
                    "producing_agent_slug": agent_slug,
                    "file_path": f"{project_id}/{filename}",
                    "size_bytes": file_path.stat().st_size
                    if file_path.exists()
                    else len(output_text.encode()),
                }
            )

        if tid not in completed_ids:
            completed_ids.append(tid)

    # Auto-commit deliverable artifacts if operating in an isolated git worktree
    if state.get("worktree_path"):
        wt_p = Path(state["worktree_path"]).resolve()
        if wt_p.exists() and wt_p.is_dir():
            try:
                commit_msg = f"chore(execution): completed tasks {ready_ids}"
                await GitWorktreeManager.commit_changes(
                    worktree_path=wt_p,
                    message=commit_msg,
                )
            except Exception as e:
                logger.warning("Auto-commit in worktree %s failed: %s", wt_p, e)

    return {
        "artifacts": artifacts,
        "completed_task_ids": completed_ids,
        "current_ready_task_ids": [],
    }


async def _mark_ingestion_failed(
    project_uuid: uuid.UUID, operation_token: str, error_message: str
) -> None:
    """Record a top-level ingestion failure on its operation row in a fresh session."""
    try:
        async with AsyncSessionLocal() as session:
            op = (
                await session.execute(
                    select(IngestionOperation).where(
                        IngestionOperation.project_id == project_uuid,
                        IngestionOperation.operation_token == operation_token,
                    )
                )
            ).scalar_one_or_none()
            if op is not None and op.status == IngestionOperationStatus.COMPLETED:
                # A concurrent winner already finished; never clobber its completed state.
                return
            if op is None:
                op = IngestionOperation(
                    project_id=project_uuid,
                    operation_token=operation_token,
                )
                session.add(op)
            op.status = IngestionOperationStatus.FAILED
            op.error_message = error_message
            await session.commit()
    except Exception as mark_err:
        logger.error("Could not record ingestion failure for %s: %s", operation_token, mark_err)


async def ingest_knowledge_node(state: OrchestrationState) -> dict[str, Any]:
    """Extracts and persists durable project knowledge after successful execution.

    Idempotent per ``operation_token``: a completed IngestionOperation short-circuits,
    and each candidate is keyed by a fingerprint so re-runs reuse existing memories.
    """
    # 1. In-memory check: if already completed, pass through
    if state.get("ingestion_status") == "completed" and state.get("ingested_memory_ids"):
        logger.info("Knowledge ingestion already completed for this execution.")
        return {}

    project_id_str = state.get("project_id", "")
    execution_id_str = state.get("execution_id", "")

    try:
        project_uuid = uuid.UUID(project_id_str)
        execution_uuid = uuid.UUID(execution_id_str) if execution_id_str else None
    except (ValueError, TypeError):
        logger.info("Project or execution ID is non-UUID; skipping memory ingestion.")
        return {
            "ingestion_status": "skipped",
            "ingested_memory_ids": [],
            "ingestion_errors": ["non_uuid_identifiers"],
        }

    # 2. Extract structured candidates
    candidates = KnowledgeExtractor.extract_from_execution(state)
    if not candidates:
        logger.info(
            "No durable knowledge candidates extracted from execution %s",
            execution_id_str,
        )
        return {
            "ingestion_status": "completed",
            "knowledge_candidates": [],
            "ingested_memory_ids": [],
            "ingestion_errors": [],
        }

    # Without an execution id, fall back to a unique token so unrelated runs never collide.
    operation_token = state.get("ingestion_operation_token") or (
        f"{execution_uuid}:final" if execution_uuid else f"{uuid.uuid4()}:final"
    )

    # 3. Database idempotency check and persistence
    ingested_ids: list[str] = []
    errors: list[str] = []

    try:
        async with AsyncSessionLocal() as session:
            # Verify execution foreign key if execution_uuid is provided
            valid_execution_id: uuid.UUID | None = None
            if execution_uuid:
                exec_row = await session.get(WorkflowExecution, execution_uuid)
                if exec_row is not None:
                    valid_execution_id = execution_uuid

            existing_op = (
                await session.execute(
                    select(IngestionOperation).where(
                        IngestionOperation.project_id == project_uuid,
                        IngestionOperation.operation_token == operation_token,
                    )
                )
            ).scalar_one_or_none()

            if existing_op is not None and existing_op.status == IngestionOperationStatus.COMPLETED:
                logger.info(
                    "Idempotent reuse: ingestion operation %s already completed",
                    operation_token,
                )
                return {
                    "ingestion_status": "completed",
                    "ingested_memory_ids": list(existing_op.ingested_memory_ids or []),
                    "knowledge_candidates": [c.model_dump() for c in candidates],
                    "ingestion_errors": [],
                }

            if existing_op is not None and existing_op.status == IngestionOperationStatus.PENDING:
                # Another worker is already executing this operation; wait for it to complete.
                winner: IngestionOperation | None = None
                for _ in range(60):
                    await asyncio.sleep(0.05)
                    async with AsyncSessionLocal() as poll_session:
                        winner = (
                            await poll_session.execute(
                                select(IngestionOperation).where(
                                    IngestionOperation.project_id == project_uuid,
                                    IngestionOperation.operation_token == operation_token,
                                )
                            )
                        ).scalar_one_or_none()
                        if (
                            winner is not None
                            and winner.status == IngestionOperationStatus.COMPLETED
                        ):
                            break
                        if winner is not None and winner.status == IngestionOperationStatus.FAILED:
                            break
                if winner is not None and winner.status == IngestionOperationStatus.COMPLETED:
                    logger.info(
                        "Concurrent ingestion for %s completed by peer; reusing its result",
                        operation_token,
                    )
                    return {
                        "ingestion_status": "completed",
                        "ingested_memory_ids": list(winner.ingested_memory_ids or []),
                        "knowledge_candidates": [c.model_dump() for c in candidates],
                        "ingestion_errors": [],
                    }

            if existing_op is None:
                op = IngestionOperation(
                    project_id=project_uuid,
                    execution_id=valid_execution_id,
                    operation_token=operation_token,
                    status=IngestionOperationStatus.PENDING,
                    candidate_count=len(candidates),
                )
                session.add(op)
            else:
                # Retry of a failed operation: reset it and reuse the row.
                op = existing_op
                op.status = IngestionOperationStatus.PENDING
                op.error_message = None
                op.candidate_count = len(candidates)

            # Persist the operation row before candidate work so failures can be recorded.
            try:
                await session.commit()
            except IntegrityError:
                # A concurrent worker won the insert for this operation_token.
                await session.rollback()
                winner: IngestionOperation | None = None
                for _ in range(60):
                    await asyncio.sleep(0.05)
                    async with AsyncSessionLocal() as poll_session:
                        winner = (
                            await poll_session.execute(
                                select(IngestionOperation).where(
                                    IngestionOperation.project_id == project_uuid,
                                    IngestionOperation.operation_token == operation_token,
                                )
                            )
                        ).scalar_one_or_none()
                        if (
                            winner is not None
                            and winner.status == IngestionOperationStatus.COMPLETED
                        ):
                            break
                        if winner is not None and winner.status == IngestionOperationStatus.FAILED:
                            break
                if winner is not None and winner.status == IngestionOperationStatus.COMPLETED:
                    logger.info(
                        "Concurrent ingestion for %s won the race; reusing its result",
                        operation_token,
                    )
                    return {
                        "ingestion_status": "completed",
                        "ingested_memory_ids": list(winner.ingested_memory_ids or []),
                        "knowledge_candidates": [c.model_dump() for c in candidates],
                        "ingestion_errors": [],
                    }
                logger.warning(
                    "Concurrent ingestion for %s did not complete (status=%s)",
                    operation_token,
                    winner.status if winner is not None else None,
                )
                return {
                    "ingestion_status": "failed",
                    "knowledge_candidates": [c.model_dump() for c in candidates],
                    "ingested_memory_ids": [],
                    "ingestion_errors": ["concurrent_ingestion_not_completed"],
                }

            for cand in candidates:
                fingerprint = compute_candidate_fingerprint(
                    project_uuid,
                    cand.category,
                    cand.summary,
                    source_execution_id=valid_execution_id,
                    source_task_id=cand.source_task_id,
                )
                existing_id = (
                    await session.execute(
                        select(ProjectMemory.id).where(
                            ProjectMemory.project_id == project_uuid,
                            ProjectMemory.fingerprint == fingerprint,
                        )
                    )
                ).scalar_one_or_none()
                if existing_id is not None:
                    ingested_ids.append(str(existing_id))
                    continue

                try:
                    # Savepoint: a failing candidate rolls back only itself.
                    async with session.begin_nested():
                        mem = await MemoryService.create_memory(
                            session,
                            project_id=project_uuid,
                            category=cand.category,
                            summary=cand.summary,
                            content=cand.content,
                            provenance_type=cand.provenance_type,
                            confidence_score=cand.confidence_score,
                            is_verified=cand.is_verified,
                            source_execution_id=valid_execution_id,
                            source_task_id=cand.source_task_id,
                            source_agent_slug=cand.source_agent_slug,
                            metadata_json=cand.metadata_json,
                            actor_type="agent",
                            actor_id=cand.source_agent_slug or "orchestrator",
                            reason=f"Ingested from execution {execution_id_str}",
                            fingerprint=fingerprint,
                            ingestion_operation_id=op.id,
                        )
                    ingested_ids.append(str(mem.id))
                except IntegrityError:
                    # A concurrent worker already committed this exact fingerprint.
                    existing_id = (
                        await session.execute(
                            select(ProjectMemory.id).where(
                                ProjectMemory.project_id == project_uuid,
                                ProjectMemory.fingerprint == fingerprint,
                            )
                        )
                    ).scalar_one_or_none()
                    if existing_id is not None:
                        ingested_ids.append(str(existing_id))
                    else:
                        errors.append(f"{cand.summary}: duplicate fingerprint conflict")
                except Exception as cand_err:
                    logger.warning("Error persisting candidate '%s': %s", cand.summary, cand_err)
                    errors.append(f"{cand.summary}: {str(cand_err)}")

            op.status = IngestionOperationStatus.COMPLETED
            op.ingested_memory_ids = ingested_ids
            op.completed_at = datetime.now(UTC)
            op.error_message = "; ".join(errors) if errors else None
            await session.commit()

        logger.info(
            "Successfully ingested %d memories for project %s (execution %s)",
            len(ingested_ids),
            project_id_str,
            execution_id_str,
        )

        return {
            "ingestion_status": "completed" if not errors else "partial",
            "knowledge_candidates": [c.model_dump() for c in candidates],
            "ingested_memory_ids": ingested_ids,
            "ingestion_errors": errors,
        }
    except Exception as e:
        logger.error("Knowledge ingestion failed: %s", e)
        await _mark_ingestion_failed(project_uuid, operation_token, str(e))
        return {
            "ingestion_status": "failed",
            "knowledge_candidates": [c.model_dump() for c in candidates],
            # Uncommitted memories were rolled back, so report none as persisted.
            "ingested_memory_ids": [],
            "ingestion_errors": [str(e)],
        }


async def complete_node(state: OrchestrationState) -> dict[str, Any]:
    logger.info("Workflow execution complete for objective: %s", state.get("objective"))
    return {"status": "completed"}


def route_after_approval_check(state: OrchestrationState) -> Literal["dispatch_task", "__end__"]:
    if state.get("status") in ("waiting_approval", "failed"):
        return "__end__"
    return "dispatch_task"


def route_after_dispatch(state: OrchestrationState) -> Literal["verify", "__end__"]:
    # Budget refusal halts before any task ran: nothing to verify, end the run.
    if state.get("budget_exhausted"):
        return "__end__"
    # Otherwise route to verify so completed tasks in the batch have their output processed
    return "verify"


def route_after_verify(
    state: OrchestrationState,
) -> Literal["remediation", "replan", "artifact"]:
    if state.get("remediation_needed"):
        return "remediation"
    if state.get("replan_needed"):
        return "replan"
    return "artifact"


def route_after_replan(
    state: OrchestrationState,
) -> Literal["approval_check", "__end__"]:
    if state.get("budget_exhausted") or state.get("status") == "failed":
        return "__end__"
    return "approval_check"


def route_after_remediation(state: OrchestrationState) -> Literal["dispatch_task", "__end__"]:
    if state.get("budget_exhausted") or state.get("status") == "failed":
        return "__end__"
    return "dispatch_task"


def route_after_artifact(
    state: OrchestrationState,
) -> Literal["approval_check", "ingest_knowledge", "__end__"]:
    if state.get("status") == "failed" or state.get("failed_task_ids"):
        return "__end__"

    tasks = state.get("tasks", [])
    completed_ids = set(state.get("completed_task_ids", []))

    if len(completed_ids) == len(tasks) and len(tasks) > 0:
        return "ingest_knowledge"

    return "approval_check"


def build_orchestrator_graph():
    """Builds and compiles the stateful LangGraph workflow."""
    workflow = StateGraph(OrchestrationState)

    workflow.add_node("retrieve_knowledge", retrieve_knowledge_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("approval_check", approval_check_node)
    workflow.add_node("dispatch_task", dispatch_task_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("remediation", remediation_node)
    workflow.add_node("replan", replan_node)
    workflow.add_node("artifact", artifact_node)
    workflow.add_node("ingest_knowledge", ingest_knowledge_node)
    workflow.add_node("complete", complete_node)

    workflow.set_entry_point("retrieve_knowledge")
    workflow.add_edge("retrieve_knowledge", "plan")
    workflow.add_edge("plan", "approval_check")

    workflow.add_conditional_edges(
        "approval_check",
        route_after_approval_check,
        {
            "dispatch_task": "dispatch_task",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "dispatch_task",
        route_after_dispatch,
        {
            "verify": "verify",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "verify",
        route_after_verify,
        {
            "remediation": "remediation",
            "replan": "replan",
            "artifact": "artifact",
        },
    )

    workflow.add_conditional_edges(
        "replan",
        route_after_replan,
        {
            "approval_check": "approval_check",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "remediation",
        route_after_remediation,
        {
            "dispatch_task": "dispatch_task",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "artifact",
        route_after_artifact,
        {
            "approval_check": "approval_check",
            "ingest_knowledge": "ingest_knowledge",
            "__end__": END,
        },
    )

    workflow.add_edge("ingest_knowledge", "complete")
    workflow.add_edge("complete", END)

    return workflow.compile()
