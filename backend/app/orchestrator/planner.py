import json
import logging
import re
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.models.project import StudioType
from app.models.task import ExecutorType, RiskLevel
from app.providers.base import BaseProvider, ProviderRequest, ProviderStatus
from app.providers.factory import ProviderFactory
from app.schemas.intelligence import ObjectiveUnderstandingResponse
from app.workspace.path_security import PathContainmentError, safe_join

logger = logging.getLogger("astrava.orchestrator.planner")


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

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


class PlannedTask(BaseModel):
    task_id: str
    title: str
    description: str
    assigned_agent_slug: str = "product-manager"
    required_capabilities: list[str] = Field(default_factory=list)
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

    @field_validator("expected_output_artifacts")
    @classmethod
    def _validate_output_artifact_names(cls, names: list[str]) -> list[str]:
        """Planner/LLM output names must stay inside the task's work directory.

        Checked with the same rules as safe_join against a dummy absolute root, so nothing
        touches the filesystem here. An unsafe name raises, and the planner falls back to the
        deterministic template plan.
        """
        dummy_root = Path("/astrava-planner-validation-root")
        for name in names:
            try:
                safe_join(dummy_root, name)
            except PathContainmentError as exc:
                raise ValueError(f"Unsafe expected output artifact name: {exc}") from exc
        return names


class CapabilityMatcher:
    """Matches tasks to registered agent personas based on declared capability tags."""

    @classmethod
    def match_agent(
        cls,
        required_capabilities: list[str],
        available_agents: list[Any],
        studio_type: StudioType | str = StudioType.SAAS,
        fallback_slug: str = "developer",
    ) -> str:
        if not required_capabilities or not available_agents:
            return fallback_slug

        studio_val = (
            studio_type.value if isinstance(studio_type, StudioType) else str(studio_type).lower()
        )
        req_set = {c.lower().strip() for c in required_capabilities}

        best_slug = fallback_slug
        best_score = -1

        for ag in available_agents:
            if isinstance(ag, dict):
                ag_studio = ag.get("studio_type")
                ag_slug = ag.get("slug", "")
                ag_caps = ag.get("capabilities", [])
                ag_enabled = ag.get("is_enabled", True)
            else:
                ag_studio = getattr(ag, "studio_type", None)
                ag_slug = getattr(ag, "slug", "")
                ag_caps = getattr(ag, "capabilities", []) or []
                ag_enabled = getattr(ag, "is_enabled", True)

            if not ag_enabled:
                continue

            curr_studio_val = (
                ag_studio.value if isinstance(ag_studio, StudioType) else str(ag_studio).lower()
            )
            studio_match_bonus = 2 if curr_studio_val == studio_val else 0

            ag_caps_set = {str(c).lower().strip() for c in ag_caps}
            overlap = len(req_set & ag_caps_set)

            score = overlap * 10 + studio_match_bonus
            if score > best_score and overlap > 0:
                best_score = score
                best_slug = ag_slug

        return best_slug


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
    retrieval_context: str | None = None


class PlannerService:
    @staticmethod
    def validate_and_compute_stages(tasks: list[PlannedTask]) -> list[list[str]]:
        """
        Validates that the task dependencies form a valid Directed Acyclic Graph (DAG)
        and computes execution stages (parallel waves of independent tasks).
        Raises ValueError if circular dependency or unknown dependency is detected.
        """
        task_ids: set[str] = set()
        for t in tasks:
            if t.task_id in task_ids:
                raise ValueError(f"Duplicate task identifier detected: '{t.task_id}'")
            task_ids.add(t.task_id)

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
        retrieval_context: str | None = None,
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

        if retrieval_context:
            strategy_summary = f"{strategy_summary} [Informed by persistent project memory]"

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
            retrieval_context=retrieval_context,
        )


class GoalDecomposer:
    """Decomposes high-level objectives into dynamic DAG execution plans using Claude Haiku."""

    @classmethod
    async def decompose_goal(
        cls,
        objective: str,
        project_id: str,
        studio_type: StudioType = StudioType.SAAS,
        retrieval_context: str | None = None,
        provider: BaseProvider | None = None,
    ) -> StructuredPlan:
        # If in test mode and no provider explicitly supplied, return deterministic template
        if settings.APP_ENV == "test" and provider is None:
            return PlannerService.generate_plan(
                project_id=project_id,
                objective=objective,
                studio_type=studio_type,
                retrieval_context=retrieval_context,
            )

        prompt = f"""You are the ASTRAVA Chief Systems Architect & Autonomous Goal Decomposer.
Decompose the following user objective into a structured execution DAG consisting of 3 to 8 discrete tasks.

## User Objective:
{objective}

## Studio Domain:
{studio_type.value}

## Project Context / Active Architectural Constraints:
{retrieval_context or "No prior project memory specified."}

## Instructions:
1. Break down the objective into modular, sequential or parallel tasks.
2. Assign each task to the most appropriate agent slug:
   - For SaaS: product-manager, solution-architect, lead-developer, frontend-engineer, qa-engineer, security-specialist
   - For Media: content-strategist, audience-analyst, scriptwriter, storyboard-artist, seo-specialist, production-assistant, content-quality-reviewer
3. Define explicit task dependencies (DAG without cycles). Independent tasks can run in parallel.
4. Specify risk_level: "low", "medium", or "high". Set requires_approval: true for high-risk operations (e.g. destructive actions, deployments, final release).
5. Specify expected output artifact filenames and acceptance criteria for each task.

Respond with ONLY valid JSON adhering to the following structure:
{{
  "strategy_summary": "High-level strategy description...",
  "estimated_cost_usd": 0.05,
  "tasks": [
    {{
      "task_id": "task-1-slug",
      "title": "Task Title",
      "description": "Task details...",
      "assigned_agent_slug": "solution-architect",
      "risk_level": "low",
      "requires_approval": false,
      "priority": 1,
      "dependencies": [],
      "expected_output_artifacts": ["architecture_spec.md"],
      "acceptance_criteria": ["Specifies component boundaries", "Defines database schema"],
      "verification_criteria": ["non_empty_file"]
    }}
  ]
}}
"""
        eval_provider = provider or ProviderFactory.get_provider("claude_code")
        req = ProviderRequest(
            prompt=prompt,
            system_prompt="You are a strict software architect. Output only JSON.",
            timeout_seconds=45,
            model="claude-haiku-5-5",
        )

        try:
            resp = await eval_provider.execute(req)
            if resp.status == ProviderStatus.SUCCESS and resp.output_text.strip():
                parsed = _extract_json_dict(resp.output_text)
                if (
                    parsed
                    and "tasks" in parsed
                    and isinstance(parsed["tasks"], list)
                    and parsed["tasks"]
                ):
                    planned_tasks: list[PlannedTask] = []
                    for t_dict in parsed["tasks"]:
                        req_caps = list(t_dict.get("required_capabilities", []))
                        assigned_slug = str(t_dict.get("assigned_agent_slug", "")).strip()
                        if req_caps:
                            from app.services.agent_service import DEFAULT_AGENTS

                            assigned_slug = CapabilityMatcher.match_agent(
                                required_capabilities=req_caps,
                                available_agents=DEFAULT_AGENTS,
                                studio_type=studio_type,
                                fallback_slug=assigned_slug or "developer",
                            )
                        elif not assigned_slug:
                            assigned_slug = "developer"

                        planned_tasks.append(
                            PlannedTask(
                                task_id=str(t_dict.get("task_id", f"task-{uuid.uuid4().hex[:6]}")),
                                title=str(t_dict.get("title", "Untitled Task")),
                                description=str(t_dict.get("description", "")),
                                assigned_agent_slug=assigned_slug,
                                required_capabilities=req_caps,
                                risk_level=RiskLevel(t_dict.get("risk_level", "low").lower())
                                if t_dict.get("risk_level", "low").lower()
                                in ("low", "medium", "high")
                                else RiskLevel.LOW,
                                requires_approval=bool(t_dict.get("requires_approval", False)),
                                priority=int(t_dict.get("priority", 1)),
                                dependencies=list(t_dict.get("dependencies", [])),
                                expected_output_artifacts=list(
                                    t_dict.get("expected_output_artifacts", [])
                                ),
                                acceptance_criteria=list(t_dict.get("acceptance_criteria", [])),
                                verification_criteria=list(
                                    t_dict.get("verification_criteria", ["non_empty_file"])
                                ),
                            )
                        )
                    # Validate DAG acyclicity using Kahn's algorithm
                    stages = PlannerService.validate_and_compute_stages(planned_tasks)
                    selected_agents = list({t.assigned_agent_slug for t in planned_tasks})
                    return StructuredPlan(
                        project_id=project_id,
                        objective=objective,
                        studio_type=studio_type,
                        strategy_summary=str(
                            parsed.get("strategy_summary", f"Dynamic plan for {objective}")
                        ),
                        estimated_cost_usd=float(
                            parsed.get("estimated_cost_usd", 0.015 * len(planned_tasks))
                        ),
                        selected_agent_slugs=selected_agents,
                        tasks=planned_tasks,
                        execution_stages=stages,
                        is_valid_dag=True,
                        retrieval_context=retrieval_context,
                    )
        except Exception as e:
            logger.warning(
                "GoalDecomposer dynamic decomposition failed, falling back to template: %s", e
            )

        # Fallback to deterministic plan
        return PlannerService.generate_plan(
            project_id=project_id,
            objective=objective,
            studio_type=studio_type,
            retrieval_context=retrieval_context,
        )


class DAGModifier:
    """Modifies an in-flight execution DAG dynamically while strictly preserving completed tasks."""

    @classmethod
    def modify_dag(
        cls,
        current_tasks: list[dict[str, Any]],
        completed_task_ids: list[str],
        failed_task_ids: list[str],
        new_or_modified_tasks: list[dict[str, Any]] | list[PlannedTask],
        replace_unexecuted: bool = True,
    ) -> list[dict[str, Any]]:
        completed_set = set(completed_task_ids)
        current_map = {t["task_id"]: dict(t) for t in current_tasks}

        # 1. Enforce invariant: completed tasks are immutable
        for cid in completed_set:
            if cid not in current_map:
                raise ValueError(f"Completed task '{cid}' missing from current task set")

        # 2. Integrate replacements or new tasks
        modified_dict_list: list[dict[str, Any]] = []
        if isinstance(new_or_modified_tasks, list):
            for item in new_or_modified_tasks:
                if isinstance(item, PlannedTask):
                    modified_dict_list.append(item.model_dump())
                elif isinstance(item, dict):
                    modified_dict_list.append(dict(item))

        # Build new task map starting with immutable completed tasks
        final_map: dict[str, dict[str, Any]] = {}
        for cid in completed_task_ids:
            task_copy = dict(current_map[cid])
            task_copy["status"] = "completed"
            final_map[cid] = task_copy

        # Merge unexecuted / modified tasks
        for t in modified_dict_list:
            tid = t["task_id"]
            if tid in completed_set:
                # Disallow modifying completed task state or dependencies
                continue
            if t.get("status") not in ("completed", "failed"):
                t["status"] = "pending"
            final_map[tid] = t

        # If not replacing all unexecuted tasks, retain any uncompleted current tasks not explicitly replaced
        if not replace_unexecuted:
            modified_ids = {t["task_id"] for t in modified_dict_list}
            for tid, t in current_map.items():
                if tid not in completed_set and tid not in modified_ids:
                    final_map[tid] = t

        # 3. Kahn's validation: convert all final tasks to PlannedTask and validate acyclicity
        planned_objects: list[PlannedTask] = []
        for tid, t in final_map.items():
            planned_objects.append(
                PlannedTask(
                    task_id=tid,
                    title=t.get("title", "Task"),
                    description=t.get("description", ""),
                    assigned_agent_slug=t.get("assigned_agent_slug", "lead-developer"),
                    risk_level=RiskLevel(t.get("risk_level", "low").lower())
                    if t.get("risk_level", "low").lower() in ("low", "medium", "high")
                    else RiskLevel.LOW,
                    requires_approval=bool(t.get("requires_approval", False)),
                    priority=int(t.get("priority", 1)),
                    dependencies=list(t.get("dependencies", [])),
                    expected_output_artifacts=list(t.get("expected_output_artifacts", [])),
                    acceptance_criteria=list(t.get("acceptance_criteria", [])),
                    verification_criteria=list(t.get("verification_criteria", ["non_empty_file"])),
                )
            )

        # validate_and_compute_stages will raise ValueError on cycles or missing dependencies
        PlannerService.validate_and_compute_stages(planned_objects)

        return list(final_map.values())
