from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.db.models import AgentJob, AgentRun, MasteryState, Student, TutorAlert
from backend.app.models.client import ModelClient
from backend.app.schemas.proposal import MasteryProposal
from backend.app.services.jobs import (
    complete_job_with_artifact,
    fail_run,
    mark_needs_review,
    record_tool_call,
    start_run,
)
from backend.app.services.mastery import compute_mastery, load_policy, upsert_mastery_state
from backend.app.tools.contracts import (
    GetAttemptEvidenceRequest,
    GetMasteryStateRequest,
    GetStudentSnapshotRequest,
    RetrieveCurriculumRequest,
)
from backend.app.tools.registry import invoke_tool


def _worker_context(job: AgentJob, student: Student) -> CallerContext:
    worker_id = job.claimed_by or f"worker-diagnostic:{job.id}"
    return CallerContext(
        user_id=worker_id,
        centre_id=student.centre_id,
        role="worker",
        student_id=student.id,
        job_id=job.id,
    )


def _record_invocation(run: AgentRun, invocation) -> None:
    if invocation.input_tokens is not None:
        run.input_tokens = (run.input_tokens or 0) + invocation.input_tokens
    if invocation.output_tokens is not None:
        run.output_tokens = (run.output_tokens or 0) + invocation.output_tokens
    if invocation.cost_usd is not None:
        run.cost_usd = (run.cost_usd or 0.0) + invocation.cost_usd


def _alert_once(
    db: Session,
    job: AgentJob,
    student: Student,
    subskill_id: str,
    alert_type: str,
    message: str,
) -> None:
    existing = db.query(TutorAlert).filter(TutorAlert.job_id == job.id, TutorAlert.type == alert_type).first()
    if existing:
        return
    db.add(
        TutorAlert(
            id=f"alert-{uuid.uuid4().hex[:8]}",
            centre_id=student.centre_id,
            student_id=student.id,
            subskill_id=subskill_id,
            job_id=job.id,
            type=alert_type,
            message=message,
            created_at=datetime.now(timezone.utc),
        )
    )


def _review(db: Session, run: AgentRun, code: str, message: str, **details) -> dict:
    mark_needs_review(db, run, {"code": code, "message": message, **details})
    db.commit()
    return {"status": "needs_tutor_review", "reason": code}


def run_diagnostic(db: Session, job: AgentJob, model_client: ModelClient) -> dict:
    """Run one claimed diagnostic job with bounded, typed tool access."""
    if job.job_type != "diagnostic":
        raise ValueError(f"unsupported diagnostic job type: {job.job_type}")
    if job.status != "claimed":
        raise ValueError(f"diagnostic job must be claimed before running: {job.status}")

    payload = json.loads(job.input_json)
    student_id = payload.get("student_id")
    subskill_id = payload.get("subskill_id")
    if not student_id or not subskill_id:
        raise ValueError("job input must contain student_id and subskill_id")
    if job.student_id != student_id:
        raise ValueError("job student_id does not match diagnostic input")
    student = db.query(Student).filter(Student.id == student_id, Student.centre_id == job.centre_id).first()
    if not student:
        raise ValueError(f"unknown or out-of-scope student {student_id}")

    caller = _worker_context(job, student)
    run = start_run(db, job, model_client.provider, model_client.model_id, worker_id=caller.user_id)
    tool_summaries: list[str] = []
    try:
        snapshot_request = GetStudentSnapshotRequest(student_id=student_id)
        snapshot = invoke_tool(db, caller, job, "get_student_snapshot", snapshot_request)
        record_tool_call(db, run, "get_student_snapshot", snapshot_request.model_dump(), snapshot.model_dump())
        tool_summaries.append("get_student_snapshot")

        # The attempt id identifies the trigger, but the proposal must be
        # grounded in the bounded batch for this student/subskill.
        evidence_request = GetAttemptEvidenceRequest(student_id=student_id, subskill_id=subskill_id)
        evidence = invoke_tool(db, caller, job, "get_attempt_evidence", evidence_request)
        record_tool_call(db, run, "get_attempt_evidence", evidence_request.model_dump(), evidence.model_dump())
        tool_summaries.append("get_attempt_evidence")

        state = (
            db.query(MasteryState)
            .filter(
                MasteryState.student_id == student_id,
                MasteryState.centre_id == student.centre_id,
                MasteryState.subskill_id == subskill_id,
            )
            .order_by(MasteryState.version.desc())
            .first()
        )
        if not state:
            state = upsert_mastery_state(db, student_id, subskill_id)
            db.flush()
        mastery_request = GetMasteryStateRequest(student_id=student_id, subskill_id=subskill_id)
        mastery = invoke_tool(db, caller, job, "get_mastery_state", mastery_request)
        record_tool_call(db, run, "get_mastery_state", mastery_request.model_dump(), mastery.model_dump())
        tool_summaries.append("get_mastery_state")

        curriculum_request = RetrieveCurriculumRequest(query=f"{subskill_id} fractions", subskill_id=subskill_id)
        curriculum = invoke_tool(db, caller, job, "retrieve_approved_curriculum", curriculum_request)
        record_tool_call(
            db,
            run,
            "retrieve_approved_curriculum",
            curriculum_request.model_dump(),
            {"count": len(curriculum.chunks), "source_refs": [chunk["id"] for chunk in curriculum.chunks[:2]]},
        )
        tool_summaries.append("retrieve_approved_curriculum")

        if not curriculum.chunks:
            _alert_once(
                db,
                job,
                student,
                subskill_id,
                "unsupported",
                f"No approved curriculum is available for {subskill_id}; the diagnostic is blocked pending tutor review.",
            )
            run.tool_calls_json = json.dumps(tool_summaries)
            return _review(
                db,
                run,
                "unsupported_content",
                "no approved curriculum was found for this subskill",
                subskill_id=subskill_id,
            )

        policy = load_policy()
        eligible = mastery.eligible_attempts
        correct = mastery.correct_attempts
        deterministic = compute_mastery(eligible, correct, policy)
        evidence_ids = evidence.evidence_ids
        policy_id = mastery.policy_id
        policy_version = mastery.policy_version
        conflicting = eligible >= 3 and 0 < correct < eligible
        needs_more_evidence = deterministic["label"] == "insufficient_evidence" or conflicting

        if deterministic["label"] == "insufficient_evidence":
            _alert_once(
                db,
                job,
                student,
                subskill_id,
                "low_evidence",
                f"Insufficient evidence for {subskill_id}: {eligible} attempts. Collect more evidence.",
            )
        if conflicting:
            _alert_once(
                db,
                job,
                student,
                subskill_id,
                "conflicting",
                f"Conflicting evidence for {subskill_id}: {correct} correct of {eligible} eligible attempts.",
            )

        prompt = (
            f"Diagnostic proposal for student {student_id} subskill {subskill_id}. "
            f"Evidence IDs: {evidence_ids}. Deterministic state: label={deterministic['label']} "
            f"confidence={deterministic['confidence']} accuracy={deterministic['accuracy']} "
            f"eligible={eligible} correct={correct} policy_id={policy_id} policy_version={policy_version}. "
            f"Explain rationale referencing evidence IDs and policy version, provide an alternative explanation if needed, "
            f"and recommend next action. Do NOT change label or confidence. Return JSON matching MasteryProposal schema."
        )
        output = model_client.generate_structured(prompt, MasteryProposal)
        _record_invocation(run, output.invocation)
        record_tool_call(
            db,
            run,
            "model.generate_structured",
            {"prompt": prompt[:500], "schema": "MasteryProposal"},
            {"raw": output.raw[:500], "parsed": output.parsed},
        )
        tool_summaries.append("model.generate_structured")

        if output.parsed is None:
            repair_prompt = prompt + " Previous output failed validation. Return only valid JSON matching the schema."
            repaired = model_client.generate_structured(repair_prompt, MasteryProposal)
            _record_invocation(run, repaired.invocation)
            record_tool_call(
                db,
                run,
                "model.generate_structured(repair)",
                {"prompt": repair_prompt[:500], "schema": "MasteryProposal"},
                {"raw": repaired.raw[:500], "parsed": repaired.parsed},
            )
            tool_summaries.append("model.generate_structured(repair)")
            output = repaired
        if output.parsed is None:
            run.tool_calls_json = json.dumps(tool_summaries)
            return _review(db, run, "invalid_model_output", "model output failed validation after repair", raw=output.raw[:1000])

        try:
            proposal = MasteryProposal.model_validate(output.parsed)
        except ValidationError as exc:
            run.tool_calls_json = json.dumps(tool_summaries)
            return _review(db, run, "invalid_proposal_schema", "proposal failed schema validation", errors=exc.errors())

        if proposal.student_id != student_id or proposal.subskill_id != subskill_id:
            run.tool_calls_json = json.dumps(tool_summaries)
            return _review(db, run, "student_scope_mismatch", "proposal identity did not match the job")
        if proposal.label != deterministic["label"] or abs(proposal.confidence - deterministic["confidence"]) > 0.001:
            run.tool_calls_json = json.dumps(tool_summaries)
            return _review(
                db,
                run,
                "label_confidence_mismatch",
                "model changed deterministic values",
                expected_label=deterministic["label"],
                expected_confidence=deterministic["confidence"],
                received_label=proposal.label,
                received_confidence=proposal.confidence,
            )
        if set(proposal.evidence_ids) != set(evidence_ids) or proposal.policy_id != policy_id or proposal.policy_version != policy_version:
            run.tool_calls_json = json.dumps(tool_summaries)
            return _review(db, run, "evidence_policy_mismatch", "evidence or policy provenance did not match the deterministic state")
        if len(proposal.evidence_ids) != len(set(proposal.evidence_ids)):
            run.tool_calls_json = json.dumps(tool_summaries)
            return _review(db, run, "duplicate_evidence_ids", "proposal contained duplicate evidence identifiers")
        if policy_version not in proposal.reason or (evidence_ids and not any(item in proposal.reason for item in evidence_ids)):
            run.tool_calls_json = json.dumps(tool_summaries)
            return _review(db, run, "rationale_provenance_missing", "rationale did not cite evidence and policy version")

        safe_status = "needs_more_evidence" if needs_more_evidence else "pending_tutor_review"
        safe_action = "collect_more_evidence" if needs_more_evidence else proposal.recommended_next_action
        review_reason = None
        if needs_more_evidence:
            review_reason = {
                "code": "low_evidence" if deterministic["label"] == "insufficient_evidence" else "conflicting_evidence",
                "message": "proposal persisted for tutor review because the evidence is insufficient or conflicting",
            }
        artifact_payload = {
            "student_id": student_id,
            "subskill_id": subskill_id,
            "label": deterministic["label"],
            "confidence": deterministic["confidence"],
            "evidence_ids": evidence_ids,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "rationale": proposal.reason,
            "alternative_explanation": proposal.alternative_explanation,
            "recommended_next_action": safe_action,
            "source_refs": [chunk["id"] for chunk in curriculum.chunks[:2]],
            "status": safe_status,
        }
        run.tool_calls_json = json.dumps(tool_summaries)
        artifact = complete_job_with_artifact(
            db,
            run,
            "mastery_proposal",
            artifact_payload,
            review_reason=review_reason,
        )
        db.commit()
        return {
            "status": "needs_tutor_review" if needs_more_evidence else "succeeded",
            "artifact_id": artifact.id,
            "proposal": artifact_payload,
        }
    except Exception as exc:
        try:
            fail_run(db, run, {"code": "worker_error", "message": str(exc)}, retryable=True)
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "failed_retryable", "error": str(exc)}
