from __future__ import annotations
# Placeholder for S1-02 domain models. Keeps Base importable for Alembic.
# S1-01 intentionally has no domain tables; health check uses SELECT 1.
from backend.app.db.base import Base  # noqa: F401
