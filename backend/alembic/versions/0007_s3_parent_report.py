"""persist parent report drafts and selected history references

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parent_report_drafts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("job_id", sa.String(length=64), sa.ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("centre_id", sa.String(length=64), sa.ForeignKey("centres.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(length=64), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_ids_json", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("artifact_id", name="uq_parent_report_draft_artifact"),
    )
    for column in ("job_id", "artifact_id", "centre_id", "student_id", "status"):
        op.create_index(f"ix_parent_report_drafts_{column}", "parent_report_drafts", [column])


def downgrade() -> None:
    for column in ("status", "student_id", "centre_id", "artifact_id", "job_id"):
        op.drop_index(f"ix_parent_report_drafts_{column}", table_name="parent_report_drafts")
    op.drop_table("parent_report_drafts")
