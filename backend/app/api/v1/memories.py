"""FastAPI router for Project Intelligence Memory endpoints.

Base path: /api/v1/projects/{project_id}/memories
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import OperatorContext, require_authorized_verifier
from app.db.session import get_db
from app.models.memory import (
    MemoryCategory,
    MemoryConflictStatus,
    MemoryProvenanceType,
    MemoryStatus,
)
from app.schemas.memory import (
    MemoryActionRequest,
    MemoryAuditLogRead,
    MemoryConflictItem,
    MemoryConflictResolveRequest,
    MemoryCreateRequest,
    MemoryRead,
    MemoryStatsResponse,
    MemoryUpdateRequest,
    MemoryVerifyRequest,
    PaginatedResponse,
)
from app.services.memory_audit_service import MemoryAuditService
from app.services.memory_service import MemoryNotFoundError, MemoryService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects/{project_id}/memories", tags=["Project Memory"])


async def _verify_project_exists(db: AsyncSession, project_id: uuid.UUID) -> None:
    """Ensures project exists and establishes project-scoped security boundary."""
    project = await ProjectService.get_by_id(db, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )


@router.get("", response_model=PaginatedResponse[MemoryRead])
async def list_memories(
    project_id: uuid.UUID,
    category: MemoryCategory | None = None,
    provenance: MemoryProvenanceType | None = Query(None, alias="provenance"),
    status_filter: MemoryStatus | None = Query(None, alias="status"),
    is_verified: bool | None = None,
    conflict_status: MemoryConflictStatus | None = None,
    search: str | None = Query(None, max_length=500),
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    include_historical: bool = Query(
        False,
        description="Include superseded, archived, and rejected memories when status is not specified",
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(
        "created_at",
        pattern="^(created_at|updated_at|revision|confidence_score|summary)$",
        description="Field to sort by",
    ),
    sort_order: str = Query(
        "desc",
        pattern="^(asc|desc)$",
        description="Sort direction (asc or desc)",
    ),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MemoryRead]:
    """List and filter memories within a project with deterministic pagination and sorting."""
    await _verify_project_exists(db, project_id)

    if created_after and created_before and created_after > created_before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="created_after cannot be later than created_before",
        )
    if updated_after and updated_before and updated_after > updated_before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="updated_after cannot be later than updated_before",
        )

    try:
        items, total = await MemoryService.list_and_count_memories(
            db=db,
            project_id=project_id,
            category=category,
            provenance_type=provenance,
            status=status_filter,
            is_verified=is_verified,
            conflict_status=conflict_status,
            search_query=search,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
            include_historical=include_historical,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return PaginatedResponse(
        items=[MemoryRead.model_validate(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    project_id: uuid.UUID,
    data: MemoryCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    """Create a new project-scoped memory.

    Enforces provenance constraints and audit logging. Verification is never directly
    assignable on creation and requires explicit verification workflows.
    """
    await _verify_project_exists(db, project_id)

    try:
        memory = await MemoryService.create_memory(
            db=db,
            project_id=project_id,
            category=data.category,
            summary=data.summary,
            content=data.content,
            provenance_type=data.provenance_type,
            confidence_score=data.confidence_score,
            source_execution_id=data.source_execution_id,
            source_task_id=data.source_task_id,
            source_artifact_id=data.source_artifact_id,
            source_agent_slug=data.source_agent_slug,
            metadata_json=data.metadata_json,
            actor_type="user",
            actor_id="user",
            reason="User created memory via REST API",
        )
        await db.commit()
        await db.refresh(memory)
        return MemoryRead.model_validate(memory)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project memory",
        ) from e


@router.get("/conflicts", response_model=PaginatedResponse[MemoryConflictItem])
async def list_conflicts(
    project_id: uuid.UUID,
    category: MemoryCategory | None = None,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MemoryConflictItem]:
    """List detected memory conflicts for a project with partner memory metadata."""
    await _verify_project_exists(db, project_id)

    try:
        items, total = await MemoryService.list_conflicts(
            db=db,
            project_id=project_id,
            category=category,
            page=page,
            page_size=page_size,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return PaginatedResponse(
        items=[MemoryConflictItem.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MemoryStatsResponse:
    """Retrieve aggregate statistics for a project's memory bank."""
    await _verify_project_exists(db, project_id)
    stats_data = await MemoryService.get_memory_stats(db, project_id)
    return MemoryStatsResponse(**stats_data)


@router.get("/{memory_id}", response_model=MemoryRead)
async def get_memory(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    """Retrieve details for a single memory, scoped strictly to the project."""
    await _verify_project_exists(db, project_id)

    memory = await MemoryService.get_memory(db, project_id, memory_id)
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found in project {project_id}",
        )

    return MemoryRead.model_validate(memory)


@router.get("/{memory_id}/revisions", response_model=list[MemoryRead])
async def get_memory_revisions(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[MemoryRead]:
    """Retrieve full immutable revision chain connected to this memory, oldest first."""
    await _verify_project_exists(db, project_id)

    memory = await MemoryService.get_memory(db, project_id, memory_id)
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found in project {project_id}",
        )

    revisions = await MemoryService.get_revision_history(db, project_id, memory_id)
    return [MemoryRead.model_validate(r) for r in revisions]


@router.patch("/{memory_id}", response_model=MemoryRead)
async def update_memory(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    data: MemoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    """Update a memory by producing an immutable new revision row.

    Requires expected_revision for optimistic concurrency control.
    Returns 409 Conflict if expected_revision does not match the current revision.
    """
    await _verify_project_exists(db, project_id)

    try:
        updated = await MemoryService.update_memory(
            db=db,
            project_id=project_id,
            memory_id=memory_id,
            expected_revision=data.expected_revision,
            summary=data.summary,
            content=data.content,
            metadata_json=data.metadata_json,
            actor_type="user",
            actor_id="user",
            reason=data.reason or "User updated memory via REST API",
        )
        await db.commit()
        await db.refresh(updated)
        return MemoryRead.model_validate(updated)
    except MemoryNotFoundError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found in project {project_id}",
        ) from err
    except ValueError as e:
        await db.rollback()
        err_msg = str(e)
        if (
            "revision conflict" in err_msg.lower()
            or "expected revision" in err_msg.lower()
            or "revision mismatch" in err_msg.lower()
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err_msg) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update project memory",
        ) from e


@router.post("/{memory_id}/archive", response_model=MemoryRead)
async def archive_memory(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    data: MemoryActionRequest = MemoryActionRequest(),
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    """Soft-archive an active or proposed memory, preserving full audit and revision history."""
    await _verify_project_exists(db, project_id)

    try:
        archived = await MemoryService.archive_memory(
            db=db,
            project_id=project_id,
            memory_id=memory_id,
            actor_type="user",
            actor_id="user",
            reason=data.reason or "Archived via REST API",
        )
        await db.commit()
        await db.refresh(archived)
        return MemoryRead.model_validate(archived)
    except MemoryNotFoundError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found in project {project_id}",
        ) from err
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{memory_id}/restore", response_model=MemoryRead)
async def restore_memory(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    data: MemoryActionRequest = MemoryActionRequest(),
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    """Restore an archived memory back to ACTIVE status."""
    await _verify_project_exists(db, project_id)

    try:
        restored = await MemoryService.restore_memory(
            db=db,
            project_id=project_id,
            memory_id=memory_id,
            actor_type="user",
            actor_id="user",
            reason=data.reason or "Restored via REST API",
        )
        await db.commit()
        await db.refresh(restored)
        return MemoryRead.model_validate(restored)
    except MemoryNotFoundError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found in project {project_id}",
        ) from err
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{memory_id}/verify", response_model=MemoryRead)
async def verify_memory(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    data: MemoryVerifyRequest,
    operator: OperatorContext = Depends(require_authorized_verifier),
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    """Mark a memory as verified with verifier attribution and evidence details.

    The verifier identity is derived from the authenticated operator context; any
    client-supplied ``verified_by`` must match it or the request is rejected.
    Upgrades AGENT_CONCLUSION provenance to VERIFIED_FINDING.
    """
    if data.verified_by is not None and data.verified_by != operator.display_name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot impersonate verifier; identity derived from authenticated operator context",
        )

    await _verify_project_exists(db, project_id)

    try:
        verified = await MemoryService.verify_memory(
            db=db,
            project_id=project_id,
            memory_id=memory_id,
            verified_by=operator.display_name,
            verification_details=data.verification_details,
            actor_type=operator.actor_type,
            actor_id=operator.actor_id,
            reason=data.reason or f"Verified by {operator.display_name}",
        )
        await db.commit()
        await db.refresh(verified)
        return MemoryRead.model_validate(verified)
    except MemoryNotFoundError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found in project {project_id}",
        ) from err
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{memory_id}/resolve", response_model=MemoryRead)
async def resolve_conflict(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    data: MemoryConflictResolveRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoryRead:
    """Resolve a detected memory conflict using supersede, reject, or merge strategies."""
    await _verify_project_exists(db, project_id)

    try:
        resolved = await MemoryService.resolve_conflict(
            db=db,
            project_id=project_id,
            memory_id=memory_id,
            resolution=data.resolution,
            actor_id=data.actor_id or "user",
            reason=data.reason,
            merged_summary=data.merged_summary,
            merged_content=data.merged_content,
        )
        await db.commit()
        await db.refresh(resolved)
        return MemoryRead.model_validate(resolved)
    except MemoryNotFoundError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory {memory_id} not found in project {project_id}",
        ) from err
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{memory_id}/audit", response_model=PaginatedResponse[MemoryAuditLogRead])
async def get_memory_audit(
    project_id: uuid.UUID,
    memory_id: uuid.UUID,
    order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order by created_at"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MemoryAuditLogRead]:
    """Retrieve immutable audit history for a memory record. Read-only."""
    await _verify_project_exists(db, project_id)

    memory = await MemoryService.get_memory(db, project_id, memory_id)
    if not memory:
        # Also check if any audit entries exist for this memory_id in this project
        # (in case the memory row was hard-deleted but audit trail remains)
        entries, count = await MemoryAuditService.list_by_memory_paginated(
            db=db,
            memory_id=memory_id,
            project_id=project_id,
            page=1,
            page_size=1,
            order=order,
        )
        if count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Memory {memory_id} not found in project {project_id}",
            )

    try:
        entries, total = await MemoryAuditService.list_by_memory_paginated(
            db=db,
            memory_id=memory_id,
            project_id=project_id,
            page=page,
            page_size=page_size,
            order=order,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return PaginatedResponse(
        items=[MemoryAuditLogRead.model_validate(entry) for entry in entries],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
