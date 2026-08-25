from __future__ import annotations
from sqlalchemy.orm import Session
from backend.app.db.models import Student, User, Class, Enrolment, GuardianLink, CurriculumChunk
from backend.app.auth.context import CallerContext

class PermissionDenied(Exception):
    pass

def _student_centre(db: Session, student_id: str) -> str | None:
    s = db.query(Student).filter(Student.id == student_id).first()
    return s.centre_id if s else None

def can_read_student(db: Session, caller: CallerContext, student_id: str) -> bool:
    sc = _student_centre(db, student_id)
    if sc is None:
        return False
    if caller.role == "worker":
        # Worker is server-scoped, can read within job centre (checked by job)
        return True
    if caller.centre_id != sc:
        return False
    if caller.role in ("admin",):
        return True
    if caller.role == "tutor":
        # Must be assigned via class enrolment
        q = db.query(Enrolment).join(Class, Enrolment.class_id == Class.id).filter(Class.tutor_id == caller.user_id, Enrolment.student_id == student_id).first()
        return q is not None
    if caller.role == "student":
        return caller.student_id == student_id
    if caller.role == "guardian":
        # Guardian link must be verified and match student
        gl = db.query(GuardianLink).filter(GuardianLink.id == caller.guardian_link_id, GuardianLink.student_id == student_id, GuardianLink.verification_status == "verified", GuardianLink.reporting_consent == True).first()  # noqa
        return gl is not None
    return False

def require_read_student(db: Session, caller: CallerContext, student_id: str) -> None:
    if not can_read_student(db, caller, student_id):
        raise PermissionDenied(f"read_student denied for {caller.role} {caller.user_id} -> {student_id}")

def can_approve_student(db: Session, caller: CallerContext, student_id: str) -> bool:
    # Only assigned tutor or admin can approve
    sc = _student_centre(db, student_id)
    if sc is None or caller.centre_id != sc:
        return False
    if caller.role == "admin":
        return True
    if caller.role == "tutor":
        q = db.query(Enrolment).join(Class, Enrolment.class_id == Class.id).filter(Class.tutor_id == caller.user_id, Enrolment.student_id == student_id).first()
        return q is not None
    return False

def can_access_guardian_report(db: Session, caller: CallerContext, student_id: str) -> bool:
    # Report access requires verified guardian link + consent
    gl = db.query(GuardianLink).filter(GuardianLink.student_id == student_id).first()
    if not gl:
        return False
    if gl.verification_status != "verified" or not gl.reporting_consent:
        return False
    # Caller must be the linked guardian or an authorized tutor/admin
    if caller.role == "guardian":
        return caller.guardian_link_id == gl.id
    if caller.role in ("tutor", "admin"):
        return can_read_student(db, caller, student_id)
    return False

def assert_curriculum_approved(chunk: CurriculumChunk) -> None:
    if chunk.approval_status != "approved":
        raise PermissionDenied("curriculum not approved")
