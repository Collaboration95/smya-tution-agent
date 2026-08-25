from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.models import AgentJob, AgentRun, Artifact, ToolCallRecord

VALID_STATUSES = {
    "queued",
    "claimed",
    "running",
    "succeeded",
    "needs_tutor_review",
    "failed_retryable",
    "failed_terminal",
    "cancelled",
}
TERMINAL = {"succeeded", "needs_tutor_review", "failed_terminal", "cancelled"}
CLAIMABLE = {"queued"}
JOB_TYPES = {"diagnostic", "assessment", "parent_report"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _duration_ms(start: datetime, end: datetime) -> int:
    return int((_aware(end) - _aware(start)).total_seconds() * 1000)


def stable_idempotency_key(job_type: str, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{job_type}:{raw}".encode()).hexdigest()[:16]
    return f"{job_type}:{digest}"


def _idempotency_payload(
    job_type: str,
    centre_id: str | None,
    student_id: str | None,
    input_payload: dict,
) -> dict:
    # A diagnostic is the durable per-student/subskill boundary in S1. The
    # trigger and attempt id describe why it was requested, but must not make
    # repeated manual/event triggers create parallel jobs for the same slice.
    if job_type == "diagnostic" and student_id and input_payload.get("subskill_id"):
        return {
            "centre_id": centre_id,
            "student_id": student_id,
            "subskill_id": input_payload["subskill_id"],
        }
    return {"centre_id": centre_id, "input": input_payload}


def create_job(
    db: Session,
    job_type: str,
    centre_id: str | None,
    student_id: str | None,
    input_payload: dict,
    max_retries: int = 3,
) -> AgentJob:
    if job_type not in JOB_TYPES:
        raise ValueError(f"unsupported job type: {job_type}")
    if not 0 <= max_retries <= 5:
        raise ValueError("max_retries must be between 0 and 5")
    payload_student_id = input_payload.get("student_id")
    if student_id and payload_student_id and payload_student_id != student_id:
        raise ValueError("job student_id does not match input_payload.student_id")
    if job_type == "diagnostic":
        if not student_id or payload_student_id != student_id:
            raise ValueError("diagnostic jobs require matching student_id values")
        if not isinstance(input_payload.get("subskill_id"), str) or not input_payload["subskill_id"]:
            raise ValueError("diagnostic jobs require input_payload.subskill_id")
    key_payload = _idempotency_payload(job_type, centre_id, student_id, input_payload)
    key = stable_idempotency_key(job_type, key_payload)
    existing = db.query(AgentJob).filter(AgentJob.idempotency_key == key).first()
    if existing:
        return existing
    job = AgentJob(
        id=f"job-{uuid.uuid4().hex[:8]}",
        job_type=job_type,
        centre_id=centre_id,
        student_id=student_id,
        input_json=json.dumps(input_payload, sort_keys=True),
        idempotency_key=key,
        status="queued",
        retry_count=0,
        max_retries=max_retries,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        # The unique idempotency constraint is the final arbiter when two
        # requests race between the lookup and insert.
        existing = db.query(AgentJob).filter(AgentJob.idempotency_key == key).first()
        if existing:
            return existing
        raise
    return job


def _recover_stale(db: Session, heartbeat_timeout_s: int) -> None:
    cutoff = _now() - timedelta(seconds=heartbeat_timeout_s)
    stale = (
        db.query(AgentJob)
        .filter(
            AgentJob.status.in_(("claimed", "running")),
            AgentJob.heartbeat_at.is_not(None),
            AgentJob.heartbeat_at < cutoff,
        )
        .with_for_update(skip_locked=True)
        .all()
    )
    for job in stale:
        job.retry_count += 1
        active_run = (
            db.query(AgentRun)
            .filter(AgentRun.job_id == job.id, AgentRun.status == "running")
            .order_by(AgentRun.attempt.desc())
            .first()
        )
        job.claimed_by = None
        job.claimed_at = None
        job.heartbeat_at = None
        if job.retry_count > job.max_retries:
            job.status = "failed_terminal"
            error = {"code": "heartbeat_timeout_exceeded", "message": "worker heartbeat expired"}
            job.error_json = json.dumps(error, sort_keys=True)
            if active_run:
                _finish_run(db, active_run, "failed_terminal", error=error)
        else:
            job.status = "queued"
            if active_run:
                _finish_run(
                    db,
                    active_run,
                    "failed_retryable",
                    error={"code": "heartbeat_timeout", "message": "worker heartbeat expired; job requeued"},
                )
        job.updated_at = _now()
    db.flush()


def _claim_row(job: AgentJob, worker_id: str) -> AgentJob:
    if job.status not in CLAIMABLE:
        raise ValueError(f"job {job.id} is not claimable from {job.status}")
    now = _now()
    job.status = "claimed"
    job.claimed_by = worker_id
    job.claimed_at = now
    job.heartbeat_at = now
    job.updated_at = now
    return job


def claim_job(
    db: Session,
    worker_id: str,
    job_type: str | None = None,
    heartbeat_timeout_s: int = 60,
) -> AgentJob | None:
    _recover_stale(db, heartbeat_timeout_s)
    query = db.query(AgentJob).filter(AgentJob.status == "queued")
    if job_type:
        if job_type not in JOB_TYPES:
            raise ValueError(f"unsupported job type: {job_type}")
        query = query.filter(AgentJob.job_type == job_type)
    job = query.order_by(AgentJob.created_at.asc()).with_for_update(skip_locked=True).first()
    if not job:
        return None
    _claim_row(job, worker_id)
    db.flush()
    return job


def claim_specific_job(
    db: Session,
    job_id: str,
    worker_id: str,
    heartbeat_timeout_s: int = 60,
) -> AgentJob | None:
    _recover_stale(db, heartbeat_timeout_s)
    job = db.query(AgentJob).filter(AgentJob.id == job_id).with_for_update(skip_locked=True).first()
    if not job:
        return None
    if job.status == "claimed" and job.claimed_by == worker_id:
        return job
    if job.status not in CLAIMABLE:
        return None
    _claim_row(job, worker_id)
    db.flush()
    return job


def heartbeat(db: Session, job_id: str, worker_id: str) -> bool:
    job = db.query(AgentJob).filter(AgentJob.id == job_id, AgentJob.claimed_by == worker_id).first()
    if not job or job.status not in ("claimed", "running"):
        return False
    job.heartbeat_at = _now()
    job.updated_at = job.heartbeat_at
    db.flush()
    return True


def start_run(
    db: Session,
    job: AgentJob,
    provider: str,
    model_id: str,
    worker_id: str | None = None,
) -> AgentRun:
    if job.status != "claimed":
        raise ValueError(f"job {job.id} cannot start from {job.status}")
    if worker_id is not None and job.claimed_by != worker_id:
        raise PermissionError(f"job {job.id} is claimed by another worker")
    job.status = "running"
    job.updated_at = _now()
    job.heartbeat_at = job.updated_at
    db.flush()
    last = db.query(AgentRun).filter(AgentRun.job_id == job.id).order_by(AgentRun.attempt.desc()).first()
    attempt = (last.attempt + 1) if last else 1
    run = AgentRun(
        id=f"run-{uuid.uuid4().hex[:8]}",
        job_id=job.id,
        attempt=attempt,
        provider=provider,
        model_id=model_id,
        status="running",
        started_at=_now(),
    )
    db.add(run)
    db.flush()
    return run


def record_tool_call(
    db: Session,
    run: AgentRun,
    tool_name: str,
    request: dict,
    response: dict | None,
) -> ToolCallRecord:
    call = ToolCallRecord(
        id=f"tc-{uuid.uuid4().hex[:8]}",
        run_id=run.id,
        job_id=run.job_id,
        tool_name=tool_name,
        request_json=json.dumps(request, sort_keys=True),
        response_json=json.dumps(response, sort_keys=True) if response is not None else None,
    )
    db.add(call)
    db.flush()
    return call


def _finish_run(
    db: Session,
    run: AgentRun,
    status: str,
    payload: dict | None = None,
    error: dict | None = None,
) -> None:
    now = _now()
    run.status = status
    run.finished_at = now
    run.duration_ms = _duration_ms(run.started_at, now)
    if payload is not None:
        run.output_json = json.dumps(payload, sort_keys=True)
    if error is not None:
        run.error_json = json.dumps(error, sort_keys=True)


def _clear_claim(job: AgentJob) -> None:
    job.claimed_by = None
    job.claimed_at = None
    job.heartbeat_at = None
    job.updated_at = _now()


def complete_job_with_artifact(
    db: Session,
    run: AgentRun,
    artifact_type: str,
    payload: dict,
    review_reason: dict | None = None,
) -> Artifact:
    job = db.query(AgentJob).filter(AgentJob.id == run.job_id).first()
    if not job:
        raise ValueError("job not found")
    if run.status != "running" or job.status != "running":
        raise ValueError(f"run/job is not completing from running: {run.status}/{job.status}")
    existing = (
        db.query(Artifact)
        .filter(Artifact.job_id == job.id, Artifact.type == artifact_type)
        .order_by(Artifact.version.desc())
        .first()
    )
    if existing:
        existing_payload = json.loads(existing.payload_json)
        if existing_payload == payload:
            status = "needs_tutor_review" if review_reason else "succeeded"
            _finish_run(db, run, status, payload, error=review_reason)
            job.status = status
            _clear_claim(job)
            db.flush()
            return existing
        version = existing.version + 1
    else:
        version = 1
    artifact = Artifact(
        id=f"art-{uuid.uuid4().hex[:8]}",
        job_id=job.id,
        run_id=run.id,
        type=artifact_type,
        payload_json=json.dumps(payload, sort_keys=True),
        version=version,
    )
    db.add(artifact)
    status = "needs_tutor_review" if review_reason else "succeeded"
    _finish_run(db, run, status, payload, error=review_reason)
    job.status = status
    _clear_claim(job)
    db.flush()
    return artifact


def fail_run(db: Session, run: AgentRun, error: dict, retryable: bool = True) -> AgentRun:
    job = db.query(AgentJob).filter(AgentJob.id == run.job_id).first()
    if not job:
        raise ValueError("job not found")
    if run.status != "running" or job.status != "running":
        raise ValueError(f"run/job is not failing from running: {run.status}/{job.status}")
    if retryable and job.retry_count < job.max_retries:
        _finish_run(db, run, "failed_retryable", error=error)
        job.retry_count += 1
        job.status = "queued"
        _clear_claim(job)
    elif error.get("code") == "needs_tutor_review":
        _finish_run(db, run, "needs_tutor_review", error=error)
        job.status = "needs_tutor_review"
        _clear_claim(job)
    else:
        _finish_run(db, run, "failed_terminal", error=error)
        job.status = "failed_terminal"
        job.error_json = json.dumps(error, sort_keys=True)
        _clear_claim(job)
    db.flush()
    return run


def mark_needs_review(db: Session, run: AgentRun, reason: dict) -> AgentRun:
    job = db.query(AgentJob).filter(AgentJob.id == run.job_id).first()
    if not job:
        raise ValueError("job not found")
    if run.status != "running" or job.status != "running":
        raise ValueError(f"run/job is not reviewable from running: {run.status}/{job.status}")
    _finish_run(db, run, "needs_tutor_review", error=reason)
    job.status = "needs_tutor_review"
    _clear_claim(job)
    db.flush()
    return run


def cancel_job(db: Session, job_id: str) -> AgentJob | None:
    job = db.query(AgentJob).filter(AgentJob.id == job_id).first()
    if not job or job.status in TERMINAL:
        return None
    job.status = "cancelled"
    _clear_claim(job)
    db.flush()
    return job


def get_job(db: Session, job_id: str) -> AgentJob | None:
    return db.query(AgentJob).filter(AgentJob.id == job_id).first()


def list_jobs(
    db: Session,
    centre_id: str | None = None,
    student_id: str | None = None,
    status: str | None = None,
) -> list[AgentJob]:
    query = db.query(AgentJob)
    if centre_id:
        query = query.filter(AgentJob.centre_id == centre_id)
    if student_id:
        query = query.filter(AgentJob.student_id == student_id)
    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"unsupported status: {status}")
        query = query.filter(AgentJob.status == status)
    return query.order_by(AgentJob.created_at.desc()).all()
