from __future__ import annotations
import uuid
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied, require_read_student, can_read_student
from backend.app.db.models import Attempt, MasteryEvidence, MasteryState, AuditEvent, Student, Question
from backend.app.tools.contracts import GetStudentSnapshotRequest, GetStudentSnapshotResponse, GetAttemptEvidenceRequest, GetAttemptEvidenceResponse, GetMasteryStateRequest, GetMasteryStateResponse
from backend.app.services.mastery import get_eligible_attempts

def _audit(db: Session, caller: CallerContext, event: str, entity_type: str, entity_id: str, before: dict | None = None, after: dict | None = None):
    ae = AuditEvent(id=f"aud-{uuid.uuid4().hex[:8]}", centre_id=caller.centre_id, actor_id=caller.user_id, actor_role=caller.role, event=event, entity_type=entity_type, entity_id=entity_id, before_json=json.dumps(before) if before else None, after_json=json.dumps(after) if after else None, created_at=datetime.now(timezone.utc))
    db.add(ae)
    db.flush()

def get_student_snapshot(db: Session, caller: CallerContext, req: GetStudentSnapshotRequest) -> GetStudentSnapshotResponse:
    require_read_student(db, caller, req.student_id)
    s = db.query(Student).filter(Student.id == req.student_id).first()
    if not s:
        raise PermissionDenied("student not found")
    _audit(db, caller, "tool.get_student_snapshot", "student", s.id)
    return GetStudentSnapshotResponse(student_id=s.id, centre_id=s.centre_id, level_id=s.level_id, display_name=s.display_name)

def get_attempt_evidence(db: Session, caller: CallerContext, req: GetAttemptEvidenceRequest) -> GetAttemptEvidenceResponse:
    require_read_student(db, caller, req.student_id)
    eligible, correct, attempts = get_eligible_attempts(db, req.student_id, req.subskill_id or "FRC-ADD-SUB-UNLIKE")
    evs = db.query(MasteryEvidence).filter(MasteryEvidence.student_id == req.student_id, MasteryEvidence.subskill_id == (req.subskill_id or "FRC-ADD-SUB-UNLIKE")).all()
    _audit(db, caller, "tool.get_attempt_evidence", "student", req.student_id, after={"subskill": req.subskill_id})
    return GetAttemptEvidenceResponse(evidence_ids=[e.id for e in evs], attempt_ids=[a.id for a in attempts], eligible_attempts=eligible, correct_attempts=correct)

def get_mastery_state(db: Session, caller: CallerContext, req: GetMasteryStateRequest) -> GetMasteryStateResponse:
    require_read_student(db, caller, req.student_id)
    st = db.query(MasteryState).filter(MasteryState.student_id == req.student_id, MasteryState.subskill_id == req.subskill_id).order_by(MasteryState.version.desc()).first()
    if not st:
        raise PermissionDenied("mastery not found")
    _audit(db, caller, "tool.get_mastery_state", "mastery_state", st.id)
    return GetMasteryStateResponse(student_id=st.student_id, subskill_id=st.subskill_id, version=st.version, eligible_attempts=st.eligible_attempts, correct_attempts=st.correct_attempts, accuracy=st.accuracy, confidence=st.confidence, label=st.label, policy_id=st.policy_id, policy_version=st.policy_version, is_override=st.is_override)

# Tool allow-list per job type (S1-03). Agent jobs may only call tools in their allow-list.
TOOL_ALLOW_LIST = {
    "diagnostic": {"get_student_snapshot", "get_attempt_evidence", "get_mastery_state", "retrieve_approved_curriculum"},
    "assessment": {"get_mastery_state", "retrieve_approved_curriculum"},
    "parent_report": {"get_mastery_state"},
}

def is_tool_allowed(job_type: str, tool_name: str) -> bool:
    return tool_name in TOOL_ALLOW_LIST.get(job_type, set())
