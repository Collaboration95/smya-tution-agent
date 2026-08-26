from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied, can_approve_student, can_read_student, require_read_student
from backend.app.db.models import (
    AssessmentAssignment,
    AssessmentDraft,
    Attempt,
    AuditEvent,
    Class,
    Enrolment,
    MasteryEvidence,
    PracticeHint,
    PracticeSession,
    Question,
    Student,
)
from backend.app.practice.selector import (
    SELECTION_POLICY_ID,
    SELECTION_POLICY_VERSION,
    select_practice_items,
    validate_question_selection,
)
from backend.app.services.jobs import create_job
from backend.app.services.mastery import get_effective_mastery, load_policy, normalise_answer, upsert_mastery_state


DRAFT_STATUSES = {"draft", "pending_tutor_review", "approved", "assigned", "active", "closed", "rejected", "blocked"}
ASSIGNMENT_STATUSES = {"assigned", "active", "closed"}
MAX_HINT_LEVEL = 2
HINTS_BY_SUBSKILL = {
    "FRC-ADD-SUB-UNLIKE": {
        1: "Find a common denominator before you add or subtract.",
        2: "Rewrite both fractions with the same denominator, then combine the numerators.",
    },
    "FRC-EQUIVALENCE": {
        1: "Multiply the numerator and denominator by the same number.",
        2: "Check that the value stays the same when the denominator changes.",
    },
    "FRC-COMPARE-ORDER": {
        1: "Compare the fractions using a common denominator.",
        2: "Rewrite both fractions with matching denominators, then compare numerators.",
    },
    "FRC-MULTIPLY-WHOLE": {
        1: "Multiply the numerator by the whole number and keep the denominator.",
        2: "Write the multiplication as repeated addition before simplifying.",
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(
    db: Session,
    *,
    caller: CallerContext,
    event: str,
    entity_type: str,
    entity_id: str,
    after: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            id=f"aud-{uuid.uuid4().hex[:8]}",
            centre_id=caller.centre_id,
            actor_id=caller.user_id,
            actor_role=caller.role,
            event=event,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=json.dumps(before, sort_keys=True) if before is not None else None,
            after_json=json.dumps(after, sort_keys=True) if after is not None else None,
            created_at=_now(),
        )
    )
    db.flush()


def _student(db: Session, student_id: str) -> Student:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise ValueError(f"unknown student: {student_id}")
    return student


def _require_draft_manager(db: Session, caller: CallerContext, student_id: str, class_id: str | None = None) -> None:
    if caller.role not in ("admin", "tutor"):
        raise PermissionDenied("only an admin or assigned tutor may manage practice drafts")
    if caller.centre_id != _student(db, student_id).centre_id:
        raise PermissionDenied("student is outside caller centre")
    if not can_approve_student(db, caller, student_id):
        raise PermissionDenied("caller is not assigned to the target student")
    if class_id:
        class_record = (
            db.query(Class)
            .filter(Class.id == class_id, Class.centre_id == caller.centre_id)
            .first()
        )
        if not class_record or (caller.role == "tutor" and class_record.tutor_id != caller.user_id):
            raise PermissionDenied("caller cannot manage the target class")
        enrolled = (
            db.query(Enrolment)
            .filter(
                Enrolment.class_id == class_id,
                Enrolment.student_id == student_id,
                Enrolment.centre_id == caller.centre_id,
                Enrolment.status == "active",
            )
            .first()
        )
        if not enrolled:
            raise PermissionDenied("student is not actively enrolled in the target class")


def _draft_snapshot(draft: AssessmentDraft) -> dict[str, Any]:
    return json.loads(draft.input_json)


def _question_count(draft: AssessmentDraft) -> int:
    return len(json.loads(draft.question_ids_json))


def _assignment_for_draft(db: Session, draft_id: str) -> AssessmentAssignment | None:
    return db.query(AssessmentAssignment).filter(AssessmentAssignment.draft_id == draft_id).first()


def serialize_draft(db: Session, draft: AssessmentDraft) -> dict[str, Any]:
    assignment = _assignment_for_draft(db, draft.id)
    return {
        "id": draft.id,
        "centre_id": draft.centre_id,
        "student_id": draft.student_id,
        "class_id": draft.class_id,
        "subskill_id": draft.subskill_id,
        "status": draft.status,
        "selection_policy_id": draft.selection_policy_id,
        "selection_policy_version": draft.selection_policy_version,
        "policy_id": draft.policy_id,
        "policy_version": draft.policy_version,
        "mastery_state_version": draft.mastery_state_version,
        "question_ids": json.loads(draft.question_ids_json),
        "input": _draft_snapshot(draft),
        "created_by": draft.created_by,
        "reviewed_by": draft.reviewed_by,
        "review_reason": draft.review_reason,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "assignment_id": assignment.id if assignment else None,
    }


def _store_draft(
    db: Session,
    *,
    caller: CallerContext,
    student: Student,
    subskill_id: str,
    snapshot: dict[str, Any],
    class_id: str | None,
) -> AssessmentDraft:
    state = get_effective_mastery(db, student.id, subskill_id)
    if not state:
        raise ValueError(f"effective mastery state is unavailable for {student.id}/{subskill_id}")
    policy = load_policy()
    question_ids = snapshot.get("question_ids")
    if not isinstance(question_ids, list):
        raise ValueError("selection snapshot must contain question_ids")
    snapshot = dict(snapshot)
    snapshot["status"] = "pending_tutor_review"
    snapshot["created_by"] = caller.user_id
    snapshot["created_at"] = _now().isoformat()
    draft = AssessmentDraft(
        id=f"draft-{uuid.uuid4().hex[:10]}",
        centre_id=student.centre_id,
        student_id=student.id,
        class_id=class_id,
        subskill_id=subskill_id,
        status="pending_tutor_review",
        selection_policy_id=snapshot.get("selection_policy_id", SELECTION_POLICY_ID),
        selection_policy_version=snapshot.get("selection_policy_version", SELECTION_POLICY_VERSION),
        policy_id=state.policy_id,
        policy_version=state.policy_version,
        mastery_state_version=state.version,
        question_ids_json=json.dumps(question_ids),
        input_json=json.dumps(snapshot, sort_keys=True),
        created_by=caller.user_id,
        created_at=_now(),
        updated_at=_now(),
    )
    if draft.policy_id != policy["policy_id"] or draft.policy_version != policy["version"]:
        raise ValueError("selection policy does not match the current mastery policy")
    db.add(draft)
    db.flush()
    _audit(
        db,
        caller=caller,
        event="assessment_draft.created",
        entity_type="assessment_draft",
        entity_id=draft.id,
        after={"status": draft.status, "question_ids": question_ids, "cache_key": snapshot.get("cache_key")},
    )
    return draft


def create_assessment_draft(
    db: Session,
    *,
    caller: CallerContext,
    student_id: str,
    subskill_id: str,
    item_count: int = 2,
    recent_question_ids: list[str] | None = None,
    class_id: str | None = None,
) -> AssessmentDraft:
    _require_draft_manager(db, caller, student_id, class_id)
    student = _student(db, student_id)
    snapshot = select_practice_items(
        db,
        student_id=student_id,
        subskill_id=subskill_id,
        item_count=item_count,
        recent_question_ids=recent_question_ids,
    )
    return _store_draft(
        db,
        caller=caller,
        student=student,
        subskill_id=subskill_id,
        snapshot=snapshot,
        class_id=class_id,
    )


def create_assessment_draft_from_selection(
    db: Session,
    *,
    caller: CallerContext,
    student_id: str,
    subskill_id: str,
    question_ids: list[str],
    selection_policy_version: str,
    policy_version: str,
    class_id: str | None = None,
) -> AssessmentDraft:
    """Persist a typed tool selection after re-checking every boundary."""

    _require_draft_manager(db, caller, student_id, class_id)
    student = _student(db, student_id)
    state = get_effective_mastery(db, student_id, subskill_id)
    policy = load_policy()
    if not state or state.policy_version != policy_version or policy["version"] != policy_version:
        raise ValueError("selection mastery policy is stale")
    if selection_policy_version != SELECTION_POLICY_VERSION:
        raise ValueError("unsupported selection policy version")
    questions = validate_question_selection(
        db,
        student_id=student_id,
        subskill_id=subskill_id,
        question_ids=question_ids,
    )
    snapshot = {
        "student_id": student_id,
        "centre_id": student.centre_id,
        "subskill_id": subskill_id,
        "selection_policy_id": SELECTION_POLICY_ID,
        "selection_policy_version": selection_policy_version,
        "cache_key": None,
        "item_count": len(question_ids),
        "recent_question_ids": [],
        "target_difficulty": "human_selected",
        "effective_mastery": {"label": state.label, "version": state.version, "is_override": state.is_override},
        "policy": {"policy_id": policy["policy_id"], "policy_version": policy["version"]},
        "questions": questions,
        "question_ids": question_ids,
        "source_ids": sorted({question["source_id"] for question in questions}),
    }
    return _store_draft(
        db,
        caller=caller,
        student=student,
        subskill_id=subskill_id,
        snapshot=snapshot,
        class_id=class_id,
    )


def get_draft_for_manager(db: Session, caller: CallerContext, draft_id: str) -> AssessmentDraft:
    draft = db.query(AssessmentDraft).filter(AssessmentDraft.id == draft_id).first()
    if not draft:
        raise ValueError("draft not found")
    _require_draft_manager(db, caller, draft.student_id, draft.class_id)
    return draft


def edit_draft(
    db: Session,
    *,
    caller: CallerContext,
    draft_id: str,
    question_ids: list[str],
    reason: str,
) -> AssessmentDraft:
    draft = get_draft_for_manager(db, caller, draft_id)
    if draft.status not in ("draft", "pending_tutor_review"):
        raise ValueError(f"draft cannot be edited from {draft.status}")
    questions = validate_question_selection(
        db,
        student_id=draft.student_id,
        subskill_id=draft.subskill_id,
        question_ids=question_ids,
    )
    snapshot = _draft_snapshot(draft)
    snapshot["questions"] = questions
    snapshot["question_ids"] = question_ids
    snapshot["item_count"] = len(question_ids)
    snapshot["human_edit"] = {"editor": caller.user_id, "reason": reason.strip(), "edited_at": _now().isoformat()}
    before_status = draft.status
    draft.status = "pending_tutor_review"
    draft.question_ids_json = json.dumps(question_ids)
    draft.input_json = json.dumps(snapshot, sort_keys=True)
    draft.reviewed_by = None
    draft.review_reason = reason.strip() or None
    draft.updated_at = _now()
    db.flush()
    _audit(
        db,
        caller=caller,
        event="assessment_draft.edited",
        entity_type="assessment_draft",
        entity_id=draft.id,
        before={"status": before_status},
        after={"status": draft.status, "question_ids": question_ids, "reason": reason.strip()},
    )
    return draft


def approve_draft(db: Session, *, caller: CallerContext, draft_id: str, reason: str | None = None) -> AssessmentDraft:
    draft = get_draft_for_manager(db, caller, draft_id)
    if draft.status != "pending_tutor_review":
        raise ValueError(f"draft cannot be approved from {draft.status}")
    draft.status = "approved"
    draft.reviewed_by = caller.user_id
    draft.review_reason = reason.strip() if reason and reason.strip() else None
    draft.updated_at = _now()
    db.flush()
    _audit(
        db,
        caller=caller,
        event="assessment_draft.approved",
        entity_type="assessment_draft",
        entity_id=draft.id,
        after={"status": draft.status, "reason": draft.review_reason},
    )
    return draft


def reject_draft(db: Session, *, caller: CallerContext, draft_id: str, reason: str) -> AssessmentDraft:
    draft = get_draft_for_manager(db, caller, draft_id)
    if draft.status != "pending_tutor_review":
        raise ValueError(f"draft cannot be rejected from {draft.status}")
    if not reason.strip():
        raise ValueError("a rejection reason is required")
    draft.status = "rejected"
    draft.reviewed_by = caller.user_id
    draft.review_reason = reason.strip()
    draft.updated_at = _now()
    db.flush()
    _audit(
        db,
        caller=caller,
        event="assessment_draft.rejected",
        entity_type="assessment_draft",
        entity_id=draft.id,
        after={"status": draft.status, "reason": draft.review_reason},
    )
    return draft


def block_draft(db: Session, *, caller: CallerContext, draft_id: str, reason: str) -> AssessmentDraft:
    draft = get_draft_for_manager(db, caller, draft_id)
    if draft.status not in ("pending_tutor_review", "approved"):
        raise ValueError(f"draft cannot be blocked from {draft.status}")
    if not reason.strip():
        raise ValueError("a blocking reason is required")
    before_status = draft.status
    draft.status = "blocked"
    draft.reviewed_by = caller.user_id
    draft.review_reason = reason.strip()
    draft.updated_at = _now()
    db.flush()
    _audit(
        db,
        caller=caller,
        event="assessment_draft.blocked",
        entity_type="assessment_draft",
        entity_id=draft.id,
        before={"status": before_status},
        after={"status": draft.status, "reason": draft.review_reason},
    )
    return draft


def assign_draft(db: Session, *, caller: CallerContext, draft_id: str) -> AssessmentAssignment:
    draft = get_draft_for_manager(db, caller, draft_id)
    existing = _assignment_for_draft(db, draft.id)
    if existing:
        return existing
    if draft.status != "approved":
        raise ValueError("only an approved assessment draft can be assigned")
    idempotency_key = f"assessment-assignment:{hashlib.sha256(draft.id.encode()).hexdigest()[:24]}"
    assignment = AssessmentAssignment(
        id=f"asg-{uuid.uuid4().hex[:10]}",
        draft_id=draft.id,
        centre_id=draft.centre_id,
        student_id=draft.student_id,
        class_id=draft.class_id,
        status="assigned",
        assigned_by=caller.user_id,
        idempotency_key=idempotency_key,
        assigned_at=_now(),
        created_at=_now(),
    )
    db.add(assignment)
    draft.status = "assigned"
    draft.updated_at = _now()
    db.flush()
    _audit(
        db,
        caller=caller,
        event="assessment_assignment.created",
        entity_type="assessment_assignment",
        entity_id=assignment.id,
        after={"draft_id": draft.id, "student_id": draft.student_id, "status": assignment.status},
    )
    return assignment


def _require_assignment_access(db: Session, caller: CallerContext, assignment: AssessmentAssignment) -> None:
    if caller.centre_id != assignment.centre_id:
        raise PermissionDenied("assignment is outside caller centre")
    if caller.role == "student":
        if caller.student_id != assignment.student_id:
            raise PermissionDenied("student may only access their own assignment")
        return
    if caller.role in ("admin", "tutor") and can_read_student(db, caller, assignment.student_id):
        return
    raise PermissionDenied("caller cannot access this assignment")


def _assignment(db: Session, assignment_id: str) -> AssessmentAssignment:
    assignment = db.query(AssessmentAssignment).filter(AssessmentAssignment.id == assignment_id).first()
    if not assignment:
        raise ValueError("assignment not found")
    return assignment


def serialize_assignment(db: Session, assignment: AssessmentAssignment) -> dict[str, Any]:
    draft = db.query(AssessmentDraft).filter(AssessmentDraft.id == assignment.draft_id).first()
    if not draft:
        raise ValueError("assignment draft not found")
    snapshot = _draft_snapshot(draft)
    return {
        "id": assignment.id,
        "draft_id": draft.id,
        "centre_id": assignment.centre_id,
        "student_id": assignment.student_id,
        "class_id": assignment.class_id,
        "status": assignment.status,
        "draft_status": draft.status,
        "subskill_id": draft.subskill_id,
        "difficulty": snapshot.get("target_difficulty"),
        "question_count": _question_count(draft),
        "selection_policy_version": draft.selection_policy_version,
        "policy_version": draft.policy_version,
        "assigned_at": assignment.assigned_at,
        "started_at": assignment.started_at,
        "closed_at": assignment.closed_at,
    }


def list_assignments(db: Session, *, caller: CallerContext, student_id: str | None = None) -> list[dict[str, Any]]:
    if caller.role == "student":
        if student_id and student_id != caller.student_id:
            raise PermissionDenied("student may only list their own assignments")
        student_id = caller.student_id
    elif student_id:
        require_read_student(db, caller, student_id)
    elif caller.role not in ("admin", "tutor"):
        raise PermissionDenied("assignment list is not available for this role")
    query = db.query(AssessmentAssignment).filter(
        AssessmentAssignment.centre_id == caller.centre_id,
        AssessmentAssignment.status.in_(sorted(ASSIGNMENT_STATUSES)),
    )
    if student_id:
        query = query.filter(AssessmentAssignment.student_id == student_id)
    assignments = query.order_by(AssessmentAssignment.created_at.desc(), AssessmentAssignment.id.asc()).all()
    if caller.role == "tutor" and not student_id:
        assignments = [item for item in assignments if can_read_student(db, caller, item.student_id)]
    return [serialize_assignment(db, item) for item in assignments]


def get_assignment(db: Session, *, caller: CallerContext, assignment_id: str) -> AssessmentAssignment:
    assignment = _assignment(db, assignment_id)
    _require_assignment_access(db, caller, assignment)
    draft = db.query(AssessmentDraft).filter(AssessmentDraft.id == assignment.draft_id).first()
    if not draft or draft.status not in ("approved", "assigned", "active", "closed"):
        raise PermissionDenied("assignment is not approved for delivery")
    _session_questions(db, assignment)
    return assignment


def start_assignment(db: Session, *, caller: CallerContext, assignment_id: str) -> PracticeSession:
    if caller.role != "student":
        raise PermissionDenied("only the assigned student may start practice")
    assignment = get_assignment(db, caller=caller, assignment_id=assignment_id)
    existing = db.query(PracticeSession).filter(PracticeSession.assignment_id == assignment.id).first()
    if existing:
        return existing
    if assignment.status != "assigned":
        raise ValueError(f"assignment cannot start from {assignment.status}")
    session = PracticeSession(
        id=f"session-{uuid.uuid4().hex[:10]}",
        assignment_id=assignment.id,
        centre_id=assignment.centre_id,
        student_id=assignment.student_id,
        status="active",
        current_index=0,
        started_at=_now(),
    )
    assignment.status = "active"
    assignment.started_at = _now()
    draft = db.query(AssessmentDraft).filter(AssessmentDraft.id == assignment.draft_id).first()
    if not draft:
        raise ValueError("assignment draft not found")
    draft.status = "active"
    draft.updated_at = _now()
    db.add(session)
    db.flush()
    _audit(
        db,
        caller=caller,
        event="practice_session.started",
        entity_type="practice_session",
        entity_id=session.id,
        after={"assignment_id": assignment.id, "status": session.status},
    )
    return session


def _session(db: Session, session_id: str) -> PracticeSession:
    session = db.query(PracticeSession).filter(PracticeSession.id == session_id).first()
    if not session:
        raise ValueError("practice session not found")
    return session


def _require_session_access(db: Session, caller: CallerContext, session: PracticeSession) -> AssessmentAssignment:
    assignment = _assignment(db, session.assignment_id)
    _require_assignment_access(db, caller, assignment)
    if caller.role != "student" or caller.student_id != session.student_id:
        raise PermissionDenied("only the assigned student may operate a practice session")
    return assignment


def get_session(db: Session, *, caller: CallerContext, session_id: str) -> PracticeSession:
    session = _session(db, session_id)
    _require_session_access(db, caller, session)
    return session


def _session_questions(db: Session, assignment: AssessmentAssignment) -> list[Question]:
    draft = db.query(AssessmentDraft).filter(AssessmentDraft.id == assignment.draft_id).first()
    if not draft:
        raise ValueError("assignment draft not found")
    question_ids = json.loads(draft.question_ids_json)
    questions = db.query(Question).filter(Question.id.in_(question_ids)).all()
    by_id = {question.id: question for question in questions}
    if len(by_id) != len(question_ids):
        raise ValueError("assignment contains a question that is no longer available")
    policy = load_policy()
    approved_status = policy["evidence_eligibility"]["required_question_status"]
    approved_answer_type = policy["evidence_eligibility"]["required_answer_type"]
    approved_source_ids = set(policy["evidence_eligibility"]["required_source_ids"])
    if any(
        question.status != approved_status
        or question.answer_type != approved_answer_type
        or question.source_id not in approved_source_ids
        or question.subskill_id != draft.subskill_id
        or question.centre_id not in (assignment.centre_id, None)
        for question in questions
    ):
        raise ValueError("assignment contains a question that is no longer approved for delivery")
    return [by_id[question_id] for question_id in question_ids]


def _student_question(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "prompt": question.prompt,
        "difficulty": question.difficulty,
        "subskill_id": question.subskill_id,
        "template_id": question.template_id,
        "source_id": question.source_id,
        "answer_type": question.answer_type,
    }


def _feedback(question: Question, is_correct: bool, hint_level: int) -> str:
    if is_correct:
        return "Correct — your answer matches the approved solution."
    if hint_level:
        return "Not yet. Use the hint and check each step before trying the next question."
    return "Not yet. Try the next step carefully, or ask for a hint before continuing."


def serialize_session(db: Session, session: PracticeSession) -> dict[str, Any]:
    assignment = _assignment(db, session.assignment_id)
    questions = _session_questions(db, assignment)
    attempts = (
        db.query(Attempt)
        .filter(Attempt.practice_session_id == session.id)
        .order_by(Attempt.created_at.asc(), Attempt.id.asc())
        .all()
    )
    answer_rows = [
        {
            "question_id": attempt.question_id,
            "is_correct": attempt.is_correct,
            "hint_level": attempt.hint_level,
            "feedback": _feedback(next(q for q in questions if q.id == attempt.question_id), attempt.is_correct, attempt.hint_level),
        }
        for attempt in attempts
    ]
    current_question = questions[session.current_index] if session.current_index < len(questions) else None
    hints = db.query(PracticeHint).filter(PracticeHint.session_id == session.id).order_by(PracticeHint.created_at.asc()).all()
    return {
        "id": session.id,
        "assignment_id": assignment.id,
        "student_id": session.student_id,
        "status": session.status,
        "current_index": session.current_index,
        "total_questions": len(questions),
        "answered_count": len(attempts),
        "current_question": _student_question(current_question) if current_question else None,
        "answers": answer_rows,
        "hints": [{"question_id": hint.question_id, "level": hint.level, "text": hint.text, "source_id": hint.source_id} for hint in hints],
        "started_at": session.started_at,
        "completed_at": session.completed_at,
    }


def request_hint(db: Session, *, caller: CallerContext, session_id: str, question_id: str) -> dict[str, Any]:
    session = _session(db, session_id)
    assignment = _require_session_access(db, caller, session)
    questions = _session_questions(db, assignment)
    if session.status != "active":
        raise ValueError("practice session is not active")
    current = questions[session.current_index] if session.current_index < len(questions) else None
    if not current or current.id != question_id:
        raise ValueError("hint can only be requested for the current question")
    last = (
        db.query(PracticeHint)
        .filter(PracticeHint.session_id == session.id, PracticeHint.question_id == question_id)
        .order_by(PracticeHint.level.desc())
        .first()
    )
    if last and last.level >= MAX_HINT_LEVEL:
        return {"question_id": question_id, "level": last.level, "text": last.text, "source_id": last.source_id}
    level = (last.level + 1) if last else 1
    text = HINTS_BY_SUBSKILL.get(current.subskill_id, {}).get(level, "Break the question into one small step at a time.")
    hint = PracticeHint(
        id=f"hint-{uuid.uuid4().hex[:10]}",
        session_id=session.id,
        assignment_id=assignment.id,
        centre_id=session.centre_id,
        student_id=session.student_id,
        question_id=question_id,
        level=level,
        text=text,
        source_id=current.source_id,
        created_at=_now(),
    )
    db.add(hint)
    db.flush()
    _audit(
        db,
        caller=caller,
        event="practice_hint.requested",
        entity_type="practice_session",
        entity_id=session.id,
        after={"question_id": question_id, "level": level, "source_id": current.source_id},
    )
    return {"question_id": question_id, "level": level, "text": text, "source_id": current.source_id}


def submit_answer(
    db: Session,
    *,
    caller: CallerContext,
    session_id: str,
    question_id: str,
    answer: str,
) -> dict[str, Any]:
    session = _session(db, session_id)
    assignment = _require_session_access(db, caller, session)
    if session.status != "active":
        raise ValueError("practice session is not active")
    if not answer.strip() or len(answer) > 255:
        raise ValueError("answer must contain between 1 and 255 characters")
    questions = _session_questions(db, assignment)
    current = questions[session.current_index] if session.current_index < len(questions) else None
    if not current or current.id != question_id:
        raise ValueError("answer can only be submitted for the current question")
    existing = (
        db.query(Attempt)
        .filter(Attempt.practice_session_id == session.id, Attempt.question_id == question_id)
        .first()
    )
    if existing:
        raise ValueError("this question has already been answered")
    latest_hint = (
        db.query(PracticeHint)
        .filter(PracticeHint.session_id == session.id, PracticeHint.question_id == question_id)
        .order_by(PracticeHint.level.desc())
        .first()
    )
    hint_level = latest_hint.level if latest_hint else 0
    is_correct = normalise_answer(answer) == normalise_answer(current.expected_answer)
    attempt = Attempt(
        id=f"att-practice-{uuid.uuid4().hex[:12]}",
        centre_id=session.centre_id,
        student_id=session.student_id,
        question_id=current.id,
        assignment_id=assignment.id,
        practice_session_id=session.id,
        submitted_answer=answer.strip(),
        grading_status="graded",
        is_correct=is_correct,
        hint_level=hint_level,
        created_at=_now(),
    )
    db.add(attempt)
    db.flush()
    policy = load_policy()
    evidence = MasteryEvidence(
        id=f"ev-practice-{uuid.uuid4().hex[:12]}",
        centre_id=session.centre_id,
        attempt_id=attempt.id,
        student_id=session.student_id,
        subskill_id=current.subskill_id,
        is_correct=is_correct,
        policy_id=policy["policy_id"],
        policy_version=policy["version"],
        created_at=_now(),
    )
    db.add(evidence)
    db.flush()
    upsert_mastery_state(db, session.student_id, current.subskill_id)

    session.current_index += 1
    diagnostic_job_id = None
    if session.current_index >= len(questions):
        session.status = "completed"
        session.completed_at = _now()
        assignment.status = "closed"
        assignment.closed_at = _now()
        draft = db.query(AssessmentDraft).filter(AssessmentDraft.id == assignment.draft_id).first()
        if not draft:
            raise ValueError("assignment draft not found")
        draft.status = "closed"
        draft.updated_at = _now()
        diagnostic_job = create_job(
            db,
            "diagnostic",
            session.centre_id,
            session.student_id,
            {
                "student_id": session.student_id,
                "subskill_id": current.subskill_id,
                "practice_session_id": session.id,
                "trigger": "practice_completed",
            },
        )
        diagnostic_job_id = diagnostic_job.id
    session_payload = serialize_session(db, session)
    feedback = _feedback(current, is_correct, hint_level)
    _audit(
        db,
        caller=caller,
        event="practice.answer_submitted",
        entity_type="practice_session",
        entity_id=session.id,
        after={"question_id": question_id, "is_correct": is_correct, "hint_level": hint_level, "session_status": session.status},
    )
    return {
        "question_id": question_id,
        "is_correct": is_correct,
        "hint_level": hint_level,
        "feedback": feedback,
        "diagnostic_job_id": diagnostic_job_id,
        "session": session_payload,
    }
