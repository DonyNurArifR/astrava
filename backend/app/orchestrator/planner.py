import uuid
from collections import defaultdict, deque
from typing import Any

from pydantic import BaseModel, Field

from app.models.project import StudioType
from app.models.task import ExecutorType, RiskLevel
from app.schemas.intelligence import ObjectiveUnderstandingResponse


class PlannedTask(BaseModel):
    task_id: str
    title: str
    description: str
    assigned_agent_slug: str = "product-manager"
    executor_type: ExecutorType = ExecutorType.CLAUDE_CODE
    assigned_model: str = "claude-haiku-5-5"
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    priority: int = 1
    dependencies: list[str] = Field(default_factory=list)
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_output_artifacts: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    verification_criteria: list[str] = Field(default_factory=list)


class StructuredPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    objective: str
    studio_type: StudioType = StudioType.SAAS
    strategy_summary: str
    estimated_cost_usd: float = 0.05
    selected_agent_slugs: list[str] = Field(default_factory=list)
    tasks: list[PlannedTask] = Field(default_factory=list)
    execution_stages: list[list[str]] = Field(default_factory=list)
    is_valid_dag: bool = True


class PlannerService:
    @staticmethod
    def validate_and_compute_stages(tasks: list[PlannedTask]) -> list[list[str]]:
        """
        Validates that the task dependencies form a valid Directed Acyclic Graph (DAG)
        and computes execution stages (parallel waves of independent tasks).
        Raises ValueError if circular dependency or unknown dependency is detected.
        """
        task_ids = {t.task_id for t in tasks}
        in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
        dependents: dict[str, list[str]] = defaultdict(list)

        # Validate existence of dependencies and build graph
        for t in tasks:
            for dep in t.dependencies:
                if dep not in task_ids:
                    raise ValueError(f"Task '{t.task_id}' depends on non-existent task '{dep}'")
                dependents[dep].append(t.task_id)
                in_degree[t.task_id] += 1

        # Kahn's algorithm by layers (parallel execution stages)
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        stages: list[list[str]] = []
        processed_count = 0

        while queue:
            current_stage = list(queue)
            stages.append(current_stage)
            queue.clear()
            next_stage_candidates: list[str] = []

            for tid in current_stage:
                processed_count += 1
                for dep_task_id in dependents[tid]:
                    in_degree[dep_task_id] -= 1
                    if in_degree[dep_task_id] == 0:
                        next_stage_candidates.append(dep_task_id)

            queue.extend(next_stage_candidates)

        if processed_count != len(tasks):
            # Find remaining cycles
            unprocessed = [tid for tid, deg in in_degree.items() if deg > 0]
            raise ValueError(
                f"Circular dependency detected involving tasks: {', '.join(unprocessed)}"
            )

        return stages

    @classmethod
    def generate_plan(
        cls,
        project_id: str,
        objective: str,
        studio_type: StudioType = StudioType.SAAS,
        understanding: ObjectiveUnderstandingResponse | None = None,
    ) -> StructuredPlan:
        """
        Generates a validated structured execution plan based on the objective,
        studio type, and optional semantic understanding.
        Constructs a dependency-aware DAG with concurrent stages and assigned agents.
        """
        if studio_type == StudioType.SAAS:
            tasks = [
                # Stage 1: Concurrent Research & Competitor Analysis
                PlannedTask(
                    task_id="task-1-market-research",
                    title="Conduct Product & Market Opportunity Research",
                    description=f"Investigate target personas, market dynamics, and acute pain points for: {objective}",
                    assigned_agent_slug="product-researcher",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=1,
                    dependencies=[],
                    expected_output_artifacts=["research_findings.md"],
                    acceptance_criteria=[
                        "Identifies user personas and target market segments",
                        "Validates core customer pain points",
                        "Specifies market opportunity boundaries",
                    ],
                    verification_criteria=["non_empty_file", "has_persona_sections"],
                ),
                PlannedTask(
                    task_id="task-2-competitor-analysis",
                    title="Execute Competitor Benchmarking & Gap Analysis",
                    description=f"Analyze existing market competitors and differentiate capabilities for: {objective}",
                    assigned_agent_slug="competitor-analyst",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=1,
                    dependencies=[],
                    expected_output_artifacts=["competitor_matrix.md"],
                    acceptance_criteria=[
                        "Profiles minimum 2 market alternatives",
                        "Constructs feature parity comparison matrix",
                        "Defines unique defensible advantages",
                    ],
                    verification_criteria=["non_empty_file", "has_matrix_table"],
                ),
                # Stage 2: Strategic Synthesis
                PlannedTask(
                    task_id="task-3-product-strategy",
                    title="Formulate Product Strategy & MVP Scope",
                    description=f"Synthesize research and competitive analysis into a strategic roadmap for: {objective}",
                    assigned_agent_slug="product-strategist",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=2,
                    dependencies=["task-1-market-research", "task-2-competitor-analysis"],
                    expected_output_artifacts=["product_strategy.md"],
                    acceptance_criteria=[
                        "Defines sharp positioning statement",
                        "Prioritizes MVP feature scope",
                        "Establishes phased delivery roadmap",
                    ],
                    verification_criteria=["non_empty_file"],
                ),
                # Stage 3: Product Requirements Document (PRD)
                PlannedTask(
                    task_id="task-4-prd",
                    title="Generate Product Requirements Document (PRD)",
                    description=f"Formulate structured functional and non-functional requirements for: {objective}",
                    assigned_agent_slug="product-manager",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=3,
                    dependencies=["task-3-product-strategy"],
                    expected_output_artifacts=["prd.md"],
                    acceptance_criteria=[
                        "Defines user stories and acceptance criteria",
                        "Specifies non-functional performance and security constraints",
                        "Details data entity requirements",
                    ],
                    verification_criteria=["non_empty_file", "has_acceptance_criteria"],
                ),
                # Stage 4: Technical Architecture
                PlannedTask(
                    task_id="task-5-architecture",
                    title="Design Technical Architecture & System Contracts",
                    description=f"Design modular system components, data schemas, and API contracts for: {objective}",
                    assigned_agent_slug="solution-architect",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=4,
                    dependencies=["task-4-prd"],
                    expected_output_artifacts=["architecture.md"],
                    acceptance_criteria=[
                        "Defines relational entity schema",
                        "Specifies API endpoints and payloads",
                        "Establishes security and authentication boundaries",
                    ],
                    verification_criteria=["non_empty_file", "has_api_endpoints"],
                ),
                # Stage 5: Core Software Implementation
                PlannedTask(
                    task_id="task-6-implementation",
                    title="Implement Core Software Modules",
                    description=f"Implement application models, endpoints, and domain logic for: {objective}",
                    assigned_agent_slug="developer",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=False,
                    priority=5,
                    dependencies=["task-5-architecture"],
                    expected_output_artifacts=["implementation_diff.patch"],
                    acceptance_criteria=[
                        "Adheres to modular software design",
                        "Implements schemas, models, and routes",
                        "Passes static syntax checks",
                    ],
                    verification_criteria=["non_empty_file"],
                ),
                # Stage 6: Quality Assurance & Verification
                PlannedTask(
                    task_id="task-7-qa",
                    title="Run Quality Assurance & Deterministic Verification",
                    description="Execute deterministic verification suite, test coverage inspection, and defect audit.",
                    assigned_agent_slug="qa-engineer",
                    executor_type=ExecutorType.DETERMINISTIC,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=6,
                    dependencies=["task-6-implementation"],
                    expected_output_artifacts=["qa_report.json"],
                    acceptance_criteria=[
                        "Deterministic tests pass cleanly",
                        "Zero regressions detected",
                    ],
                    verification_criteria=["non_empty_file", "valid_json"],
                ),
            ]
            strategy_summary = (
                f"SaaS Studio Multi-Agent Workflow: Parallel market & competitor discovery, strategic positioning, "
                f"PRD authoring, architectural modeling, modular implementation, and deterministic verification for '{objective}'."
            )
        else:
            tasks = [
                # Stage 1: Concurrent Content Research & Audience Profiling
                PlannedTask(
                    task_id="task-1-content-research",
                    title="Conduct Content & Benchmark Research",
                    description=f"Research topic trends, narrative hooks, and benchmark high-retention references for: {objective}",
                    assigned_agent_slug="content-researcher",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=1,
                    dependencies=[],
                    expected_output_artifacts=["content_research.md"],
                    acceptance_criteria=[
                        "Identifies high-impact topic angles",
                        "Cites benchmark references and hook concepts",
                    ],
                    verification_criteria=["non_empty_file"],
                ),
                PlannedTask(
                    task_id="task-2-audience-analysis",
                    title="Analyze Audience Personas & Retention Triggers",
                    description=f"Profile viewer demographics, emotional resonance triggers, and tone guidelines for: {objective}",
                    assigned_agent_slug="audience-analyst",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=1,
                    dependencies=[],
                    expected_output_artifacts=["audience_persona.md"],
                    acceptance_criteria=[
                        "Defines demographic and psychographic profile",
                        "Specifies retention hooks and tone boundaries",
                    ],
                    verification_criteria=["non_empty_file"],
                ),
                # Stage 2: Content Strategy
                PlannedTask(
                    task_id="task-3-content-strategy",
                    title="Develop Content Strategy & Multi-Channel Narrative",
                    description=f"Structure narrative arc, key hooks, and multi-channel distribution pillars for: {objective}",
                    assigned_agent_slug="content-strategist",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=2,
                    dependencies=["task-1-content-research", "task-2-audience-analysis"],
                    expected_output_artifacts=["content_strategy.md"],
                    acceptance_criteria=[
                        "Outlines 3-act narrative structure",
                        "Defines recurring visual and verbal themes",
                    ],
                    verification_criteria=["non_empty_file"],
                ),
                # Stage 3: Scriptwriting
                PlannedTask(
                    task_id="task-4-scriptwriting",
                    title="Draft Production Script & Narration",
                    description=f"Write complete scene-by-scene script with timestamps, dialogue, audio cues, and voiceover for: {objective}",
                    assigned_agent_slug="scriptwriter",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=3,
                    dependencies=["task-3-content-strategy"],
                    expected_output_artifacts=["script.md"],
                    acceptance_criteria=[
                        "Detailed scene-by-scene script with timing markers",
                        "Audio, sound effects, and voiceover cues specified",
                    ],
                    verification_criteria=["non_empty_file", "has_timestamps"],
                ),
                # Stage 4: Concurrent Storyboard Design & SEO Metadata Optimization
                PlannedTask(
                    task_id="task-5-storyboard",
                    title="Design Visual Storyboard & Thumbnail Concepts",
                    description="Specify visual shot framing, camera motion, on-screen text graphics, and thumbnail variations.",
                    assigned_agent_slug="storyboard-designer",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=4,
                    dependencies=["task-4-scriptwriting"],
                    expected_output_artifacts=["storyboard.json"],
                    acceptance_criteria=[
                        "Scene framing and shot composition details",
                        "High-CTR thumbnail concept descriptions",
                    ],
                    verification_criteria=["non_empty_file", "valid_json"],
                ),
                PlannedTask(
                    task_id="task-6-seo-optimization",
                    title="Optimize Video SEO, Tags & Discoverability Metadata",
                    description="Generate SEO-optimized title variants, keywords, chapters, and description copy.",
                    assigned_agent_slug="seo-analyst",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=4,
                    dependencies=["task-4-scriptwriting"],
                    expected_output_artifacts=["seo_metadata.json"],
                    acceptance_criteria=[
                        "Top 3 title variants evaluated for CTR",
                        "Keyword tags and timestamped chapter markers",
                    ],
                    verification_criteria=["non_empty_file", "valid_json"],
                ),
                # Stage 5: Production Assistant Assembly
                PlannedTask(
                    task_id="task-7-production-manifest",
                    title="Compile Production Manifest & Technical Specs",
                    description="Compile technical specs, asset requirements, b-roll checklist, and delivery preflight.",
                    assigned_agent_slug="production-assistant",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    priority=5,
                    dependencies=["task-5-storyboard"],
                    expected_output_artifacts=["production_manifest.json"],
                    acceptance_criteria=[
                        "Complete technical asset checklist",
                        "Video resolution, framerate, and audio loudness specs",
                    ],
                    verification_criteria=["non_empty_file", "valid_json"],
                ),
                # Stage 6: Content Quality Review & Human Approval Gate
                PlannedTask(
                    task_id="task-8-quality-review",
                    title="Editorial Quality Review & Release Authorization",
                    description="Audit narrative quality, tone alignment, and publish readiness before distribution.",
                    assigned_agent_slug="content-quality-reviewer",
                    executor_type=ExecutorType.CLAUDE_CODE,
                    assigned_model="claude-haiku-5-5",
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=True,  # Mandatory human approval gate before release
                    priority=6,
                    dependencies=["task-6-seo-optimization", "task-7-production-manifest"],
                    expected_output_artifacts=["quality_review.json"],
                    acceptance_criteria=[
                        "Editorial consistency evaluation",
                        "Human approval required before public release",
                    ],
                    verification_criteria=["non_empty_file", "valid_json"],
                ),
            ]
            strategy_summary = (
                f"Media Studio Multi-Agent Workflow: Parallel content & audience research, narrative strategy, "
                f"scriptwriting, parallel storyboard & SEO optimization, production packaging, and editorial approval for '{objective}'."
            )

        # Validate DAG and compute parallel execution stages
        stages = cls.validate_and_compute_stages(tasks)
        selected_agents = list({t.assigned_agent_slug for t in tasks})

        return StructuredPlan(
            project_id=project_id,
            objective=objective,
            studio_type=studio_type,
            strategy_summary=strategy_summary,
            estimated_cost_usd=0.015 * len(tasks),
            selected_agent_slugs=selected_agents,
            tasks=tasks,
            execution_stages=stages,
            is_valid_dag=True,
        )
