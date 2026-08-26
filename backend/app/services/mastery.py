from __future__ import annotations

import json
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.db.models import Attempt, MasteryEvidence, MasteryState, Question, Student, TutorEvidenceExclusion

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "domain" / "mastery_policy" / "mastery_policy_v1.json"


def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _decimal(value: float | int) -> Decimal:
    return Decimal(str(value))


def _round_half_up(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalise_answer(value: str) -> str:
    return "".join(value.lower().split())


def compute_mastery(
    eligible: int,
    correct: int,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if eligible < 0 or correct < 0 or correct > eligible:
        raise ValueError("correct attempts must be between zero and eligible attempts")
    if policy is None:
        policy = load_policy()
    calculation = policy["calculation"]
    confidence = _round_half_up(
        min(
            _decimal(calculation["confidence_cap"]),
            _decimal(calculation["confidence_base"])
            + _decimal(calculation["confidence_per_attempt"]) * eligible,
        )
    )
    accuracy = _round_half_up(_decimal(correct) / eligible) if eligible else 0.0
    for outcome in policy["outcomes"]:
        maximum_attempts = outcome.get("maximum_attempts_exclusive")
        if maximum_attempts is not None:
            if eligible < maximum_attempts:
                return {
                    "eligible_attempts": eligible,
                    "correct_attempts": correct,
                    "accuracy": accuracy,
                    "confidence": confidence,
                    "label": outcome["label"],
                    "policy_id": policy["policy_id"],
                    "policy_version": policy["version"],
                }
            continue
        if eligible < outcome.get("minimum_attempts", 0):
            continue
        minimum_accuracy = _decimal(outcome.get("minimum_accuracy", 0))
        maximum_accuracy = outcome.get("maximum_accuracy_exclusive")
        if _decimal(accuracy) >= minimum_accuracy and (
            maximum_accuracy is None or _decimal(accuracy) < _decimal(maximum_accuracy)
        ):
            return {
                "eligible_attempts": eligible,
                "correct_attempts": correct,
                "accuracy": accuracy,
                "confidence": confidence,
                "label": outcome["label"],
                "policy_id": policy["policy_id"],
                "policy_version": policy["version"],
            }
    raise ValueError("No matching mastery outcome")


def get_eligible_attempts(
    db: Session,
    student_id: str,
    subskill_id: str,
    policy: dict[str, Any] | None = None,
) -> tuple[int, int, list[Attempt]]:
    if policy is None:
        policy = load_policy()
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return 0, 0, []
    allowed_sources = set(policy["evidence_eligibility"]["required_source_ids"])
    required_status = policy["evidence_eligibility"]["required_question_status"]
    required_type = policy["evidence_eligibility"]["required_answer_type"]
    attempts = (
        db.query(Attempt)
        .join(Question, Attempt.question_id == Question.id)
        .filter(
            Attempt.student_id == student_id,
            or_(Attempt.centre_id == student.centre_id, Attempt.centre_id.is_(None)),
            Question.subskill_id == subskill_id,
            Question.status == required_status,
            Question.answer_type == required_type,
            Question.source_id.in_(allowed_sources),
            or_(Question.centre_id == student.centre_id, Question.centre_id.is_(None)),
        )
        .order_by(Attempt.created_at.asc(), Attempt.id.asc())
        .limit(100)
        .all()
    )
    excluded_evidence_ids = {
        evidence_id
        for (evidence_id,) in db.query(TutorEvidenceExclusion.evidence_id)
        .filter(
            TutorEvidenceExclusion.student_id == student_id,
            TutorEvidenceExclusion.subskill_id == subskill_id,
            TutorEvidenceExclusion.centre_id == student.centre_id,
        )
        .all()
    }
    eligible_attempts: list[Attempt] = []
    for attempt in attempts:
        evidence = (
            db.query(MasteryEvidence)
            .filter(
                MasteryEvidence.attempt_id == attempt.id,
                MasteryEvidence.student_id == student_id,
                MasteryEvidence.subskill_id == subskill_id,
                MasteryEvidence.policy_id == policy["policy_id"],
                MasteryEvidence.policy_version == policy["version"],
                or_(MasteryEvidence.centre_id == student.centre_id, MasteryEvidence.centre_id.is_(None)),
            )
            .first()
        )
        if (
            evidence is not None
            and evidence.id not in excluded_evidence_ids
            and attempt.grading_status == "graded"
            and evidence.is_correct == attempt.is_correct
        ):
            eligible_attempts.append(attempt)
    correct = sum(1 for attempt in eligible_attempts if attempt.is_correct)
    return len(eligible_attempts), correct, eligible_attempts


def _same_deterministic_state(state: MasteryState, computed: dict[str, Any]) -> bool:
    return (
        not state.is_override
        and state.eligible_attempts == computed["eligible_attempts"]
        and state.correct_attempts == computed["correct_attempts"]
        and state.accuracy == computed["accuracy"]
        and state.confidence == computed["confidence"]
        and state.label == computed["label"]
        and state.policy_id == computed["policy_id"]
        and state.policy_version == computed["policy_version"]
    )


def upsert_mastery_state(db: Session, student_id: str, subskill_id: str) -> MasteryState:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise ValueError(f"unknown student: {student_id}")
    policy = load_policy()
    eligible, correct, _ = get_eligible_attempts(db, student_id, subskill_id, policy)
    computed = compute_mastery(eligible, correct, policy)
    latest = (
        db.query(MasteryState)
        .filter(
            MasteryState.student_id == student_id,
            MasteryState.centre_id == student.centre_id,
            MasteryState.subskill_id == subskill_id,
        )
        .order_by(MasteryState.version.desc())
        .first()
    )
    latest_deterministic = (
        db.query(MasteryState)
        .filter(
            MasteryState.student_id == student_id,
            MasteryState.centre_id == student.centre_id,
            MasteryState.subskill_id == subskill_id,
            MasteryState.is_override.is_(False),
        )
        .order_by(MasteryState.version.desc())
        .first()
    )
    if latest_deterministic and _same_deterministic_state(latest_deterministic, computed):
        return latest or latest_deterministic
    next_version = (latest.version + 1) if latest else 1
    state = MasteryState(
        id=f"mst-{student_id}-{subskill_id}-v{next_version}-{uuid.uuid4().hex[:6]}",
        centre_id=student.centre_id,
        student_id=student_id,
        subskill_id=subskill_id,
        version=next_version,
        eligible_attempts=computed["eligible_attempts"],
        correct_attempts=computed["correct_attempts"],
        accuracy=computed["accuracy"],
        confidence=computed["confidence"],
        label=computed["label"],
        policy_id=computed["policy_id"],
        policy_version=computed["policy_version"],
        is_override=False,
    )
    db.add(state)
    db.flush()
    return state


def get_current_mastery(db: Session, student_id: str, subskill_id: str) -> MasteryState | None:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return None
    return (
        db.query(MasteryState)
        .filter(
            MasteryState.student_id == student_id,
            MasteryState.centre_id == student.centre_id,
            MasteryState.subskill_id == subskill_id,
        )
        .order_by(MasteryState.version.desc())
        .first()
    )


def get_effective_mastery(db: Session, student_id: str, subskill_id: str) -> MasteryState | None:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return None
    override = (
        db.query(MasteryState)
        .filter(
            MasteryState.student_id == student_id,
            MasteryState.centre_id == student.centre_id,
            MasteryState.subskill_id == subskill_id,
            MasteryState.is_override.is_(True),
        )
        .order_by(MasteryState.version.desc())
        .first()
    )
    return override or get_current_mastery(db, student_id, subskill_id)


def get_history(db: Session, student_id: str, subskill_id: str) -> list[MasteryState]:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return []
    return (
        db.query(MasteryState)
        .filter(
            MasteryState.student_id == student_id,
            MasteryState.centre_id == student.centre_id,
            MasteryState.subskill_id == subskill_id,
        )
        .order_by(MasteryState.version.asc())
        .all()
    )
