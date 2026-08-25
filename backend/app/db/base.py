from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models so that Alembic and Base.metadata.create_all see them.
# S1-02 populates tenant-scoped tables; import at module load ensures alembic and create_all see them.
try:
    from backend.app.db import models  # noqa: F401  # type: ignore
except Exception:  # pragma: no cover - models may not be importable in some tool contexts
    pass

def import_models() -> None:  # pragma: no cover - import side-effect
    from backend.app.db import models  # noqa: F401  # type: ignore
