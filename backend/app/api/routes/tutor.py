from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.db.session import get_db
from backend.app.auth.deps import get_caller_context
from backend.app.auth.context import CallerContext
from backend.app.services.jobs import get_job
from backend.app.db.models import AgentRun, ToolCallRecord, Artifact, TutorAlert, TutorCorrection, MasteryState
from backend.app.auth.permissions import can_read_student

router = APIRouter(prefix="/api/tutor", tags=["tutor"])

@router.get("/jobs/{job_id}")
def get_trace(job_id: str, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    # Scope: only tutor/admin for assigned student can view
    if caller.role not in ("tutor", "admin", "worker"):
        # Students/guardians cannot view traces
        raise HTTPException(status_code=403, detail="forbidden")
    if caller.centre_id != job.centre_id and caller.role != "worker":
        raise HTTPException(status_code=403, detail="forbidden")
    if job.student_id and not can_read_student(db, caller, job.student_id) and caller.role != "worker":
        raise HTTPException(status_code=403, detail="not assigned to student")
    runs = db.query(AgentRun).filter(AgentRun.job_id == job.id).order_by(AgentRun.attempt.asc()).all()
    tcs = db.query(ToolCallRecord).filter(ToolCallRecord.job_id == job.id).order_by(ToolCallRecord.created_at.asc()).all()
    arts = db.query(Artifact).filter(Artifact.job_id == job.id).order_by(Artifact.version.asc()).all()
    alerts = db.query(TutorAlert).filter(TutorAlert.job_id == job.id).all()
    # Build trace without exposing hidden reasoning or out-of-scope data
    trace = {
        "job": {
            "id": job.id,
            "type": job.job_type,
            "status": job.status,
            "centre_id": job.centre_id,
            "student_id": job.student_id,
            "input": json.loads(job.input_json),
            "idempotency_key": job.idempotency_key,
            "retry_count": job.retry_count,
            "max_retries": job.max_retries,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "claimed_by": job.claimed_by,
        },
        "runs": [
            {
                "id": r.id,
                "attempt": r.attempt,
                "provider": r.provider,
                "model_id": r.model_id,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "duration_ms": r.duration_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": r.cost_usd,
                "error": json.loads(r.error_json) if r.error_json else None,
                "output": json.loads(r.output_json) if r.output_json else None,
            } for r in runs
        ],
        "tool_calls": [
            {"tool": tc.tool_name, "request": json.loads(tc.request_json), "response": json.loads(tc.response_json) if tc.response_json else None, "created_at": tc.created_at.isoformat()}
            for tc in tcs
        ],
        "artifacts": [
            {"id": a.id, "type": a.type, "version": a.version, "payload": json.loads(a.payload_json), "run_id": a.run_id, "created_at": a.created_at.isoformat()}
            for a in arts
        ],
        "alerts": [
            {"id": al.id, "type": al.type, "message": al.message, "created_at": al.created_at.isoformat()} for al in alerts
        ],
        "provenance": {
            "provider": runs[-1].provider if runs else None,
            "model_id": runs[-1].model_id if runs else None,
            "tool_summary": [tc.tool_name for tc in tcs],
            "stop_reason": runs[-1].error_json if runs and runs[-1].error_json else (runs[-1].status if runs else job.status),
        }
    }
    return trace

@router.get("/jobs")
def list_tutor_jobs(caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db), student_id: str | None = None):
    from backend.app.services.jobs import list_jobs
    if caller.role not in ("tutor", "admin", "worker"):
        raise HTTPException(status_code=403, detail="forbidden")
    jobs = list_jobs(db, caller.centre_id, student_id, None)
    # Filter to only assigned students for tutor
    if caller.role == "tutor":
        # keep only jobs where student is assigned
        filtered = []
        for j in jobs:
            if j.student_id and can_read_student(db, caller, j.student_id):
                filtered.append(j)
        jobs = filtered
    return [{"id": j.id, "type": j.job_type, "status": j.status, "student_id": j.student_id, "input": json.loads(j.input_json), "created_at": j.created_at.isoformat()} for j in jobs]

@router.post("/jobs/{job_id}/decision")
def decide(job_id: str, action: str, reason: str | None = None, corrected_label: str | None = None, caller: CallerContext = Depends(get_caller_context), db: Session = Depends(get_db)):
    """
    Actions: accept | edit | reject | more_evidence
    - accept: mark artifact as accepted (audit only; job stays succeeded)
    - edit: tutor provides corrected_label, creates TutorCorrection and override MasteryState
    - reject: mark job as cancelled/rejected
    - more_evidence: mark needs_more_evidence
    """
    if caller.role not in ("tutor", "admin"):
        raise HTTPException(status_code=403, detail="only tutor can decide")
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    if not can_read_student(db, caller, job.student_id):
        raise HTTPException(status_code=403, detail="not assigned")
    if action not in ("accept", "edit", "reject", "more_evidence"):
        raise HTTPException(status_code=400, detail="invalid action")
    from backend.app.db.models import TutorCorrection, MasteryState, AuditEvent
    import uuid as _uuid
    # Ensure artifact exists for accept/edit
    arts = db.query(Artifact).filter(Artifact.job_id == job.id).all()
    if action in ("accept", "edit") and not arts:
        raise HTTPException(status_code=409, detail="no artifact to accept")
    now = datetime.now(timezone.utc)
    if action == "accept":
        ae = AuditEvent(id=f"aud-{_uuid.uuid4().hex[:8]}", centre_id=caller.centre_id, actor_id=caller.user_id, actor_role=caller.role, event="tutor_decision.accept", entity_type="agent_job", entity_id=job.id, after_json=json.dumps({"action": action, "reason": reason}), created_at=now)
        db.add(ae)
        db.commit()
        return {"status": "accepted", "job_id": job.id}
    if action == "reject":
        job.status = "cancelled"
        job.updated_at = now
        ae = AuditEvent(id=f"aud-{_uuid.uuid4().hex[:8]}", centre_id=caller.centre_id, actor_id=caller.user_id, actor_role=caller.role, event="tutor_decision.reject", entity_type="agent_job", entity_id=job.id, after_json=json.dumps({"action": action, "reason": reason}), created_at=now)
        db.add(ae)
        db.commit()
        return {"status": "rejected", "job_id": job.id}
    if action == "more_evidence":
        job.status = "needs_tutor_review"
        job.updated_at = now
        alert = TutorAlert(id=f"alert-{_uuid.uuid4().hex[:8]}", centre_id=caller.centre_id, student_id=job.student_id, subskill_id=json.loads(job.input_json).get("subskill_id","unknown"), job_id=job.id, type="more_evidence_requested", message=reason or "Tutor requested more evidence", created_at=now)
        db.add(alert)
        ae = AuditEvent(id=f"aud-{_uuid.uuid4().hex[:8]}", centre_id=caller.centre_id, actor_id=caller.user_id, actor_role=caller.role, event="tutor_decision.more_evidence", entity_type="agent_job", entity_id=job.id, after_json=json.dumps({"action": action, "reason": reason}), created_at=now)
        db.add(ae)
        db.commit()
        return {"status": "more_evidence", "job_id": job.id}
    if action == "edit":
        if not corrected_label:
            raise HTTPException(status_code=400, detail="corrected_label required for edit")
        # Create correction and override mastery state
        latest_state = db.query(MasteryState).filter(MasteryState.student_id == job.student_id, MasteryState.subskill_id == json.loads(job.input_json).get("subskill_id")).order_by(MasteryState.version.desc()).first()
        if not latest_state:
            raise HTTPException(status_code=409, detail="no mastery state to correct")
        corr = TutorCorrection(id=f"corr-{_uuid.uuid4().hex[:8]}", student_id=job.student_id, subskill_id=json.loads(job.input_json).get("subskill_id"), author_tutor_id=caller.user_id, original_state_id=latest_state.id, corrected_label=corrected_label, reason=reason or "tutor edit", supersedes_version=latest_state.version)
        db.add(corr)
        # Create override mastery state with new label but same metrics
        override = MasteryState(id=f"mst-{_uuid.uuid4().hex[:8]}", student_id=job.student_id, subskill_id=latest_state.subskill_id, version=latest_state.version+1, eligible_attempts=latest_state.eligible_attempts, correct_attempts=latest_state.correct_attempts, accuracy=latest_state.accuracy, confidence=latest_state.confidence, label=corrected_label, policy_id=latest_state.policy_id, policy_version=latest_state.policy_version, is_override=True, created_at=now)
        db.add(override)
        ae = AuditEvent(id=f"aud-{_uuid.uuid4().hex[:8]}", centre_id=caller.centre_id, actor_id=caller.user_id, actor_role=caller.role, event="tutor_decision.edit", entity_type="mastery_state", entity_id=override.id, before_json=json.dumps({"label": latest_state.label}), after_json=json.dumps({"label": corrected_label, "reason": reason}), created_at=now)
        db.add(ae)
        db.commit()
        return {"status": "edited", "correction_id": corr.id, "new_state_id": override.id, "label": corrected_label}
