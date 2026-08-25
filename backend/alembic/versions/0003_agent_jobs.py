"""agent jobs and runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("agent_jobs", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("job_type", sa.String(length=32), nullable=False), sa.Column("centre_id", sa.String(length=64), nullable=True), sa.Column("student_id", sa.String(length=64), nullable=True), sa.Column("input_json", sa.Text(), nullable=False), sa.Column("idempotency_key", sa.String(length=128), nullable=False), sa.Column("status", sa.String(length=32), nullable=False), sa.Column("claimed_by", sa.String(length=64), nullable=True), sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True), sa.Column("retry_count", sa.Integer(), nullable=False), sa.Column("max_retries", sa.Integer(), nullable=False), sa.Column("error_json", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("idempotency_key"))
    op.create_index("ix_agent_jobs_centre_id", "agent_jobs", ["centre_id"])
    op.create_index("ix_agent_jobs_student_id", "agent_jobs", ["student_id"])
    op.create_index("ix_agent_jobs_idempotency_key", "agent_jobs", ["idempotency_key"], unique=True)
    op.create_index("ix_agent_jobs_job_type", "agent_jobs", ["job_type"])
    op.create_index("ix_agent_jobs_status", "agent_jobs", ["status"])
    op.create_table("agent_runs", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("job_id", sa.String(length=64), sa.ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("provider", sa.String(length=32), nullable=False), sa.Column("model_id", sa.String(length=64), nullable=False), sa.Column("status", sa.String(length=32), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True), sa.Column("duration_ms", sa.Integer(), nullable=True), sa.Column("input_tokens", sa.Integer(), nullable=True), sa.Column("output_tokens", sa.Integer(), nullable=True), sa.Column("cost_usd", sa.Float(), nullable=True), sa.Column("tool_calls_json", sa.Text(), nullable=True), sa.Column("output_json", sa.Text(), nullable=True), sa.Column("error_json", sa.Text(), nullable=True))
    op.create_index("ix_agent_runs_job_id", "agent_runs", ["job_id"])
    op.create_table("tool_call_records", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("run_id", sa.String(length=64), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("job_id", sa.String(length=64), sa.ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("tool_name", sa.String(length=64), nullable=False), sa.Column("request_json", sa.Text(), nullable=False), sa.Column("response_json", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_tool_call_records_run_id", "tool_call_records", ["run_id"])
    op.create_index("ix_tool_call_records_job_id", "tool_call_records", ["job_id"])
    op.create_table("artifacts", sa.Column("id", sa.String(length=64), primary_key=True), sa.Column("job_id", sa.String(length=64), sa.ForeignKey("agent_jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("run_id", sa.String(length=64), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("type", sa.String(length=32), nullable=False), sa.Column("payload_json", sa.Text(), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("job_id", "version", name="uq_artifact_job_version"))
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])

def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("tool_call_records")
    op.drop_table("agent_runs")
    op.drop_table("agent_jobs")
