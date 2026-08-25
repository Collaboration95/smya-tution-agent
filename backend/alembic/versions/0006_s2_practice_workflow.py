"""durable practice drafts, approval, assignments, and sessions

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assessment_drafts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.String(length=64), sa.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subskill_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("selection_policy_id", sa.String(length=64), nullable=False),
        sa.Column("selection_policy_version", sa.String(length=32), nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("mastery_state_version", sa.Integer(), nullable=False),
        sa.Column("question_ids_json", sa.Text(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("centre_id", "student_id", "class_id", "subskill_id", "status"):
        op.create_index(f"ix_assessment_drafts_{column}", "assessment_drafts", [column])

    op.create_table(
        "assessment_assignments",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("draft_id", sa.String(length=64), sa.ForeignKey("assessment_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.String(length=64), sa.ForeignKey("classes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assigned_by", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("draft_id", name="uq_assessment_assignment_draft"),
        sa.UniqueConstraint("idempotency_key", name="uq_assessment_assignment_idempotency"),
    )
    for column in ("draft_id", "centre_id", "student_id", "class_id", "status", "idempotency_key"):
        op.create_index(f"ix_assessment_assignments_{column}", "assessment_assignments", [column])

    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("assignment_id", sa.String(length=64), sa.ForeignKey("assessment_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("assignment_id", name="uq_practice_session_assignment"),
    )
    for column in ("assignment_id", "centre_id", "student_id", "status"):
        op.create_index(f"ix_practice_sessions_{column}", "practice_sessions", [column])

    op.create_table(
        "practice_hints",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), sa.ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assignment_id", sa.String(length=64), sa.ForeignKey("assessment_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(length=64), sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "question_id", "level", name="uq_practice_hint_session_question_level"),
    )
    for column in ("session_id", "assignment_id", "centre_id", "student_id", "question_id"):
        op.create_index(f"ix_practice_hints_{column}", "practice_hints", [column])

    bind = op.get_bind()
    attempt_columns = [
        sa.Column(
            "assignment_id",
            sa.String(length=64),
            sa.ForeignKey("assessment_assignments.id", ondelete="SET NULL", name="fk_attempts_assignment_id"),
            nullable=True,
        ),
        sa.Column(
            "practice_session_id",
            sa.String(length=64),
            sa.ForeignKey("practice_sessions.id", ondelete="SET NULL", name="fk_attempts_practice_session_id"),
            nullable=True,
        ),
        sa.Column("hint_level", sa.Integer(), nullable=False, server_default="0"),
    ]
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("attempts", recreate="always") as batch_op:
            for column in attempt_columns:
                batch_op.add_column(column)
    else:
        for column in attempt_columns:
            op.add_column("attempts", column)
    op.create_index("ix_attempts_assignment_id", "attempts", ["assignment_id"])
    op.create_index("ix_attempts_practice_session_id", "attempts", ["practice_session_id"])


def downgrade() -> None:
    op.drop_index("ix_attempts_practice_session_id", table_name="attempts")
    op.drop_index("ix_attempts_assignment_id", table_name="attempts")
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("attempts", recreate="always") as batch_op:
            batch_op.drop_column("hint_level")
            batch_op.drop_column("practice_session_id")
            batch_op.drop_column("assignment_id")
    else:
        op.drop_column("attempts", "hint_level")
        op.drop_column("attempts", "practice_session_id")
        op.drop_column("attempts", "assignment_id")

    for column in ("session_id", "assignment_id", "centre_id", "student_id", "question_id"):
        op.drop_index(f"ix_practice_hints_{column}", table_name="practice_hints")
    op.drop_table("practice_hints")

    for column in ("assignment_id", "centre_id", "student_id", "status"):
        op.drop_index(f"ix_practice_sessions_{column}", table_name="practice_sessions")
    op.drop_table("practice_sessions")

    for column in ("draft_id", "centre_id", "student_id", "class_id", "status", "idempotency_key"):
        op.drop_index(f"ix_assessment_assignments_{column}", table_name="assessment_assignments")
    op.drop_table("assessment_assignments")

    for column in ("centre_id", "student_id", "class_id", "subskill_id", "status"):
        op.drop_index(f"ix_assessment_drafts_{column}", table_name="assessment_drafts")
    op.drop_table("assessment_drafts")
