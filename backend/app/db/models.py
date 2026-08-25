from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, Float, Text, DateTime, ForeignKey, UniqueConstraint, Index, event
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db.base import Base

def utcnow():
    return datetime.now(timezone.utc)

# --- Core tenant entities ---

class Centre(Base):
    __tablename__ = "centres"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # admin|tutor|student|guardian|worker
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (Index("ix_users_centre_role", "centre_id", "role"),)

class Student(Base):
    __tablename__ = "students"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=False, index=True)
    level_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class Class(Base):
    __tablename__ = "classes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=False, index=True)
    tutor_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    level_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class Enrolment(Base):
    __tablename__ = "enrolments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    class_id: Mapped[str] = mapped_column(String(64), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_enrolment_class_student"),)

class GuardianLink(Base):
    __tablename__ = "guardian_links"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    student_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)  # verified|pending|blocked
    reporting_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class CurriculumChunk(Base):
    __tablename__ = "curriculum_chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # NULL means a globally approved synthetic source; centre-owned material must set this.
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subskill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)  # approved|pending|rejected
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # NULL means a globally approved synthetic source; centre-owned questions must set this.
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subskill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(32), nullable=False)  # foundation|core|stretch
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_type: Mapped[str] = mapped_column(String(32), nullable=False)  # objective_exact
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # approved
    selection_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    student_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(String(64), ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True)
    submitted_answer: Mapped[str] = mapped_column(String(255), nullable=False)
    grading_status: Mapped[str] = mapped_column(String(32), nullable=False)  # graded
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    # Immutability is enforced at service layer; DB does not allow UPDATE via app code.

class MasteryEvidence(Base):
    __tablename__ = "mastery_evidence"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    attempt_id: Mapped[str] = mapped_column(String(64), ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    student_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    subskill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    # Append-only: no UPDATE/DELETE via service layer.

class MasteryState(Base):
    __tablename__ = "mastery_states"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    student_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    subskill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)  # insufficient_evidence|requires_support|developing|secure
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("student_id", "subskill_id", "version", name="uq_mastery_version"),
        Index("ix_mastery_student_subskill_version", "student_id", "subskill_id", "version"),
    )

class TutorCorrection(Base):
    __tablename__ = "tutor_corrections"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    student_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    subskill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    author_tutor_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    original_state_id: Mapped[str] = mapped_column(String(64), ForeignKey("mastery_states.id", ondelete="RESTRICT"), nullable=True)
    corrected_label: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=True)
    after_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

# Agent jobs and runs — S1-04
class AgentJob(Base):
    __tablename__ = "agent_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # diagnostic|assessment|parent_report
    centre_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    student_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # queued|claimed|running|succeeded|needs_tutor_review|failed_retryable|failed_terminal|cancelled
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # running|succeeded|failed_retryable|failed_terminal|needs_tutor_review
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    tool_calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)

class ToolCallRecord(Base):
    __tablename__ = "tool_call_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)



class TutorAlert(Base):
    __tablename__ = "tutor_alerts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    centre_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    student_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subskill_id: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # low_evidence|conflicting|unsupported
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class TutorDecision(Base):
    __tablename__ = "tutor_decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    centre_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("centres.id", ondelete="CASCADE"), nullable=True, index=True)
    student_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # accept|edit|reject|more_evidence
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (Index("ix_tutor_decisions_job_created", "job_id", "created_at"),)

class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # mastery_proposal|assessment_draft etc
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (UniqueConstraint("job_id", "version", name="uq_artifact_job_version"),)


@event.listens_for(Attempt, "before_update")
def _reject_attempt_update(mapper, connection, target):
    raise ValueError("attempts are immutable factual inputs")


@event.listens_for(Attempt, "before_delete")
def _reject_attempt_delete(mapper, connection, target):
    raise ValueError("attempts are immutable factual inputs")


@event.listens_for(MasteryEvidence, "before_update")
def _reject_evidence_update(mapper, connection, target):
    raise ValueError("mastery evidence is append-only")


@event.listens_for(MasteryEvidence, "before_delete")
def _reject_evidence_delete(mapper, connection, target):
    raise ValueError("mastery evidence is append-only")
