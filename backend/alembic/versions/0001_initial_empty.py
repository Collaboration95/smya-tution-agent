"""initial empty schema for S1-01

Revision ID: 0001
Revises: 
Create Date: 2026-08-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # S1-01 has no domain tables; schema is intentionally empty.
    # S1-02 will add tenant-scoped tables in 0002.
    pass

def downgrade() -> None:
    pass
