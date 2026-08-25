from __future__ import annotations
from pydantic import BaseModel, Field
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

class ToolError(BaseModel):
    code: Literal["permission_denied", "not_found", "validation_error", "unsupported_content"]
    message: str
