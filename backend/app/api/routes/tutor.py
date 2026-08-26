from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.deps import get_caller_context
from backend.app.auth.permissions import (
    PermissionDenied,
    can_approve_student,
    can_read_job,
    can_read_student,
    require_job_access,
    require_job_decision_access,
)
from backend.app.db.models import (
    AgentRun,
    Artifact,
    AuditEvent,
    MasteryEvidence,
    MasteryState,
    ToolCallRecord,
    TutorAlert,
    TutorCorrection,
    TutorDecision,
    TutorEvidenceExclusion,
)
from backend.app.db.session import get_db
from backend.app.services.jobs import get_job, list_jobs
from backend.app.services.mastery import get_effective_mastery, get_history, upsert_mastery_state
from backend.app.schemas.review import TutorAlertResolveRequest

router = APIRouter(prefix="/api/tutor", tags=["tutor"])
VALID_ACTIONS = {"accept", "edit", "reject", "more_evidence", "exclude_evidence"}
VALID_LABELS = {"insufficient_evidence", "requires_support", "developing", "secure"}
VALID_ALERT_RESOLUTIONS = {
    "acknowledged",
    "collect_more_evidence",
    "corrected",
    "dismissed",
    "keep_blocked",
    "resolved",
    "supported_content_selected",
}


def _audit(
    db: Session,
    caller: CallerContext,
    event: str,
    entity_type: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            id=f"aud-{uuid.uuid4().hex[:8]}",
            centre_id=caller.centre_id,
            actor_id=caller.user_id,
            actor_role=caller.role,
            event=event,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=json.dumps(before, sort_keys=True) if before is not None else None,
            after_json=json.dumps(after, sort_keys=True) if after is not None else None,
            created_at=datetime.now(timezone.utc),
        )
    )


def _forbidden(exc: Exception) -> HTTPException:
    return HTTPException(status_code=403, detail="forbidden")


@router.get("/jobs/{job_id}")
def get_trace(
    job_id: str,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    if caller.role not in ("tutor", "admin", "worker"):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        require_job_access(db, caller, job)
    except PermissionDenied as exc:
        raise _forbidden(exc) from exc

    runs = db.query(AgentRun).filter(AgentRun.job_id == job.id).order_by(AgentRun.attempt.asc()).all()
    tool_calls = db.query(ToolCallRecord).filter_by(job_id=job.id).order_by(ToolCallRecord.created_at.asc()).all()
    artifacts = db.query(Artifact).filter(Artifact.job_id == job.id).order_by(Artifact.version.asc()).all()
    alerts = db.query(TutorAlert).filter(TutorAlert.job_id == job.id).order_by(TutorAlert.created_at.asc()).all()
    decisions = db.query(TutorDecision).filter(TutorDecision.job_id == job.id).order_by(TutorDecision.created_at.asc()).all()
    job_input = json.loads(job.input_json)
    subskill_id = job_input.get("subskill_id")
    effective_state = get_effective_mastery(db, job.student_id, subskill_id) if job.student_id and subskill_id else None
    mastery_history = get_history(db, job.student_id, subskill_id) if job.student_id and subskill_id else []
    corrections = (
        db.query(TutorCorrection)
        .filter(TutorCorrection.job_id == job.id)
        .order_by(TutorCorrection.created_at.asc())
        .all()
    )
    evidence_exclusions = (
        db.query(TutorEvidenceExclusion)
        .filter(TutorEvidenceExclusion.job_id == job.id)
        .order_by(TutorEvidenceExclusion.created_at.asc())
        .all()
    )

    def run_error(run: AgentRun):
        return json.loads(run.error_json) if run.error_json else None

    def validation_result(run: AgentRun):
        error = run_error(run)
        if error is None:
            return {"status": "passed" if run.output_json else "not_run"}
        if error.get("code") in {
            "low_evidence",
            "conflicting_evidence",
            "insufficient_history",
            "parent_report_requires_tutor_review",
            "unsupported_content",
        }:
            return {"status": "passed", "review_required": True, "reason": error["code"]}
        return {"status": "failed", "reason": error.get("code", "worker_error")}

    latest_run = runs[-1] if runs else None
    return {
        "job": {
            "id": job.id,
            "type": job.job_type,
            "status": job.status,
            "centre_id": job.centre_id,
            "student_id": job.student_id,
            "input": job_input,
            "idempotency_key": job.idempotency_key,
            "retry_count": job.retry_count,
            "max_retries": job.max_retries,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "claimed_by": job.claimed_by,
        },
        "effective_mastery": (
            {
                "id": effective_state.id,
                "version": effective_state.version,
                "label": effective_state.label,
                "eligible_attempts": effective_state.eligible_attempts,
                "correct_attempts": effective_state.correct_attempts,
                "accuracy": effective_state.accuracy,
                "confidence": effective_state.confidence,
                "policy_id": effective_state.policy_id,
                "policy_version": effective_state.policy_version,
                "is_override": effective_state.is_override,
                "created_at": effective_state.created_at.isoformat() if effective_state.created_at else None,
            }
            if effective_state
            else None
        ),
        "runs": [
            {
                "id": run.id,
                "attempt": run.attempt,
                "provider": run.provider,
                "model_id": run.model_id,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "duration_ms": run.duration_ms,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "cost_usd": run.cost_usd,
                "error": run_error(run),
                "output": json.loads(run.output_json) if run.output_json else None,
                "validation": validation_result(run),
            }
            for run in runs
        ],
        "tool_calls": [
            {
                "tool": call.tool_name,
                "request": json.loads(call.request_json),
                "response": json.loads(call.response_json) if call.response_json else None,
                "created_at": call.created_at.isoformat(),
            }
            for call in tool_calls
        ],
        "artifacts": [
            {
                "id": artifact.id,
                "type": artifact.type,
                "version": artifact.version,
                "payload": json.loads(artifact.payload_json),
                "run_id": artifact.run_id,
                "created_at": artifact.created_at.isoformat(),
            }
            for artifact in artifacts
        ],
        "alerts": [
            {
                "id": alert.id,
                "type": alert.type,
                "message": alert.message,
                "status": alert.status,
                "resolution": alert.resolution,
                "resolution_reason": alert.resolution_reason,
                "resolved_by": alert.resolved_by,
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                "created_at": alert.created_at.isoformat(),
            }
            for alert in alerts
        ],
        "decisions": [
            {
                "id": decision.id,
                "action": decision.action,
                "actor_id": decision.actor_id,
                "actor_role": decision.actor_role,
                "reason": decision.reason,
                "corrected_label": decision.corrected_label,
                "evidence_id": decision.evidence_id,
                "alert_id": decision.alert_id,
                "correction_id": decision.correction_id,
                "artifact_id": decision.artifact_id,
                "created_at": decision.created_at.isoformat(),
            }
            for decision in decisions
        ],
        "corrections": [
            {
                "id": correction.id,
                "job_id": correction.job_id,
                "artifact_id": correction.artifact_id,
                "original_state_id": correction.original_state_id,
                "corrected_label": correction.corrected_label,
                "author_tutor_id": correction.author_tutor_id,
                "reason": correction.reason,
                "supersedes_version": correction.supersedes_version,
                "created_at": correction.created_at.isoformat(),
            }
            for correction in corrections
        ],
        "evidence_exclusions": [
            {
                "id": exclusion.id,
                "evidence_id": exclusion.evidence_id,
                "author_tutor_id": exclusion.author_tutor_id,
                "reason": exclusion.reason,
                "created_at": exclusion.created_at.isoformat(),
            }
            for exclusion in evidence_exclusions
        ],
        "mastery_history": [
            {
                "id": state.id,
                "version": state.version,
                "label": state.label,
                "eligible_attempts": state.eligible_attempts,
                "correct_attempts": state.correct_attempts,
                "accuracy": state.accuracy,
                "confidence": state.confidence,
                "is_override": state.is_override,
                "created_at": state.created_at.isoformat(),
            }
            for state in mastery_history
        ],
        "provenance": {
            "provider": latest_run.provider if latest_run else None,
            "model_id": latest_run.model_id if latest_run else None,
            "tool_summary": [call.tool_name for call in tool_calls],
            "stop_reason": run_error(latest_run) if latest_run and latest_run.error_json else (latest_run.status if latest_run else job.status),
        },
    }


@router.get("/jobs")
def list_tutor_jobs(
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
    student_id: str | None = None,
):
    if caller.role not in ("tutor", "admin"):
        raise HTTPException(status_code=403, detail="forbidden")
    jobs = list_jobs(db, caller.centre_id, student_id, None)
    return [
        {
            "id": job.id,
            "type": job.job_type,
            "status": job.status,
            "student_id": job.student_id,
            "input": json.loads(job.input_json),
            "created_at": job.created_at.isoformat(),
        }
        for job in jobs
        if can_read_job(db, caller, job)
    ]


def _alert_payload(alert: TutorAlert) -> dict:
    return {
        "id": alert.id,
        "job_id": alert.job_id,
        "centre_id": alert.centre_id,
        "student_id": alert.student_id,
        "subskill_id": alert.subskill_id,
        "type": alert.type,
        "message": alert.message,
        "status": alert.status,
        "resolution": alert.resolution,
        "resolution_reason": alert.resolution_reason,
        "resolved_by": alert.resolved_by,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


@router.get("/alerts")
def list_tutor_alerts(
    status: str | None = None,
    student_id: str | None = None,
    alert_type: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role not in ("tutor", "admin"):
        raise HTTPException(status_code=403, detail="forbidden")
    if status is not None and status not in {"open", "resolved"}:
        raise HTTPException(status_code=422, detail="invalid alert status")
    if student_id is not None and not can_read_student(db, caller, student_id):
        raise HTTPException(status_code=403, detail="forbidden")
    query = db.query(TutorAlert).filter(TutorAlert.centre_id == caller.centre_id)
    if status is not None:
        query = query.filter(TutorAlert.status == status)
    if student_id is not None:
        query = query.filter(TutorAlert.student_id == student_id)
    if alert_type is not None:
        query = query.filter(TutorAlert.type == alert_type)
    alerts = query.order_by(TutorAlert.created_at.desc(), TutorAlert.id.desc()).all()
    return [_alert_payload(alert) for alert in alerts if can_read_student(db, caller, alert.student_id)]


@router.post("/alerts/{alert_id}/resolve")
def resolve_tutor_alert(
    alert_id: str,
    reason: str | None = None,
    resolution: str | None = None,
    payload: TutorAlertResolveRequest | None = None,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if caller.role not in ("tutor", "admin"):
        raise HTTPException(status_code=403, detail="forbidden")
    alert = db.query(TutorAlert).filter(TutorAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="not found")
    if alert.centre_id != caller.centre_id or not can_approve_student(db, caller, alert.student_id):
        raise HTTPException(status_code=403, detail="forbidden")
    selected_reason = payload.reason if payload is not None else reason
    selected_resolution = payload.resolution if payload is not None else (resolution or "acknowledged")
    if not selected_reason or not selected_reason.strip():
        raise HTTPException(status_code=422, detail="reason is required")
    if selected_resolution not in VALID_ALERT_RESOLUTIONS:
        raise HTTPException(status_code=422, detail="invalid alert resolution")
    if alert.status == "resolved":
        return {"status": "resolved", "alert": _alert_payload(alert)}

    job = get_job(db, alert.job_id)
    if not job:
        raise HTTPException(status_code=409, detail="alert job not found")
    now = datetime.now(timezone.utc)
    alert.status = "resolved"
    alert.resolution = selected_resolution
    alert.resolution_reason = selected_reason.strip()
    alert.resolved_by = caller.user_id
    alert.resolved_at = now
    latest_artifact = (
        db.query(Artifact)
        .filter(Artifact.job_id == job.id)
        .order_by(Artifact.version.desc())
        .first()
    )
    decision = TutorDecision(
        id=f"decision-{uuid.uuid4().hex[:8]}",
        job_id=job.id,
        artifact_id=latest_artifact.id if latest_artifact else None,
        centre_id=caller.centre_id,
        student_id=alert.student_id,
        actor_id=caller.user_id,
        actor_role=caller.role,
        action="resolve_alert",
        reason=selected_reason.strip(),
        alert_id=alert.id,
        created_at=now,
    )
    db.add(decision)
    _audit(
        db,
        caller,
        "tutor_alert.resolve",
        "tutor_alert",
        alert.id,
        before={"status": "open"},
        after={"status": "resolved", "resolution": selected_resolution, "reason": selected_reason.strip()},
    )
    db.commit()
    return {"status": "resolved", "alert": _alert_payload(alert), "decision_id": decision.id, "job_status": job.status}


@router.post("/jobs/{job_id}/decision")
def decide(
    job_id: str,
    action: str,
    reason: str | None = None,
    corrected_label: str | None = None,
    evidence_id: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if action not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail="invalid action")
    if corrected_label is not None and corrected_label not in VALID_LABELS:
        raise HTTPException(status_code=422, detail="invalid corrected_label")
    if action == "edit" and corrected_label is None:
        raise HTTPException(status_code=400, detail="corrected_label required for edit")
    if action == "exclude_evidence" and not evidence_id:
        raise HTTPException(status_code=400, detail="evidence_id required for exclude_evidence")
    if action in {"edit", "exclude_evidence"} and (not reason or not reason.strip()):
        raise HTTPException(status_code=422, detail="reason is required")
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    if job.job_type == "parent_report":
        raise HTTPException(
            status_code=409,
            detail="parent reports use the consent-gated parent report workflow",
        )
    try:
        require_job_decision_access(db, caller, job)
    except PermissionDenied as exc:
        raise _forbidden(exc) from exc
    if job.status == "cancelled" and action != "reject":
        raise HTTPException(status_code=409, detail="cancelled job cannot receive this decision")

    artifacts = db.query(Artifact).filter(Artifact.job_id == job.id).order_by(Artifact.version.desc()).all()
    if action in ("accept", "edit", "exclude_evidence") and not artifacts:
        raise HTTPException(status_code=409, detail="no artifact to decide")
    artifact = artifacts[0] if artifacts else None

    previous = (
        db.query(TutorDecision)
        .filter(
            TutorDecision.job_id == job.id,
            TutorDecision.actor_id == caller.user_id,
            TutorDecision.action == action,
            TutorDecision.reason == reason,
            TutorDecision.corrected_label == corrected_label,
            TutorDecision.evidence_id == evidence_id,
        )
        .order_by(TutorDecision.created_at.desc())
        .first()
    )
    if previous:
        return {"status": previous.action if previous.action != "more_evidence" else "more_evidence", "job_id": job.id, "decision_id": previous.id}

    now = datetime.now(timezone.utc)
    decision = TutorDecision(
        id=f"decision-{uuid.uuid4().hex[:8]}",
        job_id=job.id,
        artifact_id=artifact.id if artifact else None,
        centre_id=caller.centre_id,
        student_id=job.student_id,
        actor_id=caller.user_id,
        actor_role=caller.role,
        action=action,
        reason=reason,
        corrected_label=corrected_label,
        evidence_id=evidence_id,
        created_at=now,
    )
    db.add(decision)

    if action == "accept":
        job.status = "succeeded"
        job.updated_at = now
        _audit(db, caller, "tutor_decision.accept", "agent_job", job.id, after={"action": action, "reason": reason})
        db.commit()
        return {"status": "accepted", "job_id": job.id, "decision_id": decision.id}

    if action == "reject":
        job.status = "cancelled"
        job.updated_at = now
        _audit(db, caller, "tutor_decision.reject", "agent_job", job.id, after={"action": action, "reason": reason})
        db.commit()
        return {"status": "rejected", "job_id": job.id, "decision_id": decision.id}

    if action == "more_evidence":
        job.status = "needs_tutor_review"
        job.updated_at = now
        subskill_id = json.loads(job.input_json).get("subskill_id", "unknown")
        db.add(
            TutorAlert(
                id=f"alert-{uuid.uuid4().hex[:8]}",
                centre_id=caller.centre_id,
                student_id=job.student_id,
                subskill_id=subskill_id,
                job_id=job.id,
                type="more_evidence_requested",
                message=reason or "Tutor requested more evidence",
                created_at=now,
            )
        )
        _audit(db, caller, "tutor_decision.more_evidence", "agent_job", job.id, after={"action": action, "reason": reason})
        db.commit()
        return {"status": "more_evidence", "job_id": job.id, "decision_id": decision.id}

    subskill_id = json.loads(job.input_json).get("subskill_id")
    if action == "exclude_evidence":
        artifact_payload = json.loads(artifact.payload_json) if artifact else {}
        if evidence_id not in set(artifact_payload.get("evidence_ids", [])):
            raise HTTPException(status_code=422, detail="evidence_id is not part of the proposal")
        evidence = (
            db.query(MasteryEvidence)
            .filter(
                MasteryEvidence.id == evidence_id,
                MasteryEvidence.student_id == job.student_id,
                MasteryEvidence.centre_id == caller.centre_id,
                MasteryEvidence.subskill_id == subskill_id,
            )
            .first()
        )
        if not evidence:
            raise HTTPException(status_code=404, detail="evidence not found")
        if db.query(TutorEvidenceExclusion).filter(TutorEvidenceExclusion.evidence_id == evidence_id).first():
            raise HTTPException(status_code=409, detail="evidence is already excluded")
        latest_state = (
            db.query(MasteryState)
            .filter(
                MasteryState.student_id == job.student_id,
                MasteryState.subskill_id == subskill_id,
                MasteryState.centre_id == caller.centre_id,
            )
            .order_by(MasteryState.version.desc())
            .with_for_update()
            .first()
        )
        if not latest_state:
            raise HTTPException(status_code=409, detail="no mastery state to update")
        exclusion = TutorEvidenceExclusion(
            id=f"exclude-{uuid.uuid4().hex[:8]}",
            centre_id=caller.centre_id,
            evidence_id=evidence_id,
            student_id=job.student_id,
            subskill_id=subskill_id,
            author_tutor_id=caller.user_id,
            job_id=job.id,
            reason=(reason or "tutor excluded evidence").strip(),
            created_at=now,
        )
        db.add(exclusion)
        decision.evidence_id = evidence_id
        db.flush()
        updated_state = upsert_mastery_state(db, job.student_id, subskill_id)
        job.status = "needs_tutor_review"
        job.updated_at = now
        _audit(
            db,
            caller,
            "tutor_decision.exclude_evidence",
            "tutor_evidence_exclusion",
            exclusion.id,
            before={"effective_state_id": latest_state.id, "eligible_attempts": latest_state.eligible_attempts},
            after={"effective_state_id": updated_state.id, "eligible_attempts": updated_state.eligible_attempts, "evidence_id": evidence_id},
        )
        db.commit()
        return {
            "status": "evidence_excluded",
            "job_id": job.id,
            "decision_id": decision.id,
            "exclusion_id": exclusion.id,
            "new_state_id": updated_state.id,
            "label": updated_state.label,
            "eligible_attempts": updated_state.eligible_attempts,
        }

    latest_state = (
        db.query(MasteryState)
        .filter(MasteryState.student_id == job.student_id, MasteryState.subskill_id == subskill_id)
        .filter(MasteryState.centre_id == caller.centre_id)
        .order_by(MasteryState.version.desc())
        .with_for_update()
        .first()
    )
    if not latest_state:
        raise HTTPException(status_code=409, detail="no mastery state to correct")
    correction = TutorCorrection(
        id=f"corr-{uuid.uuid4().hex[:8]}",
        centre_id=caller.centre_id,
        student_id=job.student_id,
        subskill_id=subskill_id,
        author_tutor_id=caller.user_id,
        original_state_id=latest_state.id,
        job_id=job.id,
        artifact_id=artifact.id if artifact else None,
        corrected_label=corrected_label,
        reason=reason or "tutor edit",
        supersedes_version=latest_state.version,
    )
    db.add(correction)
    decision.correction_id = correction.id
    override = MasteryState(
        id=f"mst-{uuid.uuid4().hex[:8]}",
        centre_id=caller.centre_id,
        student_id=job.student_id,
        subskill_id=subskill_id,
        version=latest_state.version + 1,
        eligible_attempts=latest_state.eligible_attempts,
        correct_attempts=latest_state.correct_attempts,
        accuracy=latest_state.accuracy,
        confidence=latest_state.confidence,
        label=corrected_label,
        policy_id=latest_state.policy_id,
        policy_version=latest_state.policy_version,
        is_override=True,
        created_at=now,
    )
    db.add(override)
    job.status = "succeeded"
    job.updated_at = now
    _audit(db, caller, "tutor_decision.edit", "mastery_state", override.id, before={"label": latest_state.label}, after={"label": corrected_label, "reason": reason, "correction_id": correction.id, "artifact_id": artifact.id if artifact else None})
    db.commit()
    return {"status": "edited", "correction_id": correction.id, "new_state_id": override.id, "label": corrected_label, "decision_id": decision.id}
