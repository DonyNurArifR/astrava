"""Persistent project memory: CRUD, revisions, verification, conflicts, audit.

Transaction policy: every method flushes but never commits. The caller owns the
transaction, so memory rows and their audit entries land together.

Design notes:
- ``verified_by`` and ``verification_details`` have no columns on
  ``ProjectMemory``. They are stored under ``metadata_json["verified_by"]`` and
  ``metadata_json["verification_details"]``.
- Revisions are immutable rows. Updates insert a new row and mark the old row
  SUPERSEDED. ``list_memories`` hides SUPERSEDED rows unless ``status`` is given.
- Duplicate and conflict checks use normalized text: whitespace is collapsed and
  case is folded. Only ACTIVE memories in the same category are compared.
- ``delete_memory(hard_delete=True)`` records an ARCHIVED audit entry with
  ``new_state={"hard_deleted": True}``. The enum has no DELETED action, so this
  avoids a schema change. The audit row survives because its FK is SET NULL.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import (
    MemoryAuditAction,
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
    ProjectMemory,
)
from app.services.memory_audit_service import MemoryAuditService

CONFIDENCE_POLICY: dict[MemoryProvenanceType, float] = {
    MemoryProvenanceType.USER_PROVIDED: 1.0,
    MemoryProvenanceType.VERIFIED_FINDING: 0.95,
    MemoryProvenanceType.AGENT_CONCLUSION: 0.70,
    MemoryProvenanceType.ASSUMPTION: 0.50,
}

SUMMARY_MAX_LENGTH = 500

ConflictResolution = Literal["supersede", "reject", "merge"]

_TERMINAL_STATUSES = frozenset({MemoryStatus.SUPERSEDED, MemoryStatus.REJECTED})
_REJECTABLE_STATUSES = frozenset(
    {MemoryStatus.PROPOSED, MemoryStatus.ACTIVE, MemoryStatus.ARCHIVED}
)
_ARCHIVABLE_STATUSES = frozenset({MemoryStatus.PROPOSED, MemoryStatus.ACTIVE})


class MemoryNotFoundError(LookupError):
    """Raised by mutators when the memory does not exist in the given project."""


# ----------------------------------------------------------------------
# Module helpers
# ----------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize(text: str) -> str:
    """Collapse whitespace and fold case for deterministic comparison."""
    return " ".join(text.split()).casefold()


def _clean_summary(summary: str) -> str:
    cleaned = summary.strip()
    if not cleaned:
        raise ValueError("summary must not be empty.")
    if len(cleaned) > SUMMARY_MAX_LENGTH:
        raise ValueError(f"summary must be at most {SUMMARY_MAX_LENGTH} characters.")
    return cleaned


def _clean_content(content: str) -> str:
    cleaned = content.strip()
    if not cleaned:
        raise ValueError("content must not be empty.")
    return cleaned


def _resolve_confidence(provenance: MemoryProvenanceType, score: float | None) -> float:
    if score is None:
        return CONFIDENCE_POLICY[provenance]
    if not 0.0 <= score <= 1.0:
        raise ValueError("confidence_score must be between 0 and 1.")
    return float(score)


def _str_or_none(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _snapshot(memory: ProjectMemory) -> dict[str, Any]:
    """JSON-serializable column snapshot. Reads columns only, so no lazy loads."""
    return {
        "id": str(memory.id),
        "project_id": str(memory.project_id),
        "category": memory.category.value,
        "summary": memory.summary,
        "content": memory.content,
        "provenance_type": memory.provenance_type.value,
        "confidence_score": memory.confidence_score,
        "is_verified": memory.is_verified,
        "verified_at": memory.verified_at.isoformat() if memory.verified_at else None,
        "source_execution_id": _str_or_none(memory.source_execution_id),
        "source_task_id": memory.source_task_id,
        "source_artifact_id": _str_or_none(memory.source_artifact_id),
        "source_agent_slug": memory.source_agent_slug,
        "status": memory.status.value,
        "revision": memory.revision,
        "previous_revision_id": _str_or_none(memory.previous_revision_id),
        "conflict_status": memory.conflict_status.value,
        "conflicting_memory_id": _str_or_none(memory.conflicting_memory_id),
        "metadata_json": dict(memory.metadata_json or {}),
    }


class MemoryService:
    """Async service for project memory. All methods are static, like ProjectService."""

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @staticmethod
    async def get_memory(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> ProjectMemory | None:
        """Return the memory only if it belongs to ``project_id``."""
        stmt = select(ProjectMemory).where(
            ProjectMemory.id == memory_id,
            ProjectMemory.project_id == project_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_memories(
        db: AsyncSession,
        project_id: uuid.UUID,
        category: MemoryCategory | str | None = None,
        provenance_type: MemoryProvenanceType | str | None = None,
        status: MemoryStatus | str | None = None,
        is_verified: bool | None = None,
        limit: int = 100,
    ) -> list[ProjectMemory]:
        """List project memories, newest first.

        When ``status`` is None, SUPERSEDED revisions are excluded so only current
        revisions are returned. Pass ``status=MemoryStatus.SUPERSEDED`` to see them.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1.")

        stmt = select(ProjectMemory).where(ProjectMemory.project_id == project_id)
        if category is not None:
            stmt = stmt.where(ProjectMemory.category == MemoryCategory(category))
        if provenance_type is not None:
            stmt = stmt.where(
                ProjectMemory.provenance_type == MemoryProvenanceType(provenance_type)
            )
        if status is not None:
            stmt = stmt.where(ProjectMemory.status == MemoryStatus(status))
        else:
            stmt = stmt.where(ProjectMemory.status != MemoryStatus.SUPERSEDED)
        if is_verified is not None:
            stmt = stmt.where(ProjectMemory.is_verified == is_verified)

        stmt = stmt.order_by(ProjectMemory.created_at.desc(), ProjectMemory.id.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_and_count_memories(
        db: AsyncSession,
        project_id: uuid.UUID,
        category: MemoryCategory | str | None = None,
        provenance_type: MemoryProvenanceType | str | None = None,
        status: MemoryStatus | str | None = None,
        is_verified: bool | None = None,
        conflict_status: MemoryConflictStatus | str | None = None,
        search_query: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        include_historical: bool = False,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[ProjectMemory], int]:
        """List project memories with filtering, search, sorting, and total count for pagination."""
        if page < 1:
            raise ValueError("page must be >= 1.")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100.")

        conditions = [ProjectMemory.project_id == project_id]

        if category is not None:
            conditions.append(ProjectMemory.category == MemoryCategory(category))
        if provenance_type is not None:
            conditions.append(
                ProjectMemory.provenance_type == MemoryProvenanceType(provenance_type)
            )
        if status is not None:
            conditions.append(ProjectMemory.status == MemoryStatus(status))
        elif not include_historical:
            # By default exclude superseded, rejected, and archived memories
            conditions.append(
                ProjectMemory.status.in_([MemoryStatus.ACTIVE, MemoryStatus.PROPOSED])
            )

        if is_verified is not None:
            conditions.append(ProjectMemory.is_verified == is_verified)

        if conflict_status is not None:
            conditions.append(
                ProjectMemory.conflict_status == MemoryConflictStatus(conflict_status)
            )

        if created_after is not None:
            conditions.append(ProjectMemory.created_at >= created_after)
        if created_before is not None:
            conditions.append(ProjectMemory.created_at <= created_before)
        if updated_after is not None:
            conditions.append(ProjectMemory.updated_at >= updated_after)
        if updated_before is not None:
            conditions.append(ProjectMemory.updated_at <= updated_before)

        if search_query and search_query.strip():
            clean_search = search_query.strip()
            conditions.append(
                or_(
                    ProjectMemory.summary.ilike(f"%{clean_search}%"),
                    ProjectMemory.content.ilike(f"%{clean_search}%"),
                )
            )

        # Total count query
        count_stmt = select(func.count(ProjectMemory.id)).where(*conditions)
        total_count = (await db.execute(count_stmt)).scalar_one() or 0

        # Sort mapping
        sort_col_map = {
            "created_at": ProjectMemory.created_at,
            "updated_at": ProjectMemory.updated_at,
            "revision": ProjectMemory.revision,
            "confidence_score": ProjectMemory.confidence_score,
            "summary": ProjectMemory.summary,
        }
        sort_col = sort_col_map.get(sort_by, ProjectMemory.created_at)
        order_clause = sort_col.desc() if sort_order.lower() == "desc" else sort_col.asc()

        offset = (page - 1) * page_size
        items_stmt = (
            select(ProjectMemory)
            .where(*conditions)
            .order_by(order_clause, ProjectMemory.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(items_stmt)
        items = list(result.scalars().all())

        return items, total_count

    @staticmethod
    async def get_memory_stats(
        db: AsyncSession,
        project_id: uuid.UUID,
    ) -> dict[str, int]:
        """Aggregate memory statistics for a project in a single query."""
        stmt = select(
            func.count(ProjectMemory.id)
            .filter(ProjectMemory.status == MemoryStatus.ACTIVE)
            .label("total_active"),
            func.count(ProjectMemory.id)
            .filter(
                ProjectMemory.provenance_type == MemoryProvenanceType.VERIFIED_FINDING,
                ProjectMemory.status != MemoryStatus.SUPERSEDED,
            )
            .label("verified_findings"),
            func.count(ProjectMemory.id)
            .filter(
                ProjectMemory.provenance_type == MemoryProvenanceType.AGENT_CONCLUSION,
                ProjectMemory.status != MemoryStatus.SUPERSEDED,
            )
            .label("agent_conclusions"),
            func.count(ProjectMemory.id)
            .filter(
                ProjectMemory.provenance_type == MemoryProvenanceType.ASSUMPTION,
                ProjectMemory.status != MemoryStatus.SUPERSEDED,
            )
            .label("assumptions"),
            func.count(ProjectMemory.id)
            .filter(ProjectMemory.conflict_status == MemoryConflictStatus.DETECTED)
            .label("open_conflicts"),
            func.count(ProjectMemory.id)
            .filter(ProjectMemory.status == MemoryStatus.ARCHIVED)
            .label("archived"),
        ).where(ProjectMemory.project_id == project_id)
        row = (await db.execute(stmt)).one()
        return {
            "total_active": row.total_active or 0,
            "verified_findings": row.verified_findings or 0,
            "agent_conclusions": row.agent_conclusions or 0,
            "assumptions": row.assumptions or 0,
            "open_conflicts": row.open_conflicts or 0,
            "archived": row.archived or 0,
        }

    @staticmethod
    async def list_conflicts(
        db: AsyncSession,
        project_id: uuid.UUID,
        category: MemoryCategory | str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """List detected conflicts with partner memory details."""
        if page < 1:
            raise ValueError("page must be >= 1.")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100.")

        conditions = [
            ProjectMemory.project_id == project_id,
            ProjectMemory.conflict_status == MemoryConflictStatus.DETECTED,
        ]
        if category is not None:
            conditions.append(ProjectMemory.category == MemoryCategory(category))

        count_stmt = select(func.count(ProjectMemory.id)).where(*conditions)
        total_count = (await db.execute(count_stmt)).scalar_one() or 0

        offset = (page - 1) * page_size
        items_stmt = (
            select(ProjectMemory)
            .where(*conditions)
            .order_by(ProjectMemory.created_at.desc(), ProjectMemory.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(items_stmt)
        memories = list(result.scalars().all())

        # Collect partner IDs
        partner_ids = [m.conflicting_memory_id for m in memories if m.conflicting_memory_id]
        partners_map: dict[uuid.UUID, ProjectMemory] = {}
        if partner_ids:
            p_stmt = select(ProjectMemory).where(
                ProjectMemory.project_id == project_id,
                ProjectMemory.id.in_(partner_ids),
            )
            p_rows = list((await db.execute(p_stmt)).scalars().all())
            partners_map = {p.id: p for p in p_rows}

        items: list[dict[str, Any]] = []
        for mem in memories:
            partner = (
                partners_map.get(mem.conflicting_memory_id) if mem.conflicting_memory_id else None
            )
            items.append(
                {
                    "memory_id": mem.id,
                    "summary": mem.summary,
                    "category": mem.category,
                    "status": mem.status,
                    "revision": mem.revision,
                    "provenance_type": mem.provenance_type,
                    "conflict_status": mem.conflict_status,
                    "conflicting_memory_id": mem.conflicting_memory_id,
                    "partner_summary": partner.summary if partner else None,
                    "partner_status": partner.status if partner else None,
                    "partner_provenance_type": partner.provenance_type if partner else None,
                    "partner_revision": partner.revision if partner else None,
                    "created_at": mem.created_at,
                }
            )

        return items, total_count

    @staticmethod
    async def get_revision_history(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> list[ProjectMemory]:
        """Return every revision connected to ``memory_id``, oldest first.

        Walks ancestors through ``previous_revision_id``, then descendants by
        searching for rows that point back. Every query is scoped to the project.
        Returns an empty list if the memory is not found.
        """
        memory = await MemoryService.get_memory(db, project_id, memory_id)
        if memory is None:
            return []

        chain: dict[uuid.UUID, ProjectMemory] = {memory.id: memory}

        # Ancestors
        cursor = memory
        while cursor.previous_revision_id is not None:
            if cursor.previous_revision_id in chain:
                break
            prev = await MemoryService.get_memory(db, project_id, cursor.previous_revision_id)
            if prev is None:
                break
            chain[prev.id] = prev
            cursor = prev

        # Descendants (breadth-first)
        frontier: list[uuid.UUID] = [memory.id]
        while frontier:
            stmt = select(ProjectMemory).where(
                ProjectMemory.project_id == project_id,
                ProjectMemory.previous_revision_id.in_(frontier),
            )
            result = await db.execute(stmt)
            children = [c for c in result.scalars().all() if c.id not in chain]
            for child in children:
                chain[child.id] = child
            frontier = [c.id for c in children]

        return sorted(chain.values(), key=lambda m: (m.revision, m.created_at))

    # ------------------------------------------------------------------
    # Duplicate and conflict detection
    # ------------------------------------------------------------------

    @staticmethod
    async def _active_in_category(
        db: AsyncSession,
        project_id: uuid.UUID,
        category: MemoryCategory,
    ) -> list[ProjectMemory]:
        stmt = (
            select(ProjectMemory)
            .where(
                ProjectMemory.project_id == project_id,
                ProjectMemory.category == category,
                ProjectMemory.status == MemoryStatus.ACTIVE,
            )
            .order_by(ProjectMemory.created_at.asc(), ProjectMemory.id.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def _find_exact_duplicate(
        db: AsyncSession,
        project_id: uuid.UUID,
        category: MemoryCategory,
        summary: str,
        content: str,
    ) -> ProjectMemory | None:
        target_summary = _normalize(summary)
        target_content = _normalize(content)
        for candidate in await MemoryService._active_in_category(db, project_id, category):
            if (
                _normalize(candidate.summary) == target_summary
                and _normalize(candidate.content) == target_content
            ):
                return candidate
        return None

    @staticmethod
    async def detect_conflicts(
        db: AsyncSession,
        project_id: uuid.UUID,
        category: MemoryCategory | str,
        summary: str,
        content: str,
    ) -> ProjectMemory | None:
        """Return an ACTIVE memory with the same summary but different content.

        Exact duplicates (same summary and content) are not conflicts. They are
        handled by ``create_memory`` before this check runs.
        """
        cat = MemoryCategory(category)
        target_summary = _normalize(summary)
        target_content = _normalize(content)
        for candidate in await MemoryService._active_in_category(db, project_id, cat):
            if (
                _normalize(candidate.summary) == target_summary
                and _normalize(candidate.content) != target_content
            ):
                return candidate
        return None

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    @staticmethod
    async def create_memory(
        db: AsyncSession,
        project_id: uuid.UUID,
        category: MemoryCategory | str,
        summary: str,
        content: str,
        provenance_type: MemoryProvenanceType | str,
        confidence_score: float | None = None,
        is_verified: bool = False,
        verified_by: str | None = None,
        source_execution_id: uuid.UUID | None = None,
        source_task_id: str | None = None,
        source_artifact_id: uuid.UUID | None = None,
        source_agent_slug: str | None = None,
        metadata_json: dict[str, Any] | None = None,
        actor_type: str = "system",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> ProjectMemory:
        """Create a memory, or return the existing exact duplicate.

        Rules:
        - ``confidence_score`` defaults to the provenance policy weight.
        - agent_conclusion is verified only when ``verified_by`` is given. In that
          case provenance is upgraded to verified_finding, matching verify_memory.
        - Exact active duplicate: returns the existing row and writes no new row.
        - Same summary, different content: the new row is created with
          conflict_status DETECTED, and both rows are linked to each other.
        - Status: ACTIVE for user_provided and verified_finding, otherwise PROPOSED.
        """
        cat = MemoryCategory(category)
        summary_clean = _clean_summary(summary)
        content_clean = _clean_content(content)
        provenance = MemoryProvenanceType(provenance_type)

        duplicate = await MemoryService._find_exact_duplicate(
            db, project_id, cat, summary_clean, content_clean
        )
        if duplicate is not None:
            return duplicate

        verified = bool(is_verified) or verified_by is not None
        if provenance == MemoryProvenanceType.AGENT_CONCLUSION:
            if verified_by is None:
                verified = False
            else:
                provenance = MemoryProvenanceType.VERIFIED_FINDING

        confidence = _resolve_confidence(provenance, confidence_score)
        now = _utcnow()

        meta: dict[str, Any] = dict(metadata_json or {})
        if verified_by is not None:
            meta["verified_by"] = verified_by

        status = (
            MemoryStatus.ACTIVE
            if provenance
            in (MemoryProvenanceType.USER_PROVIDED, MemoryProvenanceType.VERIFIED_FINDING)
            else MemoryStatus.PROPOSED
        )

        conflict = await MemoryService.detect_conflicts(
            db, project_id, cat, summary_clean, content_clean
        )

        memory = ProjectMemory(
            project_id=project_id,
            category=cat,
            summary=summary_clean,
            content=content_clean,
            provenance_type=provenance,
            confidence_score=confidence,
            is_verified=verified,
            verified_at=now if verified else None,
            source_execution_id=source_execution_id,
            source_task_id=source_task_id,
            source_artifact_id=source_artifact_id,
            source_agent_slug=source_agent_slug,
            status=status,
            revision=1,
            previous_revision_id=None,
            conflict_status=MemoryConflictStatus.NONE,
            conflicting_memory_id=None,
            metadata_json=meta,
        )
        db.add(memory)
        await db.flush()

        await MemoryAuditService.record_action(
            db,
            memory.id,
            project_id,
            MemoryAuditAction.CREATED,
            actor_type,
            actor_id,
            previous_state=None,
            new_state=_snapshot(memory),
            reason=reason,
        )

        if conflict is not None:
            memory.conflict_status = MemoryConflictStatus.DETECTED
            memory.conflicting_memory_id = conflict.id
            conflict.conflict_status = MemoryConflictStatus.DETECTED
            conflict.conflicting_memory_id = memory.id
            await db.flush()
            await MemoryAuditService.record_action(
                db,
                memory.id,
                project_id,
                MemoryAuditAction.CONFLICT_DETECTED,
                actor_type,
                actor_id,
                previous_state=None,
                new_state={"conflicting_memory_id": str(conflict.id)},
                reason=reason or "Same summary as an active memory with different content.",
            )

        await db.refresh(memory)
        return memory

    # ------------------------------------------------------------------
    # Update (revision-creating)
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_or_raise(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> ProjectMemory:
        stmt = select(ProjectMemory).where(
            ProjectMemory.id == memory_id,
            ProjectMemory.project_id == project_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()
        if memory is None:
            raise MemoryNotFoundError(f"Memory {memory_id} not found in project {project_id}.")
        return memory

    @staticmethod
    async def _create_revision(
        db: AsyncSession,
        current: ProjectMemory,
        *,
        summary: str,
        content: str,
        confidence_score: float,
        metadata_json: dict[str, Any],
        actor_type: str,
        actor_id: str | None,
        reason: str | None,
        status: MemoryStatus | None = None,
        conflict_status: MemoryConflictStatus | None = None,
        conflicting_memory_id: uuid.UUID | None = None,
    ) -> ProjectMemory:
        """Insert revision N+1, mark ``current`` SUPERSEDED, and audit UPDATED.

        If the text changes, verification is cleared because the verified content
        no longer exists. ``verified_by`` and ``verification_details`` are removed
        from metadata in that case.
        """
        previous_state = _snapshot(current)

        content_changed = _normalize(summary) != _normalize(current.summary) or _normalize(
            content
        ) != _normalize(current.content)
        verified = current.is_verified and not content_changed

        meta = dict(metadata_json)
        if not verified:
            meta.pop("verified_by", None)
            meta.pop("verification_details", None)

        new_conflict_status = conflict_status
        if new_conflict_status is None:
            new_conflict_status = current.conflict_status
        new_conflicting_id = (
            conflicting_memory_id
            if conflicting_memory_id is not None
            else current.conflicting_memory_id
        )

        new_memory = ProjectMemory(
            project_id=current.project_id,
            category=current.category,
            summary=summary,
            content=content,
            provenance_type=current.provenance_type,
            confidence_score=confidence_score,
            is_verified=verified,
            verified_at=current.verified_at if verified else None,
            source_execution_id=current.source_execution_id,
            source_task_id=current.source_task_id,
            source_artifact_id=current.source_artifact_id,
            source_agent_slug=current.source_agent_slug,
            status=status if status is not None else current.status,
            revision=current.revision + 1,
            previous_revision_id=current.id,
            conflict_status=new_conflict_status,
            conflicting_memory_id=new_conflicting_id,
            metadata_json=meta,
        )
        db.add(new_memory)
        await db.flush()

        # Re-point the conflict partner at the new revision, so it does not
        # reference a superseded row.
        if (
            current.conflict_status == MemoryConflictStatus.DETECTED
            and current.conflicting_memory_id is not None
            and new_conflicting_id is not None
        ):
            partner = await MemoryService.get_memory(
                db, current.project_id, current.conflicting_memory_id
            )
            if partner is not None and partner.conflicting_memory_id == current.id:
                partner.conflicting_memory_id = new_memory.id
                await db.flush()

        current.status = MemoryStatus.SUPERSEDED
        if current.conflict_status == MemoryConflictStatus.DETECTED:
            current.conflict_status = MemoryConflictStatus.RESOLVED
        await db.flush()
        await db.refresh(new_memory)

        await MemoryAuditService.record_action(
            db,
            new_memory.id,
            new_memory.project_id,
            MemoryAuditAction.UPDATED,
            actor_type,
            actor_id,
            previous_state=previous_state,
            new_state=_snapshot(new_memory),
            reason=reason,
        )
        return new_memory

    @staticmethod
    async def update_memory(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        summary: str | None = None,
        content: str | None = None,
        confidence_score: float | None = None,
        metadata_json: dict[str, Any] | None = None,
        expected_revision: int | None = None,
        actor_type: str = "user",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> ProjectMemory:
        """Create revision N+1 of a memory with optimistic concurrency control.

        - Raises ``ValueError`` if ``expected_revision`` does not match the current
          revision.
        - Raises ``ValueError`` if the target row is SUPERSEDED or REJECTED. Callers
          must update the latest revision.
        - Fields left as None keep their current value. ``metadata_json`` replaces
          the whole dict when given.
        """
        current = await MemoryService._get_or_raise(db, project_id, memory_id, for_update=True)

        if current.status in _TERMINAL_STATUSES:
            raise ValueError(
                f"Memory {memory_id} is {current.status.value}; update the latest revision."
            )
        if expected_revision is not None and expected_revision != current.revision:
            raise ValueError(
                f"Revision conflict: expected {expected_revision}, current is {current.revision}."
            )

        new_summary = _clean_summary(summary) if summary is not None else current.summary
        new_content = _clean_content(content) if content is not None else current.content
        new_confidence = (
            _resolve_confidence(current.provenance_type, confidence_score)
            if confidence_score is not None
            else current.confidence_score
        )
        new_metadata = (
            dict(metadata_json) if metadata_json is not None else dict(current.metadata_json or {})
        )

        return await MemoryService._create_revision(
            db,
            current,
            summary=new_summary,
            content=new_content,
            confidence_score=new_confidence,
            metadata_json=new_metadata,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # In-place status transitions
    # ------------------------------------------------------------------

    @staticmethod
    async def _transition(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        *,
        allowed_from: frozenset[MemoryStatus],
        new_status: MemoryStatus,
        action: MemoryAuditAction,
        verb: str,
        actor_type: str,
        actor_id: str | None,
        reason: str | None,
    ) -> ProjectMemory:
        memory = await MemoryService._get_or_raise(db, project_id, memory_id, for_update=True)
        if memory.status not in allowed_from:
            raise ValueError(f"Cannot {verb} memory in status {memory.status.value}.")

        before = _snapshot(memory)
        memory.status = new_status
        await db.flush()
        await db.refresh(memory)

        await MemoryAuditService.record_action(
            db,
            memory.id,
            project_id,
            action,
            actor_type,
            actor_id,
            previous_state=before,
            new_state=_snapshot(memory),
            reason=reason,
        )
        return memory

    @staticmethod
    async def archive_memory(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        actor_type: str = "user",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> ProjectMemory:
        """Set status to ARCHIVED. Allowed from PROPOSED or ACTIVE."""
        return await MemoryService._transition(
            db,
            project_id,
            memory_id,
            allowed_from=_ARCHIVABLE_STATUSES,
            new_status=MemoryStatus.ARCHIVED,
            action=MemoryAuditAction.ARCHIVED,
            verb="archive",
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )

    @staticmethod
    async def restore_memory(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        actor_type: str = "user",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> ProjectMemory:
        """Set status to ACTIVE. Allowed only from ARCHIVED."""
        return await MemoryService._transition(
            db,
            project_id,
            memory_id,
            allowed_from=frozenset({MemoryStatus.ARCHIVED}),
            new_status=MemoryStatus.ACTIVE,
            action=MemoryAuditAction.UPDATED,
            verb="restore",
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )

    @staticmethod
    async def reject_memory(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        actor_type: str = "user",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> ProjectMemory:
        """Set status to REJECTED. Not allowed from SUPERSEDED or REJECTED."""
        return await MemoryService._transition(
            db,
            project_id,
            memory_id,
            allowed_from=_REJECTABLE_STATUSES,
            new_status=MemoryStatus.REJECTED,
            action=MemoryAuditAction.REJECTED,
            verb="reject",
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )

    @staticmethod
    async def verify_memory(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        verified_by: str,
        verification_details: dict[str, Any] | None = None,
        actor_type: str = "user",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> ProjectMemory:
        """Mark a memory verified. Sets ``verified_at`` and stores who verified it.

        agent_conclusion is upgraded to verified_finding. Status is not changed.
        Not allowed on SUPERSEDED or REJECTED rows.
        """
        if not verified_by or not verified_by.strip():
            raise ValueError("verified_by must be a non-empty string.")

        memory = await MemoryService._get_or_raise(db, project_id, memory_id, for_update=True)
        if memory.status in _TERMINAL_STATUSES:
            raise ValueError(f"Cannot verify memory in status {memory.status.value}.")

        before = _snapshot(memory)

        meta = dict(memory.metadata_json or {})
        meta["verified_by"] = verified_by
        if verification_details is not None:
            meta["verification_details"] = verification_details
        memory.metadata_json = meta

        memory.is_verified = True
        memory.verified_at = _utcnow()
        if memory.provenance_type == MemoryProvenanceType.AGENT_CONCLUSION:
            memory.provenance_type = MemoryProvenanceType.VERIFIED_FINDING
        if memory.status == MemoryStatus.PROPOSED:
            memory.status = MemoryStatus.ACTIVE

        await db.flush()
        await db.refresh(memory)

        await MemoryAuditService.record_action(
            db,
            memory.id,
            project_id,
            MemoryAuditAction.VERIFIED,
            actor_type,
            actor_id,
            previous_state=before,
            new_state=_snapshot(memory),
            reason=reason,
        )
        return memory

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------

    @staticmethod
    async def resolve_conflict(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        resolution: ConflictResolution,
        actor_id: str | None,
        reason: str | None,
        merged_summary: str | None = None,
        merged_content: str | None = None,
    ) -> ProjectMemory:
        """Resolve a DETECTED conflict between ``memory_id`` and its partner.

        - ``supersede``: ``memory_id`` becomes ACTIVE and the partner becomes SUPERSEDED.
        - ``reject``: ``memory_id`` becomes REJECTED and the partner is kept.
        - ``merge``: requires merged_summary and merged_content. A new revision of
          ``memory_id`` is created with the merged text and becomes ACTIVE. Both the
          original and the partner become SUPERSEDED.

        Both rows end with conflict_status RESOLVED. ``conflicting_memory_id`` is kept
        for traceability. Audit actor_type is "user".
        """
        if resolution not in ("supersede", "reject", "merge"):
            raise ValueError(f"Unknown resolution: {resolution!r}.")

        memory = await MemoryService._get_or_raise(db, project_id, memory_id, for_update=True)
        if memory.conflict_status != MemoryConflictStatus.DETECTED or (
            memory.conflicting_memory_id is None
        ):
            raise ValueError(f"Memory {memory_id} has no unresolved conflict.")

        partner = await MemoryService._get_or_raise(
            db, project_id, memory.conflicting_memory_id, for_update=True
        )
        actor_type = "user"
        before = _snapshot(memory)
        partner_before = _snapshot(partner)

        if resolution == "supersede":
            if memory.status in _TERMINAL_STATUSES:
                raise ValueError(f"Cannot supersede memory in status {memory.status.value}.")
            memory.status = MemoryStatus.ACTIVE
            memory.conflict_status = MemoryConflictStatus.RESOLVED
            partner.status = MemoryStatus.SUPERSEDED
            partner.conflict_status = MemoryConflictStatus.RESOLVED
            await db.flush()
            await db.refresh(memory)
            result = memory

        elif resolution == "reject":
            if memory.status not in _REJECTABLE_STATUSES:
                raise ValueError(f"Cannot reject memory in status {memory.status.value}.")
            memory.status = MemoryStatus.REJECTED
            memory.conflict_status = MemoryConflictStatus.RESOLVED
            partner.conflict_status = MemoryConflictStatus.RESOLVED
            await db.flush()
            await db.refresh(memory)
            result = memory

        else:  # merge
            if not merged_summary or not merged_content:
                raise ValueError("merge requires merged_summary and merged_content.")
            if memory.status in _TERMINAL_STATUSES:
                raise ValueError(f"Cannot merge memory in status {memory.status.value}.")
            merged = await MemoryService._create_revision(
                db,
                memory,
                summary=_clean_summary(merged_summary),
                content=_clean_content(merged_content),
                confidence_score=max(memory.confidence_score, partner.confidence_score),
                metadata_json=dict(memory.metadata_json or {}),
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
                status=MemoryStatus.ACTIVE,
                conflict_status=MemoryConflictStatus.RESOLVED,
                conflicting_memory_id=partner.id,
            )
            partner.status = MemoryStatus.SUPERSEDED
            partner.conflict_status = MemoryConflictStatus.RESOLVED
            await db.flush()
            result = merged

        await MemoryAuditService.record_action(
            db,
            result.id,
            project_id,
            MemoryAuditAction.CONFLICT_RESOLVED,
            actor_type,
            actor_id,
            previous_state={"memory": before, "conflicting_memory": partner_before},
            new_state={
                "resolution": resolution,
                "memory": _snapshot(result),
                "conflicting_memory": _snapshot(partner),
            },
            reason=reason,
        )
        return result

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    @staticmethod
    async def _clear_conflict_partner(db: AsyncSession, memory: ProjectMemory) -> None:
        """Reset the partner's conflict fields before this row is hard deleted."""
        if memory.conflicting_memory_id is None:
            return
        partner = await MemoryService.get_memory(
            db, memory.project_id, memory.conflicting_memory_id
        )
        if partner is not None and partner.conflicting_memory_id == memory.id:
            partner.conflicting_memory_id = None
            partner.conflict_status = MemoryConflictStatus.NONE
            await db.flush()

    @staticmethod
    async def delete_memory(
        db: AsyncSession,
        project_id: uuid.UUID,
        memory_id: uuid.UUID,
        hard_delete: bool = False,
        actor_type: str = "user",
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> bool:
        """Delete a memory and return True. Return False if it does not exist.

        - Soft delete (default): status becomes ARCHIVED and an audit entry is written.
        - Hard delete: an audit entry is written first with the snapshot and
          ``new_state={"hard_deleted": True, ...}``. The row is then removed. Audit
          rows keep their project_id, and their memory_id is set to NULL by the DB.
        """
        memory = await MemoryService.get_memory(db, project_id, memory_id)
        if memory is None:
            return False

        before = _snapshot(memory)

        if hard_delete:
            await MemoryAuditService.record_action(
                db,
                memory.id,
                project_id,
                MemoryAuditAction.ARCHIVED,
                actor_type,
                actor_id,
                previous_state=before,
                new_state={"hard_deleted": True, "memory_id": str(memory.id)},
                reason=reason or "hard delete",
            )
            await MemoryService._clear_conflict_partner(db, memory)
            await db.delete(memory)
            await db.flush()
            return True

        if memory.status != MemoryStatus.ARCHIVED:
            memory.status = MemoryStatus.ARCHIVED
            await db.flush()
            await db.refresh(memory)
            await MemoryAuditService.record_action(
                db,
                memory.id,
                project_id,
                MemoryAuditAction.ARCHIVED,
                actor_type,
                actor_id,
                previous_state=before,
                new_state=_snapshot(memory),
                reason=reason or "soft delete",
            )
        return True
