"""Knowledge extraction engine for ASTRAVA LangGraph workflows (M1.3-5).

Extracts durable, high-value project knowledge (decisions, requirements, constraints,
discoveries, milestones) from completed workflow tasks and verification results
with strict provenance classification.
"""

import hashlib
import logging
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import MemoryCategory, MemoryProvenanceType
from app.orchestrator.state import OrchestrationState

logger = logging.getLogger("astrava.orchestrator.knowledge_extraction")

# Agent slugs that produce architectural decisions, requirements, or core strategy
STRATEGIC_AGENTS = {
    "solution-architect",
    "product-manager",
    "lead-developer",
    "creative-director",
    "scriptwriter",
    "product-researcher",
}


def compute_candidate_fingerprint(
    project_id: uuid.UUID,
    category: MemoryCategory | str,
    summary: str,
    source_execution_id: uuid.UUID | None = None,
    source_task_id: str | None = None,
) -> str:
    """Stable SHA256 identity for a knowledge candidate, used for idempotent ingestion."""
    raw = (
        f"{project_id}:{category}:{summary.strip().lower()}:"
        f"{source_execution_id or ''}:{source_task_id or ''}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ExtractedMemoryCandidate(BaseModel):
    """Structured, validated candidate for persistent project memory."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    category: MemoryCategory
    summary: str = Field(min_length=5, max_length=200)
    content: str = Field(min_length=10)
    provenance_type: MemoryProvenanceType
    confidence_score: float = Field(ge=0.0, le=1.0)
    is_verified: bool
    source_task_id: str | None = None
    source_agent_slug: str | None = None
    source_artifact_id: uuid.UUID | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class KnowledgeExtractor:
    """Extracts durable project knowledge from completed workflow execution state."""

    @classmethod
    def extract_from_execution(cls, state: OrchestrationState) -> list[ExtractedMemoryCandidate]:
        """Extracts validated knowledge candidates from completed tasks and deliverables.

        Rules:
        - Successful pipeline objective is recorded as a milestone.
        - Strategic deliverables (architecture, PRD, strategy) yield decisions/requirements.
        - Findings with programmatic test verification qualify as verified_finding.
        - Agent outputs without deterministic test evidence remain agent_conclusion.
        - Scratch thoughts and temporary status updates are excluded.
        """
        objective = state.get("objective", "").strip()
        tasks = state.get("tasks", [])
        completed_ids = set(state.get("completed_task_ids", []))
        verif_results = state.get("verification_results", [])
        artifacts = state.get("artifacts", [])

        if not objective or not completed_ids:
            return []

        candidates: list[ExtractedMemoryCandidate] = []
        seen_summaries: set[str] = set()

        # Check if any deterministic verification passed
        overall_verified = False
        for vr in verif_results:
            report = vr.get("report", {})
            if report.get("overall_passed") is True:
                overall_verified = True
                break

        # ------------------------------------------------------------------
        # 1. Milestone Candidate: Completed pipeline objective
        # ------------------------------------------------------------------
        milestone_summary = f"Milestone Completed: {objective[:80]}"
        milestone_content = (
            f"Successfully completed execution workflow for objective: '{objective}'. "
            f"Generated {len(artifacts)} deliverables across {len(completed_ids)} completed tasks."
        )

        milestone_meta = {
            "source": "workflow_completion",
            "qa_tests_passed": overall_verified,
            "deliverable_count": len(artifacts),
        }

        candidates.append(
            ExtractedMemoryCandidate(
                category=MemoryCategory.MILESTONE,
                summary=milestone_summary,
                content=milestone_content,
                provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
                confidence_score=0.70,
                is_verified=False,
                source_task_id=None,
                source_agent_slug="orchestrator",
                metadata_json=milestone_meta,
            )
        )
        seen_summaries.add(milestone_summary.lower())

        # ------------------------------------------------------------------
        # 2. Extract from completed tasks of strategic agents
        # ------------------------------------------------------------------
        for t in tasks:
            tid = t.get("task_id", "")
            if tid not in completed_ids:
                continue

            agent_slug = t.get("assigned_agent_slug", "")
            output_text = (t.get("output_text") or "").strip()
            title = t.get("title", tid)

            if not output_text or len(output_text) < 30:
                continue

            # Classify category by task role / title
            title_lower = title.lower()
            if "architecture" in title_lower or "system design" in title_lower:
                category = MemoryCategory.DECISION
            elif "requirement" in title_lower or "prd" in title_lower:
                category = MemoryCategory.REQUIREMENT
            elif "strategy" in title_lower or "opportunity" in title_lower:
                category = MemoryCategory.OBJECTIVE
            elif "research" in title_lower or "competitor" in title_lower:
                category = MemoryCategory.DISCOVERY
            elif "constraint" in title_lower or "boundary" in title_lower:
                category = MemoryCategory.CONSTRAINT
            elif agent_slug in STRATEGIC_AGENTS:
                category = MemoryCategory.DECISION
            else:
                continue

            # Clean and bound content (max 1500 chars for a durable memory)
            clean_content = output_text
            if len(clean_content) > 1500:
                clean_content = clean_content[:1500] + "..."

            candidate_summary = f"{title[:120]}"
            if candidate_summary.lower() in seen_summaries:
                continue

            # Record task-specific QA execution without conflating with formal verification
            task_qa_passed = False
            for vr in verif_results:
                if vr.get("task_id") == tid:
                    report = vr.get("report", {})
                    if report.get("overall_passed") is True:
                        task_qa_passed = True
                        break

            candidates.append(
                ExtractedMemoryCandidate(
                    category=category,
                    summary=candidate_summary,
                    content=clean_content,
                    provenance_type=MemoryProvenanceType.AGENT_CONCLUSION,
                    confidence_score=0.70,
                    is_verified=False,
                    source_task_id=tid,
                    source_agent_slug=agent_slug,
                    metadata_json={
                        "task_title": title,
                        "qa_tests_passed": task_qa_passed,
                    },
                )
            )
            seen_summaries.add(candidate_summary.lower())

        return candidates
