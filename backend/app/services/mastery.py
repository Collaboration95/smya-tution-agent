from __future__ import annotations
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import Attempt, MasteryEvidence, MasteryState, Question

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "domain" / "mastery_policy" / "mastery_policy_v1.json"

def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))

def _decimal(v: float | int) -> Decimal:
    return Decimal(str(v))

def _round_half_up(v: Decimal) -> float:
    return float(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def normalise_answer(v: str) -> str:
    return "".join(v.lower().split())

def compute_mastery(eligible: int, correct: int, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    if policy is None:
        policy = load_policy()
    calc = policy["calculation"]
    confidence = _round_half_up(min(_decimal(calc["confidence_cap"]), _decimal(calc["confidence_base"]) + _decimal(calc["confidence_per_attempt"]) * eligible))
    accuracy = _round_half_up(_decimal(correct) / eligible) if eligible else 0.0
    # Find matching outcome
    for outcome in policy["outcomes"]:
        max_attempts = outcome.get("maximum_attempts_exclusive")
        if max_attempts is not None:
            if eligible < max_attempts:
                return {"eligible_attempts": eligible, "correct_attempts": correct, "accuracy": accuracy, "confidence": confidence, "label": outcome["label"], "policy_id": policy["policy_id"], "policy_version": policy["version"]}
            continue
        if eligible < outcome.get("minimum_attempts", 0):
            continue
        min_acc = _decimal(outcome.get("minimum_accuracy", 0))
        max_acc = outcome.get("maximum_accuracy_exclusive")
        if _decimal(accuracy) >= min_acc and (max_acc is None or _decimal(accuracy) < _decimal(max_acc)):
            return {"eligible_attempts": eligible, "correct_attempts": correct, "accuracy": accuracy, "confidence": confidence, "label": outcome["label"], "policy_id": policy["policy_id"], "policy_version": policy["version"]}
    raise ValueError("No matching mastery outcome")

def get_eligible_attempts(db: Session, student_id: str, subskill_id: str, policy: dict[str, Any] | None = None) -> tuple[int, int, list[Attempt]]:
    if policy is None:
        policy = load_policy()
    allowed_sources = set(policy["evidence_eligibility"]["required_source_ids"])
    required_status = policy["evidence_eligibility"]["required_question_status"]
    required_type = policy["evidence_eligibility"]["required_answer_type"]
    # Also need to respect tutor_voided etc via mastery_evidence exclude? For S1 we exclude via policy exclude_if but no voided rows in seed.
    attempts = db.query(Attempt).join(Question, Attempt.question_id == Question.id).filter(Attempt.student_id == student_id, Question.subskill_id == subskill_id, Question.status == required_status, Question.answer_type == required_type, Question.source_id.in_(allowed_sources)).all()
    # Check evidence existence? eligible is attempts that have evidence; but for S1 we treat attempts as eligible if they have evidence row.
    # For determinism we count attempts that have corresponding mastery_evidence or are graded.
    eligible_attempts = []
    for a in attempts:
        ev = db.query(MasteryEvidence).filter(MasteryEvidence.attempt_id == a.id).first()
        if ev is not None:
            eligible_attempts.append(a)
        elif a.grading_status == "graded":
            # If no evidence yet (pre-evidence creation), count as eligible if it would be eligible
            eligible_attempts.append(a)
    correct = sum(1 for a in eligible_attempts if a.is_correct)
    return len(eligible_attempts), correct, eligible_attempts

def upsert_mastery_state(db: Session, student_id: str, subskill_id: str) -> MasteryState:
    policy = load_policy()
    eligible, correct, _ = get_eligible_attempts(db, student_id, subskill_id, policy)
    computed = compute_mastery(eligible, correct, policy)
    # Determine next version
    latest = db.query(MasteryState).filter(MasteryState.student_id == student_id, MasteryState.subskill_id == subskill_id).order_by(MasteryState.version.desc()).first()
    next_version = (latest.version + 1) if latest else 1
    import uuid
    state = MasteryState(id=f"mst-{student_id}-{subskill_id}-v{next_version}-{uuid.uuid4().hex[:6]}", student_id=student_id, subskill_id=subskill_id, version=next_version, eligible_attempts=computed["eligible_attempts"], correct_attempts=computed["correct_attempts"], accuracy=computed["accuracy"], confidence=computed["confidence"], label=computed["label"], policy_id=computed["policy_id"], policy_version=computed["policy_version"], is_override=False)
    db.add(state)
    db.flush()
    return state

def get_current_mastery(db: Session, student_id: str, subskill_id: str) -> MasteryState | None:
    return db.query(MasteryState).filter(MasteryState.student_id == student_id, MasteryState.subskill_id == subskill_id).order_by(MasteryState.version.desc()).first()

def get_effective_mastery(db: Session, student_id: str, subskill_id: str) -> MasteryState | None:
    # If latest is override, it is effective; otherwise deterministic latest.
    # TutorCorrections create an override MasteryState with is_override=True
    return get_current_mastery(db, student_id, subskill_id)

def get_history(db: Session, student_id: str, subskill_id: str) -> list[MasteryState]:
    return db.query(MasteryState).filter(MasteryState.student_id == student_id, MasteryState.subskill_id == subskill_id).order_by(MasteryState.version.asc()).all()
