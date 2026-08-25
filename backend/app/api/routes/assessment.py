from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.deps import get_caller_context
from backend.app.auth.permissions import PermissionDenied
from backend.app.db.session import get_db
from backend.app.practice.service import (
    approve_draft,
    assign_draft,
    block_draft,
    create_assessment_draft,
    edit_draft,
    get_draft_for_manager,
    reject_draft,
    serialize_assignment,
    serialize_draft,
)
from backend.app.schemas.practice import (
    AssessmentDraftCreateRequest,
    AssessmentDraftEditRequest,
    AssessmentRejectRequest,
    AssessmentReviewRequest,
)


router = APIRouter(prefix="/api/assessment", tags=["assessment"])


def _failure(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionDenied):
        return HTTPException(status_code=403, detail=str(exc))
    message = str(exc)
    if "not found" in message:
        return HTTPException(status_code=404, detail=message)
    if "cannot" in message or "only an approved" in message or "already" in message:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.post("/drafts")
def create_draft(
    request: AssessmentDraftCreateRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = create_assessment_draft(
            db,
            caller=caller,
            student_id=request.student_id,
            subskill_id=request.subskill_id,
            item_count=request.item_count,
            recent_question_ids=request.recent_question_ids,
            class_id=request.class_id,
        )
        db.commit()
        return serialize_draft(db, draft)
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc

@router.get("/drafts/{draft_id}")
def read_draft(
    draft_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = get_draft_for_manager(db, caller, draft_id)
        return serialize_draft(db, draft)
    except (PermissionDenied, ValueError) as exc:
        raise _failure(exc) from exc


@router.post("/drafts/{draft_id}/edit")
def edit(
    draft_id: str,
    request: AssessmentDraftEditRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = edit_draft(
            db,
            caller=caller,
            draft_id=draft_id,
            question_ids=request.question_ids,
            reason=request.reason,
        )
        db.commit()
        return serialize_draft(db, draft)
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc


@router.post("/drafts/{draft_id}/approve")
def approve(
    draft_id: str,
    request: AssessmentReviewRequest | None = None,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = approve_draft(
            db,
            caller=caller,
            draft_id=draft_id,
            reason=request.reason if request else None,
        )
        db.commit()
        return serialize_draft(db, draft)
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc


@router.post("/drafts/{draft_id}/reject")
def reject(
    draft_id: str,
    request: AssessmentRejectRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = reject_draft(db, caller=caller, draft_id=draft_id, reason=request.reason)
        db.commit()
        return serialize_draft(db, draft)
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc


@router.post("/drafts/{draft_id}/assign")
def assign(
    draft_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        assignment = assign_draft(db, caller=caller, draft_id=draft_id)
        db.commit()
        return serialize_assignment(db, assignment)
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc


@router.post("/drafts/{draft_id}/block")
def block(
    draft_id: str,
    request: AssessmentRejectRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = block_draft(db, caller=caller, draft_id=draft_id, reason=request.reason)
        db.commit()
        return serialize_draft(db, draft)
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc
