import logging
from typing import Any, Literal

from langgraph.graph import END, StateGraph

from app.config import settings
from app.models.project import StudioType
from app.orchestrator.planner import PlannerService
from app.orchestrator.state import OrchestrationState
from app.providers.base import ProviderRequest, ProviderStatus
from app.providers.factory import ProviderFactory
from app.verification.engine import VerificationEngine

logger = logging.getLogger("astrava.orchestrator")


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
        "current_task_index": 0,
        "completed_task_ids": [],
        "status": "running",
    }


async def approval_check_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    idx = state.get("current_task_index", 0)

    if idx >= len(tasks):
        return {"status": "completed"}

    current_task = tasks[idx]
    requires_approval = current_task.get("requires_approval", False)

    # Check if task was already approved via state
    if requires_approval and not current_task.get("approved", False):
        logger.info("Task '%s' requires human approval. Pausing execution.", current_task["title"])
        return {
            "status": "waiting_approval",
            "active_approval_id": current_task["task_id"],
        }

    return {"status": "running"}


async def dispatch_task_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    idx = state.get("current_task_index", 0)
    current_task = tasks[idx]
    project_id = state.get("project_id", "default")

    logger.info("Dispatching task %d/%d: %s", idx + 1, len(tasks), current_task["title"])

    # Task working directory inside sandboxed project storage
    project_work_dir = (settings.ARTIFACT_STORAGE_PATH / project_id).resolve()
    project_work_dir.mkdir(parents=True, exist_ok=True)

    provider = ProviderFactory.get_provider("claude_code")
    req = ProviderRequest(
        prompt=(
            f"You are executing an autonomous ASTRAVA task.\n"
            f"Task: {current_task['title']}\n"
            f"Description: {current_task['description']}\n"
            f"Acceptance Criteria: {current_task.get('acceptance_criteria', [])}\n"
            f"Generate the required solution directly."
        ),
        working_directory=project_work_dir,
        model=current_task.get("assigned_model", "haiku"),
        timeout_seconds=settings.CLAUDE_EXECUTION_TIMEOUT_SECONDS,
    )

    resp = await provider.execute(req)

    usage_record = {
        "task_id": current_task["task_id"],
        "provider": "claude_code",
        "model": resp.canonical_model or current_task.get("assigned_model", "claude-haiku-5-5"),
        "duration_ms": resp.duration_ms,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "cache_read_tokens": resp.cache_read_tokens,
        "cache_creation_tokens": resp.cache_creation_tokens,
        "cost_usd": resp.cost_usd,
        "status": resp.status.value,
        "exit_code": resp.exit_code,
    }

    usage_list = list(state.get("usage_records", []))
    usage_list.append(usage_record)

    current_task["output_text"] = resp.output_text
    current_task["exit_code"] = resp.exit_code

    if resp.status in (ProviderStatus.FAILED, ProviderStatus.TIMEOUT):
        error_msg = resp.error_message or "Task execution failed"
        current_task["status"] = "failed"
        current_task["error_message"] = error_msg
        return {
            "tasks": tasks,
            "usage_records": usage_list,
            "status": "failed",
            "error": error_msg,
        }

    return {
        "tasks": tasks,
        "usage_records": usage_list,
        "status": "running",
    }


async def verify_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    idx = state.get("current_task_index", 0)
    current_task = tasks[idx]
    project_id = state.get("project_id", "default")
    project_work_dir = (settings.ARTIFACT_STORAGE_PATH / project_id).resolve()

    logger.info("Running deterministic verification for task: %s", current_task["title"])
    report = await VerificationEngine.verify_task(project_work_dir)

    results = list(state.get("verification_results", []))
    results.append(
        {
            "task_id": current_task["task_id"],
            "report": report.model_dump(),
        }
    )

    return {"verification_results": results}


async def artifact_node(state: OrchestrationState) -> dict[str, Any]:
    tasks = state.get("tasks", [])
    idx = state.get("current_task_index", 0)
    current_task = tasks[idx]
    project_id = state.get("project_id", "default")
    project_work_dir = (settings.ARTIFACT_STORAGE_PATH / project_id).resolve()

    # Register output artifacts
    artifacts = list(state.get("artifacts", []))
    output_text = current_task.get("output_text", "")

    for filename in current_task.get("expected_output_artifacts", []):
        file_path = project_work_dir / filename
        if output_text and not file_path.exists():
            file_path.write_text(output_text, encoding="utf-8")

        artifacts.append(
            {
                "task_id": current_task["task_id"],
                "name": filename,
                "file_path": f"{project_id}/{filename}",
                "size_bytes": file_path.stat().st_size
                if file_path.exists()
                else len(output_text.encode()),
            }
        )

    completed_ids = list(state.get("completed_task_ids", []))
    completed_ids.append(current_task["task_id"])

    return {
        "artifacts": artifacts,
        "completed_task_ids": completed_ids,
        "current_task_index": idx + 1,
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


def route_after_artifact(state: OrchestrationState) -> Literal["approval_check", "complete"]:
    tasks = state.get("tasks", [])
    idx = state.get("current_task_index", 0)
    if idx < len(tasks):
        return "approval_check"
    return "complete"


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
        },
    )

    workflow.add_edge("complete", END)

    return workflow.compile()
