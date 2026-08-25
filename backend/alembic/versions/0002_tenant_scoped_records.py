"""tenant-scoped learning records and deterministic mastery state

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("centres", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("display_name", sa.String(length=255), nullable=False), sa.Column("is_synthetic", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("users", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=False), sa.Column("role", sa.String(length=32), nullable=False), sa.Column("display_name", sa.String(length=255), nullable=False), sa.Column("is_synthetic", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_users_centre_id", "users", ["centre_id"])
    op.create_index("ix_users_centre_role", "users", ["centre_id", "role"])
    op.create_table("students", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=False), sa.Column("level_id", sa.String(length=64), nullable=False), sa.Column("display_name", sa.String(length=255), nullable=False), sa.Column("is_synthetic", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_students_centre_id", "students", ["centre_id"])
    op.create_table("classes", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=False), sa.Column("tutor_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("subject_id", sa.String(length=64), nullable=False), sa.Column("level_id", sa.String(length=64), nullable=False), sa.Column("topic_id", sa.String(length=64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_classes_centre_id", "classes", ["centre_id"])
    op.create_table("enrolments", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("class_id", sa.String(length=64), sa.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False), sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False), sa.Column("status", sa.String(length=32), nullable=False), sa.UniqueConstraint("class_id", "student_id", name="uq_enrolment_class_student"))
    op.create_index("ix_enrolments_class_id", "enrolments", ["class_id"])
    op.create_index("ix_enrolments_student_id", "enrolments", ["student_id"])
    op.create_table("guardian_links", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False), sa.Column("display_name", sa.String(length=255), nullable=False), sa.Column("verification_status", sa.String(length=32), nullable=False), sa.Column("reporting_consent", sa.Boolean(), nullable=False), sa.Column("is_synthetic", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_guardian_links_student_id", "guardian_links", ["student_id"])
    op.create_table("curriculum_chunks", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("source_id", sa.String(length=64), nullable=False), sa.Column("subskill_id", sa.String(length=64), nullable=False), sa.Column("approval_status", sa.String(length=32), nullable=False), sa.Column("text", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_curriculum_chunks_source_id", "curriculum_chunks", ["source_id"])
    op.create_index("ix_curriculum_chunks_subskill_id", "curriculum_chunks", ["subskill_id"])
    op.create_table("questions", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("source_id", sa.String(length=64), nullable=False), sa.Column("subskill_id", sa.String(length=64), nullable=False), sa.Column("template_id", sa.String(length=64), nullable=False), sa.Column("difficulty", sa.String(length=32), nullable=False), sa.Column("prompt", sa.Text(), nullable=False), sa.Column("expected_answer", sa.String(length=255), nullable=False), sa.Column("answer_type", sa.String(length=32), nullable=False), sa.Column("status", sa.String(length=32), nullable=False), sa.Column("selection_rank", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_questions_source_id", "questions", ["source_id"])
    op.create_index("ix_questions_subskill_id", "questions", ["subskill_id"])
    op.create_table("attempts", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False), sa.Column("question_id", sa.String(length=64), sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False), sa.Column("submitted_answer", sa.String(length=255), nullable=False), sa.Column("grading_status", sa.String(length=32), nullable=False), sa.Column("is_correct", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_attempts_student_id", "attempts", ["student_id"])
    op.create_index("ix_attempts_question_id", "attempts", ["question_id"])
    op.create_table("mastery_evidence", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("attempt_id", sa.String(length=64), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False), sa.Column("subskill_id", sa.String(length=64), nullable=False), sa.Column("is_correct", sa.Boolean(), nullable=False), sa.Column("policy_id", sa.String(length=64), nullable=False), sa.Column("policy_version", sa.String(length=32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_mastery_evidence_attempt_id", "mastery_evidence", ["attempt_id"])
    op.create_index("ix_mastery_evidence_student_id", "mastery_evidence", ["student_id"])
    op.create_index("ix_mastery_evidence_subskill_id", "mastery_evidence", ["subskill_id"])
    op.create_table("mastery_states", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False), sa.Column("subskill_id", sa.String(length=64), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("eligible_attempts", sa.Integer(), nullable=False), sa.Column("correct_attempts", sa.Integer(), nullable=False), sa.Column("accuracy", sa.Float(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False), sa.Column("label", sa.String(length=32), nullable=False), sa.Column("policy_id", sa.String(length=64), nullable=False), sa.Column("policy_version", sa.String(length=32), nullable=False), sa.Column("is_override", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("student_id", "subskill_id", "version", name="uq_mastery_version"))
    op.create_index("ix_mastery_states_student_id", "mastery_states", ["student_id"])
    op.create_index("ix_mastery_states_subskill_id", "mastery_states", ["subskill_id"])
    op.create_index("ix_mastery_student_subskill_version", "mastery_states", ["student_id", "subskill_id", "version"])
    op.create_table("tutor_corrections", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False), sa.Column("subskill_id", sa.String(length=64), nullable=False), sa.Column("author_tutor_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("original_state_id", sa.String(length=64), sa.ForeignKey("mastery_states.id", ondelete="RESTRICT"), nullable=True), sa.Column("corrected_label", sa.String(length=32), nullable=False), sa.Column("reason", sa.Text(), nullable=False), sa.Column("supersedes_version", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_tutor_corrections_student_id", "tutor_corrections", ["student_id"])
    op.create_table("audit_events", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("centre_id", sa.String(length=64), nullable=True), sa.Column("actor_id", sa.String(length=64), nullable=False), sa.Column("actor_role", sa.String(length=32), nullable=False), sa.Column("event", sa.String(length=64), nullable=False), sa.Column("entity_type", sa.String(length=64), nullable=False), sa.Column("entity_id", sa.String(length=64), nullable=False), sa.Column("before_json", sa.Text(), nullable=True), sa.Column("after_json", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_events_centre_id", "audit_events", ["centre_id"])

def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("tutor_corrections")
    op.drop_table("mastery_states")
    op.drop_table("mastery_evidence")
    op.drop_table("attempts")
    op.drop_table("questions")
    op.drop_table("curriculum_chunks")
    op.drop_table("guardian_links")
    op.drop_table("enrolments")
    op.drop_table("classes")
    op.drop_table("students")
    op.drop_table("users")
    op.drop_table("centres")
