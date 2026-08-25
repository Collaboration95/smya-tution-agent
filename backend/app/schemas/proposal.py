from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal

MasteryLabel = Literal["insufficient_evidence", "requires_support", "developing", "secure"]
ProposalStatus = Literal["pending_tutor_review", "needs_more_evidence", "needs_tutor_review"]
NextAction = Literal["assign_targeted_practice", "collect_more_evidence", "tutor_review"]

class MasteryProposal(BaseModel):
    student_id: str
    subskill_id: str
    status: ProposalStatus
    label: MasteryLabel
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]
    policy_id: str
    policy_version: str
    reason: str = Field(min_length=1, description="Evidence-backed rationale, must reference evidence_ids and policy version")
    alternative_explanation: str | None = None
    recommended_next_action: NextAction
    source_refs: list[str] | None = None

    model_config = {"extra": "forbid"}
