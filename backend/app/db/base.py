from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models so that Alembic and Base.metadata.create_all see them.
# S1-01 has no domain tables yet; later S1 issues import their models here.
# Keeping the import in a function avoids circular imports at import time.

def import_models() -> None:  # pragma: no cover - import side-effect
    # S1-02+ will populate these.
    from backend.app.db import models  # noqa: F401  # type: ignore
