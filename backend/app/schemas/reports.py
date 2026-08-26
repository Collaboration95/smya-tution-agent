from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReportPeriod(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_range(self) -> "ReportPeriod":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("report periods must use timezone-aware timestamps")
        if self.start >= self.end:
            raise ValueError("report period start must be before end")
        return self


class ParentReportJobRequest(BaseModel):
    student_id: str
    subskill_ids: list[str] = Field(min_length=1, max_length=5)
    previous_period: ReportPeriod
    current_period: ReportPeriod
    max_retries: int = Field(default=3, ge=0, le=5)

    @model_validator(mode="after")
    def validate_request(self) -> "ParentReportJobRequest":
        if len(set(self.subskill_ids)) != len(self.subskill_ids):
            raise ValueError("subskill_ids must be unique")
        if self.previous_period.end > self.current_period.start:
            raise ValueError("comparison periods must not overlap")
        return self

    model_config = {"extra": "forbid"}


ReportSignal = Literal["improved", "steady", "needs_support", "mixed", "insufficient_evidence"]
NextStepCode = Literal[
    "collect_more_evidence",
    "review_foundation",
    "review_core",
    "continue_practice",
    "try_stretch",
]


class ParentReportProposal(BaseModel):
    """Closed-vocabulary model output; prose is rendered by trusted code."""

    student_id: str
    progress_signal: ReportSignal
    next_step_codes: list[NextStepCode] = Field(min_length=1, max_length=3)
    snapshot_ids: list[str]
    evidence_ids: list[str]

    model_config = {"extra": "forbid"}


class ParentReportJobResponse(BaseModel):
    job_id: str
    status: str
    idempotency_key: str


class ParentReportDraftResponse(BaseModel):
    id: str
    job_id: str
    artifact_id: str
    student_id: str
    status: str
    snapshot_ids: list[str]
    evidence_ids: list[str]
    content: dict
    approved_guardian_link_id: str | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_at: str | None = None
    blocked_reason: str | None = None
    queued_at: str | None = None
    delivered_at: str | None = None
    guardian_links: list["GuardianLinkResponse"] = Field(default_factory=list)
    delivery: "ParentReportDeliveryResponse | None" = None
    audit: list["ParentReportAuditResponse"] = Field(default_factory=list)


class ParentReportApproveRequest(BaseModel):
    guardian_link_id: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=1000)

    model_config = {"extra": "forbid"}


class ParentReportRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    model_config = {"extra": "forbid"}


class GuardianLinkResponse(BaseModel):
    id: str
    display_name: str
    verification_status: str
    reporting_consent: bool


class ParentReportAuditResponse(BaseModel):
    id: str
    event: str
    entity_type: str
    entity_id: str
    actor_id: str
    actor_role: str
    before: dict | None = None
    after: dict | None = None
    created_at: str | None = None


class ParentReportDeliveryResponse(BaseModel):
    id: str
    draft_id: str
    status: str
    idempotency_key: str
    guardian_link_id: str
    approved_by: str
    approved_at: str
    queued_at: str
    delivered_at: str | None = None
    provider_message_id: str | None = None
    blocked_reason: str | None = None
    approved_content: dict | None = None


ParentReportDraftResponse.model_rebuild()
