from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.deps import get_caller_context
from backend.app.auth.permissions import PermissionDenied
from backend.app.db.session import get_db
from backend.app.practice.service import (
    get_assignment,
    get_session,
    list_assignments,
    request_hint,
    serialize_assignment,
    serialize_session,
    start_assignment,
    submit_answer,
)
from backend.app.schemas.practice import PracticeAnswerRequest, PracticeHintRequest


router = APIRouter(prefix="/api/practice", tags=["practice"])


def _failure(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionDenied):
        return HTTPException(status_code=403, detail=str(exc))
    message = str(exc)
    if "not found" in message:
        return HTTPException(status_code=404, detail=message)
    if "cannot" in message or "only the assigned" in message or "only the" in message:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.get("/assignments")
def assignments(
    student_id: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        return list_assignments(db, caller=caller, student_id=student_id)
    except (PermissionDenied, ValueError) as exc:
        raise _failure(exc) from exc

@router.get("/assignments/{assignment_id}")
def assignment(
    assignment_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        return serialize_assignment(db, get_assignment(db, caller=caller, assignment_id=assignment_id))
    except (PermissionDenied, ValueError) as exc:
        raise _failure(exc) from exc


@router.post("/assignments/{assignment_id}/start")
def start(
    assignment_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        session = start_assignment(db, caller=caller, assignment_id=assignment_id)
        db.commit()
        return serialize_session(db, session)
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc


@router.get("/sessions/{session_id}")
def session(
    session_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        return serialize_session(db, get_session(db, caller=caller, session_id=session_id))
    except (PermissionDenied, ValueError) as exc:
        raise _failure(exc) from exc


@router.post("/sessions/{session_id}/hint")
def hint(
    session_id: str,
    request: PracticeHintRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        result = request_hint(db, caller=caller, session_id=session_id, question_id=request.question_id)
        db.commit()
        return result
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc


@router.post("/sessions/{session_id}/answers")
def answer(
    session_id: str,
    request: PracticeAnswerRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        result = submit_answer(
            db,
            caller=caller,
            session_id=session_id,
            question_id=request.question_id,
            answer=request.answer,
        )
        db.commit()
        return result
    except (PermissionDenied, ValueError) as exc:
        db.rollback()
        raise _failure(exc) from exc
