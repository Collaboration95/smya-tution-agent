from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agents.parent_report import run_parent_report
from backend.app.auth.context import CallerContext
from backend.app.db.base import Base
from backend.app.db.models import Artifact, MasteryState, ParentReportDraft
from backend.app.main import app
from backend.app.models.client import FakeModelClient
from backend.app.schemas.reports import ParentReportJobRequest, ReportPeriod
from backend.app.services.jobs import claim_job, create_job, get_job
from backend.app.services.seed import seed_db
from backend.app.reports.service import create_parent_report_job
from backend.app.tools.contracts import GetMasteryHistoryRequest
from backend.app.tools.history import get_mastery_history
from backend.app.db.session import get_db


CENTRE_ID = "CTR-SYNTH-NORTHSTAR"
STUDENT_ID = "STU-SYNTH-A"
SUBSKILL_ID = "FRC-ADD-SUB-UNLIKE"
UTC = timezone.utc


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        seed_db(db)
    return Session


def request() -> ParentReportJobRequest:
    base = datetime.now(UTC).replace(microsecond=0)
    return ParentReportJobRequest(
        student_id=STUDENT_ID,
        subskill_ids=[SUBSKILL_ID],
        previous_period=ReportPeriod(
            start=base - timedelta(days=10),
            end=base - timedelta(hours=1),
        ),
        current_period=ReportPeriod(
            start=base,
            end=base + timedelta(days=10),
        ),
    )


def tutor() -> CallerContext:
    return CallerContext(user_id="TUT-SYNTH-ALPHA", centre_id=CENTRE_ID, role="tutor")


def prepare_history(db) -> tuple[str, str, str]:
    base = datetime.now(UTC).replace(microsecond=0)
    previous_at = base - timedelta(days=2)
    current_at = base + timedelta(days=2)
    future_at = base + timedelta(days=30)
    state = (
        db.query(MasteryState)
        .filter_by(student_id=STUDENT_ID, subskill_id=SUBSKILL_ID)
        .order_by(MasteryState.version.asc())
        .first()
    )
    assert state is not None
    policy_id = state.policy_id
    policy_version = state.policy_version
    state.version = 2
    state.created_at = current_at
    state.label = "developing"
    state.accuracy = 0.5
    prior = MasteryState(
        id="mst-parent-report-previous",
        centre_id=CENTRE_ID,
        student_id=STUDENT_ID,
        subskill_id=SUBSKILL_ID,
        version=1,
        eligible_attempts=4,
        correct_attempts=1,
        accuracy=0.25,
        confidence=0.8,
        label="requires_support",
        policy_id=policy_id,
        policy_version=policy_version,
        is_override=False,
        created_at=previous_at,
    )
    future = MasteryState(
        id="mst-parent-report-future",
        centre_id=CENTRE_ID,
        student_id=STUDENT_ID,
        subskill_id=SUBSKILL_ID,
        version=3,
        eligible_attempts=4,
        correct_attempts=1,
        accuracy=0.25,
        confidence=0.8,
        label="requires_support",
        policy_id=policy_id,
        policy_version=policy_version,
        is_override=False,
        created_at=future_at,
    )
    db.add_all([prior, future])
    db.flush()
    return prior.id, state.id, future.id


def test_parent_report_compares_selected_history_not_mutable_latest_row():
    Session = make_db()
    with Session() as db:
        previous_id, current_id, future_id = prepare_history(db)
        response = get_mastery_history(
            db,
            tutor(),
            GetMasteryHistoryRequest(
                student_id=STUDENT_ID,
                subskill_ids=[SUBSKILL_ID],
                previous_period_start=request().previous_period.start,
                previous_period_end=request().previous_period.end,
                current_period_start=request().current_period.start,
                current_period_end=request().current_period.end,
            ),
        )
        assert response.previous_period[0].id == previous_id
        assert response.current_period[0].id == current_id
        assert response.current_period[0].id != future_id
        assert response.current_period[0].evidence_ids


def test_parent_report_worker_persists_bounded_draft_and_references_sources():
    Session = make_db()
    with Session() as db:
        prepare_history(db)
        report_request = request()
        job = create_parent_report_job(db, tutor(), report_request)
        db.commit()
        duplicate = create_parent_report_job(db, tutor(), report_request)
        assert duplicate.id == job.id
        claimed = claim_job(db, "worker-parent-report-1", job_type="parent_report")
        assert claimed is not None
        result = run_parent_report(db, get_job(db, job.id), FakeModelClient())
        assert result["status"] == "needs_tutor_review"
        assert result["progress_signal"] == "improved"
        artifact = db.query(Artifact).filter(Artifact.id == result["artifact_id"]).one()
        content = json.loads(artifact.payload_json)
        draft = db.query(ParentReportDraft).filter(ParentReportDraft.id == result["draft_id"]).one()
        assert draft.status == "pending_tutor_review"
        assert json.loads(draft.snapshot_ids_json) == content["snapshot_ids"]
        assert json.loads(draft.evidence_ids_json) == content["evidence_ids"]
        assert content["headline"]
        assert content["next_steps"]
        assert "Synthetic Student B" not in json.dumps(content)
        assert "raw chat" not in json.dumps(content).lower()
        assert get_job(db, job.id).status == "needs_tutor_review"


def test_parent_report_model_failure_becomes_reviewable_without_draft():
    Session = make_db()
    with Session() as db:
        prepare_history(db)
        job = create_parent_report_job(db, tutor(), request())
        db.commit()
        claimed = claim_job(db, "worker-parent-report-2", job_type="parent_report")
        assert claimed is not None
        invalid = FakeModelClient(
            fixtures={
                "Parent report proposal": {
                    "student_id": STUDENT_ID,
                    "progress_signal": "improved",
                    "next_step_codes": ["continue_practice"],
                    "snapshot_ids": [],
                    "evidence_ids": [],
                    "hidden_reasoning": "must never persist",
                }
            }
        )
        result = run_parent_report(db, get_job(db, job.id), invalid)
        assert result == {"status": "needs_tutor_review", "reason": "invalid_model_output"}
        assert get_job(db, job.id).status == "needs_tutor_review"
        assert db.query(ParentReportDraft).filter_by(job_id=job.id).count() == 0
        assert db.query(Artifact).filter_by(job_id=job.id).count() == 0
        assert "must never persist" not in json.dumps(get_job(db, job.id).error_json)


def test_parent_report_provider_failure_becomes_reviewable():
    class BrokenModelClient(FakeModelClient):
        def generate_structured(self, prompt, schema, **kwargs):
            raise RuntimeError("provider unavailable")

    Session = make_db()
    with Session() as db:
        prepare_history(db)
        job = create_parent_report_job(db, tutor(), request())
        db.commit()
        claimed = claim_job(db, "worker-parent-report-provider", job_type="parent_report")
        assert claimed is not None
        result = run_parent_report(db, get_job(db, job.id), BrokenModelClient())
        assert result == {"status": "needs_tutor_review", "reason": "model_provider_error"}
        assert get_job(db, job.id).status == "needs_tutor_review"


def test_parent_report_job_requires_verified_scope_and_policy():
    with pytest.raises(ValueError, match="verified_scope"):
        create_job(
            make_db()(),
            "parent_report",
            CENTRE_ID,
            STUDENT_ID,
            {
                "student_id": STUDENT_ID,
                "subskill_ids": [SUBSKILL_ID],
                "previous_period": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-01-31T00:00:00+00:00"},
                "current_period": {"start": "2026-02-01T00:00:00+00:00", "end": "2026-04-30T00:00:00+00:00"},
            },
        )


def test_parent_report_api_keeps_draft_scoped_and_tutor_reviewable():
    Session = make_db()
    with Session() as db:
        prepare_history(db)
        db.commit()

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    body = request().model_dump(mode="json")
    try:
        created = client.post("/api/parent-reports/jobs", json=body, headers={"X-User-Id": "TUT-SYNTH-ALPHA"})
        assert created.status_code == 200, created.text
        job_id = created.json()["job_id"]
        ran = client.post(f"/api/parent-reports/jobs/{job_id}/run", headers={"X-User-Id": "TUT-SYNTH-ALPHA"})
        assert ran.status_code == 200, ran.text
        assert ran.json()["status"] == "needs_tutor_review"
        draft = client.get(f"/api/parent-reports/jobs/{job_id}", headers={"X-User-Id": "TUT-SYNTH-ALPHA"})
        assert draft.status_code == 200, draft.text
        assert draft.json()["student_id"] == STUDENT_ID
        assert "STU-SYNTH-B" not in json.dumps(draft.json())
    finally:
        app.dependency_overrides.clear()
