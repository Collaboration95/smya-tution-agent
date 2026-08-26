from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.db.models import Question, Student
from backend.app.services.mastery import get_effective_mastery, load_policy


SELECTION_POLICY_ID = "practice_selection_v1"
SELECTION_POLICY_VERSION = "1.0.0"
DIFFICULTY_BY_LABEL = {
    "insufficient_evidence": "foundation",
    "requires_support": "foundation",
    "developing": "core",
    "secure": "stretch",
}


def selection_cache_key(
    *,
    centre_id: str,
    student_id: str,
    subskill_id: str,
    mastery_state_version: int,
    policy_id: str,
    policy_version: str,
    recent_question_ids: list[str],
    item_count: int,
) -> str:
    """Build a stable key for one deterministic selection decision."""

    payload = {
        "centre_id": centre_id,
        "student_id": student_id,
        "subskill_id": subskill_id,
        "mastery_state_version": mastery_state_version,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "selection_policy_id": SELECTION_POLICY_ID,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "recent_question_ids": sorted(set(recent_question_ids)),
        "item_count": item_count,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"practice:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def _question_snapshot(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "source_id": question.source_id,
        "subskill_id": question.subskill_id,
        "template_id": question.template_id,
        "difficulty": question.difficulty,
        "prompt": question.prompt,
        "expected_answer": question.expected_answer,
        "answer_type": question.answer_type,
        "status": question.status,
        "selection_rank": question.selection_rank,
    }


def select_practice_items(
    db: Session,
    *,
    student_id: str,
    subskill_id: str,
    item_count: int = 2,
    recent_question_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Select approved questions from the student's effective mastery state.

    The query, ordering, and cache input are intentionally deterministic. The
    returned snapshot is suitable for persisting in an AssessmentDraft so a
    later state change cannot silently change an already-reviewed draft.
    """

    if not 1 <= item_count <= 10:
        raise ValueError("item_count must be between 1 and 10")
    recent = sorted(set(recent_question_ids or []))
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise ValueError(f"unknown student: {student_id}")
    state = get_effective_mastery(db, student_id, subskill_id)
    if not state:
        raise ValueError(f"effective mastery state is unavailable for {student_id}/{subskill_id}")
    difficulty = DIFFICULTY_BY_LABEL.get(state.label)
    if difficulty is None:
        raise ValueError(f"unsupported mastery label: {state.label}")

    policy = load_policy()
    approved_source_ids = set(policy["evidence_eligibility"]["required_source_ids"])
    if not approved_source_ids:
        raise ValueError("selection policy does not declare approved question sources")
    candidates = (
        db.query(Question)
        .filter(
            Question.subskill_id == subskill_id,
            Question.difficulty == difficulty,
            Question.status == "approved",
            Question.answer_type == "objective_exact",
            Question.source_id.in_(approved_source_ids),
            or_(Question.centre_id == student.centre_id, Question.centre_id.is_(None)),
        )
        .order_by(Question.selection_rank.asc(), Question.id.asc())
        .all()
    )
    selected = [question for question in candidates if question.id not in recent][:item_count]
    if len(selected) != item_count:
        raise ValueError(
            f"not enough approved {difficulty} questions for {student_id}/{subskill_id} "
            f"after excluding {len(recent)} recent question(s)"
        )

    cache_key = selection_cache_key(
        centre_id=student.centre_id,
        student_id=student_id,
        subskill_id=subskill_id,
        mastery_state_version=state.version,
        policy_id=state.policy_id,
        policy_version=state.policy_version,
        recent_question_ids=recent,
        item_count=item_count,
    )
    return {
        "student_id": student_id,
        "centre_id": student.centre_id,
        "subskill_id": subskill_id,
        "selection_policy_id": SELECTION_POLICY_ID,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "cache_key": cache_key,
        "item_count": item_count,
        "recent_question_ids": recent,
        "target_difficulty": difficulty,
        "effective_mastery": {
            "label": state.label,
            "version": state.version,
            "accuracy": state.accuracy,
            "confidence": state.confidence,
            "is_override": state.is_override,
            "policy_id": state.policy_id,
            "policy_version": state.policy_version,
        },
        "policy": {
            "policy_id": policy["policy_id"],
            "policy_version": policy["version"],
        },
        "questions": [_question_snapshot(question) for question in selected],
        "question_ids": [question.id for question in selected],
        "source_ids": sorted({question.source_id for question in selected}),
    }


def validate_question_selection(
    db: Session,
    *,
    student_id: str,
    subskill_id: str,
    question_ids: list[str],
) -> list[dict[str, Any]]:
    """Validate a human-edited question list against the approval boundary."""

    if not question_ids or len(question_ids) > 10 or len(set(question_ids)) != len(question_ids):
        raise ValueError("question_ids must contain between 1 and 10 unique questions")
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise ValueError(f"unknown student: {student_id}")
    policy = load_policy()
    approved_source_ids = set(policy["evidence_eligibility"]["required_source_ids"])
    if not approved_source_ids:
        raise ValueError("selection policy does not declare approved question sources")
    questions = (
        db.query(Question)
        .filter(
            Question.id.in_(question_ids),
            Question.subskill_id == subskill_id,
            Question.status == "approved",
            Question.answer_type == "objective_exact",
            Question.source_id.in_(approved_source_ids),
            or_(Question.centre_id == student.centre_id, Question.centre_id.is_(None)),
        )
        .all()
    )
    by_id = {question.id: question for question in questions}
    if len(by_id) != len(question_ids):
        raise ValueError("every selected question must be approved, objective, in-scope, and match the subskill")
    return [_question_snapshot(by_id[question_id]) for question_id in question_ids]
