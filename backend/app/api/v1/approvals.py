import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.approval import ApprovalDecisionRequest, ApprovalRead
from app.services.approval_service import ApprovalService
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("", response_model=list[ApprovalRead])
async def list_approvals(
    pending_only: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRead]:
    if pending_only:
        approvals = await ApprovalService.list_pending(db)
    else:
        approvals = await ApprovalService.list_all(db)
    return [ApprovalRead.model_validate(a) for a in approvals]


@router.get("/pending", response_model=list[ApprovalRead])
async def list_pending_approvals(
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRead]:
    approvals = await ApprovalService.list_pending(db)
    return [ApprovalRead.model_validate(a) for a in approvals]


@router.get("/{approval_id}", response_model=ApprovalRead)
async def get_approval(
    approval_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRead:
    approval = await ApprovalService.get_by_id(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return ApprovalRead.model_validate(approval)


@router.post("/{approval_id}/decide", response_model=ApprovalRead)
async def decide_approval(
    approval_id: uuid.UUID,
    decision_req: ApprovalDecisionRequest,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRead:
    approval = await ApprovalService.decide(
        db,
        approval_id,
        status=decision_req.decision,
        reason=decision_req.reason,
        decided_by=decision_req.decided_by,
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    # Record event on execution
    await WorkflowService.record_event(
        db,
        approval.execution_id,
        "approval_decided",
        {
            "approval_id": str(approval.id),
            "decision": approval.status.value,
            "reason": approval.decision_reason,
            "decided_by": approval.decided_by,
        },
    )
    return ApprovalRead.model_validate(approval)
