from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied, require_job_access, require_read_student
from backend.app.db.models import AgentJob, AuditEvent, MasteryEvidence, MasteryState, Student
from backend.app.services.mastery import get_eligible_attempts
from backend.app.tools.contracts import (
    GetAttemptEvidenceRequest,
    GetAttemptEvidenceResponse,
    GetMasteryStateRequest,
    GetMasteryStateResponse,
    GetStudentSnapshotRequest,
    GetStudentSnapshotResponse,
    RetrieveCurriculumRequest,
)

TOOL_ALLOW_LIST = {
    "diagnostic": {
        "get_student_snapshot",
        "get_attempt_evidence",
        "get_mastery_state",
        "retrieve_approved_curriculum",
    },
    "assessment": {"get_mastery_state", "retrieve_approved_curriculum"},
    "parent_report": {"get_mastery_state"},
}


def _audit(
    db: Session,
    caller: CallerContext,
    event: str,
    entity_type: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
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
            created_at=datetime.now(timezone.utc),
        )
    )
    db.flush()


def get_student_snapshot(
    db: Session,
    caller: CallerContext,
    req: GetStudentSnapshotRequest,
) -> GetStudentSnapshotResponse:
    require_read_student(db, caller, req.student_id)
    student = db.query(Student).filter(Student.id == req.student_id, Student.centre_id == caller.centre_id).first()
    if not student:
        raise PermissionDenied("student not found")
    _audit(db, caller, "tool.get_student_snapshot", "student", student.id)
    return GetStudentSnapshotResponse(
        student_id=student.id,
        centre_id=student.centre_id,
        level_id=student.level_id,
        display_name=student.display_name,
    )


def get_attempt_evidence(
    db: Session,
    caller: CallerContext,
    req: GetAttemptEvidenceRequest,
) -> GetAttemptEvidenceResponse:
    require_read_student(db, caller, req.student_id)
    subskill_id = req.subskill_id or "FRC-ADD-SUB-UNLIKE"
    eligible, correct, attempts = get_eligible_attempts(db, req.student_id, subskill_id)
    if req.attempt_id:
        attempts = [attempt for attempt in attempts if attempt.id == req.attempt_id]
        eligible = len(attempts)
        correct = sum(1 for attempt in attempts if attempt.is_correct)
    evidence_query = db.query(MasteryEvidence).filter(
        MasteryEvidence.student_id == req.student_id,
        MasteryEvidence.centre_id == caller.centre_id,
        MasteryEvidence.subskill_id == subskill_id,
    )
    if req.attempt_id:
        evidence_query = evidence_query.filter(MasteryEvidence.attempt_id == req.attempt_id)
    evidence = evidence_query.order_by(MasteryEvidence.created_at.asc()).limit(100).all()
    _audit(
        db,
        caller,
        "tool.get_attempt_evidence",
        "student",
        req.student_id,
        after={"subskill": subskill_id, "attempt_id": req.attempt_id},
    )
    return GetAttemptEvidenceResponse(
        evidence_ids=[item.id for item in evidence],
        attempt_ids=[attempt.id for attempt in attempts],
        eligible_attempts=eligible,
        correct_attempts=correct,
    )


def get_mastery_state(
    db: Session,
    caller: CallerContext,
    req: GetMasteryStateRequest,
) -> GetMasteryStateResponse:
    require_read_student(db, caller, req.student_id)
    state = (
        db.query(MasteryState)
        .filter(
            MasteryState.student_id == req.student_id,
            MasteryState.centre_id == caller.centre_id,
            MasteryState.subskill_id == req.subskill_id,
        )
        .order_by(MasteryState.version.desc())
        .first()
    )
    if not state:
        raise PermissionDenied("mastery not found")
    _audit(db, caller, "tool.get_mastery_state", "mastery_state", state.id)
    return GetMasteryStateResponse(
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
    )


def is_tool_allowed(job_type: str, tool_name: str) -> bool:
    return tool_name in TOOL_ALLOW_LIST.get(job_type, set())


def invoke_tool(db: Session, caller: CallerContext, job: AgentJob, tool_name: str, request: Any):
    """Dispatch one typed tool only within the job's explicit allow-list."""
    require_job_access(db, caller, job)
    if not is_tool_allowed(job.job_type, tool_name):
        raise PermissionDenied(f"tool {tool_name} is not allowed for {job.job_type}")
    if caller.role == "worker" and caller.job_id != job.id:
        raise PermissionDenied("worker is not bound to this job")
    if caller.role == "worker" and job.status != "running":
        raise PermissionDenied("worker tools are only available during a running job")

    from backend.app.tools.curriculum import retrieve_approved_curriculum

    typed_request: Any
    if tool_name == "get_student_snapshot":
        typed_request = GetStudentSnapshotRequest.model_validate(request)
        response = get_student_snapshot(db, caller, typed_request)
    elif tool_name == "get_attempt_evidence":
        typed_request = GetAttemptEvidenceRequest.model_validate(request)
        response = get_attempt_evidence(db, caller, typed_request)
    elif tool_name == "get_mastery_state":
        typed_request = GetMasteryStateRequest.model_validate(request)
        response = get_mastery_state(db, caller, typed_request)
    elif tool_name == "retrieve_approved_curriculum":
        typed_request = RetrieveCurriculumRequest.model_validate(request)
        response = retrieve_approved_curriculum(db, caller, typed_request)
    else:
        raise PermissionDenied(f"unknown tool: {tool_name}")

    _audit(
        db,
        caller,
        "tool.invoke",
        "agent_job",
        job.id,
        after={"tool": tool_name, "purpose": job.job_type},
    )
    return response
