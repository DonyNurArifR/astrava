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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.budget import BudgetReservationStatus
from app.models.execution import WorkflowExecution
from app.models.memory import IngestionOperation, IngestionOperationStatus, ProjectMemory
from app.models.project import StudioType
from app.models.task import ExecutorType
from app.orchestrator.knowledge_extraction import (
    KnowledgeExtractor,
    compute_candidate_fingerprint,
)
from app.orchestrator.planner import PlannerService
from app.orchestrator.state import OrchestrationState
from app.providers.base import ProviderRequest, ProviderStatus
from app.providers.factory import ProviderFactory
from app.services.agent_service import DEFAULT_AGENTS
from app.services.budget_governor import (
    BudgetExhaustedError,
    BudgetGovernor,
    FencingTokenMismatchError,
    ReservationNotFoundError,
)
from app.services.memory_service import MemoryService
from app.services.retrieval.schemas import RetrievalQuery
from app.services.retrieval.service import RetrievalService
from app.verification.engine import VerificationEngine

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

    plan = PlannerService.generate_plan(
        project_id=state.get("project_id", "default"),
        objective=state.get("objective", ""),
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
    fence_token: str | None = None,
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
            if res_id:
                try:
                    await _settle_reservation(res_id, None, fence_token=fence)
                except Exception:
                    pass
            raise
        if res_id:
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

    # 2. Deterministic task execution (e.g. QA engineer)
    if task.get("executor_type") == ExecutorType.DETERMINISTIC:
        report = await VerificationEngine.verify_task(project_work_dir)
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
        if init_res_id is not None:
            try:
                async with AsyncSessionLocal() as session:
                    await BudgetGovernor.reconcile(
                        session,
                        init_res_id,
                        actual_input_tokens=0,
                        actual_output_tokens=0,
                        duration_ms=report.total_duration_ms,
                        actual_cost_usd=Decimal("0.0"),
                        is_cost_estimated=False,
                        is_cost_zero_confirmed=True,
                        fence_token=init_fence_token,
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
        working_directory=project_work_dir,
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

        # Settle this attempt immediately with BudgetGovernor
        if current_res_id is not None:
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
                        actual_cost_usd=actual_cost,
                        is_cost_estimated=resp.is_cost_estimated or actual_cost is None,
                        fence_token=current_fence,
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

        if resp.status in (ProviderStatus.FAILED, ProviderStatus.TIMEOUT):
            last_error = resp.error_message or f"Provider returned status {resp.status.value}"
        elif not resp.output_text.strip():
            last_error = "Agent produced empty deliverable"
        else:
            # Check schema validation if required fields specified
            output_schema = agent_info.get("output_schema", {})
            required_fields = output_schema.get("required", [])
            if required_fields:
                parsed_dict = _extract_json_dict(resp.output_text)
                if parsed_dict:
                    missing = [f for f in required_fields if f not in parsed_dict]
                    if missing:
                        last_error = f"Deliverable missing required schema fields: {missing}"
                        if attempt < max_retries:
                            logger.warning(
                                "Task '%s' deliverable missing schema fields: %s. Retrying (%d/%d)...",
                                task["task_id"],
                                missing,
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(1)
                            continue
                    else:
                        success = True
                        break
                else:
                    # Output was not JSON, but succeeded
                    success = True
                    break
            else:
                success = True
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
    project_work_dir.mkdir(parents=True, exist_ok=True)

    task_map = {t["task_id"]: t for t in tasks}
    ready_tasks = [task_map[tid] for tid in ready_ids if tid in task_map]

    logger.info("Dispatching %d task(s) concurrently in this stage", len(ready_tasks))

    # Reserve budget for the whole wave atomically: any refusal rolls back every
    # reservation in this wave and nothing is dispatched.
    execution_id = uuid.UUID(state["execution_id"])
    reservations: dict[str, tuple[uuid.UUID, str]] = {}
    tasks_to_dispatch: list[dict[str, Any]] = []

    try:
        async with AsyncSessionLocal() as session:
            budget = await BudgetGovernor.initialize_budget(
                session, execution_id, uuid.UUID(state["project_id"])
            )
            for t in ready_tasks:
                res_key = f"task:{t['task_id']}:attempt:0"
                # Crash recovery idempotency: check if attempt 0 already reconciled
                existing = await BudgetGovernor.get_reservation_by_key(session, budget.id, res_key)
                if existing is not None and existing.status == BudgetReservationStatus.RECONCILED:
                    logger.info("Task %s attempt 0 already reconciled in prior run", t["task_id"])
                    t["status"] = "completed"
                    continue

                reservation = await BudgetGovernor.reserve(
                    session,
                    execution_id,
                    reservation_key=res_key,
                    task_id=t["task_id"],
                    agent_slug=t.get("assigned_agent_slug"),
                    purpose="agent_dispatch",
                    attempt_number=0,
                    timeout_seconds=_reservation_timeout_seconds(t, state),
                )
                reservations[t["task_id"]] = (reservation.id, reservation.fence_token)
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
    failed_ids = list(state.get("failed_task_ids", []))
    any_failed = False
    error_msg = None

    for i, res in enumerate(results):
        target_task = ready_tasks[i]
        if isinstance(res, Exception):
            logger.error("Task %s raised unhandled exception: %s", target_task["task_id"], res)
            target_task["status"] = "failed"
            target_task["error_message"] = str(res)
            failed_ids.append(target_task["task_id"])
            any_failed = True
            error_msg = str(res)
        else:
            updated_task, u_records = res
            target_task.update(updated_task)
            usage_list.extend(u_records)
            if target_task.get("status") == "failed":
                failed_ids.append(target_task["task_id"])
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
    project_id = state.get("project_id", "default")
    project_work_dir = (settings.ARTIFACT_STORAGE_PATH / project_id).resolve()

    logger.info("Running deterministic verification for batch: %s", ready_ids)
    report = await VerificationEngine.verify_task(project_work_dir)

    results = list(state.get("verification_results", []))
    for tid in ready_ids:
        results.append(
            {
                "task_id": tid,
                "report": report.model_dump(),
            }
        )

    return {"verification_results": results}


async def artifact_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    ready_ids = state.get("current_ready_task_ids", [])
    project_id = state.get("project_id", "default")
    project_work_dir = (settings.ARTIFACT_STORAGE_PATH / project_id).resolve()

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
    workflow.add_edge("verify", "artifact")

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
