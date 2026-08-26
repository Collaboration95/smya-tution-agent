from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.agents.diagnostic import run_diagnostic
from backend.app.agents.parent_report import run_parent_report
from backend.app.models.client import ModelClient, get_model_client
from backend.app.services.jobs import claim_job


def run_next_job(
    db: Session,
    worker_id: str,
    model_client: ModelClient | None = None,
    job_type: str = "diagnostic",
) -> dict | None:
    """Claim and execute one queued bounded job, leaving retryable failures queued."""
    job = claim_job(db, worker_id, job_type=job_type)
    if not job:
        db.commit()
        return None
    client = model_client or get_model_client()
    if job.job_type == "diagnostic":
        return run_diagnostic(db, job, client)
    if job.job_type == "parent_report":
        return run_parent_report(db, job, client)
    raise ValueError(f"no worker implementation for {job.job_type}")
