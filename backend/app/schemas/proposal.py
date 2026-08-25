from __future__ import annotations
from pydantic import BaseModel, Field

class MasteryProposal(BaseModel):
    student_id: str
    subskill_id: str
    status: str = Field(description="pending_tutor_review|needs_more_evidence|needs_tutor_review")
    label: str = Field(description="deterministic label: insufficient_evidence|requires_support|developing|secure")
    confidence: float
    evidence_ids: list[str]
    policy_id: str
    policy_version: str
    reason: str = Field(description="Evidence-backed rationale, must reference evidence_ids and policy version")
    alternative_explanation: str | None = None
    recommended_next_action: str = Field(description="assign_targeted_practice|collect_more_evidence|tutor_review")
    source_refs: list[str] | None = None

    model_config = {"extra": "forbid"}
