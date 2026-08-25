from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.app.db.models import AgentJob, AgentRun, ToolCallRecord, Artifact

VALID_STATUSES = {"queued","claimed","running","succeeded","needs_tutor_review","failed_retryable","failed_terminal","cancelled"}
TERMINAL = {"succeeded","needs_tutor_review","failed_terminal","cancelled"}
RETRYABLE = {"failed_retryable"}

def _now():
    return datetime.now(timezone.utc)

def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def _duration_ms(start: datetime, end: datetime) -> int:
    return int((_aware(end) - _aware(start)).total_seconds() * 1000)

def stable_idempotency_key(job_type: str, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",",":"))
    h = hashlib.sha256(f"{job_type}:{raw}".encode()).hexdigest()[:16]
    return f"{job_type}:{h}"

def create_job(db: Session, job_type: str, centre_id: str | None, student_id: str | None, input_payload: dict, max_retries: int = 3) -> AgentJob:
    key = stable_idempotency_key(job_type, input_payload)
    existing = db.query(AgentJob).filter(AgentJob.idempotency_key == key).first()
    if existing:
        return existing
    job = AgentJob(id=f"job-{uuid.uuid4().hex[:8]}", job_type=job_type, centre_id=centre_id, student_id=student_id, input_json=json.dumps(input_payload, sort_keys=True), idempotency_key=key, status="queued", retry_count=0, max_retries=max_retries)
    db.add(job)
    db.flush()
    return job

def claim_job(db: Session, worker_id: str, job_type: str | None = None, heartbeat_timeout_s: int = 60) -> AgentJob | None:
    # First, recover stale claimed jobs
    cutoff = _now() - timedelta(seconds=heartbeat_timeout_s)
    stale = db.query(AgentJob).filter(AgentJob.status == "claimed", AgentJob.heartbeat_at < cutoff).all()
    for j in stale:
        j.status = "queued"
        j.claimed_by = None
        j.claimed_at = None
        j.heartbeat_at = None
        j.retry_count += 1
        if j.retry_count > j.max_retries:
            j.status = "failed_terminal"
            j.error_json = json.dumps({"error": "heartbeat_timeout_exceeded"})
    db.flush()
    # Now claim one queued job
    q = db.query(AgentJob).filter(AgentJob.status == "queued")
    if job_type:
        q = q.filter(AgentJob.job_type == job_type)
    job = q.order_by(AgentJob.created_at.asc()).first()
    if not job:
        return None
    # Optimistic claim
    job.status = "claimed"
    job.claimed_by = worker_id
    job.claimed_at = _now()
    job.heartbeat_at = _now()
    db.flush()
    return job

def heartbeat(db: Session, job_id: str, worker_id: str) -> bool:
    job = db.query(AgentJob).filter(AgentJob.id == job_id, AgentJob.claimed_by == worker_id).first()
    if not job or job.status not in ("claimed","running"):
        return False
    job.heartbeat_at = _now()
    db.flush()
    return True

def start_run(db: Session, job: AgentJob, provider: str, model_id: str) -> AgentRun:
    # Transition job to running if claimed
    if job.status == "claimed":
        job.status = "running"
        job.updated_at = _now()
        db.flush()
    # Determine next attempt number
    last = db.query(AgentRun).filter(AgentRun.job_id == job.id).order_by(AgentRun.attempt.desc()).first()
    nxt = (last.attempt + 1) if last else 1
    run = AgentRun(id=f"run-{uuid.uuid4().hex[:8]}", job_id=job.id, attempt=nxt, provider=provider, model_id=model_id, status="running", started_at=_now())
    db.add(run)
    db.flush()
    return run

def record_tool_call(db: Session, run: AgentRun, tool_name: str, request: dict, response: dict | None) -> ToolCallRecord:
    tc = ToolCallRecord(id=f"tc-{uuid.uuid4().hex[:8]}", run_id=run.id, job_id=run.job_id, tool_name=tool_name, request_json=json.dumps(request), response_json=json.dumps(response) if response else None)
    db.add(tc)
    db.flush()
    return tc

def complete_job_with_artifact(db: Session, run: AgentRun, artifact_type: str, payload: dict) -> Artifact:
    job = db.query(AgentJob).filter(AgentJob.id == run.job_id).first()
    if not job:
        raise ValueError("job not found")
    # Artifact reconciliation: if artifact already exists for this job, do not duplicate
    existing = db.query(Artifact).filter(Artifact.job_id == job.id).order_by(Artifact.version.desc()).first()
    if existing:
        # Check if payload is semantically same (for idempotency)
        existing_payload = json.loads(existing.payload_json)
        if existing_payload == payload:
            # Reuse existing artifact, mark run succeeded
            run.status = "succeeded"
            run.finished_at = _now()
            run.duration_ms = _duration_ms(run.started_at, run.finished_at)
            run.output_json = json.dumps(payload)
            job.status = "succeeded"
            job.updated_at = _now()
            db.flush()
            return existing
        # Different payload -> new version (should not happen for retry of same run, but handle)
        version = existing.version + 1
    else:
        version = 1
    art = Artifact(id=f"art-{uuid.uuid4().hex[:8]}", job_id=job.id, run_id=run.id, type=artifact_type, payload_json=json.dumps(payload, sort_keys=True), version=version)
    db.add(art)
    run.status = "succeeded"
    run.finished_at = _now()
    run.duration_ms = _duration_ms(run.started_at, run.finished_at)
    run.output_json = json.dumps(payload)
    run.tool_calls_json = json.dumps([{"tool": "save_artifact", "type": artifact_type}])
    job.status = "succeeded"
    job.updated_at = _now()
    db.flush()
    return art

def fail_run(db: Session, run: AgentRun, error: dict, retryable: bool = True) -> AgentRun:
    job = db.query(AgentJob).filter(AgentJob.id == run.job_id).first()
    run.finished_at = _now()
    run.duration_ms = _duration_ms(run.started_at, run.finished_at)
    run.error_json = json.dumps(error)
    if retryable and job.retry_count < job.max_retries:
        run.status = "failed_retryable"
        job.status = "failed_retryable"
        # Return to queued for retry
        job.retry_count += 1
        job.status = "queued"
        job.claimed_by = None
        job.claimed_at = None
        job.heartbeat_at = None
    else:
        # Terminal or needs review
        if error.get("code") == "needs_tutor_review":
            run.status = "needs_tutor_review"
            job.status = "needs_tutor_review"
        else:
            run.status = "failed_terminal"
            job.status = "failed_terminal"
            job.error_json = json.dumps(error)
    job.updated_at = _now()
    db.flush()
    return run

def mark_needs_review(db: Session, run: AgentRun, reason: dict) -> AgentRun:
    job = db.query(AgentJob).filter(AgentJob.id == run.job_id).first()
    run.status = "needs_tutor_review"
    run.finished_at = _now()
    run.duration_ms = _duration_ms(run.started_at, run.finished_at)
    run.error_json = json.dumps(reason)
    job.status = "needs_tutor_review"
    job.updated_at = _now()
    db.flush()
    return run

def cancel_job(db: Session, job_id: str) -> AgentJob | None:
    job = db.query(AgentJob).filter(AgentJob.id == job_id).first()
    if not job or job.status in TERMINAL:
        return None
    job.status = "cancelled"
    job.updated_at = _now()
    db.flush()
    return job

def get_job(db: Session, job_id: str) -> AgentJob | None:
    return db.query(AgentJob).filter(AgentJob.id == job_id).first()

def list_jobs(db: Session, centre_id: str | None = None, student_id: str | None = None, status: str | None = None) -> list[AgentJob]:
    q = db.query(AgentJob)
    if centre_id:
        q = q.filter(AgentJob.centre_id == centre_id)
    if student_id:
        q = q.filter(AgentJob.student_id == student_id)
    if status:
        q = q.filter(AgentJob.status == status)
    return q.order_by(AgentJob.created_at.desc()).all()
