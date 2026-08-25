from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from backend.app.db.base import Base
from backend.app.services.seed import seed_db
from backend.app.services.jobs import create_job, claim_job
from backend.app.agents.diagnostic import run_diagnostic
from backend.app.models.client import FakeModelClient
from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.db.models import MasteryEvidence, MasteryState
import json

def seeded_client_and_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    app.dependency_overrides[get_db] = override
    return TestClient(app), Session

def fake_for(ev_ids, label="requires_support", confidence=0.8):
    return FakeModelClient(fixtures={"Diagnostic proposal": {
        "student_id": "STU-SYNTH-A",
        "subskill_id": "FRC-ADD-SUB-UNLIKE",
        "status": "pending_tutor_review",
        "label": label,
        "confidence": confidence,
        "evidence_ids": ev_ids,
        "policy_id": "mastery_policy_v1",
        "policy_version": "1.0.0",
        "reason": f"Evidence {ev_ids} supports {label}; policy version 1.0.0 was applied.",
        "alternative_explanation": None,
        "recommended_next_action": "assign_targeted_practice",
        "source_refs": []
    }})

def test_tutor_can_open_seeded_diagnostic_trace():
    client, Session = seeded_client_and_session()
    with Session() as db:
        job = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id":"STU-SYNTH-A","subskill_id":"FRC-ADD-SUB-UNLIKE"})
        db.commit()
        claim_job(db, "worker-1")
        job = db.query(type(job)).filter_by(id=job.id).first()
        evs = db.query(MasteryEvidence).filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-ADD-SUB-UNLIKE").all()
        ev_ids = [e.id for e in evs]
        fake = fake_for(ev_ids)
        run_diagnostic(db, job, fake)
        job_id = job.id
    r = client.get(f"/api/tutor/jobs/{job_id}", headers={"X-User-Id":"TUT-SYNTH-ALPHA"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["job"]["id"] == job_id
    assert "runs" in j and len(j["runs"]) == 1
    assert "tool_calls" in j and len(j["tool_calls"]) >= 4
    assert "artifacts" in j and len(j["artifacts"]) == 1
    assert j["job"]["centre_id"] == "CTR-SYNTH-NORTHSTAR"
    # Must not expose hidden reasoning
    assert "hidden" not in json.dumps(j).lower()
    app.dependency_overrides.clear()

def test_proposal_can_be_accepted_edited_rejected_more_evidence():
    client, Session = seeded_client_and_session()
    with Session() as db:
        job = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id":"STU-SYNTH-A","subskill_id":"FRC-ADD-SUB-UNLIKE"})
        db.commit()
        claim_job(db, "worker-1")
        job = db.query(type(job)).filter_by(id=job.id).first()
        evs = db.query(MasteryEvidence).filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-ADD-SUB-UNLIKE").all()
        ev_ids = [e.id for e in evs]
        fake = fake_for(ev_ids)
        run_diagnostic(db, job, fake)
        job_id = job.id
    # Accept
    r = client.post(f"/api/tutor/jobs/{job_id}/decision?action=accept&reason=looks_good", headers={"X-User-Id":"TUT-SYNTH-ALPHA"})
    assert r.status_code == 200 and r.json()["status"]=="accepted"
    # Edit with corrected label
    r = client.post(f"/api/tutor/jobs/{job_id}/decision?action=edit&corrected_label=developing&reason=re-evaluated", headers={"X-User-Id":"TUT-SYNTH-ALPHA"})
    assert r.status_code == 200 and r.json()["status"]=="edited"
    with Session() as db:
        states = db.query(MasteryState).filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-ADD-SUB-UNLIKE").order_by(MasteryState.version.desc()).first()
        assert states.label == "developing" and states.is_override
    # More evidence
    r = client.post(f"/api/tutor/jobs/{job_id}/decision?action=more_evidence&reason=need_more", headers={"X-User-Id":"TUT-SYNTH-ALPHA"})
    assert r.status_code == 200
    # Reject
    r = client.post(f"/api/tutor/jobs/{job_id}/decision?action=reject&reason=not_valid", headers={"X-User-Id":"TUT-SYNTH-ALPHA"})
    assert r.status_code == 200 and r.json()["status"]=="rejected"
    app.dependency_overrides.clear()

def test_ui_shows_only_scoped_data_and_never_hidden_reasoning():
    client, Session = seeded_client_and_session()
    with Session() as db:
        job = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id":"STU-SYNTH-A","subskill_id":"FRC-ADD-SUB-UNLIKE"})
        db.commit()
        claim_job(db, "worker-1")
        job = db.query(type(job)).filter_by(id=job.id).first()
        evs = db.query(MasteryEvidence).filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-ADD-SUB-UNLIKE").all()
        fake = fake_for([e.id for e in evs])
        run_diagnostic(db, job, fake)
        job_id = job.id
    # Unassigned tutor should 403
    r = client.get(f"/api/tutor/jobs/{job_id}", headers={"X-User-Id":"TUT-SYNTH-BRAVO"})
    assert r.status_code == 403
    # Student should 403 (no tutor trace)
    r = client.get(f"/api/tutor/jobs/{job_id}", headers={"X-User-Id":"USER-STU-SYNTH-A"})
    assert r.status_code == 403
    # Assigned tutor can see but payload should not contain other student data
    r = client.get(f"/api/tutor/jobs/{job_id}", headers={"X-User-Id":"TUT-SYNTH-ALPHA"})
    j = r.json()
    assert "STU-SYNTH-B" not in json.dumps(j)
    app.dependency_overrides.clear()

def test_tutor_decision_persisted_and_visible_in_history():
    client, Session = seeded_client_and_session()
    with Session() as db:
        job = create_job(db, "diagnostic", "CTR-SYNTH-NORTHSTAR", "STU-SYNTH-A", {"student_id":"STU-SYNTH-A","subskill_id":"FRC-ADD-SUB-UNLIKE"})
        db.commit()
        claim_job(db, "worker-1")
        job = db.query(type(job)).filter_by(id=job.id).first()
        evs = db.query(MasteryEvidence).filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-ADD-SUB-UNLIKE").all()
        fake = fake_for([e.id for e in evs])
        run_diagnostic(db, job, fake)
        job_id = job.id
    client.post(f"/api/tutor/jobs/{job_id}/decision?action=edit&corrected_label=secure&reason=override", headers={"X-User-Id":"TUT-SYNTH-ALPHA"})
    with Session() as db:
        states = db.query(MasteryState).filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-ADD-SUB-UNLIKE").order_by(MasteryState.version.asc()).all()
        # Last should be override
        assert states[-1].is_override and states[-1].label=="secure"
        # Check audit
        from backend.app.db.models import AuditEvent
        audits = db.query(AuditEvent).filter(AuditEvent.event=="tutor_decision.edit").all()
        assert len(audits) >=1
    # Trace should still be readable after decision
    r = client.get(f"/api/tutor/jobs/{job_id}", headers={"X-User-Id":"TUT-SYNTH-ALPHA"})
    assert r.status_code == 200
    app.dependency_overrides.clear()
