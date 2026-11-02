"""Structured context package assembler for ASTRAVA knowledge retrieval.

Formats retrieved memories and artifacts into a Markdown package within a strict,
configurable character budget (default 4,000 chars), preserving complete item
boundaries, category groupings, and source attribution.
"""

from app.services.retrieval.schemas import (
    ContextAssemblySummary,
    ScoredArtifact,
    ScoredMemory,
)


class ContextAssembler:
    """Assembles bounded Markdown prompt packages from scored memories and artifacts."""

    DEFAULT_BUDGET = 4000

    @classmethod
    def assemble(
        cls,
        memories: list[ScoredMemory],
        artifacts: list[ScoredArtifact],
        budget_chars: int = DEFAULT_BUDGET,
    ) -> tuple[str, ContextAssemblySummary]:
        """Assembles Markdown context strictly bounded by budget_chars.

        Guarantees:
        - len(output_markdown) <= budget_chars.
        - Preserves complete item blocks without mid-content or mid-metadata truncations.
        - Prioritizes higher-ranked items.
        - Reports omitted items.
        """
        header = "# Project Intelligence Context\n\n"
        if len(header) >= budget_chars:
            # Degenerate case: tiny budget
            truncated_header = header[:budget_chars]
            return truncated_header, ContextAssemblySummary(
                budget_limit_chars=budget_chars,
                total_context_chars=len(truncated_header),
                memories_included_count=0,
                memories_omitted_count=len(memories),
                artifacts_included_count=0,
                artifacts_omitted_count=len(artifacts),
                budget_exhausted=True,
            )

        if not memories and not artifacts:
            empty_msg = header + "_No relevant project knowledge or artifacts found._\n"
            final_text = empty_msg[:budget_chars]
            return final_text, ContextAssemblySummary(
                budget_limit_chars=budget_chars,
                total_context_chars=len(final_text),
                memories_included_count=0,
                memories_omitted_count=0,
                artifacts_included_count=0,
                artifacts_omitted_count=0,
                budget_exhausted=False,
            )

        # Budget reservation for summary footer (e.g. "*Context budget reached (3,850/4,000 chars). Omitted 3 items.*")
        footer_reservation = 120
        effective_budget = max(len(header), budget_chars - footer_reservation)

        current_text = header
        memories_included = 0
        memories_omitted = 0
        artifacts_included = 0
        artifacts_omitted = 0

        # ------------------------------------------------------------------
        # 1. Format & append memories in rank order
        # ------------------------------------------------------------------
        if memories:
            current_text += "## Persistent Project Knowledge\n\n"

        for mem in memories:
            item_block = cls._format_memory_block(mem)
            if len(current_text) + len(item_block) <= effective_budget:
                current_text += item_block
                memories_included += 1
            else:
                memories_omitted += 1

        # ------------------------------------------------------------------
        # 2. Format & append artifacts in rank order
        # ------------------------------------------------------------------
        if artifacts and len(current_text) < effective_budget:
            artifacts_section_header = "## Relevant Artifacts & Lineage\n\n"
            if len(current_text) + len(artifacts_section_header) <= effective_budget:
                current_text += artifacts_section_header

            for art in artifacts:
                art_block = cls._format_artifact_block(art)
                if len(current_text) + len(art_block) <= effective_budget:
                    current_text += art_block
                    artifacts_included += 1
                else:
                    artifacts_omitted += 1
        else:
            artifacts_omitted += len(artifacts)

        # ------------------------------------------------------------------
        # 3. Append omission footer if any items were skipped
        # ------------------------------------------------------------------
        total_omitted = memories_omitted + artifacts_omitted
        budget_exhausted = total_omitted > 0

        if budget_exhausted:
            footer = (
                f"\n*Context budget reached ({len(current_text)} / {budget_chars} chars). "
                f"Omitted {total_omitted} lower-ranked items.*\n"
            )
            if len(current_text) + len(footer) <= budget_chars:
                current_text += footer

        # Final safety boundary check
        final_context = current_text[:budget_chars]

        summary = ContextAssemblySummary(
            budget_limit_chars=budget_chars,
            total_context_chars=len(final_context),
            memories_included_count=memories_included,
            memories_omitted_count=memories_omitted,
            artifacts_included_count=artifacts_included,
            artifacts_omitted_count=artifacts_omitted,
            budget_exhausted=budget_exhausted,
        )

        return final_context, summary

    @staticmethod
    def _format_memory_block(mem: ScoredMemory) -> str:
        """Formats a single memory item with provenance and boundary preservation."""
        cat_tag = mem.category.value.upper()
        verif_tag = "verified" if mem.is_verified else "unverified"
        prov_tag = mem.provenance_type.value

        source_info: list[str] = []
        if mem.source_task_id:
            source_info.append(f"task:{mem.source_task_id}")
        if mem.source_agent_slug:
            source_info.append(f"agent:{mem.source_agent_slug}")
        if mem.revision > 1:
            source_info.append(f"rev:{mem.revision}")

        source_str = f" ({', '.join(source_info)})" if source_info else ""

        block = (
            f"- **[{cat_tag}] {mem.summary}**\n"
            f"  *Provenance:* `{prov_tag}` | `{verif_tag}` | score: {mem.composite_score:.2f}{source_str}\n"
            f"  {mem.content.strip()}\n\n"
        )
        return block

    @staticmethod
    def _format_artifact_block(art: ScoredArtifact) -> str:
        """Formats a single artifact item with version and lineage context."""
        verif_tag = art.verification_status.value
        lineage_parts: list[str] = [f"v{art.version}"]
        if art.ancestors:
            parent_name = art.ancestors[-1]["name"]
            lineage_parts.append(f"parent: {parent_name}")
        if art.superseded_by_name:
            lineage_parts.append(f"superseded_by: {art.superseded_by_name}")

        lineage_str = f" ({', '.join(lineage_parts)})"

        block = (
            f"- **`{art.name}`**{lineage_str}\n"
            f"  *Path:* `{art.file_path}` | `{verif_tag}` | score: {art.composite_score:.2f}\n\n"
        )
        return block
