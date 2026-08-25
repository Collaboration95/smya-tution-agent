from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.app.db.models import AgentJob, AgentRun, Artifact, TutorAlert
from backend.app.services.jobs import start_run, record_tool_call, complete_job_with_artifact, fail_run, mark_needs_review
from backend.app.services.mastery import get_eligible_attempts, compute_mastery, load_policy
from backend.app.db.models import MasteryEvidence, MasteryState, Student, Question, Attempt
from backend.app.tools.registry import get_student_snapshot, get_attempt_evidence, get_mastery_state
from backend.app.tools.contracts import GetStudentSnapshotRequest, GetAttemptEvidenceRequest, GetMasteryStateRequest, RetrieveCurriculumRequest
from backend.app.tools.curriculum import retrieve_approved_curriculum
from backend.app.models.client import ModelClient, FakeModelClient
from backend.app.schemas.proposal import MasteryProposal
from backend.app.auth.context import CallerContext

def _worker_context(student_id: str, subskill_id: str) -> CallerContext:
    # Worker acts as server principal; use centre derived from student
    # This will be resolved via DB in actual run_diagnostic; placeholder
    return CallerContext(user_id="worker-diagnostic", centre_id="CTR-SYNTH-NORTHSTAR", role="worker")

def run_diagnostic(db: Session, job: AgentJob, model_client: ModelClient) -> dict:
    """
    Bounded diagnostic run. Returns result dict with artifact or error.
    Uses typed tools, validates structured output against deterministic state, and is idempotent.
    """
    payload = json.loads(job.input_json)
    student_id = payload.get("student_id")
    subskill_id = payload.get("subskill_id")
    if not student_id or not subskill_id:
        raise ValueError("job input must contain student_id and subskill_id")

    # Derive worker caller context from student's centre
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise ValueError(f"unknown student {student_id}")
    caller = CallerContext(user_id="worker-diagnostic", centre_id=student.centre_id, role="worker", student_id=None)

    run = start_run(db, job, model_client.provider, model_client.model_id)
    tool_summaries = []

    try:
        # 1) get_student_snapshot
        ss_req = GetStudentSnapshotRequest(student_id=student_id)
        ss_resp = get_student_snapshot(db, caller, ss_req)
        record_tool_call(db, run, "get_student_snapshot", ss_req.model_dump(), ss_resp.model_dump())
        tool_summaries.append("get_student_snapshot")

        # 2) get_attempt_evidence (bounded)
        ev_req = GetAttemptEvidenceRequest(student_id=student_id, subskill_id=subskill_id)
        ev_resp = get_attempt_evidence(db, caller, ev_req)
        record_tool_call(db, run, "get_attempt_evidence", ev_req.model_dump(), ev_resp.model_dump())
        tool_summaries.append("get_attempt_evidence")

        # 3) get_mastery_state (deterministic)
        ms_req = GetMasteryStateRequest(student_id=student_id, subskill_id=subskill_id)
        # May not exist if no state yet — compute from evidence
        from backend.app.db.models import MasteryState
        ms = db.query(MasteryState).filter(MasteryState.student_id == student_id, MasteryState.subskill_id == subskill_id).order_by(MasteryState.version.desc()).first()
        if not ms:
            # Compute and persist if missing (should have been created by seed, but handle)
            from backend.app.services.mastery import upsert_mastery_state
            ms = upsert_mastery_state(db, student_id, subskill_id)
            db.flush()
        # Also call tool for audit
        try:
            ms_resp = get_mastery_state(db, caller, ms_req)
            record_tool_call(db, run, "get_mastery_state", ms_req.model_dump(), ms_resp.model_dump())
            tool_summaries.append("get_mastery_state")
            deterministic_label = ms_resp.label
            deterministic_confidence = ms_resp.confidence
            evidence_ids = ev_resp.evidence_ids
            policy_version = ms_resp.policy_version
            policy_id = ms_resp.policy_id
        except Exception:
            # Fallback to computed
            eligible, correct, _ = get_eligible_attempts(db, student_id, subskill_id)
            computed = compute_mastery(eligible, correct)
            deterministic_label = computed["label"]
            deterministic_confidence = computed["confidence"]
            evidence_ids = ev_resp.evidence_ids
            policy_version = computed["policy_version"]
            policy_id = computed["policy_id"]

        # 4) retrieve_approved_curriculum (optional grounding)
        try:
            cur_req = RetrieveCurriculumRequest(query=f"{subskill_id} fractions", subskill_id=subskill_id)
            cur_resp = retrieve_approved_curriculum(db, caller, cur_req)
            record_tool_call(db, run, "retrieve_approved_curriculum", cur_req.model_dump(), {"count": len(cur_resp.chunks)})
            tool_summaries.append("retrieve_approved_curriculum")
            source_refs = [c["id"] for c in cur_resp.chunks[:2]]
        except Exception:
            source_refs = []

        # Build prompt for model — include deterministic facts, instruct to not change label/confidence
        eligible = ms.eligible_attempts if ms else ev_resp.eligible_attempts
        correct = ms.correct_attempts if ms else ev_resp.correct_attempts
        accuracy = ms.accuracy if ms else (round(correct/eligible,2) if eligible else 0.0)

        prompt = (
            f"Diagnostic proposal for student {student_id} subskill {subskill_id}. "
            f"Evidence IDs: {evidence_ids}. Deterministic state: label={deterministic_label} confidence={deterministic_confidence} "
            f"accuracy={accuracy} eligible={eligible} correct={correct} policy_version={policy_version}. "
            f"Explain rationale referencing evidence and policy, provide alternative explanation if needed, and recommend next action. "
            f"Do NOT change label or confidence. Return JSON matching MasteryProposal schema."
        )

        # 5) Model call with one conservative repair attempt
        out = model_client.generate_structured(prompt, MasteryProposal)
        parsed = out.parsed
        # Record model invocation as tool-like for trace
        record_tool_call(db, run, "model.generate_structured", {"prompt": prompt[:500], "schema": "MasteryProposal"}, {"raw": out.raw[:500], "parsed": parsed})
        tool_summaries.append("model.generate_structured")

        # If invalid, try one repair
        if parsed is None:
            repair_prompt = prompt + " Your previous output was invalid JSON or failed schema validation. Return ONLY valid JSON matching the schema with correct label and confidence."
            out2 = model_client.generate_structured(repair_prompt, MasteryProposal)
            record_tool_call(db, run, "model.generate_structured(repair)", {"prompt": repair_prompt[:500]}, {"raw": out2.raw[:500], "parsed": out2.parsed})
            parsed = out2.parsed
            out = out2
            if parsed is None:
                # Still invalid -> mark needs review / failed_terminal
                mark_needs_review(db, run, {"code": "invalid_model_output", "message": "model output failed validation after repair", "raw": out.raw[:1000]})
                db.commit()
                return {"status": "needs_tutor_review", "reason": "invalid_model_output"}

        # Validate that model did not change deterministic label/confidence
        if parsed.get("label") != deterministic_label or abs(parsed.get("confidence", -1) - deterministic_confidence) > 0.001:
            # Reject — model changed calculated values
            record_tool_call(db, run, "validation.reject", parsed, {"expected_label": deterministic_label, "expected_confidence": deterministic_confidence})
            mark_needs_review(db, run, {"code": "label_confidence_mismatch", "message": f"model changed deterministic values: got {parsed.get('label')}/{parsed.get('confidence')} expected {deterministic_label}/{deterministic_confidence}", "parsed": parsed})
            db.commit()
            return {"status": "needs_tutor_review", "reason": "label_confidence_mismatch"}

        # Validate evidence_ids and policy_version match
        if set(parsed.get("evidence_ids", [])) != set(evidence_ids) or parsed.get("policy_version") != policy_version or parsed.get("policy_id") != policy_id:
            mark_needs_review(db, run, {"code": "evidence_policy_mismatch", "message": "evidence or policy version mismatch"})
            db.commit()
            return {"status": "needs_tutor_review", "reason": "evidence_policy_mismatch"}

        # Handle low evidence / conflicting evidence -> needs review but still persist proposal with appropriate status
        if deterministic_label == "insufficient_evidence":
            # Create tutor alert
            alert = TutorAlert(id=f"alert-{uuid.uuid4().hex[:8]}", centre_id=caller.centre_id, student_id=student_id, subskill_id=subskill_id, job_id=job.id, type="low_evidence", message=f"Insufficient evidence for {subskill_id}: {eligible} attempts. Collect more evidence.", created_at=datetime.now(timezone.utc))
            db.add(alert)
            # Still persist proposal as needs_tutor_review? But spec says low evidence produces reviewable action
            # We will complete with artifact but job will be marked needs_tutor_review if status indicates need more evidence
            # If proposal status is not pending_tutor_review, still allow but we mark job accordingly
            if parsed.get("status") not in ("pending_tutor_review", "needs_more_evidence", "needs_tutor_review"):
                parsed["status"] = "needs_tutor_review"

        # Persist artifact
        artifact_payload = {
            "student_id": student_id,
            "subskill_id": subskill_id,
            "label": deterministic_label,
            "confidence": deterministic_confidence,
            "evidence_ids": evidence_ids,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "rationale": parsed.get("reason", ""),
            "alternative_explanation": parsed.get("alternative_explanation"),
            "recommended_next_action": parsed.get("recommended_next_action"),
            "source_refs": source_refs,
            "status": parsed.get("status", "pending_tutor_review"),
        }
        art = complete_job_with_artifact(db, run, "mastery_proposal", artifact_payload)
        # Update run tool summary
        run.tool_calls_json = json.dumps(tool_summaries)
        # If low evidence, mark job as needs_tutor_review even though artifact persisted
        if deterministic_label == "insufficient_evidence":
            # Keep artifact but job status becomes needs_tutor_review for tutor action
            job = db.query(AgentJob).filter(AgentJob.id == job.id).first()
            job.status = "needs_tutor_review"
            job.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "succeeded" if deterministic_label != "insufficient_evidence" else "needs_tutor_review", "artifact_id": art.id, "proposal": artifact_payload}

    except Exception as e:
        # Unexpected error -> retryable
        try:
            fail_run(db, run, {"code": "worker_error", "message": str(e)}, retryable=True)
            db.commit()
        except Exception:
            pass
        return {"status": "failed_retryable", "error": str(e)}
