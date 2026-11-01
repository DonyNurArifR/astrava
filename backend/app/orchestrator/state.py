from typing import Any, TypedDict


class OrchestrationState(TypedDict, total=False):
    execution_id: str
    project_id: str
    objective: str
    studio_type: str
    plan: dict[str, Any]
    agent_snapshots: dict[str, dict[str, Any]]
    current_task_index: int
    current_ready_task_ids: list[str]
    tasks: list[dict[str, Any]]
    completed_task_ids: list[str]
    failed_task_ids: list[str]
    active_approval_id: str | None
    is_paused: bool
    status: str
    verification_results: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    usage_records: list[dict[str, Any]]
    task_db_ids: dict[str, str]
    synced_usage_count: int
    error: str | None
