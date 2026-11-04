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
    error_message: str | None
    # Execution budget governance (BudgetGovernor)
    budget_exhausted: bool
    replanning: bool
    replan_count: int
    # Project Intelligence & Memory (V1.3 M1.3-5)
    retrieved_memories: list[dict[str, Any]]
    retrieved_artifacts: list[dict[str, Any]]
    retrieval_context: str
    retrieval_metadata: dict[str, Any]
    retrieval_error: str | None
    knowledge_candidates: list[dict[str, Any]]
    ingestion_status: str
    ingested_memory_ids: list[str]
    ingestion_errors: list[str]
