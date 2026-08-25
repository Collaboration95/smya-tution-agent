from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.db.session import get_db
from backend.app.auth.deps import get_caller_context
from backend.app.auth.context import CallerContext
from backend.app.services.jobs import create_job, get_job
from backend.app.db.models import MasteryEvidence, MasteryState
from backend.app.services.mastery import get_eligible_attempts
from backend.app.agents.diagnostic import run_diagnostic
from backend.app.models.client import get_model_client

router = APIRouter(prefix="/api/diagnostic", tags=["diagnostic"])

@router.post("/jobs")
def create_diagnostic_job(student_id: str, subskill_id: str, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    from backend.app.auth.permissions import require_read_student
    try:
        require_read_student(db, caller, student_id)
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))
    payload = {"student_id": student_id, "subskill_id": subskill_id}
    job = create_job(db, "diagnostic", caller.centre_id, student_id, payload)
    db.commit()
    return {"job_id": job.id, "status": job.status, "idempotency_key": job.idempotency_key}

@router.post("/jobs/{job_id}/run")
def run(job_id: str, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    # Only worker or tutor can trigger run in S1 (tutor manual refresh)
    if caller.role not in ("worker", "tutor", "admin"):
        raise HTTPException(status_code=403, detail="forbidden")
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    if caller.centre_id != job.centre_id:
        raise HTTPException(status_code=403, detail="forbidden")
    client = get_model_client()
    result = run_diagnostic(db, job, client)
    return result

@router.get("/jobs/{job_id}")
def read(job_id: str, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    if caller.centre_id != job.centre_id and caller.role != "worker":
        raise HTTPException(status_code=403, detail="forbidden")
    return {"id": job.id, "type": job.job_type, "status": job.status, "input": json.loads(job.input_json), "retry_count": job.retry_count}
