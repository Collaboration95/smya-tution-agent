"""durable tutor review corrections, exclusions, and alert resolution

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_columns(table_name: str, columns: list[sa.Column]) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            for column in columns:
                batch_op.add_column(column)
    else:
        for column in columns:
            op.add_column(table_name, column)


def _drop_columns(table_name: str, column_names: tuple[str, ...]) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            for column_name in column_names:
                batch_op.drop_column(column_name)
    else:
        for column_name in column_names:
            op.drop_column(table_name, column_name)


def upgrade() -> None:
    _add_columns(
        "tutor_corrections",
        [
            sa.Column(
                "job_id",
                sa.String(length=64),
                sa.ForeignKey("agent_jobs.id", name="fk_tutor_corrections_job_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "artifact_id",
                sa.String(length=64),
                sa.ForeignKey("artifacts.id", name="fk_tutor_corrections_artifact_id", ondelete="SET NULL"),
                nullable=True,
            ),
        ],
    )
    op.create_index("ix_tutor_corrections_job_id", "tutor_corrections", ["job_id"])
    op.create_index("ix_tutor_corrections_artifact_id", "tutor_corrections", ["artifact_id"])

    _add_columns(
        "tutor_alerts",
        [
            sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
            sa.Column("resolution", sa.String(length=32), nullable=True),
            sa.Column("resolution_reason", sa.Text(), nullable=True),
            sa.Column(
                "resolved_by",
                sa.String(length=64),
                sa.ForeignKey("users.id", name="fk_tutor_alerts_resolved_by", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    op.create_index("ix_tutor_alerts_status", "tutor_alerts", ["status"])

    _add_columns(
        "tutor_decisions",
        [
            sa.Column(
                "evidence_id",
                sa.String(length=64),
                sa.ForeignKey("mastery_evidence.id", name="fk_tutor_decisions_evidence_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "alert_id",
                sa.String(length=64),
                sa.ForeignKey("tutor_alerts.id", name="fk_tutor_decisions_alert_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "correction_id",
                sa.String(length=64),
                sa.ForeignKey("tutor_corrections.id", name="fk_tutor_decisions_correction_id", ondelete="SET NULL"),
                nullable=True,
            ),
        ],
    )
    op.create_index("ix_tutor_decisions_evidence_id", "tutor_decisions", ["evidence_id"])
    op.create_index("ix_tutor_decisions_alert_id", "tutor_decisions", ["alert_id"])
    op.create_index("ix_tutor_decisions_correction_id", "tutor_decisions", ["correction_id"])

    op.create_table(
        "tutor_evidence_exclusions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "centre_id",
            sa.String(length=64),
            sa.ForeignKey("centres.id", name="fk_tutor_evidence_exclusions_centre_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "evidence_id",
            sa.String(length=64),
            sa.ForeignKey("mastery_evidence.id", name="fk_tutor_evidence_exclusions_evidence_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.String(length=64),
            sa.ForeignKey("students.id", name="fk_tutor_evidence_exclusions_student_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subskill_id", sa.String(length=64), nullable=False),
        sa.Column(
            "author_tutor_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", name="fk_tutor_evidence_exclusions_author_tutor_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("agent_jobs.id", name="fk_tutor_evidence_exclusions_job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("evidence_id", name="uq_tutor_evidence_exclusion_evidence"),
    )
    for column in ("centre_id", "evidence_id", "student_id", "subskill_id", "author_tutor_id", "job_id"):
        op.create_index(f"ix_tutor_evidence_exclusions_{column}", "tutor_evidence_exclusions", [column])


def downgrade() -> None:
    for column in ("job_id", "author_tutor_id", "subskill_id", "student_id", "evidence_id", "centre_id"):
        op.drop_index(f"ix_tutor_evidence_exclusions_{column}", table_name="tutor_evidence_exclusions")
    op.drop_table("tutor_evidence_exclusions")

    op.drop_index("ix_tutor_decisions_correction_id", table_name="tutor_decisions")
    op.drop_index("ix_tutor_decisions_alert_id", table_name="tutor_decisions")
    op.drop_index("ix_tutor_decisions_evidence_id", table_name="tutor_decisions")
    _drop_columns("tutor_decisions", ("correction_id", "alert_id", "evidence_id"))

    op.drop_index("ix_tutor_alerts_status", table_name="tutor_alerts")
    _drop_columns("tutor_alerts", ("resolved_at", "resolved_by", "resolution_reason", "resolution", "status"))

    op.drop_index("ix_tutor_corrections_artifact_id", table_name="tutor_corrections")
    op.drop_index("ix_tutor_corrections_job_id", table_name="tutor_corrections")
    _drop_columns("tutor_corrections", ("artifact_id", "job_id"))
