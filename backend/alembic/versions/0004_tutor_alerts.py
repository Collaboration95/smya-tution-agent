"""tutor alerts for diagnostic low evidence

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("tutor_alerts", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("centre_id", sa.String(length=64), nullable=True), sa.Column("student_id", sa.String(length=64), nullable=False), sa.Column("subskill_id", sa.String(length=64), nullable=False), sa.Column("job_id", sa.String(length=64), sa.ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("type", sa.String(length=32), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_tutor_alerts_centre_id", "tutor_alerts", ["centre_id"])
    op.create_index("ix_tutor_alerts_student_id", "tutor_alerts", ["student_id"])
    op.create_index("ix_tutor_alerts_job_id", "tutor_alerts", ["job_id"])

def downgrade() -> None:
    op.drop_table("tutor_alerts")
