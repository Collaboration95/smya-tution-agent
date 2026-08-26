"""add parent report approval and simulated delivery gates

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    draft_columns = [
        sa.Column(
            "approved_guardian_link_id",
            sa.String(length=64),
            sa.ForeignKey(
                "guardian_links.id",
                name="fk_parent_report_drafts_guardian_link",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.String(length=128), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    ]
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("parent_report_drafts", recreate="always") as batch_op:
            for column in draft_columns:
                batch_op.add_column(column)
    else:
        for column in draft_columns:
            op.add_column("parent_report_drafts", column)
    op.create_index(
        "ix_parent_report_drafts_approved_guardian_link_id",
        "parent_report_drafts",
        ["approved_guardian_link_id"],
    )

    op.create_table(
        "parent_report_deliveries",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "draft_id",
            sa.String(length=64),
            sa.ForeignKey("parent_report_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "centre_id",
            sa.String(length=64),
            sa.ForeignKey("centres.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.String(length=64),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "guardian_link_id",
            sa.String(length=64),
            sa.ForeignKey("guardian_links.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("approved_content_json", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.String(length=64), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.String(length=128), nullable=True),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("draft_id", name="uq_parent_report_delivery_draft"),
        sa.UniqueConstraint("idempotency_key", name="uq_parent_report_delivery_idempotency"),
    )
    for column in ("draft_id", "centre_id", "student_id", "guardian_link_id", "status", "idempotency_key"):
        op.create_index(f"ix_parent_report_deliveries_{column}", "parent_report_deliveries", [column])
    op.create_index(
        "ix_parent_report_deliveries_student_status",
        "parent_report_deliveries",
        ["student_id", "status"],
    )


def downgrade() -> None:
    for index_name in (
        "ix_parent_report_deliveries_student_status",
        "ix_parent_report_deliveries_idempotency_key",
        "ix_parent_report_deliveries_status",
        "ix_parent_report_deliveries_guardian_link_id",
        "ix_parent_report_deliveries_student_id",
        "ix_parent_report_deliveries_centre_id",
        "ix_parent_report_deliveries_draft_id",
    ):
        op.drop_index(index_name, table_name="parent_report_deliveries")
    op.drop_table("parent_report_deliveries")
    op.drop_index(
        "ix_parent_report_drafts_approved_guardian_link_id",
        table_name="parent_report_drafts",
    )
    draft_columns = (
        "delivered_at",
        "queued_at",
        "blocked_reason",
        "rejected_at",
        "approved_at",
        "approved_by",
        "review_reason",
        "reviewed_by",
        "approved_guardian_link_id",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("parent_report_drafts", recreate="always") as batch_op:
            for column in draft_columns:
                batch_op.drop_column(column)
    else:
        for column in draft_columns:
            op.drop_column("parent_report_drafts", column)
