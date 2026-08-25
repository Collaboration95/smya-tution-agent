from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.db.session import get_db
from backend.app.auth.deps import get_caller_context
from backend.app.auth.context import CallerContext
from backend.app.services.jobs import create_job, get_job, list_jobs, claim_job, heartbeat
from backend.app.schemas.jobs import JobCreateRequest, JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

@router.post("", response_model=JobResponse)
def create(job_req: JobCreateRequest, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    # For S1, any tutor/admin/worker can create diagnostic jobs for students they can read
    if job_req.student_id:
        from backend.app.auth.permissions import require_read_student
        try:
            require_read_student(db, caller, job_req.student_id)
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
    job = create_job(db, job_req.job_type, job_req.centre_id or caller.centre_id, job_req.student_id, job_req.input_payload, job_req.max_retries)
    db.commit()
    return job

@router.get("/{job_id}", response_model=JobResponse)
def read_job(job_id: str, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    # Scope check
    if caller.centre_id != job.centre_id and caller.role != "worker":
        raise HTTPException(status_code=403, detail="forbidden")
    if job.student_id and caller.role in ("student","guardian"):
        from backend.app.auth.permissions import can_read_student
        if not can_read_student(db, caller, job.student_id):
            raise HTTPException(status_code=403, detail="forbidden")
    return job

@router.get("", response_model=list[JobResponse])
def list_all(centre_id: str | None = None, student_id: str | None = None, status: str | None = None, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    # Tutor can only list within centre
    cid = centre_id or caller.centre_id
    if caller.centre_id != cid and caller.role != "worker":
        raise HTTPException(status_code=403, detail="forbidden")
    return list_jobs(db, cid, student_id, status)

@router.post("/{job_id}/heartbeat")
def hb(job_id: str, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    ok = heartbeat(db, job_id, caller.user_id)
    if not ok:
        raise HTTPException(status_code=409, detail="not claimed by you or not running")
    db.commit()
    return {"ok": True}
