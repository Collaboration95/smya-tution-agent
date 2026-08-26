from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.deps import get_caller_context
from backend.app.auth.permissions import PermissionDenied, can_read_job, require_job_access, require_job_decision_access
from backend.app.db.models import (
    AgentRun,
    Artifact,
    AuditEvent,
    MasteryState,
    ToolCallRecord,
    TutorAlert,
    TutorCorrection,
    TutorDecision,
)
from backend.app.db.session import get_db
from backend.app.services.jobs import get_job, list_jobs
from backend.app.services.mastery import get_effective_mastery

router = APIRouter(prefix="/api/tutor", tags=["tutor"])
VALID_ACTIONS = {"accept", "edit", "reject", "more_evidence"}
VALID_LABELS = {"insufficient_evidence", "requires_support", "developing", "secure"}


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
    effective_state = get_effective_mastery(db, job.student_id, job_input.get("subskill_id")) if job.student_id and job_input.get("subskill_id") else None

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
            {"id": alert.id, "type": alert.type, "message": alert.message, "created_at": alert.created_at.isoformat()}
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
                "artifact_id": decision.artifact_id,
                "created_at": decision.created_at.isoformat(),
            }
            for decision in decisions
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


@router.post("/jobs/{job_id}/decision")
def decide(
    job_id: str,
    action: str,
    reason: str | None = None,
    corrected_label: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    db: Session = Depends(get_db),
):
    if action not in VALID_ACTIONS:
        raise HTTPException(status_code=400, detail="invalid action")
    if corrected_label is not None and corrected_label not in VALID_LABELS:
        raise HTTPException(status_code=422, detail="invalid corrected_label")
    if action == "edit" and corrected_label is None:
        raise HTTPException(status_code=400, detail="corrected_label required for edit")
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    try:
        require_job_decision_access(db, caller, job)
    except PermissionDenied as exc:
        raise _forbidden(exc) from exc
    if job.status == "cancelled" and action != "reject":
        raise HTTPException(status_code=409, detail="cancelled job cannot receive this decision")

    artifacts = db.query(Artifact).filter(Artifact.job_id == job.id).order_by(Artifact.version.desc()).all()
    if action in ("accept", "edit") and not artifacts:
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
        corrected_label=corrected_label,
        reason=reason or "tutor edit",
        supersedes_version=latest_state.version,
    )
    db.add(correction)
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
    _audit(db, caller, "tutor_decision.edit", "mastery_state", override.id, before={"label": latest_state.label}, after={"label": corrected_label, "reason": reason})
    db.commit()
    return {"status": "edited", "correction_id": correction.id, "new_state_id": override.id, "label": corrected_label, "decision_id": decision.id}
