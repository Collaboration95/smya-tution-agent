from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied
from backend.app.db.base import Base
from backend.app.db.models import (
    AssessmentAssignment,
    AssessmentDraft,
    Attempt,
    AuditEvent,
    Centre,
    MasteryEvidence,
    Question,
)
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.practice.selector import select_practice_items, selection_cache_key, validate_question_selection
from backend.app.practice.service import (
    approve_draft,
    assign_draft,
    block_draft,
    create_assessment_draft,
    edit_draft,
    get_assignment,
)
from backend.app.services.mastery import load_policy
from backend.app.services.seed import seed_db
from backend.app.services.jobs import create_job
from backend.app.tools.contracts import SaveAssessmentDraftRequest
from backend.app.tools.registry import invoke_tool


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


def tutor_context(user_id: str = "TUT-SYNTH-ALPHA") -> CallerContext:
    return CallerContext(
        user_id=user_id,
        centre_id="CTR-SYNTH-NORTHSTAR",
        role="tutor",
    )


def test_selector_diverges_by_effective_state_and_is_repeatable():
    Session = seeded_session()
    with Session() as db:
        student_a = select_practice_items(
            db,
            student_id="STU-SYNTH-A",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            item_count=2,
        )
        student_b = select_practice_items(
            db,
            student_id="STU-SYNTH-B",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            item_count=2,
        )
        assert student_a["target_difficulty"] == "foundation"
        assert student_a["question_ids"] == ["Q-FRC-ADD-001", "Q-FRC-ADD-005"]
        assert student_b["target_difficulty"] == "stretch"
        assert student_b["question_ids"] == ["Q-FRC-ADD-006", "Q-FRC-ADD-004"]
        assert student_a["question_ids"] != student_b["question_ids"]
        assert select_practice_items(
            db,
            student_id="STU-SYNTH-A",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            item_count=2,
        ) == student_a
        assert student_a["cache_key"] != student_b["cache_key"]
        key = selection_cache_key(
            centre_id="CTR-SYNTH-NORTHSTAR",
            student_id="STU-SYNTH-A",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            mastery_state_version=student_a["effective_mastery"]["version"],
            policy_id="mastery_policy_v1",
            policy_version="1.0.0",
            recent_question_ids=[],
            item_count=2,
        )
        assert key == student_a["cache_key"]
        assert key != selection_cache_key(
            centre_id="CTR-SYNTH-NORTHSTAR",
            student_id="STU-SYNTH-A",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            mastery_state_version=student_a["effective_mastery"]["version"],
            policy_id="mastery_policy_v1",
            policy_version="1.0.0",
            recent_question_ids=["Q-FRC-ADD-001"],
            item_count=2,
        )


def test_selector_excludes_recent_and_rejects_unapproved_or_cross_centre_questions():
    Session = seeded_session()
    with Session() as db:
        db.add(Centre(id="CTR-OTHER", display_name="Other Synthetic Centre", is_synthetic=True))
        db.flush()
        db.add(
            Question(
                id="Q-PENDING-FOUNDATION",
                centre_id="CTR-SYNTH-NORTHSTAR",
                source_id="SRC-SYNTH-FRACTIONS-V1",
                subskill_id="FRC-ADD-SUB-UNLIKE",
                template_id="pending",
                difficulty="foundation",
                prompt="pending",
                expected_answer="0",
                answer_type="objective_exact",
                status="pending",
                selection_rank=1,
            )
        )
        db.add(
            Question(
                id="Q-OTHER-FOUNDATION",
                centre_id="CTR-OTHER",
                source_id="SRC-SYNTH-FRACTIONS-V1",
                subskill_id="FRC-ADD-SUB-UNLIKE",
                template_id="other",
                difficulty="foundation",
                prompt="other centre",
                expected_answer="0",
                answer_type="objective_exact",
                status="approved",
                selection_rank=1,
            )
        )
        db.commit()
        selected = select_practice_items(
            db,
            student_id="STU-SYNTH-A",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            item_count=1,
            recent_question_ids=["Q-FRC-ADD-001"],
        )
        assert selected["question_ids"] == ["Q-FRC-ADD-005"]
        with pytest.raises(ValueError, match="approved"):
            validate_question_selection(
                db,
                student_id="STU-SYNTH-A",
                subskill_id="FRC-ADD-SUB-UNLIKE",
                question_ids=["Q-PENDING-FOUNDATION"],
            )


def test_draft_is_separate_from_assignment_and_approval_is_audited():
    Session = seeded_session()
    with Session() as db:
        caller = tutor_context()
        draft = create_assessment_draft(
            db,
            caller=caller,
            student_id="STU-SYNTH-A",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            item_count=2,
            class_id="CLS-SYNTH-P5-FRACTIONS",
        )
        assert draft.status == "pending_tutor_review"
        assert db.query(AssessmentAssignment).filter_by(draft_id=draft.id).count() == 0
        snapshot = json.loads(draft.input_json)
        assert snapshot["question_ids"] == ["Q-FRC-ADD-001", "Q-FRC-ADD-005"]
        assert snapshot["questions"][0]["template_id"]
        assert snapshot["questions"][0]["source_id"] == "SRC-SYNTH-FRACTIONS-V1"
        assert snapshot["policy"]["policy_version"] == "1.0.0"
        with pytest.raises(ValueError, match="approved"):
            assign_draft(db, caller=caller, draft_id=draft.id)

        edited = edit_draft(
            db,
            caller=caller,
            draft_id=draft.id,
            question_ids=["Q-FRC-ADD-005", "Q-FRC-ADD-001"],
            reason="Tutor reordered scaffold steps",
        )
        assert edited.status == "pending_tutor_review"
        assert json.loads(edited.input_json)["human_edit"]["reason"] == "Tutor reordered scaffold steps"
        approved = approve_draft(db, caller=caller, draft_id=draft.id, reason="Reviewed for this class")
        assert approved.status == "approved"
        assignment = assign_draft(db, caller=caller, draft_id=draft.id)
        assert assignment.status == "assigned"
        assert db.get(AssessmentDraft, draft.id).status == "assigned"
        events = db.query(AuditEvent).filter(AuditEvent.entity_id == draft.id).all()
        assert {event.event for event in events} >= {
            "assessment_draft.created",
            "assessment_draft.edited",
            "assessment_draft.approved",
        }

        blocked_draft = create_assessment_draft(
            db,
            caller=caller,
            student_id="STU-SYNTH-A",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            item_count=2,
            class_id="CLS-SYNTH-P5-FRACTIONS",
        )
        blocked = block_draft(db, caller=caller, draft_id=blocked_draft.id, reason="Source review required")
        assert blocked.status == "blocked"
        with pytest.raises(ValueError, match="approved"):
            assign_draft(db, caller=caller, draft_id=blocked_draft.id)


def test_only_assigned_tutor_can_approve_and_typed_tool_rechecks_sources():
    Session = seeded_session()
    with Session() as db:
        with pytest.raises(PermissionDenied):
            create_assessment_draft(
                db,
                caller=tutor_context("TUT-SYNTH-BRAVO"),
                student_id="STU-SYNTH-A",
                subskill_id="FRC-ADD-SUB-UNLIKE",
                item_count=2,
            )

        policy = load_policy()
        job = create_job(
            db,
            "assessment",
            "CTR-SYNTH-NORTHSTAR",
            "STU-SYNTH-A",
            {
                "student_id": "STU-SYNTH-A",
                "approval_status": "approved",
            },
        )
        response = invoke_tool(
            db,
            tutor_context(),
            job,
            "save_assessment_draft",
            SaveAssessmentDraftRequest(
                student_id="STU-SYNTH-A",
                subskill_id="FRC-ADD-SUB-UNLIKE",
                question_ids=["Q-FRC-ADD-001", "Q-FRC-ADD-005"],
                selection_policy_version="1.0.0",
                policy_version=policy["version"],
            ).model_dump(),
        )
        assert response.status == "pending_tutor_review"
        assert db.query(AssessmentAssignment).filter_by(draft_id=response.draft_id).count() == 0


def test_assessment_api_keeps_approval_and_assignment_as_separate_operations():
    Session = seeded_session()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    headers = {"X-User-Id": "TUT-SYNTH-ALPHA"}
    try:
        created = client.post(
            "/api/assessment/drafts",
            headers=headers,
            json={
                "student_id": "STU-SYNTH-A",
                "subskill_id": "FRC-ADD-SUB-UNLIKE",
                "item_count": 2,
                "class_id": "CLS-SYNTH-P5-FRACTIONS",
            },
        )
        assert created.status_code == 200, created.text
        draft = created.json()
        assert draft["status"] == "pending_tutor_review"
        assert draft["assignment_id"] is None
        assert client.post(f"/api/assessment/drafts/{draft['id']}/assign", headers=headers).status_code == 409

        approved = client.post(
            f"/api/assessment/drafts/{draft['id']}/approve",
            headers=headers,
            json={"reason": "Reviewed source and difficulty"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assigned = client.post(f"/api/assessment/drafts/{draft['id']}/assign", headers=headers)
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["status"] == "assigned"
        assert assigned.json()["draft_status"] == "assigned"
    finally:
        app.dependency_overrides.clear()


def test_student_api_delivers_hints_answers_evidence_and_next_diagnostic():
    Session = seeded_session()
    with Session() as db:
        assignment_a = db.query(AssessmentAssignment).filter_by(student_id="STU-SYNTH-A").first()
        assignment_b = db.query(AssessmentAssignment).filter_by(student_id="STU-SYNTH-B").first()
        assert assignment_a is not None and assignment_b is not None
        assignment_a_id = assignment_a.id
        assignment_b_id = assignment_b.id
        expected_by_question = {
            q.id: q.expected_answer
            for q in db.query(Question).filter(Question.id.in_(["Q-FRC-ADD-001", "Q-FRC-ADD-005"])).all()
        }

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        headers_a = {"X-User-Id": "USER-STU-SYNTH-A"}
        headers_b = {"X-User-Id": "USER-STU-SYNTH-B"}
        listing = client.get("/api/practice/assignments", headers=headers_a)
        assert listing.status_code == 200, listing.text
        assert [item["student_id"] for item in listing.json()] == ["STU-SYNTH-A"]
        assert "expected_answer" not in json.dumps(listing.json())
        assert client.get(f"/api/practice/assignments/{assignment_a_id}", headers=headers_b).status_code == 403

        started = client.post(f"/api/practice/assignments/{assignment_a_id}/start", headers=headers_a)
        assert started.status_code == 200, started.text
        session = started.json()
        session_id = session["id"]
        question_id = session["current_question"]["id"]
        assert "expected_answer" not in json.dumps(session)

        hint_one = client.post(
            f"/api/practice/sessions/{session_id}/hint",
            json={"question_id": question_id},
            headers=headers_a,
        )
        hint_two = client.post(
            f"/api/practice/sessions/{session_id}/hint",
            json={"question_id": question_id},
            headers=headers_a,
        )
        hint_three = client.post(
            f"/api/practice/sessions/{session_id}/hint",
            json={"question_id": question_id},
            headers=headers_a,
        )
        assert hint_one.json()["level"] == 1
        assert hint_two.json()["level"] == 2
        assert hint_three.json()["level"] == 2

        first_answer = client.post(
            f"/api/practice/sessions/{session_id}/answers",
            json={"question_id": question_id, "answer": expected_by_question[question_id]},
            headers=headers_a,
        )
        assert first_answer.status_code == 200, first_answer.text
        assert first_answer.json()["is_correct"] is True
        next_question_id = first_answer.json()["session"]["current_question"]["id"]
        second_answer = client.post(
            f"/api/practice/sessions/{session_id}/answers",
            json={"question_id": next_question_id, "answer": "not the answer"},
            headers=headers_a,
        )
        assert second_answer.status_code == 200, second_answer.text
        assert second_answer.json()["session"]["status"] == "completed"
        assert second_answer.json()["diagnostic_job_id"]

        with Session() as db:
            assert db.query(Attempt).filter(Attempt.practice_session_id == session_id).count() == 2
            assert db.query(MasteryEvidence).filter(MasteryEvidence.student_id == "STU-SYNTH-A").count() == 7
            assert db.query(AssessmentAssignment).filter_by(id=assignment_a_id, status="closed").count() == 1
            draft_id = db.query(AssessmentAssignment).filter_by(id=assignment_a_id).one().draft_id
            assert db.get(AssessmentDraft, draft_id).status == "closed"
            assert client.get(f"/api/practice/assignments/{assignment_b_id}", headers=headers_a).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_delivery_rechecks_question_approval_after_assignment():
    Session = seeded_session()
    with Session() as db:
        assignment = db.query(AssessmentAssignment).filter_by(student_id="STU-SYNTH-A").first()
        question = db.get(Question, "Q-FRC-ADD-001")
        assert assignment is not None and question is not None
        question.status = "rejected"
        db.commit()
        student = CallerContext(
            user_id="USER-STU-SYNTH-A",
            centre_id="CTR-SYNTH-NORTHSTAR",
            role="student",
            student_id="STU-SYNTH-A",
        )
        with pytest.raises(ValueError, match="no longer approved"):
            get_assignment(db, caller=student, assignment_id=assignment.id)
