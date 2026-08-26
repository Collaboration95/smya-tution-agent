from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import PermissionDenied, require_read_student
from backend.app.db.models import Student
from backend.app.schemas.reports import ParentReportJobRequest
from backend.app.services.jobs import create_job
from backend.app.services.mastery import load_policy


def create_parent_report_job(
    db: Session,
    caller: CallerContext,
    request: ParentReportJobRequest,
) -> object:
    if caller.role not in ("admin", "tutor"):
        raise PermissionDenied("only staff may create parent report jobs")
    require_read_student(db, caller, request.student_id)
    student = (
        db.query(Student)
        .filter(Student.id == request.student_id, Student.centre_id == caller.centre_id)
        .first()
    )
    if student is None:
        raise ValueError("student not found")
    policy = load_policy()
    payload = {
        "schema": "parent_report_v1",
        "student_id": student.id,
        "verified_scope": {"centre_id": student.centre_id, "student_id": student.id},
        "subskill_ids": request.subskill_ids,
        "previous_period": request.previous_period.model_dump(mode="json"),
        "current_period": request.current_period.model_dump(mode="json"),
        "history_policy_id": policy["policy_id"],
        "history_policy_version": policy["version"],
        "trigger": "manual_request",
    }
    return create_job(
        db,
        "parent_report",
        student.centre_id,
        student.id,
        payload,
        max_retries=request.max_retries,
    )
