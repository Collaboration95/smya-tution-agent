from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agents.diagnostic import run_diagnostic
from backend.app.db.base import Base
from backend.app.db.models import (
    AgentRun,
    Artifact,
    AuditEvent,
    MasteryEvidence,
    MasteryState,
    ToolCallRecord,
    TutorAlert,
    TutorDecision,
    TutorEvidenceExclusion,
)
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.client import FakeModelClient
from backend.app.services.jobs import claim_job, create_job, get_job
from backend.app.services.seed import seed_db

CENTRE_ID = "CTR-SYNTH-NORTHSTAR"
TUTOR_ID = "TUT-SYNTH-ALPHA"
UNASSIGNED_TUTOR_ID = "TUT-SYNTH-BRAVO"


def seeded_client_and_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        seed_db(db)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override
    return TestClient(app), Session


def diagnostic_fixture(student_id: str, subskill_id: str, label: str, confidence: float, evidence_ids: list[str]):
    return FakeModelClient(
        fixtures={
            "Diagnostic proposal": {
                "student_id": student_id,
                "subskill_id": subskill_id,
                "status": "pending_tutor_review",
                "label": label,
                "confidence": confidence,
                "evidence_ids": evidence_ids,
                "policy_id": "mastery_policy_v1",
                "policy_version": "1.0.0",
                "reason": f"Evidence {evidence_ids} supports {label}; policy version 1.0.0 was applied.",
                "alternative_explanation": None,
                "recommended_next_action": "assign_targeted_practice",
                "source_refs": ["CHK-SYNTH-ADD-001"],
            }
        }
    )


def test_unsupported_content_escalates_before_model_and_is_resolvable():
    client, Session = seeded_client_and_session()
    with Session() as db:
        job = create_job(
            db,
            "diagnostic",
            CENTRE_ID,
            "STU-SYNTH-A",
            {"student_id": "STU-SYNTH-A", "subskill_id": "DECIMALS"},
        )
        db.commit()
        claim_job(db, "worker-review")
        result = run_diagnostic(db, get_job(db, job.id), FakeModelClient())
        assert result == {
            "status": "needs_tutor_review",
            "reason": "unsupported_content",
        }
        alert = db.query(TutorAlert).filter(TutorAlert.job_id == job.id).one()
        assert alert.type == "unsupported"
        assert alert.status == "open"
        assert db.query(Artifact).filter(Artifact.job_id == job.id).count() == 0
        tool_names = [
            row.tool_name
            for row in db.query(ToolCallRecord).filter(ToolCallRecord.job_id == job.id).all()
        ]
        assert "retrieve_approved_curriculum" in tool_names
        assert not any(name.startswith("model.generate") for name in tool_names)
        alert_id = alert.id

    resolved = client.post(
        f"/api/tutor/alerts/{alert_id}/resolve",
        json={"resolution": "keep_blocked", "reason": "Unsupported topic remains outside the approved corpus."},
        headers={"X-User-Id": TUTOR_ID},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["alert"]["status"] == "resolved"
    assert resolved.json()["job_status"] == "needs_tutor_review"

    with Session() as db:
        alert = db.get(TutorAlert, alert_id)
        assert alert.status == "resolved"
        assert alert.resolution == "keep_blocked"
        decision = db.query(TutorDecision).filter(TutorDecision.alert_id == alert_id).one()
        assert decision.action == "resolve_alert"
        audit = db.query(AuditEvent).filter(AuditEvent.entity_id == alert_id).one()
        assert audit.event == "tutor_alert.resolve"
    app.dependency_overrides.clear()


def test_excluding_evidence_recomputes_state_and_trace_keeps_versioned_review_history():
    client, Session = seeded_client_and_session()
    with Session() as db:
        subskill_id = "FRC-ADD-SUB-UNLIKE"
        job = create_job(
            db,
            "diagnostic",
            CENTRE_ID,
            "STU-SYNTH-A",
            {"student_id": "STU-SYNTH-A", "subskill_id": subskill_id},
        )
        db.commit()
        claim_job(db, "worker-review")
        job = get_job(db, job.id)
        evidence_ids = [
            row.id
            for row in db.query(MasteryEvidence)
            .filter(MasteryEvidence.student_id == "STU-SYNTH-A", MasteryEvidence.subskill_id == subskill_id)
            .order_by(MasteryEvidence.created_at.asc(), MasteryEvidence.id.asc())
            .all()
        ]
        result = run_diagnostic(
            db,
            job,
            diagnostic_fixture("STU-SYNTH-A", subskill_id, "requires_support", 0.8, evidence_ids),
        )
        assert result["artifact_id"]
        evidence_id = evidence_ids[0]
        job_id = job.id

    excluded = client.post(
        f"/api/tutor/jobs/{job_id}/decision",
        params={"action": "exclude_evidence", "evidence_id": evidence_id, "reason": "Attempt was duplicated."},
        headers={"X-User-Id": TUTOR_ID},
    )
    assert excluded.status_code == 200, excluded.text
    payload = excluded.json()
    assert payload["status"] == "evidence_excluded"
    assert payload["eligible_attempts"] == 3

    edited = client.post(
        f"/api/tutor/jobs/{job_id}/decision",
        params={"action": "edit", "corrected_label": "developing", "reason": "Tutor re-evaluated the remaining evidence."},
        headers={"X-User-Id": TUTOR_ID},
    )
    assert edited.status_code == 200, edited.text

    with Session() as db:
        exclusion = db.query(TutorEvidenceExclusion).filter(TutorEvidenceExclusion.evidence_id == evidence_id).one()
        assert exclusion.author_tutor_id == TUTOR_ID
        states = (
            db.query(MasteryState)
            .filter(MasteryState.student_id == "STU-SYNTH-A", MasteryState.subskill_id == subskill_id)
            .order_by(MasteryState.version.asc())
            .all()
        )
        assert states[-1].is_override is True
        assert states[-1].label == "developing"
        assert any(state.eligible_attempts == 3 and not state.is_override for state in states)
        run_error = json.loads(db.query(AgentRun).filter(AgentRun.job_id == job_id).one().error_json or "null")
        assert run_error["code"] == "conflicting_evidence"

    trace = client.get(f"/api/tutor/jobs/{job_id}", headers={"X-User-Id": TUTOR_ID})
    assert trace.status_code == 200, trace.text
    trace_payload = trace.json()
    assert trace_payload["corrections"][0]["artifact_id"] == trace_payload["artifacts"][0]["id"]
    assert trace_payload["evidence_exclusions"][0]["evidence_id"] == evidence_id
    assert len(trace_payload["mastery_history"]) >= 3
    assert {item["action"] for item in trace_payload["decisions"]} >= {"exclude_evidence", "edit"}
    app.dependency_overrides.clear()


def test_alerts_and_review_actions_are_assignment_scoped():
    client, Session = seeded_client_and_session()
    with Session() as db:
        job = create_job(
            db,
            "diagnostic",
            CENTRE_ID,
            "STU-SYNTH-A",
            {"student_id": "STU-SYNTH-A", "subskill_id": "FRC-MULTIPLY-WHOLE"},
        )
        db.commit()
        claim_job(db, "worker-review")
        result = run_diagnostic(db, get_job(db, job.id), FakeModelClient())
        assert result["status"] == "needs_tutor_review"
        alert_id = db.query(TutorAlert).filter(TutorAlert.job_id == job.id).one().id

    assert client.get("/api/tutor/alerts?student_id=STU-SYNTH-A", headers={"X-User-Id": UNASSIGNED_TUTOR_ID}).status_code == 403
    assert client.get("/api/tutor/alerts", headers={"X-User-Id": UNASSIGNED_TUTOR_ID}).json() == []
    assert client.post(
        f"/api/tutor/alerts/{alert_id}/resolve",
        json={"reason": "Not assigned to this student."},
        headers={"X-User-Id": UNASSIGNED_TUTOR_ID},
    ).status_code == 403
    app.dependency_overrides.clear()
