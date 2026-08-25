"""tenant backfills and durable tutor decisions

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCOPED_TABLES = (
    "enrolments",
    "guardian_links",
    "curriculum_chunks",
    "questions",
    "attempts",
    "mastery_evidence",
    "mastery_states",
    "tutor_corrections",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in SCOPED_TABLES:
        column = sa.Column(
            "centre_id",
            sa.String(length=64),
            sa.ForeignKey(
                "centres.id",
                name=f"fk_{table}_centre_id_centres",
                ondelete="CASCADE",
            ),
            nullable=True,
        )
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(table, recreate="always") as batch_op:
                batch_op.add_column(column)
        else:
            op.add_column(table, column)
        op.create_index(f"ix_{table}_centre_id", table, ["centre_id"])

    op.execute(
        sa.text(
            "UPDATE enrolments SET centre_id = "
            "(SELECT centre_id FROM classes WHERE classes.id = enrolments.class_id) "
            "WHERE centre_id IS NULL"
        )
    )
    for table in ("guardian_links", "attempts", "mastery_evidence", "mastery_states", "tutor_corrections"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET centre_id = "
                f"(SELECT centre_id FROM students WHERE students.id = {table}.student_id) "
                "WHERE centre_id IS NULL"
            )
        )
    # The S1 fixture corpus is a centre-approved synthetic source. Existing
    # rows are assigned to the single seeded centre; future global source rows
    # may remain nullable and are filtered as approved, non-sensitive content.
    for table in ("curriculum_chunks", "questions"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET centre_id = "
                "(SELECT id FROM centres ORDER BY id LIMIT 1) "
                "WHERE centre_id IS NULL"
            )
        )

    op.create_table(
        "tutor_decisions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("job_id", sa.String(length=64), sa.ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=True),
        sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("corrected_label", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tutor_decisions_job_id", "tutor_decisions", ["job_id"])
    op.create_index("ix_tutor_decisions_centre_id", "tutor_decisions", ["centre_id"])
    op.create_index("ix_tutor_decisions_student_id", "tutor_decisions", ["student_id"])
    op.create_index("ix_tutor_decisions_job_created", "tutor_decisions", ["job_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_tutor_decisions_job_created", table_name="tutor_decisions")
    op.drop_index("ix_tutor_decisions_student_id", table_name="tutor_decisions")
    op.drop_index("ix_tutor_decisions_centre_id", table_name="tutor_decisions")
    op.drop_index("ix_tutor_decisions_job_id", table_name="tutor_decisions")
    op.drop_table("tutor_decisions")
    bind = op.get_bind()
    for table in reversed(SCOPED_TABLES):
        op.drop_index(f"ix_{table}_centre_id", table_name=table)
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(table, recreate="always") as batch_op:
                batch_op.drop_column("centre_id")
        else:
            op.drop_column(table, "centre_id")
