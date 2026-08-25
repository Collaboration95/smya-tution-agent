from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.agents.diagnostic import run_diagnostic
from backend.app.models.client import ModelClient, get_model_client
from backend.app.services.jobs import claim_job


def run_next_job(db: Session, worker_id: str, model_client: ModelClient | None = None) -> dict | None:
    """Claim and execute one queued job, leaving retryable failures queued."""
    job = claim_job(db, worker_id, job_type="diagnostic")
    if not job:
        db.commit()
        return None
    client = model_client or get_model_client()
    return run_diagnostic(db, job, client)
