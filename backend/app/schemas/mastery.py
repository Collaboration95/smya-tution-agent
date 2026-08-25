from __future__ import annotations
from pydantic import BaseModel

class MasteryStateResponse(BaseModel):
    student_id: str
    subskill_id: str
    version: int
    eligible_attempts: int
    correct_attempts: int
    accuracy: float
    confidence: float
    label: str
    policy_id: str
    policy_version: str
    is_override: bool

    model_config = {"from_attributes": True}
