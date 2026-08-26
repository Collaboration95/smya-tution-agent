from __future__ import annotations

from pydantic import BaseModel, Field


class AssessmentDraftCreateRequest(BaseModel):
    student_id: str
    subskill_id: str
    item_count: int = Field(default=2, ge=1, le=10)
    recent_question_ids: list[str] = Field(default_factory=list, max_length=10)
    class_id: str | None = None

    model_config = {"extra": "forbid"}


class AssessmentDraftEditRequest(BaseModel):
    question_ids: list[str] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=1000)

    model_config = {"extra": "forbid"}


class AssessmentReviewRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)

    model_config = {"extra": "forbid"}


class AssessmentRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    model_config = {"extra": "forbid"}


class PracticeHintRequest(BaseModel):
    question_id: str

    model_config = {"extra": "forbid"}


class PracticeAnswerRequest(BaseModel):
    question_id: str
    answer: str = Field(min_length=1, max_length=255)

    model_config = {"extra": "forbid"}


class SaveAssessmentDraftRequest(BaseModel):
    student_id: str
    subskill_id: str
    question_ids: list[str] = Field(min_length=1, max_length=10)
    selection_policy_version: str
    policy_version: str
    class_id: str | None = None

    model_config = {"extra": "forbid"}


class SaveAssessmentDraftResponse(BaseModel):
    draft_id: str
    status: str
