import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.execution import WorkflowExecution
from app.models.memory import ProjectMemory
from app.models.project import StudioType
from app.models.task import ExecutorType
from app.orchestrator.knowledge_extraction import KnowledgeExtractor
from app.orchestrator.planner import PlannerService
from app.orchestrator.state import OrchestrationState
from app.providers.base import ProviderRequest, ProviderStatus
from app.providers.factory import ProviderFactory
from app.services.agent_service import DEFAULT_AGENTS
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


async def plan_node(state: OrchestrationState) -> dict[str, Any]:
    # If plan already exists in state (e.g. on resume), preserve existing plan and tasks
    if state.get("plan"):
        logger.info("Preserving existing plan on pipeline resume.")
        return {}

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


async def _execute_single_task(
    task: dict[str, Any],
    state: OrchestrationState,
    project_work_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Executes a single task using its assigned agent instructions,
    structured upstream context from completed dependencies, bounded retries,
    and output schema validation.
    """
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

        usage_records.append(
            {
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
        )
        return task, usage_records

    # 3. Claude Code CLI execution with bounded retries
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

Your Assigned Task: {task["title"]}
Task Description: {task["description"]}
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
        resp = await provider.execute(p_req)

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

    # Execute independent tasks concurrently via asyncio.gather
    results = await asyncio.gather(
        *[_execute_single_task(t, state, project_work_dir) for t in ready_tasks],
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


async def ingest_knowledge_node(state: OrchestrationState) -> dict[str, Any]:
    """Extracts and persists durable project knowledge after successful execution."""
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
                    # Check if this execution already persisted memories (crash recovery protection)
                    existing_stmt = select(ProjectMemory).where(
                        ProjectMemory.project_id == project_uuid,
                        ProjectMemory.source_execution_id == execution_uuid,
                    )
                    existing = list((await session.execute(existing_stmt)).scalars().all())
                    if existing:
                        logger.info(
                            "Found %d existing persisted memories for execution %s; skipping duplicate insertion.",
                            len(existing),
                            execution_id_str,
                        )
                        return {
                            "ingestion_status": "completed",
                            "knowledge_candidates": [c.model_dump() for c in candidates],
                            "ingested_memory_ids": [str(m.id) for m in existing],
                            "ingestion_errors": [],
                        }

            for cand in candidates:
                try:
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
                    )
                    ingested_ids.append(str(mem.id))
                except Exception as cand_err:
                    logger.warning("Error persisting candidate '%s': %s", cand.summary, cand_err)
                    errors.append(f"{cand.summary}: {str(cand_err)}")
                    await session.rollback()

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
        return {
            "ingestion_status": "failed",
            "knowledge_candidates": [c.model_dump() for c in candidates],
            "ingested_memory_ids": ingested_ids,
            "ingestion_errors": [str(e)],
        }


async def complete_node(state: OrchestrationState) -> dict[str, Any]:
    logger.info("Workflow execution complete for objective: %s", state.get("objective"))
    return {"status": "completed"}


def route_after_approval_check(state: OrchestrationState) -> Literal["dispatch_task", "__end__"]:
    if state.get("status") in ("waiting_approval", "failed"):
        return "__end__"
    return "dispatch_task"


def route_after_dispatch(state: OrchestrationState) -> Literal["verify"]:
    # Always route to verify so completed tasks in the batch have their output processed
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

    workflow.add_edge("dispatch_task", "verify")
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
