from __future__ import annotations
from pydantic import BaseModel

class CallerContext(BaseModel):
    """Server-derived identity. Never trust client-provided centre/role."""
    user_id: str
    centre_id: str
    role: str  # admin|tutor|student|guardian|worker
    student_id: str | None = None  # populated for student role
    guardian_link_id: str | None = None  # for guardian role
    job_id: str | None = None  # populated for a worker bound to one job

    model_config = {"frozen": True}
