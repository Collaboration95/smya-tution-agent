from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.agents.parent_report import run_parent_report
from backend.app.auth.context import CallerContext
from backend.app.auth.deps import get_caller_context
from backend.app.auth.permissions import PermissionDenied, require_job_access
from backend.app.db.models import ParentReportDraft
from backend.app.db.session import get_db
from backend.app.models.client import get_model_client
from backend.app.reports.service import create_parent_report_job
from backend.app.schemas.reports import (
    ParentReportDraftResponse,
    ParentReportJobRequest,
    ParentReportJobResponse,
)
from backend.app.services.jobs import claim_specific_job, get_job


router = APIRouter(prefix="/api/parent-reports", tags=["parent-reports"])


@router.post("/jobs", response_model=ParentReportJobResponse)
def create(
    request: ParentReportJobRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        job = create_parent_report_job(db, caller, request)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return ParentReportJobResponse(job_id=job.id, status=job.status, idempotency_key=job.idempotency_key)


@router.post("/jobs/{job_id}/run")
def run(
    job_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role not in ("admin", "tutor", "worker"):
        raise HTTPException(status_code=403, detail="forbidden")
    job = get_job(db, job_id)
    if not job or job.job_type != "parent_report":
        raise HTTPException(status_code=404, detail="not found")
    try:
        require_job_access(db, caller, job)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    worker_id = caller.user_id if caller.role == "worker" else f"worker-http:{caller.user_id}"
    claimed = claim_specific_job(db, job.id, worker_id)
    if not claimed:
        raise HTTPException(status_code=409, detail=f"job is not runnable from {job.status}")
    return run_parent_report(db, claimed, get_model_client())


@router.get("/jobs/{job_id}", response_model=ParentReportDraftResponse)
def read_draft(
    job_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role not in ("admin", "tutor", "worker"):
        raise HTTPException(status_code=403, detail="forbidden")
    job = get_job(db, job_id)
    if not job or job.job_type != "parent_report":
        raise HTTPException(status_code=404, detail="not found")
    try:
        require_job_access(db, caller, job)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    draft = (
        db.query(ParentReportDraft)
        .filter(ParentReportDraft.job_id == job.id)
        .order_by(ParentReportDraft.created_at.desc())
        .first()
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return ParentReportDraftResponse(
        id=draft.id,
        job_id=draft.job_id,
        artifact_id=draft.artifact_id,
        student_id=draft.student_id,
        status=draft.status,
        snapshot_ids=json.loads(draft.snapshot_ids_json),
        evidence_ids=json.loads(draft.evidence_ids_json),
        content=json.loads(draft.content_json),
    )
