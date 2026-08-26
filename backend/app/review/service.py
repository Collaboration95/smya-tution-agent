from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from backend.app.db.models import MasteryState, TutorCorrection, TutorEvidenceExclusion
from backend.app.services.mastery import upsert_mastery_state


def append_evidence_exclusion(
    db: Session,
    *,
    centre_id: str,
    evidence_id: str,
    student_id: str,
    subskill_id: str,
    author_tutor_id: str,
    job_id: str,
    reason: str,
    created_at: datetime,
) -> tuple[TutorEvidenceExclusion, MasteryState]:
    """Append an evidence exclusion and the deterministic state it produces."""
    exclusion = TutorEvidenceExclusion(
        id=f"exclude-{uuid.uuid4().hex[:8]}",
        centre_id=centre_id,
        evidence_id=evidence_id,
        student_id=student_id,
        subskill_id=subskill_id,
        author_tutor_id=author_tutor_id,
        job_id=job_id,
        reason=reason,
        created_at=created_at,
    )
    db.add(exclusion)
    db.flush()
    return exclusion, upsert_mastery_state(db, student_id, subskill_id)


def append_tutor_correction(
    db: Session,
    *,
    centre_id: str,
    student_id: str,
    subskill_id: str,
    author_tutor_id: str,
    original_state: MasteryState,
    job_id: str,
    artifact_id: str | None,
    corrected_label: str,
    reason: str,
    created_at: datetime,
) -> tuple[TutorCorrection, MasteryState]:
    """Append a tutor correction and its versioned effective override."""
    correction = TutorCorrection(
        id=f"corr-{uuid.uuid4().hex[:8]}",
        centre_id=centre_id,
        student_id=student_id,
        subskill_id=subskill_id,
        author_tutor_id=author_tutor_id,
        original_state_id=original_state.id,
        job_id=job_id,
        artifact_id=artifact_id,
        corrected_label=corrected_label,
        reason=reason,
        supersedes_version=original_state.version,
        created_at=created_at,
    )
    db.add(correction)
    db.flush()
    override = MasteryState(
        id=f"mst-{uuid.uuid4().hex[:8]}",
        centre_id=centre_id,
        student_id=student_id,
        subskill_id=subskill_id,
        version=original_state.version + 1,
        eligible_attempts=original_state.eligible_attempts,
        correct_attempts=original_state.correct_attempts,
        accuracy=original_state.accuracy,
        confidence=original_state.confidence,
        label=corrected_label,
        policy_id=original_state.policy_id,
        policy_version=original_state.policy_version,
        is_override=True,
        created_at=created_at,
    )
    db.add(override)
    return correction, override
