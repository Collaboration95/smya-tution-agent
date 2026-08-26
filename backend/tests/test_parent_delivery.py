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
from backend.app.auth.permissions import PermissionDenied
from backend.app.communication.delivery import (
    DeliveryBlocked,
    SimulatedDeliveryAdapter,
    approve_parent_report,
    deliver_parent_report,
    queue_parent_report,
    reject_parent_report,
)
from backend.app.db.base import Base
from backend.app.db.models import AuditEvent, GuardianLink, MasteryState, ParentReportDelivery, ParentReportDraft
from backend.app.main import app
from backend.app.models.client import FakeModelClient
from backend.app.reports.service import create_parent_report_job
from backend.app.schemas.reports import ParentReportJobRequest, ReportPeriod
from backend.app.services.jobs import claim_job, get_job
from backend.app.services.seed import seed_db
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


def report_request() -> ParentReportJobRequest:
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


def prepare_history(db) -> None:
    base = datetime.now(UTC).replace(microsecond=0)
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
    state.created_at = base + timedelta(days=2)
    state.label = "developing"
    state.accuracy = 0.5
    db.add(
        MasteryState(
            id="mst-delivery-previous",
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
            created_at=base - timedelta(days=2),
        )
    )
    db.add(
        MasteryState(
            id="mst-delivery-future",
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
            created_at=base + timedelta(days=30),
        )
    )
    db.flush()


def prepare_draft(db) -> ParentReportDraft:
    prepare_history(db)
    job = create_parent_report_job(db, tutor(), report_request())
    db.commit()
    claimed = claim_job(db, "worker-parent-delivery", job_type="parent_report")
    assert claimed is not None
    result = run_parent_report(db, get_job(db, job.id), FakeModelClient())
    assert result["status"] == "needs_tutor_review"
    return db.query(ParentReportDraft).filter_by(id=result["draft_id"]).one()


def add_guardian(db, guardian_id: str, *, verified: bool, consent: bool) -> None:
    db.add(
        GuardianLink(
            id=guardian_id,
            centre_id=CENTRE_ID,
            student_id=STUDENT_ID,
            display_name=guardian_id,
            verification_status="verified" if verified else "pending",
            reporting_consent=consent,
            is_synthetic=True,
        )
    )
    db.flush()


def test_unapproved_parent_report_cannot_be_queued():
    Session = make_db()
    with Session() as db:
        draft = prepare_draft(db)
        with pytest.raises(ValueError, match="only an approved"):
            queue_parent_report(db, tutor(), draft.id)
        assert db.query(ParentReportDelivery).filter_by(draft_id=draft.id).count() == 0


def test_missing_or_unverified_guardian_blocks_approval_and_delivery():
    Session = make_db()
    with Session() as db:
        draft = prepare_draft(db)
        with pytest.raises(DeliveryBlocked) as missing:
            approve_parent_report(db, tutor(), draft.id, "GRD-NOT-FOUND")
        assert missing.value.reason == "guardian_link_not_found"
        assert draft.status == "blocked"
        db.commit()

        add_guardian(db, "GRD-SYNTH-A-PENDING", verified=False, consent=False)
        with pytest.raises(DeliveryBlocked) as unverified:
            approve_parent_report(db, tutor(), draft.id, "GRD-SYNTH-A-PENDING")
        assert unverified.value.reason == "guardian_link_not_verified"
        assert draft.status == "blocked"
        assert db.query(ParentReportDelivery).count() == 0


def test_missing_consent_blocks_queue_and_send_without_adapter_call():
    Session = make_db()
    with Session() as db:
        draft = prepare_draft(db)
        add_guardian(db, "GRD-SYNTH-A-NO-CONSENT", verified=True, consent=False)
        with pytest.raises(DeliveryBlocked) as blocked:
            approve_parent_report(db, tutor(), draft.id, "GRD-SYNTH-A-NO-CONSENT")
        assert blocked.value.reason == "reporting_consent_missing"
        assert draft.status == "blocked"

    # A separate approved run proves consent is checked again at queue time.
    Session = make_db()
    with Session() as db:
        draft = prepare_draft(db)
        approve_parent_report(db, tutor(), draft.id, "GRD-SYNTH-A-VERIFIED")
        db.query(GuardianLink).filter_by(id="GRD-SYNTH-A-VERIFIED").one().reporting_consent = False
        with pytest.raises(DeliveryBlocked) as queue_blocked:
            queue_parent_report(db, tutor(), draft.id)
        assert queue_blocked.value.reason == "reporting_consent_missing"
        assert draft.status == "blocked"


def test_approved_report_queues_and_simulated_delivery_is_idempotent_and_auditable():
    Session = make_db()
    with Session() as db:
        draft = prepare_draft(db)
        approved = approve_parent_report(
            db,
            tutor(),
            draft.id,
            "GRD-SYNTH-A-VERIFIED",
            reason="Reviewed against the selected history",
        )
        assert approved.status == "approved"
        delivery = queue_parent_report(db, tutor(), draft.id)
        duplicate = queue_parent_report(db, tutor(), draft.id)
        assert duplicate.id == delivery.id
        assert delivery.status == "queued_for_delivery"
        assert json.loads(delivery.approved_content_json) == json.loads(draft.content_json)
        assert db.query(ParentReportDelivery).filter_by(draft_id=draft.id).count() == 1

        adapter = SimulatedDeliveryAdapter()
        delivered = deliver_parent_report(db, tutor(), delivery.id, adapter)
        repeated = deliver_parent_report(db, tutor(), delivery.id, adapter)
        assert delivered.id == repeated.id
        assert delivered.status == "delivered"
        assert delivered.provider_message_id == repeated.provider_message_id
        assert adapter.send_count == 1
        assert draft.status == "delivered"
        events = db.query(AuditEvent).filter(AuditEvent.entity_id.in_([draft.id, delivery.id])).all()
        event_names = {event.event for event in events}
        assert {
            "parent_report.approved",
            "parent_report.queued_for_delivery",
            "parent_report.delivered",
            "parent_report_delivery.delivered",
        }.issubset(event_names)
        assert any("content_sha256" in (event.after_json or "") for event in events)


def test_revoked_consent_blocks_queued_delivery_before_adapter_send():
    Session = make_db()
    with Session() as db:
        draft = prepare_draft(db)
        approve_parent_report(db, tutor(), draft.id, "GRD-SYNTH-A-VERIFIED")
        delivery = queue_parent_report(db, tutor(), draft.id)
        db.query(GuardianLink).filter_by(id="GRD-SYNTH-A-VERIFIED").one().reporting_consent = False
        adapter = SimulatedDeliveryAdapter()
        with pytest.raises(DeliveryBlocked) as blocked:
            deliver_parent_report(db, tutor(), delivery.id, adapter)
        assert blocked.value.reason == "reporting_consent_missing"
        assert adapter.send_count == 0
        assert delivery.status == "blocked"
        assert draft.status == "blocked"


def test_unassigned_tutor_cannot_approve_parent_report():
    Session = make_db()
    bravo = CallerContext(user_id="TUT-SYNTH-BRAVO", centre_id=CENTRE_ID, role="tutor")
    with Session() as db:
        draft = prepare_draft(db)
        with pytest.raises(PermissionDenied):
            approve_parent_report(db, bravo, draft.id, "GRD-SYNTH-A-VERIFIED")


def test_reject_parent_report_requires_reason_and_is_audited():
    Session = make_db()
    with Session() as db:
        draft = prepare_draft(db)
        with pytest.raises(ValueError, match="reason"):
            reject_parent_report(db, tutor(), draft.id, "  ")
        rejected = reject_parent_report(db, tutor(), draft.id, "Unsupported comparison")
        assert rejected.status == "rejected"
        assert rejected.reviewed_by == tutor().user_id
        assert db.query(AuditEvent).filter_by(entity_id=draft.id, event="parent_report.rejected").count() == 1


def test_parent_report_api_exposes_workflow_and_guardian_read_after_delivery():
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
    headers = {"X-User-Id": "TUT-SYNTH-ALPHA"}
    try:
        created = client.post(
            "/api/parent-reports/jobs",
            json=report_request().model_dump(mode="json"),
            headers=headers,
        )
        assert created.status_code == 200, created.text
        job_id = created.json()["job_id"]
        ran = client.post(f"/api/parent-reports/jobs/{job_id}/run", headers=headers)
        assert ran.status_code == 200, ran.text
        draft = client.get(f"/api/parent-reports/jobs/{job_id}", headers=headers)
        assert draft.status_code == 200, draft.text
        draft_id = draft.json()["id"]
        assert draft.json()["guardian_links"][0]["verification_status"] == "verified"

        denied_approval = client.post(
            f"/api/parent-reports/drafts/{draft_id}/approve",
            json={"guardian_link_id": "GRD-SYNTH-A-VERIFIED"},
            headers={"X-User-Id": "TUT-SYNTH-BRAVO"},
        )
        assert denied_approval.status_code == 403, denied_approval.text

        approved = client.post(
            f"/api/parent-reports/drafts/{draft_id}/approve",
            json={"guardian_link_id": "GRD-SYNTH-A-VERIFIED", "reason": "Tutor review complete"},
            headers=headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        queued = client.post(f"/api/parent-reports/drafts/{draft_id}/queue", headers=headers)
        assert queued.status_code == 200, queued.text
        delivery = queued.json()["delivery"]
        assert queued.json()["status"] == "queued_for_delivery"
        sent = client.post(f"/api/parent-reports/deliveries/{delivery['id']}/send", headers=headers)
        assert sent.status_code == 200, sent.text
        assert sent.json()["status"] == "delivered"
        guardian = client.get(
            f"/api/parent-reports/deliveries/{delivery['id']}",
            headers={"X-User-Id": "GRD-SYNTH-A-VERIFIED"},
        )
        assert guardian.status_code == 200, guardian.text
        assert guardian.json()["approved_content"]["student_id"] == STUDENT_ID
        pending_guardian = client.get(
            f"/api/parent-reports/deliveries/{delivery['id']}",
            headers={"X-User-Id": "GRD-SYNTH-B-PENDING"},
        )
        assert pending_guardian.status_code == 403

        blocked_generic_decision = client.post(
            f"/api/tutor/jobs/{job_id}/decision?action=accept",
            headers=headers,
        )
        assert blocked_generic_decision.status_code == 409
    finally:
        app.dependency_overrides.clear()
