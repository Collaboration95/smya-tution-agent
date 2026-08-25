from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.agents.diagnostic import run_diagnostic
from backend.app.auth.context import CallerContext
from backend.app.auth.deps import get_caller_context
from backend.app.auth.permissions import PermissionDenied, require_job_access, require_read_student
from backend.app.db.models import Attempt, Question, Student
from backend.app.db.session import get_db
from backend.app.models.client import get_model_client
from backend.app.services.jobs import claim_specific_job, create_job, get_job

router = APIRouter(prefix="/api/diagnostic", tags=["diagnostic"])


@router.post("/jobs")
def create_diagnostic_job(
    student_id: str,
    subskill_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role not in ("admin", "tutor", "worker"):
        raise HTTPException(status_code=403, detail="only staff or worker may create diagnostic jobs")
    try:
        require_read_student(db, caller, student_id)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    student = db.query(Student).filter(Student.id == student_id, Student.centre_id == caller.centre_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="student not found")
    payload = {"student_id": student_id, "subskill_id": subskill_id, "trigger": "manual_request"}
    try:
        job = create_job(db, "diagnostic", caller.centre_id, student_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return {"job_id": job.id, "status": job.status, "idempotency_key": job.idempotency_key}


@router.post("/events/attempt-completed")
def attempt_completed(
    attempt_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role not in ("admin", "tutor", "worker"):
        raise HTTPException(status_code=403, detail="only staff or worker may create diagnostic jobs")
    attempt = (
        db.query(Attempt)
        .join(Student, Attempt.student_id == Student.id)
        .join(Question, Attempt.question_id == Question.id)
        .filter(
            Attempt.id == attempt_id,
            Attempt.grading_status == "graded",
            Student.centre_id == caller.centre_id,
            or_(Question.centre_id == caller.centre_id, Question.centre_id.is_(None)),
        )
        .first()
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="completed attempt not found")
    try:
        require_read_student(db, caller, attempt.student_id)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    student = db.query(Student).filter(Student.id == attempt.student_id, Student.centre_id == caller.centre_id).first()
    question = (
        db.query(Question)
        .filter(
            Question.id == attempt.question_id,
            or_(Question.centre_id == caller.centre_id, Question.centre_id.is_(None)),
        )
        .first()
    )
    if not student or not question:
        raise HTTPException(status_code=404, detail="attempt context not found")
    payload = {
        "student_id": student.id,
        "subskill_id": question.subskill_id,
        "attempt_id": attempt.id,
        "trigger": "attempt_completed",
    }
    try:
        job = create_job(db, "diagnostic", student.centre_id, student.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return {"job_id": job.id, "status": job.status, "idempotency_key": job.idempotency_key}


@router.post("/jobs/{job_id}/run")
def run(
    job_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role not in ("worker", "tutor", "admin"):
        raise HTTPException(status_code=403, detail="forbidden")
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    try:
        require_job_access(db, caller, job)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    worker_id = caller.user_id if caller.role == "worker" else f"worker-http:{caller.user_id}"
    claimed = claim_specific_job(db, job.id, worker_id)
    if not claimed:
        raise HTTPException(status_code=409, detail=f"job is not runnable from {job.status}")
    result = run_diagnostic(db, claimed, get_model_client())
    return result


@router.get("/jobs/{job_id}")
def read(
    job_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    try:
        require_job_access(db, caller, job)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    return {
        "id": job.id,
        "type": job.job_type,
        "status": job.status,
        "input": json.loads(job.input_json),
        "retry_count": job.retry_count,
    }
