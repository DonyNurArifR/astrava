import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.project import StudioType
from app.schemas.agent import AgentCreate, AgentUpdate

logger = logging.getLogger("astrava.agents")

DEFAULT_AGENTS: list[dict[str, Any]] = [
    # ------------------ SaaS Studio Agents (7) ------------------
    {
        "slug": "product-researcher",
        "name": "Product Researcher",
        "description": "Researches market trends, user pain points, problem validation, and customer personas.",
        "studio_type": StudioType.SAAS,
        "capabilities": [
            "market_research",
            "problem_discovery",
            "user_persona_mapping",
            "trend_analysis",
        ],
        "instructions": (
            "You are a Principal Product Researcher. Analyze user objectives, investigate market conditions, "
            "identify acute target audience pain points, and define user persona segments. Produce structured, "
            "actionable research findings with concrete problem statements."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string"}},
            "required": ["objective"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "target_personas": {"type": "array", "items": {"type": "string"}},
                "core_pain_points": {"type": "array", "items": {"type": "string"}},
                "market_opportunities": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["target_personas", "core_pain_points", "market_opportunities"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output", "structured_json_or_markdown"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "competitor-analyst",
        "name": "Competitor Analyst",
        "description": "Analyzes market alternatives, compares feature matrices, and identifies strategic differentiation.",
        "studio_type": StudioType.SAAS,
        "capabilities": [
            "competitor_analysis",
            "feature_benchmarking",
            "gap_identification",
            "swot_analysis",
        ],
        "instructions": (
            "You are a Competitor & Market Intelligence Specialist. Evaluate existing competitive solutions, "
            "map feature parity, identify product weaknesses in market incumbents, and construct an actionable comparison matrix."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string"}, "research": {"type": "string"}},
            "required": ["objective"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "key_competitors": {"type": "array", "items": {"type": "string"}},
                "parity_matrix": {"type": "object"},
                "unique_differentiators": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["key_competitors", "unique_differentiators"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output", "structured_json_or_markdown"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "product-strategist",
        "name": "Product Strategist",
        "description": "Synthesizes research into high-level product strategy, positioning, and MVP milestones.",
        "studio_type": StudioType.SAAS,
        "capabilities": [
            "product_positioning",
            "mvp_scoping",
            "value_proposition",
            "roadmap_planning",
        ],
        "instructions": (
            "You are a Chief Product Strategist. Synthesize market research and competitor insights into a sharp value proposition, "
            "clear positioning strategy, and prioritized MVP feature phases."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string"}, "context": {"type": "string"}},
            "required": ["objective"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "positioning_statement": {"type": "string"},
                "mvp_scope": {"type": "array", "items": {"type": "string"}},
                "strategic_pillars": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["positioning_statement", "mvp_scope"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output", "structured_json_or_markdown"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "product-manager",
        "name": "Product Manager",
        "description": "Creates structured PRDs, defines functional specifications, user stories, and acceptance criteria.",
        "studio_type": StudioType.SAAS,
        "capabilities": [
            "prd_creation",
            "feature_specification",
            "acceptance_criteria",
            "risk_identification",
        ],
        "instructions": (
            "You are a Lead Product Manager. Transform product strategy and objectives into a comprehensive, enterprise-grade PRD. "
            "Include user personas, functional requirements, non-functional requirements, data constraints, and acceptance criteria."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string"}, "strategy": {"type": "string"}},
            "required": ["objective"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "requirements": {"type": "array", "items": {"type": "object"}},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "requirements", "acceptance_criteria"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output", "structured_json_or_markdown"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "solution-architect",
        "name": "Solution Architect",
        "description": "Designs system architecture, service boundaries, data schemas, and API contracts.",
        "studio_type": StudioType.SAAS,
        "capabilities": [
            "system_design",
            "database_modeling",
            "api_specification",
            "security_boundaries",
        ],
        "instructions": (
            "You are a Principal Enterprise Solution Architect. Formulate modular technical architectures, relational schema specifications, "
            "API routes, security controls, and operational boundaries based on PRD requirements."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"prd": {"type": "string"}},
            "required": ["prd"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "components": {"type": "array", "items": {"type": "object"}},
                "database_schema": {"type": "string"},
                "api_contracts": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["components", "database_schema"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output", "structured_json_or_markdown"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "developer",
        "name": "Developer",
        "description": "Implements clean application code, endpoints, database models, and unit tests adhering to standards.",
        "studio_type": StudioType.SAAS,
        "capabilities": [
            "code_implementation",
            "database_migrations",
            "api_development",
            "unit_testing",
        ],
        "instructions": (
            "You are a Senior Full-Stack Software Engineer. Implement robust, cleanly structured code modules, database models, "
            "and API endpoints matching architectural designs. Write self-contained unit tests and format cleanly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"architecture": {"type": "string"}, "task_spec": {"type": "string"}},
            "required": ["task_spec"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "files_modified": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["summary"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 180, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "qa-engineer",
        "name": "QA Engineer",
        "description": "Designs verification suites, tests functionality, inspects defects, and produces verification reports.",
        "studio_type": StudioType.SAAS,
        "capabilities": [
            "automated_testing",
            "regression_verification",
            "defect_analysis",
            "test_reporting",
        ],
        "instructions": (
            "You are a Lead Quality Assurance Engineer. Execute deterministic validation, verify test coverage, check regression bounds, "
            "and generate structured QA evaluation reports."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"implementation": {"type": "string"}},
            "required": ["implementation"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "test_results": {"type": "string"},
                "passed": {"type": "boolean"},
                "defects_found": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["passed"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    # ------------------ Media Studio Agents (9) ------------------
    {
        "slug": "content-researcher",
        "name": "Content Researcher",
        "description": "Identifies trending topics, audience interest data, reference benchmarks, and narrative angles.",
        "studio_type": StudioType.MEDIA,
        "capabilities": [
            "topic_research",
            "trend_scouting",
            "reference_benchmarking",
            "source_verification",
        ],
        "instructions": (
            "You are a Media Content Researcher. Discover trending angles, verify factual sources, identify compelling hooks, "
            "and deliver comprehensive narrative background for multimedia production."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string"}},
            "required": ["objective"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "core_topics": {"type": "array", "items": {"type": "string"}},
                "reference_sources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["core_topics"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "audience-analyst",
        "name": "Audience Analyst",
        "description": "Profiles viewer demographics, consumption habits, emotional resonance triggers, and tone alignment.",
        "studio_type": StudioType.MEDIA,
        "capabilities": [
            "audience_profiling",
            "psychographic_analysis",
            "engagement_triggers",
            "tone_guidance",
        ],
        "instructions": (
            "You are an Audience Insights Analyst. Formulate precise audience personas, identify emotional retention triggers, "
            "and provide explicit tone and style directives for content creation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string"}, "research": {"type": "string"}},
            "required": ["objective"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "demographic_profile": {"type": "string"},
                "key_retention_hooks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["demographic_profile", "key_retention_hooks"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "content-strategist",
        "name": "Content Strategist",
        "description": "Structures multi-channel content narratives, engagement frameworks, and strategic narrative pillars.",
        "studio_type": StudioType.MEDIA,
        "capabilities": [
            "narrative_architecture",
            "multi_channel_strategy",
            "engagement_frameworks",
            "core_messaging",
        ],
        "instructions": (
            "You are a Chief Content Strategist. Formulate high-retention narrative arcs, structure multi-channel messaging frameworks, "
            "and define core conceptual hooks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string"}, "audience_data": {"type": "string"}},
            "required": ["objective"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "narrative_pillars": {"type": "array", "items": {"type": "string"}},
                "hook_strategy": {"type": "string"},
            },
            "required": ["narrative_pillars", "hook_strategy"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "content-calendar-planner",
        "name": "Content Calendar Planner",
        "description": "Organizes publication schedules, episode cadences, asset milestones, and cross-platform releases.",
        "studio_type": StudioType.MEDIA,
        "capabilities": [
            "publishing_schedule",
            "cadence_planning",
            "milestone_mapping",
            "distribution_timing",
        ],
        "instructions": (
            "You are a Content Operations Planner. Develop publication schedules, production deadlines, and cross-platform cadence tables."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"strategy": {"type": "string"}},
            "required": ["strategy"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "cadence_schedule": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["cadence_schedule"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "scriptwriter",
        "name": "Scriptwriter",
        "description": "Writes production scripts with timing, dialogue, voiceover narration, and audio/visual cues.",
        "studio_type": StudioType.MEDIA,
        "capabilities": ["screenwriting", "spoken_dialogue", "visual_cues", "pacing_control"],
        "instructions": (
            "You are an Award-Winning Multimedia Scriptwriter. Write dynamic, scene-by-scene scripts with explicit timing markers, "
            "spoken dialogue, narrative voiceovers, and visual stage directions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"strategy": {"type": "string"}, "topic": {"type": "string"}},
            "required": ["topic"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "scenes": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["title", "scenes"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "storyboard-designer",
        "name": "Storyboard Designer",
        "description": "Creates visual shot sequences, frame descriptions, camera angles, on-screen graphics, and thumbnail concepts.",
        "studio_type": StudioType.MEDIA,
        "capabilities": [
            "visual_storyboarding",
            "shot_composition",
            "graphics_direction",
            "thumbnail_design",
        ],
        "instructions": (
            "You are a Visual Director and Storyboard Artist. Specify scene framing, camera motion, on-screen text graphics, "
            "lighting ambience, and high-CTR thumbnail compositions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"script": {"type": "string"}},
            "required": ["script"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "frames": {"type": "array", "items": {"type": "object"}},
                "thumbnail_concepts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["frames", "thumbnail_concepts"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "production-assistant",
        "name": "Production Assistant",
        "description": "Compiles asset requirements, technical specs, production checklists, and media manifests.",
        "studio_type": StudioType.MEDIA,
        "capabilities": [
            "asset_manifests",
            "production_specs",
            "preflight_checks",
            "resource_coordination",
        ],
        "instructions": (
            "You are a Media Production Coordinator. Compile technical asset manifests (resolutions, aspect ratios, audio tracks), "
            "b-roll requirements, and delivery preflight checklists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"storyboard": {"type": "string"}},
            "required": ["storyboard"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "asset_checklist": {"type": "array", "items": {"type": "string"}},
                "technical_specs": {"type": "object"},
            },
            "required": ["asset_checklist"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "seo-analyst",
        "name": "SEO Analyst",
        "description": "Optimizes titles, search tags, meta descriptions, chapters, and discoverability metadata.",
        "studio_type": StudioType.MEDIA,
        "capabilities": [
            "seo_optimization",
            "keyword_research",
            "metadata_generation",
            "chapter_formatting",
        ],
        "instructions": (
            "You are a Video & Content SEO Specialist. Formulate high-converting titles, keyword-rich video descriptions, "
            "timestamped chapters, and metadata tags optimized for search discoverability."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"script": {"type": "string"}, "topic": {"type": "string"}},
            "required": ["topic"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "title_options": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title_options", "description", "tags"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
    {
        "slug": "content-quality-reviewer",
        "name": "Content Quality Reviewer",
        "description": "Audits editorial standards, brand voice, accuracy, retention flow, and compliance before publication.",
        "studio_type": StudioType.MEDIA,
        "capabilities": [
            "editorial_review",
            "brand_compliance",
            "retention_audit",
            "pre_publish_verification",
        ],
        "instructions": (
            "You are a Quality & Brand Governance Reviewer. Conduct rigorous editorial review, evaluate pacing and tone consistency, "
            "and determine whether content deliverables are fully ready for publication."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"deliverables": {"type": "object"}},
            "required": ["deliverables"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "approved_for_release": {"type": "boolean"},
                "quality_score": {"type": "integer"},
                "feedback": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["approved_for_release", "quality_score"],
        },
        "available_tools": ["claude_code", "deterministic_verifier"],
        "model_config_data": {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        "execution_config": {"timeout_seconds": 120, "max_retries": 1},
        "verification_requirements": ["non_empty_output"],
        "version": "1.0.0",
        "is_enabled": True,
    },
]


class AgentService:
    @staticmethod
    async def seed_default_agents(db: AsyncSession) -> int:
        """Seeds default SaaS and Media Studio agents idempotently."""
        seeded = 0
        for agent_data in DEFAULT_AGENTS:
            existing = await db.scalar(select(Agent).where(Agent.slug == agent_data["slug"]))
            if not existing:
                agent = Agent(**agent_data)
                db.add(agent)
                seeded += 1
            else:
                # Update configuration non-destructively
                existing.name = agent_data["name"]
                existing.description = agent_data["description"]
                existing.capabilities = agent_data["capabilities"]
                existing.instructions = agent_data["instructions"]
                existing.input_schema = agent_data["input_schema"]
                existing.output_schema = agent_data["output_schema"]
                existing.available_tools = agent_data["available_tools"]
                existing.model_config_data = agent_data["model_config_data"]
                existing.execution_config = agent_data["execution_config"]
                existing.verification_requirements = agent_data["verification_requirements"]
        await db.commit()
        logger.info("Default agents seeded/updated: %d new agents created", seeded)
        return seeded

    @staticmethod
    async def list_agents(
        db: AsyncSession,
        studio_type: StudioType | None = None,
        is_enabled: bool | None = None,
    ) -> list[Agent]:
        stmt = select(Agent).order_by(Agent.studio_type, Agent.name)
        if studio_type is not None:
            stmt = stmt.where(Agent.studio_type == studio_type)
        if is_enabled is not None:
            stmt = stmt.where(Agent.is_enabled == is_enabled)
        res = await db.scalars(stmt)
        return list(res.all())

    @staticmethod
    async def get_by_id_or_slug(db: AsyncSession, identifier: str) -> Agent | None:
        try:
            val_uuid = uuid.UUID(identifier)
            agent = await db.scalar(select(Agent).where(Agent.id == val_uuid))
            if agent:
                return agent
        except ValueError:
            pass
        return await db.scalar(select(Agent).where(Agent.slug == identifier))

    @staticmethod
    async def create_agent(db: AsyncSession, data: AgentCreate) -> Agent:
        agent = Agent(**data.model_dump())
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        return agent

    @staticmethod
    async def update_agent(db: AsyncSession, agent: Agent, data: AgentUpdate) -> Agent:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(agent, field, value)
        await db.commit()
        await db.refresh(agent)
        return agent

    @staticmethod
    async def set_agent_status(db: AsyncSession, agent: Agent, is_enabled: bool) -> Agent:
        agent.is_enabled = is_enabled
        await db.commit()
        await db.refresh(agent)
        return agent
