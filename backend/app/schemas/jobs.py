from __future__ import annotations
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

class JobCreateRequest(BaseModel):
    job_type: Literal["diagnostic", "assessment", "parent_report"]
    centre_id: str | None = None
    student_id: str | None = None
    input_payload: dict
    max_retries: int = Field(default=3, ge=0, le=5)

    model_config = {"extra": "forbid"}


class JobResponse(BaseModel):
    id: str
    job_type: str
    centre_id: str | None
    student_id: str | None
    input_json: str
    idempotency_key: str
    status: str
    claimed_by: str | None
    retry_count: int
    max_retries: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class RunResponse(BaseModel):
    id: str
    job_id: str
    attempt: int
    provider: str
    model_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    model_config = {"from_attributes": True}
