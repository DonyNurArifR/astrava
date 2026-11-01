"""Immutable audit trail for project memory mutations.

Audit rows are append-only. This service can write and read them. Any attempt
to update or delete an audit row raises ``PermissionError``.

The service does not commit. Callers own the transaction, so audit rows are
written in the same transaction as the memory change they describe.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryAuditAction, MemoryAuditLog

_IMMUTABLE_UPDATE_MSG = "Memory audit logs are immutable; updates are not permitted."
_IMMUTABLE_DELETE_MSG = "Memory audit logs are immutable; deletes are not permitted."


class MemoryAuditService:
    """Append-only writer and reader for ``MemoryAuditLog``."""

    @staticmethod
    async def record_action(
        db: AsyncSession,
        memory_id: uuid.UUID | None,
        project_id: uuid.UUID,
        action: MemoryAuditAction | str,
        actor_type: str,
        actor_id: str | None,
        previous_state: dict[str, Any] | None = None,
        new_state: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> MemoryAuditLog:
        """Append one audit entry and flush it into the current transaction."""
        entry = MemoryAuditLog(
            memory_id=memory_id,
            project_id=project_id,
            action=MemoryAuditAction(action),
            actor_type=actor_type,
            actor_id=actor_id,
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
        )
        db.add(entry)
        await db.flush()
        return entry

    @staticmethod
    async def list_by_memory(
        db: AsyncSession,
        memory_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> list[MemoryAuditLog]:
        """Return audit entries for one memory, oldest first, scoped to the project."""
        stmt = (
            select(MemoryAuditLog)
            .where(
                MemoryAuditLog.memory_id == memory_id,
                MemoryAuditLog.project_id == project_id,
            )
            .order_by(MemoryAuditLog.created_at.asc(), MemoryAuditLog.id.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_by_project(
        db: AsyncSession,
        project_id: uuid.UUID,
        limit: int = 100,
    ) -> list[MemoryAuditLog]:
        """Return the most recent audit entries for a project, newest first."""
        if limit < 1:
            raise ValueError("limit must be >= 1.")
        stmt = (
            select(MemoryAuditLog)
            .where(MemoryAuditLog.project_id == project_id)
            .order_by(MemoryAuditLog.created_at.desc(), MemoryAuditLog.id.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Immutability guards. Audit rows are never updated or deleted.
    # Both the bare names and the explicit variants raise PermissionError.
    # ------------------------------------------------------------------

    @staticmethod
    def update(*args: Any, **kwargs: Any) -> None:
        """Always raises ``PermissionError``. Audit rows are immutable."""
        raise PermissionError(_IMMUTABLE_UPDATE_MSG)

    @staticmethod
    def update_log(*args: Any, **kwargs: Any) -> None:
        """Always raises ``PermissionError``. Audit rows are immutable."""
        raise PermissionError(_IMMUTABLE_UPDATE_MSG)

    @staticmethod
    def delete(*args: Any, **kwargs: Any) -> None:
        """Always raises ``PermissionError``. Audit rows are immutable."""
        raise PermissionError(_IMMUTABLE_DELETE_MSG)

    @staticmethod
    def delete_log(*args: Any, **kwargs: Any) -> None:
        """Always raises ``PermissionError``. Audit rows are immutable."""
        raise PermissionError(_IMMUTABLE_DELETE_MSG)
