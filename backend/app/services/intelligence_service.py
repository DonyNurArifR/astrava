import json
import logging
import re
from typing import Any

from app.config import settings
from app.models.project import StudioType
from app.providers.base import ProviderRequest, ProviderStatus
from app.providers.factory import ProviderFactory
from app.schemas.intelligence import (
    ObjectiveComplexity,
    ObjectiveUnderstandingRequest,
    ObjectiveUnderstandingResponse,
)

logger = logging.getLogger("astrava.intelligence")

MEDIA_KEYWORDS = {
    "video",
    "youtube",
    "podcast",
    "script",
    "storyboard",
    "audio",
    "episode",
    "channel",
    "tiktok",
    "reel",
    "b-roll",
    "soundtrack",
    "thumbnail",
    "voiceover",
    "social media",
    "content calendar",
    "filming",
    "narrator",
    "clip",
}

SAAS_KEYWORDS = {
    "software",
    "saas",
    "api",
    "database",
    "crud",
    "backend",
    "frontend",
    "endpoint",
    "auth",
    "subscription",
    "cloud",
    "platform",
    "dashboard",
    "microservice",
    "service",
    "system",
    "app",
    "application",
    "deployment",
}


class IntelligenceService:
    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Extracts JSON object from text, handling markdown fences or preamble."""
        text = text.strip()
        # Try direct json
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try regex fenced block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding outermost braces
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None

    @classmethod
    def _rule_based_understanding(
        cls, req: ObjectiveUnderstandingRequest
    ) -> ObjectiveUnderstandingResponse:
        """Deterministic semantic fallback engine for objective interpretation."""
        obj_lower = req.objective.lower()
        word_count = len(req.objective.split())

        # 1. Determine studio
        if req.studio_type:
            studio = req.studio_type
        else:
            media_matches = sum(1 for kw in MEDIA_KEYWORDS if kw in obj_lower)
            saas_matches = sum(1 for kw in SAAS_KEYWORDS if kw in obj_lower)
            studio = StudioType.MEDIA if media_matches > saas_matches else StudioType.SAAS

        # 2. Check ambiguity / need for clarification
        needs_clarification = False
        clarification_questions: list[str] = []
        ambiguities: list[str] = []
        missing_info: list[str] = []

        if word_count < 4 or len(req.objective.strip()) < 15:
            needs_clarification = True
            ambiguities.append("Objective description is very brief and lacks scope definition.")
            if studio == StudioType.SAAS:
                clarification_questions.append(
                    "What is the primary target audience and core problem this software solves?"
                )
                clarification_questions.append(
                    "What key functional features or integrations are essential for the MVP?"
                )
                missing_info.extend(
                    ["Target audience", "Functional MVP scope", "Technical constraints"]
                )
            else:
                clarification_questions.append(
                    "What content format (e.g. YouTube video, short-form reel, podcast) are you producing?"
                )
                clarification_questions.append(
                    "Who is the intended viewer audience and what is the key takeaway?"
                )
                missing_info.extend(["Content format", "Target audience", "Key takeaway"])

        # 3. Determine complexity
        if (
            word_count > 50
            or "enterprise" in obj_lower
            or "multi-" in obj_lower
            or "ai" in obj_lower
        ):
            complexity = ObjectiveComplexity.HIGH
        elif word_count < 15:
            complexity = ObjectiveComplexity.LOW
        else:
            complexity = ObjectiveComplexity.MEDIUM

        # 4. Capabilities and deliverables
        if studio == StudioType.SAAS:
            capabilities = [
                "market_research",
                "competitor_analysis",
                "product_positioning",
                "prd_creation",
                "system_design",
                "code_implementation",
                "automated_testing",
            ]
            deliverables = [
                "research_findings.md",
                "competitor_matrix.md",
                "product_strategy.md",
                "prd.md",
                "architecture.md",
                "implementation_diff.patch",
                "qa_report.json",
            ]
            intended_outcome = (
                f"Build and deliver verified software solution for: {req.objective.strip()}"
            )
            potential_risks = [
                "Scope creep during implementation",
                "Integration interface mismatch",
                "Unspecified non-functional performance requirements",
            ]
        else:
            capabilities = [
                "topic_research",
                "audience_profiling",
                "narrative_architecture",
                "publishing_schedule",
                "screenwriting",
                "visual_storyboarding",
                "seo_optimization",
                "editorial_review",
            ]
            deliverables = [
                "content_strategy.md",
                "audience_persona.md",
                "script.md",
                "storyboard.json",
                "publishing_manifest.json",
            ]
            intended_outcome = (
                f"Produce production-ready multimedia content package for: {req.objective.strip()}"
            )
            potential_risks = [
                "Audience tone misalignment",
                "Pacing and visual retention drop-off",
                "SEO keyword oversaturation",
            ]

        return ObjectiveUnderstandingResponse(
            objective_summary=req.objective.strip(),
            studio=studio,
            project_context=req.project_context or "",
            intended_outcome=intended_outcome,
            required_capabilities=capabilities,
            relevant_constraints=["Single-process local execution", "Deterministic verification"],
            expected_deliverables=deliverables,
            complexity=complexity,
            ambiguities=ambiguities,
            missing_information=missing_info,
            potential_risks=potential_risks,
            needs_clarification=needs_clarification,
            clarification_questions=clarification_questions,
        )

    @classmethod
    async def understand_objective(
        cls, req: ObjectiveUnderstandingRequest
    ) -> ObjectiveUnderstandingResponse:
        """
        Semantically interprets the objective using Claude Code CLI provider,
        enforcing deterministic Pydantic schema validation with fallback.
        """
        # If in test mode or explicitly flagged, use deterministic semantic engine
        if settings.APP_ENV == "test":
            return cls._rule_based_understanding(req)

        prompt = f"""You are the ASTRAVA Chief AI Architect. Analyze this user objective and produce a strict JSON object.

User Objective:
"{req.objective}"
Studio Hint: {req.studio_type.value if req.studio_type else "auto-detect"}
Project Context: {req.project_context or "None"}

Produce ONLY valid JSON conforming to this schema without explanations:
{{
  "objective_summary": "Concise summary",
  "studio": "saas" | "media",
  "project_context": "Context summary",
  "intended_outcome": "Clear end state",
  "required_capabilities": ["list", "of", "capability_slugs"],
  "relevant_constraints": ["list", "of", "constraints"],
  "expected_deliverables": ["filename.md", "spec.json"],
  "complexity": "low" | "medium" | "high",
  "ambiguities": ["ambiguity if any"],
  "missing_information": ["missing item if any"],
  "potential_risks": ["risk item"],
  "needs_clarification": true | false,
  "clarification_questions": ["question 1"]
}}
"""
        try:
            provider = ProviderFactory.get_provider("claude_code")
            p_req = ProviderRequest(
                prompt=prompt,
                model="haiku",
                timeout_seconds=30,
            )
            resp = await provider.execute(p_req)
            if resp.status == ProviderStatus.SUCCESS and resp.output_text:
                parsed = cls._extract_json(resp.output_text)
                if parsed:
                    # Validate against Pydantic schema
                    return ObjectiveUnderstandingResponse.model_validate(parsed)
        except Exception as e:
            logger.warning(
                "Live LLM objective understanding failed (%s); using deterministic fallback.", e
            )

        return cls._rule_based_understanding(req)
