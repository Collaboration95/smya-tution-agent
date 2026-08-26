from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.agents.parent_report import run_parent_report
from backend.app.auth.context import CallerContext
from backend.app.auth.deps import get_caller_context
from backend.app.auth.permissions import PermissionDenied, require_job_access
from backend.app.communication.delivery import (
    DeliveryBlocked,
    approve_parent_report,
    deliver_parent_report,
    get_parent_report_delivery,
    get_parent_report_draft,
    queue_parent_report,
    reject_parent_report,
    serialize_delivery_response,
    serialize_draft,
)
from backend.app.db.models import ParentReportDraft
from backend.app.db.session import get_db
from backend.app.models.client import get_model_client
from backend.app.reports.service import create_parent_report_job
from backend.app.schemas.reports import (
    ParentReportApproveRequest,
    ParentReportDeliveryResponse,
    ParentReportDraftResponse,
    ParentReportJobRequest,
    ParentReportJobResponse,
    ParentReportRejectRequest,
)
from backend.app.services.jobs import claim_specific_job, get_job


router = APIRouter(prefix="/api/parent-reports", tags=["parent-reports"])


def _draft_response(db: Session, draft: ParentReportDraft) -> ParentReportDraftResponse:
    return ParentReportDraftResponse.model_validate(serialize_draft(db, draft))


def _permission_error(exc: PermissionDenied) -> HTTPException:
    return HTTPException(status_code=403, detail="forbidden")


def _blocked_error(exc: DeliveryBlocked) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "delivery_blocked", "reason": exc.reason, "entity_id": exc.entity_id},
    )


@router.post("/jobs", response_model=ParentReportJobResponse)
def create(
    request: ParentReportJobRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        job = create_parent_report_job(db, caller, request)
    except PermissionDenied as exc:
        raise _permission_error(exc) from exc
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
        raise _permission_error(exc) from exc
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
        raise _permission_error(exc) from exc
    draft = (
        db.query(ParentReportDraft)
        .filter(ParentReportDraft.job_id == job.id)
        .order_by(ParentReportDraft.created_at.desc())
        .first()
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return _draft_response(db, draft)


@router.get("/drafts/{draft_id}", response_model=ParentReportDraftResponse)
def read_draft_by_id(
    draft_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = get_parent_report_draft(db, caller, draft_id)
    except PermissionDenied as exc:
        raise _permission_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    return _draft_response(db, draft)


@router.post("/drafts/{draft_id}/approve", response_model=ParentReportDraftResponse)
def approve(
    draft_id: str,
    request: ParentReportApproveRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = approve_parent_report(
            db,
            caller,
            draft_id,
            request.guardian_link_id,
            request.reason,
        )
    except PermissionDenied as exc:
        raise _permission_error(exc) from exc
    except DeliveryBlocked as exc:
        db.commit()
        raise _blocked_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return _draft_response(db, draft)


@router.post("/drafts/{draft_id}/reject", response_model=ParentReportDraftResponse)
def reject(
    draft_id: str,
    request: ParentReportRejectRequest,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        draft = reject_parent_report(db, caller, draft_id, request.reason)
    except PermissionDenied as exc:
        raise _permission_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return _draft_response(db, draft)


@router.post("/drafts/{draft_id}/queue", response_model=ParentReportDraftResponse)
def queue(
    draft_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        queue_parent_report(db, caller, draft_id)
    except PermissionDenied as exc:
        raise _permission_error(exc) from exc
    except DeliveryBlocked as exc:
        db.commit()
        raise _blocked_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    draft = get_parent_report_draft(db, caller, draft_id)
    return _draft_response(db, draft)


@router.get("/deliveries/{delivery_id}", response_model=ParentReportDeliveryResponse)
def read_delivery(
    delivery_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        delivery = get_parent_report_delivery(db, caller, delivery_id)
    except PermissionDenied as exc:
        raise _permission_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    return ParentReportDeliveryResponse.model_validate(serialize_delivery_response(delivery))


@router.post("/deliveries/{delivery_id}/send", response_model=ParentReportDeliveryResponse)
def send_delivery(
    delivery_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    try:
        delivery = deliver_parent_report(db, caller, delivery_id)
    except PermissionDenied as exc:
        raise _permission_error(exc) from exc
    except DeliveryBlocked as exc:
        db.commit()
        raise _blocked_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return ParentReportDeliveryResponse.model_validate(serialize_delivery_response(delivery))
