import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalStatus
from app.models.artifact import ArtifactType
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
from app.services.approval_service import ApprovalService
from app.services.artifact_service import ArtifactService
from app.services.task_service import TaskService
from app.services.usage_service import UsageService
from app.services.workflow_service import WorkflowService

logger = logging.getLogger("astrava.orchestrator.runner")


class OrchestrationRunner:
    @staticmethod
    async def start_pipeline(
        db: AsyncSession,
        project_id: uuid.UUID,
        objective: str,
        studio_type: str = "saas",
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
        exec_data = ExecutionCreate(
            workflow_id=workflow.id,
            project_id=project_id,
            initial_state={
                "objective": objective,
                "studio_type": studio_type,
            },
        )
        execution = await WorkflowService.create_execution(db, exec_data)
        await WorkflowService.update_execution_status(db, execution.id, ExecutionStatus.RUNNING)
        await WorkflowService.record_event(
            db,
            execution.id,
            "pipeline_started",
            {"objective": objective, "studio_type": studio_type},
        )

        # 3. Setup LangGraph initial state
        initial_state: OrchestrationState = {
            "execution_id": str(execution.id),
            "project_id": str(project_id),
            "objective": objective,
            "studio_type": studio_type,
            "tasks": [],
            "completed_task_ids": [],
            "current_task_index": 0,
            "is_paused": False,
            "status": "running",
            "verification_results": [],
            "artifacts": [],
            "usage_records": [],
        }

        # 4. Run LangGraph graph
        graph = build_orchestrator_graph()
        final_state = await graph.ainvoke(initial_state)

        # 5. Synchronize final state back to Database
        await OrchestrationRunner._sync_state_to_db(db, execution.id, project_id, final_state)
        # Reload execution with events loaded
        reloaded = await WorkflowService.get_execution(db, execution.id)
        return reloaded or execution

    @staticmethod
    async def resume_pipeline(
        db: AsyncSession,
        execution_id: uuid.UUID,
        decision_req: ApprovalDecisionRequest,
    ) -> WorkflowExecution:
        execution = await WorkflowService.get_execution(db, execution_id)
        if not execution:
            raise ValueError(f"Execution {execution_id} not found")

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
            await WorkflowService.update_execution_status(
                db,
                execution_id,
                ExecutionStatus.CANCELLED,
                error_message=f"Operator rejected: {decision_req.reason}",
            )
            await WorkflowService.record_event(
                db, execution_id, "pipeline_rejected", {"reason": decision_req.reason}
            )
            reloaded = await WorkflowService.get_execution(db, execution_id)
            return reloaded or execution

        # Approved -> Mark current task as approved in state
        tasks = state.get("tasks", [])
        idx = state.get("current_task_index", 0)
        if idx < len(tasks):
            tasks[idx]["approved"] = True
            tasks[idx]["requires_approval"] = False
        state["tasks"] = tasks
        state["status"] = "running"
        state["active_approval_id"] = None

        await WorkflowService.update_execution_status(
            db, execution_id, ExecutionStatus.RUNNING, state_data=state
        )
        await WorkflowService.record_event(
            db, execution_id, "pipeline_resumed", {"approved_task": tasks[idx]["title"]}
        )

        # Resume LangGraph execution from approved task
        graph = build_orchestrator_graph()
        final_state = await graph.ainvoke(state)

        await OrchestrationRunner._sync_state_to_db(
            db, execution_id, execution.project_id, final_state
        )
        reloaded = await WorkflowService.get_execution(db, execution_id)
        return reloaded or execution

    @staticmethod
    async def _sync_state_to_db(
        db: AsyncSession,
        execution_id: uuid.UUID,
        project_id: uuid.UUID,
        state: dict[str, Any],
    ) -> None:
        state_status = state.get("status", "running")

        # Sync tasks to DB
        tasks = state.get("tasks", [])
        for t in tasks:
            t_obj = await TaskService.create(
                db,
                TaskCreate(
                    project_id=project_id,
                    title=t.get("title", ""),
                    description=t.get("description", ""),
                    executor_type=t.get("executor_type", "claude_code"),
                    assigned_model=t.get("assigned_model", "claude-haiku-5-5"),
                    risk_level=t.get("risk_level", "low"),
                    priority=t.get("priority", 1),
                    dependency_ids=t.get("dependencies", []),
                ),
            )
            if t.get("task_id") in state.get("completed_task_ids", []):
                await TaskService.update(
                    db,
                    t_obj.id,
                    TaskUpdate(
                        status=TaskStatus.COMPLETED,
                        output_data={"result": t.get("output_text", "")},
                    ),
                )

        # Sync artifacts to DB
        for art in state.get("artifacts", []):
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
                )
            except Exception as e:
                logger.warning("Could not sync artifact %s: %s", art, e)

        # Sync usage records to DB
        for usage in state.get("usage_records", []):
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

        # Handle pause for approval if waiting
        current_step = state.get("current_task_index", 0)
        if state_status == "waiting_approval":
            active_task_id = state.get("active_approval_id")
            current_idx = state.get("current_task_index", 0)
            task_info = tasks[current_idx] if current_idx < len(tasks) else {}
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
        else:
            await WorkflowService.update_execution_status(
                db,
                execution_id,
                ExecutionStatus.RUNNING,
                state_data=state,
                current_step=current_step,
            )
