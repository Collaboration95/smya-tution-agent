from __future__ import annotations
from sqlalchemy.orm import Session
from backend.app.db.models import AgentJob, Student, Class, Enrolment, GuardianLink, CurriculumChunk
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
        # A worker is bound to exactly one job and one student. Never make the
        # worker role a blanket cross-tenant bypass.
        job = (
            db.query(AgentJob)
            .filter(AgentJob.id == caller.job_id, AgentJob.centre_id == caller.centre_id)
            .first()
        ) if caller.job_id else None
        return (
            job is not None
            and job.student_id == student_id
            and caller.centre_id == sc
            and caller.student_id == student_id
        )
    if caller.centre_id != sc:
        return False
    if caller.role in ("admin",):
        return True
    if caller.role == "tutor":
        # Must be assigned via class enrolment
        q = (
            db.query(Enrolment)
            .join(Class, Enrolment.class_id == Class.id)
            .filter(
                Class.tutor_id == caller.user_id,
                Class.centre_id == caller.centre_id,
                Enrolment.centre_id == caller.centre_id,
                Enrolment.student_id == student_id,
            )
            .first()
        )
        return q is not None
    if caller.role == "student":
        return caller.student_id == student_id
    if caller.role == "guardian":
        # Guardian link must be verified and match student
        gl = (
            db.query(GuardianLink)
            .filter(
                GuardianLink.id == caller.guardian_link_id,
                GuardianLink.centre_id == caller.centre_id,
                GuardianLink.student_id == student_id,
                GuardianLink.verification_status == "verified",
                GuardianLink.reporting_consent.is_(True),
            )
            .first()
        )  # noqa
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
        q = (
            db.query(Enrolment)
            .join(Class, Enrolment.class_id == Class.id)
            .filter(
                Class.tutor_id == caller.user_id,
                Class.centre_id == caller.centre_id,
                Enrolment.centre_id == caller.centre_id,
                Enrolment.student_id == student_id,
            )
            .first()
        )
        return q is not None
    return False


def can_read_job(db: Session, caller: CallerContext, job: AgentJob) -> bool:
    """Return whether the caller may inspect or execute this job."""
    if caller.role == "worker":
        return caller.job_id == job.id and caller.centre_id == job.centre_id
    if caller.centre_id != job.centre_id:
        return False
    if job.student_id is None:
        return caller.role == "admin"
    return can_read_student(db, caller, job.student_id)


def can_decide_job(db: Session, caller: CallerContext, job: AgentJob) -> bool:
    """Return whether the caller may make a tutor decision for this job."""
    if job.student_id is None or caller.role not in ("admin", "tutor"):
        return False
    return can_approve_student(db, caller, job.student_id)


def require_job_access(db: Session, caller: CallerContext, job: AgentJob) -> None:
    if not can_read_job(db, caller, job):
        raise PermissionDenied(f"job access denied for {caller.role} {caller.user_id} -> {job.id}")


def require_job_decision_access(db: Session, caller: CallerContext, job: AgentJob) -> None:
    if not can_decide_job(db, caller, job):
        raise PermissionDenied(f"job decision denied for {caller.role} {caller.user_id} -> {job.id}")

def can_access_guardian_report(db: Session, caller: CallerContext, student_id: str) -> bool:
    # Report access requires verified guardian link + consent
    if caller.centre_id != _student_centre(db, student_id):
        return False
    gl = (
        db.query(GuardianLink)
        .filter(
            GuardianLink.centre_id == caller.centre_id,
            GuardianLink.student_id == student_id,
        )
        .first()
    )
    if not gl:
        return False
    if gl.verification_status != "verified" or not gl.reporting_consent:
        return False
    # Caller must be the linked guardian or an authorized tutor/admin
    if caller.role == "guardian":
        return can_read_student(db, caller, student_id)
    if caller.role in ("tutor", "admin"):
        return can_read_student(db, caller, student_id)
    return False

def assert_curriculum_approved(chunk: CurriculumChunk) -> None:
    if chunk.approval_status != "approved":
        raise PermissionDenied("curriculum not approved")
