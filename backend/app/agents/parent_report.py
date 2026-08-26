from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.auth.context import CallerContext
from backend.app.db.models import AgentJob, AgentRun, Artifact, ParentReportDraft, Student
from backend.app.models.client import ModelClient
from backend.app.schemas.reports import ParentReportProposal
from backend.app.services.jobs import (
    complete_job_with_artifact,
    mark_needs_review,
    record_tool_call,
    start_run,
)
from backend.app.tools.contracts import GetMasteryHistoryRequest
from backend.app.tools.registry import invoke_tool


LABEL_RANK = {
    "insufficient_evidence": 0,
    "requires_support": 1,
    "developing": 2,
    "secure": 3,
}

SIGNAL_COPY = {
    "improved": "Progress is improving across the selected comparison periods.",
    "steady": "Progress is steady across the selected comparison periods.",
    "needs_support": "The selected history suggests that continued support is needed.",
    "mixed": "The selected history shows mixed changes across the requested skills.",
    "insufficient_evidence": "There is not enough approved history for a reliable comparison.",
}

NEXT_STEP_COPY = {
    "collect_more_evidence": "Collect more approved learning evidence before making a comparison.",
    "review_foundation": "Review the foundation skill with the tutor.",
    "review_core": "Continue focused practice on the core skill.",
    "continue_practice": "Continue the current practice routine and review the next update.",
    "try_stretch": "Try a carefully selected stretch activity with tutor oversight.",
}


def _worker_context(job: AgentJob, student: Student) -> CallerContext:
    worker_id = job.claimed_by or f"worker-parent-report:{job.id}"
    return CallerContext(
        user_id=worker_id,
        centre_id=student.centre_id,
        role="worker",
        student_id=student.id,
        job_id=job.id,
    )


def _record_invocation(run: AgentRun, invocation: Any) -> None:
    if invocation.input_tokens is not None:
        run.input_tokens = (run.input_tokens or 0) + invocation.input_tokens
    if invocation.output_tokens is not None:
        run.output_tokens = (run.output_tokens or 0) + invocation.output_tokens
    if invocation.cost_usd is not None:
        run.cost_usd = (run.cost_usd or 0.0) + invocation.cost_usd


def _review(db: Session, run: AgentRun, code: str, message: str, **details: Any) -> dict:
    # Do not persist raw provider output or free-form prompts in review errors.
    mark_needs_review(db, run, {"code": code, "message": message, **details})
    db.commit()
    return {"status": "needs_tutor_review", "reason": code}


def _signal(previous: list[Any], current: list[Any], subskill_ids: list[str]) -> str:
    if len(previous) != len(subskill_ids) or len(current) != len(subskill_ids):
        return "insufficient_evidence"
    previous_by_skill = {snapshot.subskill_id: snapshot for snapshot in previous}
    current_by_skill = {snapshot.subskill_id: snapshot for snapshot in current}
    if set(previous_by_skill) != set(subskill_ids) or set(current_by_skill) != set(subskill_ids):
        return "insufficient_evidence"
    deltas = [
        LABEL_RANK[current_by_skill[subskill_id].label] - LABEL_RANK[previous_by_skill[subskill_id].label]
        for subskill_id in subskill_ids
    ]
    if all(delta == 0 for delta in deltas):
        return "steady"
    if all(delta >= 0 for delta in deltas) and any(delta > 0 for delta in deltas):
        return "improved"
    if all(delta <= 0 for delta in deltas) and any(delta < 0 for delta in deltas):
        return "needs_support"
    return "mixed"


def _allowed_next_steps(signal: str, current: list[Any]) -> list[str]:
    if signal == "insufficient_evidence":
        return ["collect_more_evidence"]
    codes: list[str] = []
    for snapshot in current:
        if snapshot.label in {"insufficient_evidence", "requires_support"}:
            code = "review_foundation"
        elif snapshot.label == "developing":
            code = "review_core"
        else:
            code = "try_stretch"
        if code not in codes:
            codes.append(code)
    if signal in {"improved", "steady"} and "continue_practice" not in codes:
        codes.append("continue_practice")
    return codes[:3] or ["continue_practice"]


def _report_content(
    student_id: str,
    signal: str,
    next_step_codes: list[str],
    previous_period: dict,
    current_period: dict,
    previous: list[Any],
    current: list[Any],
    snapshot_ids: list[str],
    evidence_ids: list[str],
) -> dict:
    previous_by_skill = {snapshot.subskill_id: snapshot for snapshot in previous}
    current_by_skill = {snapshot.subskill_id: snapshot for snapshot in current}
    subskills = []
    for subskill_id in sorted(set(previous_by_skill) | set(current_by_skill)):
        before = previous_by_skill.get(subskill_id)
        after = current_by_skill.get(subskill_id)
        subskills.append(
            {
                "subskill_id": subskill_id,
                "previous_snapshot_id": before.id if before else None,
                "current_snapshot_id": after.id if after else None,
                "previous_label": before.label if before else None,
                "current_label": after.label if after else None,
                "previous_accuracy": before.accuracy if before else None,
                "current_accuracy": after.accuracy if after else None,
            }
        )
    return {
        "schema_version": "parent_report_v1",
        "student_id": student_id,
        "status": "pending_tutor_review",
        "progress_signal": signal,
        "headline": SIGNAL_COPY[signal],
        "next_steps": [NEXT_STEP_COPY[code] for code in next_step_codes],
        "comparison": {
            "previous_period": previous_period,
            "current_period": current_period,
            "subskills": subskills,
        },
        "snapshot_ids": snapshot_ids,
        "evidence_ids": evidence_ids,
    }


def _persist_draft(
    db: Session,
    job: AgentJob,
    artifact: Artifact,
    content: dict,
    previous_period: dict,
    current_period: dict,
    snapshot_ids: list[str],
    evidence_ids: list[str],
) -> ParentReportDraft:
    existing = db.query(ParentReportDraft).filter(ParentReportDraft.artifact_id == artifact.id).first()
    if existing:
        return existing
    draft = ParentReportDraft(
        id=f"report-draft-{uuid.uuid4().hex[:8]}",
        job_id=job.id,
        artifact_id=artifact.id,
        centre_id=job.centre_id,
        student_id=job.student_id,
        previous_period_start=datetime.fromisoformat(previous_period["start"].replace("Z", "+00:00")),
        previous_period_end=datetime.fromisoformat(previous_period["end"].replace("Z", "+00:00")),
        current_period_start=datetime.fromisoformat(current_period["start"].replace("Z", "+00:00")),
        current_period_end=datetime.fromisoformat(current_period["end"].replace("Z", "+00:00")),
        snapshot_ids_json=json.dumps(snapshot_ids, sort_keys=True),
        evidence_ids_json=json.dumps(evidence_ids, sort_keys=True),
        content_json=json.dumps(content, sort_keys=True),
        status="pending_tutor_review",
    )
    db.add(draft)
    db.flush()
    return draft


def run_parent_report(db: Session, job: AgentJob, model_client: ModelClient) -> dict:
    """Run one bounded parent-report draft job from approved history only."""
    if job.job_type != "parent_report":
        raise ValueError(f"unsupported parent report job type: {job.job_type}")
    if job.status != "claimed":
        raise ValueError(f"parent report job must be claimed before running: {job.status}")

    payload = json.loads(job.input_json)
    student_id = payload.get("student_id")
    scope = payload.get("verified_scope")
    if not student_id or scope != {"centre_id": job.centre_id, "student_id": student_id}:
        raise ValueError("parent report job scope is not verified")
    student = db.query(Student).filter(Student.id == student_id, Student.centre_id == job.centre_id).first()
    if student is None:
        raise ValueError("unknown or out-of-scope student")
    previous_period = payload["previous_period"]
    current_period = payload["current_period"]
    subskill_ids = payload["subskill_ids"]

    caller = _worker_context(job, student)
    run = start_run(db, job, model_client.provider, model_client.model_id, worker_id=caller.user_id)
    try:
        history_request = GetMasteryHistoryRequest(
            student_id=student_id,
            subskill_ids=subskill_ids,
            previous_period_start=previous_period["start"],
            previous_period_end=previous_period["end"],
            current_period_start=current_period["start"],
            current_period_end=current_period["end"],
        )
        history = invoke_tool(db, caller, job, "get_mastery_history", history_request)
        record_tool_call(
            db,
            run,
            "get_mastery_history",
            history_request.model_dump(mode="json"),
            history.model_dump(mode="json"),
        )
        previous = history.previous_period
        current = history.current_period
        expected_signal = _signal(previous, current, subskill_ids)
        allowed_next_steps = _allowed_next_steps(expected_signal, current)
        snapshot_ids = [snapshot.id for snapshot in [*previous, *current]]
        evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for snapshot in [*previous, *current]
                for evidence_id in snapshot.evidence_ids
            )
        )
        prompt = (
            f"Parent report proposal for student {student_id}. Expected progress_signal={expected_signal}. "
            f"Allowed next_step_codes={json.dumps(allowed_next_steps)}. "
            f"Snapshot IDs: {json.dumps(snapshot_ids)}. Evidence IDs: {json.dumps(evidence_ids)}. "
            "Use only these structured references. Return the exact student_id, signal, allowed next-step codes, "
            "snapshot IDs, and evidence IDs. Do not return prose, private data, raw chat, or hidden reasoning."
        )
        try:
            output = model_client.generate_structured(prompt, ParentReportProposal)
        except Exception:
            return _review(db, run, "model_provider_error", "parent report provider failed")
        _record_invocation(run, output.invocation)
        record_tool_call(
            db,
            run,
            "model.generate_structured",
            {"schema": "ParentReportProposal", "prompt_contract": "closed_vocabulary"},
            {"valid": output.parsed is not None},
        )
        if output.parsed is None:
            try:
                repair = model_client.generate_structured(
                    prompt + " Previous output failed validation. Return only the closed-vocabulary JSON object.",
                    ParentReportProposal,
                )
            except Exception:
                return _review(db, run, "model_provider_error", "parent report repair provider failed")
            _record_invocation(run, repair.invocation)
            record_tool_call(
                db,
                run,
                "model.generate_structured(repair)",
                {"schema": "ParentReportProposal", "prompt_contract": "closed_vocabulary"},
                {"valid": repair.parsed is not None},
            )
            output = repair
        if output.parsed is None:
            return _review(db, run, "invalid_model_output", "model output failed validation after repair")
        try:
            proposal = ParentReportProposal.model_validate(output.parsed)
        except ValidationError as exc:
            return _review(
                db,
                run,
                "invalid_proposal_schema",
                "parent report proposal failed schema validation",
                errors=exc.errors(),
            )
        if proposal.student_id != student_id:
            return _review(db, run, "student_scope_mismatch", "parent report proposal identity did not match the job")
        if proposal.progress_signal != expected_signal:
            return _review(db, run, "progress_signal_mismatch", "model changed the deterministic period comparison")
        if len(set(proposal.next_step_codes)) != len(proposal.next_step_codes):
            return _review(db, run, "duplicate_next_steps", "parent report proposal contained duplicate next steps")
        if not set(proposal.next_step_codes).issubset(set(allowed_next_steps)):
            return _review(db, run, "unsupported_next_step", "parent report proposal included an unapproved next step")
        if len(set(proposal.snapshot_ids)) != len(proposal.snapshot_ids) or set(proposal.snapshot_ids) != set(snapshot_ids):
            return _review(db, run, "snapshot_reference_mismatch", "parent report snapshot references were not grounded")
        if len(set(proposal.evidence_ids)) != len(proposal.evidence_ids) or set(proposal.evidence_ids) != set(evidence_ids):
            return _review(db, run, "evidence_reference_mismatch", "parent report evidence references were not grounded")

        content = _report_content(
            student_id,
            expected_signal,
            proposal.next_step_codes,
            previous_period,
            current_period,
            previous,
            current,
            snapshot_ids,
            evidence_ids,
        )
        review_reason = {
            "code": "insufficient_history" if expected_signal == "insufficient_evidence" else "parent_report_requires_tutor_review",
            "message": "structured parent report draft persisted for tutor review",
        }
        artifact = complete_job_with_artifact(
            db,
            run,
            "parent_report_draft",
            content,
            review_reason=review_reason,
        )
        draft = _persist_draft(
            db,
            job,
            artifact,
            content,
            previous_period,
            current_period,
            snapshot_ids,
            evidence_ids,
        )
        db.commit()
        return {
            "status": "needs_tutor_review",
            "job_id": job.id,
            "artifact_id": artifact.id,
            "draft_id": draft.id,
            "progress_signal": expected_signal,
        }
    except Exception as exc:
        try:
            from backend.app.services.jobs import fail_run

            fail_run(db, run, {"code": "worker_error", "message": str(exc)}, retryable=True)
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "failed_retryable", "error": str(exc)}
