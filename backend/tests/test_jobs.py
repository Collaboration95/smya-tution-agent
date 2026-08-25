from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta, timezone
from backend.app.db.base import Base
from backend.app.services.jobs import create_job, claim_job, start_run, record_tool_call, complete_job_with_artifact, fail_run, heartbeat, get_job
from backend.app.services.seed import seed_db
from pydantic import BaseModel

class ProposalSchema(BaseModel):
    student_id: str
    subskill_id: str
    label: str
    confidence: float

def make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        seed_db(db)
    return Session

def test_idempotency_and_dedup():
    Session = make_db()
    with Session() as db:
        payload = {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-ADD-SUB-UNLIKE", "attempt_id": "ATT-SYNTH-A-ADD-001"}
        j1 = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", payload)
        db.commit()
        j2 = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", payload)
        db.commit()
        assert j1.id == j2.id
        assert j1.idempotency_key == j2.idempotency_key

def test_claim_and_heartbeat_and_recovery():
    Session = make_db()
    with Session() as db:
        create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-ADD-SUB-UNLIKE", "x": 1})
        db.commit()
        claimed = claim_job(db, "worker-1")
        assert claimed is not None and claimed.status == "claimed"
        db.commit()
        ok = heartbeat(db, claimed.id, "worker-1")
        assert ok is True
        # Stale recovery: manipulate heartbeat to old
        job = get_job(db, claimed.id)
        job.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        job.status = "claimed"
        db.commit()
        # Next claim should recover stale
        claimed2 = claim_job(db, "worker-2")
        assert claimed2 is not None
        assert claimed2.id == job.id
        # retry_count should have increased
        assert get_job(db, job.id).retry_count == 1


def test_running_run_is_closed_when_heartbeat_recovery_requeues_job():
    Session = make_db()
    with Session() as db:
        job = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-ADD-SUB-UNLIKE", "x": 2})
        db.commit()
        claimed = claim_job(db, "worker-1")
        run = start_run(db, claimed, "fake", "fake-diagnostic-v1", worker_id="worker-1")
        run.heartbeat_at = None
        job = get_job(db, job.id)
        job.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        db.commit()
        claimed_again = claim_job(db, "worker-2")
        assert claimed_again is not None and claimed_again.status == "claimed"
        assert get_job(db, job.id).retry_count == 1
        assert db.query(type(run)).filter_by(id=run.id).first().status == "failed_retryable"

def test_retryable_and_terminal_failures():
    Session = make_db()
    with Session() as db:
        j = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-ADD-SUB-UNLIKE", "y": 2}, max_retries=1)
        db.commit()
        c = claim_job(db, "worker-1")
        run = start_run(db, c, "fake", "fake-diagnostic-v1")
        db.commit()
        # First failure retryable -> queued
        fail_run(db, run, {"error": "transient"}, retryable=True)
        db.commit()
        assert get_job(db, j.id).status == "queued"
        # Claim again, fail retryable but now exceeds max_retries -> terminal
        c2 = claim_job(db, "worker-1")
        run2 = start_run(db, c2, "fake", "fake-diagnostic-v1")
        fail_run(db, run2, {"error": "still fail"}, retryable=True)
        db.commit()
        assert get_job(db, j.id).status == "failed_terminal"

def test_artifact_reconciliation_no_duplicates_after_crash():
    Session = make_db()
    with Session() as db:
        j = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-ADD-SUB-UNLIKE", "z": 3})
        db.commit()
        c = claim_job(db, "worker-1")
        run = start_run(db, c, "fake", "fake-diagnostic-v1")
        payload = {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-ADD-SUB-UNLIKE", "label": "requires_support", "confidence": 0.8}
        art1 = complete_job_with_artifact(db, run, "mastery_proposal", payload)
        db.commit()
        assert get_job(db, j.id).status == "succeeded"
        # Simulate a retry after a worker crash: a recovered job is claimed again
        # before the replacement run starts.
        job = get_job(db, j.id)
        job.status = "queued"
        db.commit()
        claimed_again = claim_job(db, "worker-2")
        run2 = start_run(db, claimed_again, "fake", "fake-diagnostic-v1", worker_id="worker-2")
        art2 = complete_job_with_artifact(db, run2, "mastery_proposal", payload)
        db.commit()
        assert art1.id == art2.id  # reused
        from backend.app.db.models import Artifact
        arts = db.query(Artifact).filter(Artifact.job_id == j.id).all()
        assert len([a for a in arts if a.version == 1]) == 1

def test_fake_model_validation_becomes_safe_failure():
    Session = make_db()
    with Session() as db:
        from backend.app.models.client import FakeModelClient
        from pydantic import ValidationError
        fake = FakeModelClient(fixtures={})
        out = fake.generate_structured("prompt with no fixture", ProposalSchema)
        assert out.parsed is None
        # Simulate job that tries to use invalid output -> should become failed_retryable then terminal
        j = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-ADD-SUB-UNLIKE", "w": 4}, max_retries=0)
        db.commit()
        c = claim_job(db, "worker-1")
        run = start_run(db, c, fake.provider, fake.model_id)
        # Attempt to validate
        try:
            ProposalSchema.model_validate_json(out.raw)
            assert False
        except ValidationError:
            # Worker should mark as failed_terminal when max_retries 0 and invalid output
            fail_run(db, run, {"code": "validation_error", "message": "invalid model output"}, retryable=False)
            db.commit()
            assert get_job(db, j.id).status == "failed_terminal"

def test_bounded_tool_allow_list():
    from backend.app.tools.registry import is_tool_allowed
    assert is_tool_allowed("diagnostic", "get_student_snapshot") is True
    assert is_tool_allowed("diagnostic", "save_assessment_draft") is False
    assert is_tool_allowed("diagnostic", "retrieve_approved_curriculum") is True
    # Ensure tool_calls are recorded
    Session = make_db()
    with Session() as db:
        create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-ADD-SUB-UNLIKE", "q": 5})
        db.commit()
        c = claim_job(db, "worker-1")
        run = start_run(db, c, "fake", "fake-diagnostic-v1")
        record_tool_call(db, run, "get_student_snapshot", {"student_id": "STU-SYNTH-A"}, {"ok": True})
        db.commit()
        from backend.app.db.models import ToolCallRecord
        tcs = db.query(ToolCallRecord).filter(ToolCallRecord.run_id == run.id).all()
        assert len(tcs) == 1 and tcs[0].tool_name == "get_student_snapshot"
