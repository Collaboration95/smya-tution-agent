from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import require_read_student
from backend.app.db.models import MasteryEvidence, MasteryState, Student
from backend.app.schemas.reports import ReportPeriod
from backend.app.services.mastery import load_policy
from backend.app.tools.contracts import (
    GetMasteryHistoryRequest,
    GetMasteryHistoryResponse,
    MasteryHistorySnapshot,
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _period_snapshots(
    db: Session,
    student: Student,
    subskill_ids: list[str],
    period: ReportPeriod,
    policy: dict,
) -> list[MasteryHistorySnapshot]:
    snapshots: list[MasteryHistorySnapshot] = []
    for subskill_id in subskill_ids:
        state = (
            db.query(MasteryState)
            .filter(
                MasteryState.student_id == student.id,
                MasteryState.centre_id == student.centre_id,
                MasteryState.subskill_id == subskill_id,
                MasteryState.policy_id == policy["policy_id"],
                MasteryState.policy_version == policy["version"],
                MasteryState.created_at >= period.start,
                MasteryState.created_at <= period.end,
            )
            .order_by(MasteryState.created_at.desc(), MasteryState.version.desc(), MasteryState.id.desc())
            .first()
        )
        if state is None:
            continue
        evidence = (
            db.query(MasteryEvidence)
            .filter(
                MasteryEvidence.student_id == student.id,
                MasteryEvidence.centre_id == student.centre_id,
                MasteryEvidence.subskill_id == subskill_id,
                MasteryEvidence.policy_id == policy["policy_id"],
                MasteryEvidence.policy_version == policy["version"],
                MasteryEvidence.created_at <= state.created_at,
            )
            .order_by(MasteryEvidence.created_at.asc(), MasteryEvidence.id.asc())
            .all()
        )
        snapshots.append(
            MasteryHistorySnapshot(
                id=state.id,
                student_id=state.student_id,
                subskill_id=state.subskill_id,
                version=state.version,
                eligible_attempts=state.eligible_attempts,
                correct_attempts=state.correct_attempts,
                accuracy=state.accuracy,
                confidence=state.confidence,
                label=state.label,
                policy_id=state.policy_id,
                policy_version=state.policy_version,
                is_override=state.is_override,
                created_at=_aware(state.created_at),
                evidence_ids=[item.id for item in evidence],
            )
        )
    return snapshots


def get_mastery_history(
    db: Session,
    caller: CallerContext,
    request: GetMasteryHistoryRequest,
) -> GetMasteryHistoryResponse:
    require_read_student(db, caller, request.student_id)
    student = (
        db.query(Student)
        .filter(Student.id == request.student_id, Student.centre_id == caller.centre_id)
        .first()
    )
    if student is None:
        raise ValueError("student not found")
    if len(set(request.subskill_ids)) != len(request.subskill_ids):
        raise ValueError("subskill_ids must be unique")
    previous = ReportPeriod(start=request.previous_period_start, end=request.previous_period_end)
    current = ReportPeriod(start=request.current_period_start, end=request.current_period_end)
    if previous.end > current.start:
        raise ValueError("comparison periods must not overlap")
    policy = load_policy()
    return GetMasteryHistoryResponse(
        student_id=student.id,
        previous_period=_period_snapshots(db, student, request.subskill_ids, previous, policy),
        current_period=_period_snapshots(db, student, request.subskill_ids, current, policy),
    )
