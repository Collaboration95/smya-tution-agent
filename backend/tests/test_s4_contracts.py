from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agents.diagnostic import run_diagnostic
from backend.app.agents.worker import run_next_job
from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied
from backend.app.db.base import Base
from backend.app.db.models import AgentRun
from backend.app.models.client import FakeModelClient
from backend.app.services.jobs import (
    cancel_job,
    claim_job,
    claim_specific_job,
    complete_job_with_artifact,
    create_job,
    fail_run,
    get_job,
    heartbeat,
    start_run,
)
from backend.app.services.seed import seed_db
from backend.app.tools.contracts import GetStudentSnapshotRequest
from backend.app.tools.registry import invoke_tool


CENTRE_ID = "CTR-SYNTH-NORTHSTAR"
STUDENT_ID = "STU-SYNTH-A"
SUBSKILL_ID = "FRC-ADD-SUB-UNLIKE"
UTC = timezone.utc


def seeded_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seed_db(db)
    return session_factory


def diagnostic_payload(subskill_id: str = SUBSKILL_ID) -> dict[str, str]:
    return {"student_id": STUDENT_ID, "subskill_id": subskill_id}


def parent_report_payload(trigger: str) -> dict:
    previous_start = datetime(2026, 1, 1, tzinfo=UTC)
    previous_end = datetime(2026, 1, 31, tzinfo=UTC)
    current_start = datetime(2026, 2, 1, tzinfo=UTC)
    current_end = datetime(2026, 2, 28, tzinfo=UTC)
    return {
        "schema": "parent_report_v1",
        "student_id": STUDENT_ID,
        "verified_scope": {"centre_id": CENTRE_ID, "student_id": STUDENT_ID},
        "subskill_ids": [SUBSKILL_ID],
        "previous_period": {"start": previous_start.isoformat(), "end": previous_end.isoformat()},
        "current_period": {"start": current_start.isoformat(), "end": current_end.isoformat()},
        "history_policy_id": "mastery_policy_v1",
        "history_policy_version": "1.0.0",
        "trigger": trigger,
    }


def test_job_fsm_rejects_unclaimed_wrong_worker_and_terminal_transitions():
    Session = seeded_session()
    with Session() as db:
        job = create_job(
            db,
            "diagnostic",
            CENTRE_ID,
            STUDENT_ID,
            diagnostic_payload(),
            max_retries=0,
        )
        with pytest.raises(ValueError, match="cannot start from queued"):
            start_run(db, job, "fake", "fake-diagnostic-v1")

        db.commit()
        claimed = claim_job(db, "worker-a")
        assert claimed is not None
        assert claim_specific_job(db, job.id, "worker-b") is None
        with pytest.raises(PermissionError, match="claimed by another worker"):
            start_run(db, claimed, "fake", "fake-diagnostic-v1", worker_id="worker-b")
        assert heartbeat(db, job.id, "worker-b") is False

        run = start_run(db, claimed, "fake", "fake-diagnostic-v1", worker_id="worker-a")
        assert heartbeat(db, job.id, "worker-a") is True
        fail_run(db, run, {"code": "deterministic_failure", "message": "terminal fixture"}, retryable=False)
        db.commit()

        assert get_job(db, job.id).status == "failed_terminal"
        assert cancel_job(db, job.id) is None
        with pytest.raises(ValueError, match="not completing from running"):
            complete_job_with_artifact(db, run, "mastery_proposal", {"status": "late"})


def test_stale_running_job_exhausts_retries_and_closes_active_run():
    Session = seeded_session()
    with Session() as db:
        job = create_job(
            db,
            "diagnostic",
            CENTRE_ID,
            STUDENT_ID,
            diagnostic_payload("FRC-MULTIPLY-WHOLE"),
            max_retries=0,
        )
        db.commit()
        claimed = claim_job(db, "worker-stale")
        assert claimed is not None
        run = start_run(db, claimed, "fake", "fake-diagnostic-v1", worker_id="worker-stale")
        job.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
        db.commit()

        assert claim_job(db, "worker-replacement", heartbeat_timeout_s=60) is None
        db.refresh(job)
        db.refresh(run)
        assert job.status == "failed_terminal"
        assert job.retry_count == 1
        assert json.loads(job.error_json or "{}") == {
            "code": "heartbeat_timeout_exceeded",
            "message": "worker heartbeat expired",
        }
        assert run.status == "failed_terminal"
        assert run.finished_at is not None
        assert json.loads(run.error_json or "{}")["code"] == "heartbeat_timeout_exceeded"


def test_parent_report_idempotency_ignores_trigger_but_keeps_verified_boundaries():
    Session = seeded_session()
    with Session() as db:
        first = create_job(
            db,
            "parent_report",
            CENTRE_ID,
            STUDENT_ID,
            parent_report_payload("manual_request"),
        )
        replay = create_job(
            db,
            "parent_report",
            CENTRE_ID,
            STUDENT_ID,
            parent_report_payload("retry_after_timeout"),
        )
        assert replay.id == first.id
        assert replay.idempotency_key == first.idempotency_key

        invalid_scope = parent_report_payload("manual_request")
        invalid_scope["verified_scope"] = {"centre_id": CENTRE_ID, "student_id": "STU-SYNTH-B"}
        with pytest.raises(ValueError, match="exact verified_scope"):
            create_job(db, "parent_report", CENTRE_ID, STUDENT_ID, invalid_scope)

        invalid_period = parent_report_payload("manual_request")
        invalid_period["current_period"]["start"] = "2026-01-15T00:00:00+00:00"
        with pytest.raises(ValueError, match="must not overlap"):
            create_job(db, "parent_report", CENTRE_ID, STUDENT_ID, invalid_period)


def test_worker_runner_processes_one_job_and_is_idle_when_queue_is_empty():
    Session = seeded_session()
    with Session() as db:
        job = create_job(db, "diagnostic", CENTRE_ID, STUDENT_ID, diagnostic_payload())
        db.commit()
        fake = FakeModelClient()

        result = run_next_job(db, "worker-runner", fake)

        assert result is not None
        assert result["status"] == "needs_tutor_review"
        db.refresh(job)
        assert job.status == "needs_tutor_review"
        run = db.query(AgentRun).filter(AgentRun.job_id == job.id).one()
        assert run.provider == "fake"
        assert run.model_id == "fake-diagnostic-v1"
        assert run.finished_at is not None
        assert "model.generate_structured" in json.loads(run.tool_calls_json or "[]")
        assert len(fake.calls) >= 1

        assert run_next_job(db, "worker-runner", fake) is None


def test_tool_failure_is_retryable_then_replays_through_the_same_contract(monkeypatch):
    import backend.app.agents.diagnostic as diagnostic_module

    Session = seeded_session()
    with Session() as db:
        job = create_job(
            db,
            "diagnostic",
            CENTRE_ID,
            STUDENT_ID,
            diagnostic_payload("FRC-MULTIPLY-WHOLE"),
            max_retries=1,
        )
        db.commit()
        original_invoke_tool = diagnostic_module.invoke_tool
        call_count = 0

        def flaky_invoke_tool(db, caller, job, tool_name, request):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("approved evidence tool unavailable")
            return original_invoke_tool(db, caller, job, tool_name, request)

        monkeypatch.setattr(diagnostic_module, "invoke_tool", flaky_invoke_tool)
        first = run_diagnostic(db, claim_job(db, "worker-retry"), FakeModelClient())
        assert first["status"] == "failed_retryable"
        db.refresh(job)
        assert job.status == "queued"
        assert job.retry_count == 1
        first_run = db.query(AgentRun).filter(AgentRun.job_id == job.id).one()
        assert first_run.status == "failed_retryable"
        assert json.loads(first_run.error_json or "{}")["code"] == "worker_error"

        monkeypatch.setattr(diagnostic_module, "invoke_tool", original_invoke_tool)
        second_claim = claim_job(db, "worker-retry-replacement")
        assert second_claim is not None
        second = run_diagnostic(db, second_claim, FakeModelClient())
        assert second["status"] == "needs_tutor_review"
        db.refresh(job)
        assert job.status == "needs_tutor_review"
        runs = db.query(AgentRun).filter(AgentRun.job_id == job.id).order_by(AgentRun.attempt.asc()).all()
        assert [item.attempt for item in runs] == [1, 2]


def test_worker_tool_access_requires_exact_job_and_running_state():
    Session = seeded_session()
    with Session() as db:
        job = create_job(db, "diagnostic", CENTRE_ID, STUDENT_ID, diagnostic_payload())
        db.commit()
        claimed = claim_job(db, "worker-bound")
        assert claimed is not None
        caller = CallerContext(
            user_id="worker-bound",
            centre_id=CENTRE_ID,
            role="worker",
            student_id=STUDENT_ID,
            job_id=job.id,
        )
        with pytest.raises(PermissionDenied, match="only available during a running job"):
            invoke_tool(db, caller, job, "get_student_snapshot", {"student_id": STUDENT_ID})

        wrong_job_caller = caller.model_copy(update={"job_id": "job-not-bound"})
        with pytest.raises(PermissionDenied, match="job access denied"):
            invoke_tool(db, wrong_job_caller, job, "get_student_snapshot", {"student_id": STUDENT_ID})

        run = start_run(db, claimed, "fake", "fake-diagnostic-v1", worker_id="worker-bound")
        snapshot = invoke_tool(db, caller, job, "get_student_snapshot", GetStudentSnapshotRequest(student_id=STUDENT_ID))
        assert snapshot.student_id == STUDENT_ID
        fail_run(db, run, {"code": "test_cleanup"}, retryable=False)


def test_fake_model_fixture_contract_is_typed_deterministic_and_provenanced():
    class FixtureSchema(BaseModel):
        value: int

        model_config = {"extra": "forbid"}

    fake = FakeModelClient(
        fixtures={
            "OK_FIXTURE": {"value": 7},
            "BAD_FIXTURE": {"value": "not-an-integer"},
        },
        model_id="fake-contract-v1",
    )
    valid = fake.generate_structured("OK_FIXTURE prompt", FixtureSchema)
    repeat = fake.generate_structured("OK_FIXTURE prompt", FixtureSchema)
    invalid = fake.generate_structured("BAD_FIXTURE prompt", FixtureSchema)
    text = fake.generate_text("text prompt")

    assert valid.parsed == {"value": 7}
    assert valid.raw == repeat.raw
    assert invalid.parsed is None
    assert json.loads(invalid.raw) == {"value": "not-an-integer"}
    assert valid.invocation.provider == "fake"
    assert valid.invocation.model_id == "fake-contract-v1"
    assert valid.invocation.schema_name == "FixtureSchema"
    assert valid.invocation.cost_usd == 0.0
    assert text.invocation.schema_name is None
    assert len(fake.calls) == 4
