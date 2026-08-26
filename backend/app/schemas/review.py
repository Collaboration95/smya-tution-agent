from __future__ import annotations

from pydantic import BaseModel, Field


class TutorAlertResolveRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    resolution: str = Field(default="acknowledged", min_length=1, max_length=32)

    model_config = {"extra": "forbid"}
