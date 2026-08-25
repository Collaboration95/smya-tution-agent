from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.deps import get_caller_context
from backend.app.auth.permissions import (
    PermissionDenied,
    can_read_job,
    require_job_access,
    require_read_student,
)
from backend.app.db.session import get_db
from backend.app.schemas.jobs import JobCreateRequest, JobResponse
from backend.app.services.jobs import create_job, get_job, heartbeat, list_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse)
def create(
    job_req: JobCreateRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role not in ("admin", "tutor", "worker"):
        raise HTTPException(status_code=403, detail="only staff or worker may create jobs")
    if job_req.centre_id and job_req.centre_id != caller.centre_id:
        raise HTTPException(status_code=403, detail="client centre_id does not match caller")
    if job_req.student_id:
        try:
            require_read_student(db, caller, job_req.student_id)
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    elif caller.role not in ("admin", "worker"):
        raise HTTPException(status_code=403, detail="student scope is required for tutor jobs")
    payload_student_id = job_req.input_payload.get("student_id")
    if payload_student_id and payload_student_id != job_req.student_id:
        raise HTTPException(status_code=422, detail="input_payload.student_id must match student_id")
    try:
        job = create_job(
            db,
            job_req.job_type,
            caller.centre_id,
            job_req.student_id,
            job_req.input_payload,
            job_req.max_retries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return job


@router.get("/{job_id}", response_model=JobResponse)
def read_job(
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
    return job


@router.get("", response_model=list[JobResponse])
def list_all(
    centre_id: str | None = None,
    student_id: str | None = None,
    status: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if centre_id and centre_id != caller.centre_id:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        jobs = list_jobs(db, caller.centre_id, student_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if caller.role == "worker":
        jobs = [job for job in jobs if caller.job_id == job.id]
    else:
        jobs = [job for job in jobs if can_read_job(db, caller, job)]
    return jobs


@router.post("/{job_id}/heartbeat")
def hb(
    job_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role != "worker":
        raise HTTPException(status_code=403, detail="only a worker may heartbeat a job")
    job = get_job(db, job_id)
    if not job or caller.job_id != job.id:
        raise HTTPException(status_code=403, detail="forbidden")
    if not heartbeat(db, job_id, caller.user_id):
        raise HTTPException(status_code=409, detail="not claimed by you or not running")
    db.commit()
    return {"ok": True}
