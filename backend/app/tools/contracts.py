from __future__ import annotations
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

# Typed tool contracts — inputs and outputs are validated, not prompt strings.

class GetStudentSnapshotRequest(BaseModel):
    student_id: str

class GetStudentSnapshotResponse(BaseModel):
    student_id: str
    centre_id: str
    level_id: str
    display_name: str

class GetAttemptEvidenceRequest(BaseModel):
    attempt_id: str | None = None
    student_id: str
    subskill_id: str | None = None

class GetAttemptEvidenceResponse(BaseModel):
    evidence_ids: list[str]
    attempt_ids: list[str]
    eligible_attempts: int
    correct_attempts: int
    excluded_evidence_ids: list[str] = Field(default_factory=list)

class GetMasteryStateRequest(BaseModel):
    student_id: str
    subskill_id: str

class GetMasteryStateResponse(BaseModel):
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


class GetMasteryHistoryRequest(BaseModel):
    student_id: str
    subskill_ids: list[str] = Field(min_length=1, max_length=5)
    previous_period_start: datetime
    previous_period_end: datetime
    current_period_start: datetime
    current_period_end: datetime


class MasteryHistorySnapshot(BaseModel):
    id: str
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
    created_at: datetime
    evidence_ids: list[str]


class GetMasteryHistoryResponse(BaseModel):
    student_id: str
    previous_period: list[MasteryHistorySnapshot]
    current_period: list[MasteryHistorySnapshot]

class RetrieveCurriculumRequest(BaseModel):
    query: str = Field(description="Free-text query, must not bypass filters")
    subskill_id: str | None = None
    source_ids: list[str] | None = None  # ignored if not approved; server filters

class RetrieveCurriculumResponse(BaseModel):
    chunks: list[dict]

class SaveMasteryProposalRequest(BaseModel):
    student_id: str
    subskill_id: str
    evidence_ids: list[str]
    policy_version: str
    rationale: str

class SaveMasteryProposalResponse(BaseModel):
    proposal_id: str
    status: str

class SaveAssessmentDraftRequest(BaseModel):
    student_id: str
    subskill_id: str
    question_ids: list[str] = Field(min_length=1, max_length=10)
    selection_policy_version: str
    policy_version: str
    class_id: str | None = None

class SaveAssessmentDraftResponse(BaseModel):
    draft_id: str
    status: str

class ToolError(BaseModel):
    code: Literal["permission_denied", "not_found", "validation_error", "unsupported_content"]
    message: str
