import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.models.project import StudioType
from app.models.task import ExecutorType, RiskLevel


class PlannedTask(BaseModel):
    task_id: str
    title: str
    description: str
    executor_type: ExecutorType = ExecutorType.CLAUDE_CODE
    assigned_model: str = "claude-haiku-5-5"
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    priority: int = 1
    dependencies: list[str] = Field(default_factory=list)
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_output_artifacts: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


class StructuredPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    objective: str
    studio_type: StudioType = StudioType.SAAS
    strategy_summary: str
    estimated_cost_usd: float = 0.05
    tasks: list[PlannedTask] = Field(default_factory=list)


class PlannerService:
    @staticmethod
    def generate_plan(
        project_id: str,
        objective: str,
        studio_type: StudioType = StudioType.SAAS,
    ) -> StructuredPlan:
        """
        Generates a validated structured execution plan based on the project's studio type and objective.
        Ensures strict task schema validation before any execution occurs.
        """
        if studio_type == StudioType.SAAS:
            tasks = [
                PlannedTask(
                    task_id="task-1-prd",
                    title="Generate Product Requirements Document (PRD)",
                    description=f"Analyze requirements and generate a comprehensive enterprise PRD for: {objective}",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=1,
                    dependencies=[],
                    expected_output_artifacts=["prd.md"],
                    acceptance_criteria=[
                        "Identifies user personas and target market",
                        "Defines functional and non-functional requirements",
                        "Specifies data architecture and acceptance metrics",
                    ],
                ),
                PlannedTask(
                    task_id="task-2-arch",
                    title="Design Technical Architecture & Schema",
                    description=f"Design modular system architecture, database schema, and API contracts for: {objective}",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=2,
                    dependencies=["task-1-prd"],
                    expected_output_artifacts=["architecture.md"],
                    acceptance_criteria=[
                        "Relational entity relationships specified",
                        "API routes and response schemas defined",
                        "Security boundaries and authentication defined",
                    ],
                ),
                PlannedTask(
                    task_id="task-3-implementation",
                    title="Implement Core Software Modules",
                    description=f"Implement software logic, backend models, and endpoints for: {objective}",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=False,
                    priority=3,
                    dependencies=["task-2-arch"],
                    expected_output_artifacts=["implementation_diff.patch"],
                    acceptance_criteria=[
                        "Code adheres to clean modular structure",
                        "Unit tests implemented and passing",
                        "Linting checks pass with zero errors",
                    ],
                ),
                PlannedTask(
                    task_id="task-4-qa",
                    title="Run Quality Assurance & Verification",
                    description="Execute deterministic test suite, linter, typecheck, and build validation.",
                    executor_type=ExecutorType.DETERMINISTIC,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=4,
                    dependencies=["task-3-implementation"],
                    expected_output_artifacts=["qa_report.json"],
                    acceptance_criteria=[
                        "Deterministic tests pass cleanly",
                        "Zero regressions detected",
                    ],
                ),
            ]
            strategy_summary = (
                f"SaaS Studio Execution Pipeline: Transforming '{objective}' through PRD formulation, "
                "technical architectural design, verified software implementation, and deterministic QA."
            )
        else:
            tasks = [
                PlannedTask(
                    task_id="task-1-content-strategy",
                    title="Formulate Content Strategy & Audience Persona",
                    description=f"Research target audience, tone of voice, and content hooks for: {objective}",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=1,
                    dependencies=[],
                    expected_output_artifacts=["content_strategy.md"],
                    acceptance_criteria=[
                        "Identifies high-impact audience hooks",
                        "Outlines narrative structure and tone guidelines",
                    ],
                ),
                PlannedTask(
                    task_id="task-2-scriptwriting",
                    title="Draft Production Script & Visual Storyboard",
                    description=f"Write script with timestamps, dialogue, audio cues, and visual asset directions for: {objective}",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=2,
                    dependencies=["task-1-content-strategy"],
                    expected_output_artifacts=["script.md", "storyboard.json"],
                    acceptance_criteria=[
                        "Complete scene-by-scene script",
                        "Visual descriptions for thumbnail and frame generation",
                    ],
                ),
                PlannedTask(
                    task_id="task-3-publishing-prep",
                    title="Prepare Metadata, SEO & Publishing Manifest",
                    description="Generate SEO title, tags, description, chapters, and social media distribution copy.",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=True,  # Publishing prep requires approval before release
                    priority=3,
                    dependencies=["task-2-scriptwriting"],
                    expected_output_artifacts=["publishing_manifest.json"],
                    acceptance_criteria=[
                        "SEO optimized title variants",
                        "Human approval required before public release",
                    ],
                ),
            ]
            strategy_summary = (
                f"Media Studio Execution Pipeline: Developing content strategy, scene-by-scene script, "
                f"visual storyboards, and publishing metadata for '{objective}'."
            )

        return StructuredPlan(
            project_id=project_id,
            objective=objective,
            studio_type=studio_type,
            strategy_summary=strategy_summary,
            estimated_cost_usd=0.015 * len(tasks),
            tasks=tasks,
        )
