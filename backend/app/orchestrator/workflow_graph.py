import asyncio
import json
import logging
from typing import Any, Literal

from langgraph.graph import END, StateGraph

from app.config import settings
from app.models.project import StudioType
from app.models.task import ExecutorType
from app.orchestrator.planner import PlannerService
from app.orchestrator.state import OrchestrationState
from app.providers.base import ProviderRequest, ProviderStatus
from app.providers.factory import ProviderFactory
from app.services.agent_service import DEFAULT_AGENTS
from app.verification.engine import VerificationEngine

logger = logging.getLogger("astrava.orchestrator")

AGENT_MAP = {a["slug"]: a for a in DEFAULT_AGENTS}


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
    )
    tasks = [t.model_dump() for t in plan.tasks]

    return {
        "plan": plan.model_dump(),
        "tasks": tasks,
        "completed_task_ids": [],
        "current_ready_task_ids": [],
        "current_task_index": 0,
        "status": "running",
    }


async def approval_check_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    completed_ids = set(state.get("completed_task_ids", []))

    # All tasks completed
    if len(completed_ids) == len(tasks) and len(tasks) > 0:
        return {"status": "completed"}

    # Find tasks whose dependencies are fully met and haven't run yet
    ready_tasks = [
        t
        for t in tasks
        if t["task_id"] not in completed_ids
        and t.get("status") != "failed"
        and all(dep in completed_ids for dep in t.get("dependencies", []))
    ]

    if not ready_tasks:
        if state.get("status") == "failed":
            return {"status": "failed"}
        return {"status": "completed"}

    # Check if ANY ready task requires human approval
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
    project_work_dir: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Executes a single task using its assigned agent instructions and upstream context."""
    agent_slug = task.get("assigned_agent_slug", "developer")
    agent_info = AGENT_MAP.get(agent_slug, {})
    agent_name = agent_info.get("name", agent_slug)
    agent_instructions = agent_info.get("instructions", "Execute the task meeting all criteria.")

    # Gather upstream deliverables as context
    upstream_context_blocks = []
    task_lookup = {t["task_id"]: t for t in state.get("tasks", [])}
    for dep_id in task.get("dependencies", []):
        dep_task = task_lookup.get(dep_id, {})
        dep_title = dep_task.get("title", dep_id)
        dep_out = dep_task.get("output_text", "")
        if dep_out:
            upstream_context_blocks.append(
                f"=== Deliverable from [{dep_title}] ===\n{dep_out[:2500]}"
            )

    upstream_text = (
        "\n\n".join(upstream_context_blocks) if upstream_context_blocks else "None (Initial stage)."
    )

    # Deterministic task execution (e.g. QA engineer)
    if task.get("executor_type") == ExecutorType.DETERMINISTIC:
        report = await VerificationEngine.verify_task(project_work_dir)
        output_text = json.dumps(report.model_dump(), indent=2)
        task["output_text"] = output_text
        task["status"] = "completed" if report.overall_passed else "failed"
        task["exit_code"] = 0 if report.overall_passed else 1

        usage = {
            "task_id": task["task_id"],
            "provider": "deterministic",
            "model": "deterministic-engine",
            "duration_ms": 50,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_usd": 0.0,
            "status": "success" if report.overall_passed else "failed",
            "exit_code": task["exit_code"],
        }
        return task, usage

    # Claude Code CLI Agent execution
    prompt = f"""You are an autonomous AI Agent in the ASTRAVA platform.
Agent Identity: {agent_name} ({agent_slug})
Agent Responsibilities & Instructions:
{agent_instructions}

Project Context & Upstream Prerequisites:
{upstream_text}

Assigned Task: {task["title"]}
Description: {task["description"]}
Acceptance Criteria: {task.get("acceptance_criteria", [])}
Expected Deliverables: {task.get("expected_output_artifacts", [])}

Produce the full deliverable meeting all criteria directly."""

    provider = ProviderFactory.get_provider("claude_code")
    req = ProviderRequest(
        prompt=prompt,
        working_directory=project_work_dir,
        model=task.get("assigned_model", "haiku"),
        timeout_seconds=settings.CLAUDE_EXECUTION_TIMEOUT_SECONDS,
    )

    resp = await provider.execute(req)
    usage = {
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

    task["output_text"] = resp.output_text
    task["exit_code"] = resp.exit_code

    # Quality control: detect failed/timeout or empty output
    if resp.status in (ProviderStatus.FAILED, ProviderStatus.TIMEOUT):
        task["status"] = "failed"
        task["error_message"] = resp.error_message or "Task execution failed"
    elif not resp.output_text.strip():
        task["status"] = "failed"
        task["error_message"] = "Agent produced empty deliverable"
    else:
        task["status"] = "completed"

    return task, usage


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
    any_failed = False
    error_msg = None

    for i, res in enumerate(results):
        target_task = ready_tasks[i]
        if isinstance(res, Exception):
            logger.error("Task %s raised unhandled exception: %s", target_task["task_id"], res)
            target_task["status"] = "failed"
            target_task["error_message"] = str(res)
            any_failed = True
            error_msg = str(res)
        else:
            updated_task, usage = res
            target_task.update(updated_task)
            if usage:
                usage_list.append(usage)
            if target_task.get("status") == "failed":
                any_failed = True
                error_msg = target_task.get("error_message", "Task failed")

    return {
        "tasks": tasks,
        "usage_records": usage_list,
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

        completed_ids.append(tid)

    return {
        "artifacts": artifacts,
        "completed_task_ids": completed_ids,
        "current_ready_task_ids": [],
    }


async def complete_node(state: OrchestrationState) -> dict[str, Any]:
    logger.info("Workflow execution complete for objective: %s", state.get("objective"))
    return {"status": "completed"}


def route_after_approval_check(state: OrchestrationState) -> Literal["dispatch_task", "__end__"]:
    if state.get("status") == "waiting_approval":
        return "__end__"
    return "dispatch_task"


def route_after_dispatch(state: OrchestrationState) -> Literal["verify", "__end__"]:
    if state.get("status") == "failed":
        return "__end__"
    return "verify"


def route_after_artifact(
    state: OrchestrationState,
) -> Literal["approval_check", "complete", "__end__"]:
    if state.get("status") == "failed":
        return "__end__"

    tasks = state.get("tasks", [])
    completed_ids = set(state.get("completed_task_ids", []))

    if len(completed_ids) == len(tasks) and len(tasks) > 0:
        return "complete"

    return "approval_check"


def build_orchestrator_graph():
    """Builds and compiles the stateful LangGraph workflow."""
    workflow = StateGraph(OrchestrationState)

    workflow.add_node("plan", plan_node)
    workflow.add_node("approval_check", approval_check_node)
    workflow.add_node("dispatch_task", dispatch_task_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("artifact", artifact_node)
    workflow.add_node("complete", complete_node)

    workflow.set_entry_point("plan")
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
            "complete": "complete",
            "__end__": END,
        },
    )

    workflow.add_edge("complete", END)

    return workflow.compile()
