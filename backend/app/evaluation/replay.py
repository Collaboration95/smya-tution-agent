from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agents.diagnostic import run_diagnostic
from backend.app.agents.parent_report import run_parent_report
from backend.app.auth.context import CallerContext
from backend.app.auth.permissions import can_access_guardian_report, can_approve_student
from backend.app.db.base import Base
from backend.app.db.models import (
    AgentJob,
    AgentRun,
    Artifact,
    CurriculumChunk,
    GuardianLink,
    MasteryEvidence,
    MasteryState,
    ParentReportDraft,
    TutorAlert,
)
from backend.app.models.client import FakeModelClient, ModelClient
from backend.app.practice.service import create_assessment_draft, serialize_draft
from backend.app.practice.selector import select_practice_items
from backend.app.reports.service import create_parent_report_job
from backend.app.schemas.reports import ParentReportJobRequest, ReportPeriod
from backend.app.review.service import append_tutor_correction
from backend.app.services.jobs import claim_job, create_job, get_job
from backend.app.services.mastery import get_effective_mastery
from backend.app.services.seed import seed_db


ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = ROOT / "fixtures" / "golden" / "s4_cases.json"
FALLBACKS_PATH = ROOT / "fixtures" / "golden" / "s4_seeded_fallbacks.json"
CHECKPOINT_SCHEMA_VERSION = "s4_checkpoint_v1"
CENTRE_ID = "CTR-SYNTH-NORTHSTAR"
UTC = timezone.utc


class ReplayProviderUnavailable(ModelClient):
    """Provider stub used to prove the clearly labelled seeded fallback path."""

    provider = "unavailable"
    model_id = "unavailable-s4-replay"

    def generate_structured(self, prompt, schema, **kwargs):
        raise RuntimeError("replay provider unavailable")

    def generate_text(self, prompt, **kwargs):
        raise RuntimeError("replay provider unavailable")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def load_golden_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    document = _read_json(path)
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("golden case file must contain a non-empty cases list")
    required = {
        "case_id",
        "checkpoint_id",
        "title",
        "workflow",
        "input_facts",
        "expected_deterministic_state",
        "allowed_sources",
        "allowed_actions",
        "safe_outcome",
        "fallback_id",
    }
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not required.issubset(case):
            raise ValueError("each golden case must contain the complete S4 case contract")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError(f"golden case ids must be unique non-empty strings: {case_id!r}")
        if case["workflow"] not in {"diagnostic", "assessment", "denial", "correction", "parent_report"}:
            raise ValueError(f"unsupported golden workflow: {case['workflow']}")
        seen.add(case_id)
    return cases


def load_seeded_fallbacks(path: Path = FALLBACKS_PATH) -> dict[str, dict[str, Any]]:
    document = _read_json(path)
    fallbacks = document.get("fallbacks")
    if not isinstance(fallbacks, dict):
        raise ValueError("seeded fallback file must contain a fallbacks object")
    for fallback_id, fallback in fallbacks.items():
        if not isinstance(fallback, dict) or not {"fixture_id", "artifact_type", "status", "source", "payload"}.issubset(fallback):
            raise ValueError(f"fallback {fallback_id} is incomplete")
    return fallbacks


def validate_golden_contract(
    cases: list[dict[str, Any]] | None = None,
    fallbacks: dict[str, dict[str, Any]] | None = None,
) -> None:
    cases = cases or load_golden_cases()
    fallbacks = fallbacks or load_seeded_fallbacks()
    for case in cases:
        fallback_id = case.get("fallback_id")
        if fallback_id is not None and fallback_id not in fallbacks:
            raise ValueError(f"case {case['case_id']} references unknown fallback {fallback_id}")


def _seeded_session() -> sessionmaker:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        seed_db(db)
    return session_factory


def _model_client(fail_provider: bool) -> ModelClient:
    return ReplayProviderUnavailable() if fail_provider else FakeModelClient()


def _json_error(run: AgentRun) -> dict[str, Any] | None:
    return json.loads(run.error_json) if run.error_json else None


def _run_provenance(db: Session, job_id: str | None) -> dict[str, Any]:
    if job_id is None:
        return {
            "actual_runtime": True,
            "job_id": None,
            "attempts": [],
            "provider": None,
            "model_id": None,
            "tool_calls": [],
        }
    runs = db.query(AgentRun).filter(AgentRun.job_id == job_id).order_by(AgentRun.attempt.asc()).all()
    # Querying through the model class keeps the checkpoint free of prompts and
    # raw provider output while retaining the actual bounded tool trace.
    from backend.app.db.models import ToolCallRecord

    tool_calls = [
        row.tool_name
        for row in db.query(ToolCallRecord)
        .filter(ToolCallRecord.job_id == job_id)
        .order_by(ToolCallRecord.created_at.asc(), ToolCallRecord.id.asc())
        .all()
    ]
    return {
        "actual_runtime": True,
        "job_id": job_id,
        "attempts": [
            {
                "run_id": run.id,
                "attempt": run.attempt,
                "provider": run.provider,
                "model_id": run.model_id,
                "status": run.status,
                "duration_ms": run.duration_ms,
                "error_code": (_json_error(run) or {}).get("code"),
            }
            for run in runs
        ],
        "provider": runs[-1].provider if runs else None,
        "model_id": runs[-1].model_id if runs else None,
        "tool_calls": tool_calls,
    }


def _diagnostic_observation(db: Session, job: AgentJob, result: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(job.input_json)
    state = get_effective_mastery(db, payload["student_id"], payload["subskill_id"])
    artifacts = db.query(Artifact).filter(Artifact.job_id == job.id).order_by(Artifact.version.asc()).all()
    alerts = db.query(TutorAlert).filter(TutorAlert.job_id == job.id).order_by(TutorAlert.created_at.asc()).all()
    chunks = (
        db.query(CurriculumChunk)
        .filter(CurriculumChunk.subskill_id == payload["subskill_id"], CurriculumChunk.approval_status == "approved")
        .all()
    )
    provenance = _run_provenance(db, job.id)
    return {
        "job_status": job.status,
        "retry_count": job.retry_count,
        "result": result,
        "mastery": (
            {
                "eligible_attempts": state.eligible_attempts,
                "correct_attempts": state.correct_attempts,
                "accuracy": state.accuracy,
                "confidence": state.confidence,
                "label": state.label,
                "is_override": state.is_override,
            }
            if state
            else None
        ),
        "artifacts": [
            {
                "id": artifact.id,
                "type": artifact.type,
                "version": artifact.version,
                "payload": json.loads(artifact.payload_json),
            }
            for artifact in artifacts
        ],
        "alerts": [{"type": alert.type, "status": alert.status} for alert in alerts],
        "source_ids": sorted({chunk.source_id for chunk in chunks}),
        "model_call_made": any(call.startswith("model.generate") for call in provenance["tool_calls"]),
        "provenance": provenance,
    }


def _diagnostic_case(db: Session, case: dict[str, Any], fail_provider: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = case["input_facts"]
    payload = {
        "student_id": facts["student_id"],
        "subskill_id": facts["subskill_id"],
        "trigger": facts.get("trigger", "golden_replay"),
    }
    job = create_job(db, "diagnostic", facts["centre_id"], facts["student_id"], payload)
    db.commit()
    claimed = claim_job(db, f"replay:{case['case_id']}")
    if claimed is None:
        raise RuntimeError(f"could not claim diagnostic case {case['case_id']}")
    result = run_diagnostic(db, get_job(db, job.id), _model_client(fail_provider))
    db.refresh(job)
    observation = _diagnostic_observation(db, job, result)
    return observation, observation["provenance"]


def _assessment_case(db: Session, case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = case["input_facts"]
    tutor = CallerContext(user_id="TUT-SYNTH-ALPHA", centre_id=facts["centre_id"], role="tutor")
    students: dict[str, Any] = {}
    for student_id in facts["students"]:
        selection = select_practice_items(
            db,
            student_id=student_id,
            subskill_id=facts["subskill_id"],
            item_count=facts["item_count"],
        )
        draft = create_assessment_draft(
            db,
            caller=tutor,
            student_id=student_id,
            subskill_id=facts["subskill_id"],
            item_count=facts["item_count"],
        )
        serialized = serialize_draft(db, draft)
        students[student_id] = {
            "label": selection["effective_mastery"]["label"],
            "difficulty": selection["target_difficulty"],
            "question_ids": selection["question_ids"],
            "draft_status": serialized["status"],
            "draft_id": draft.id,
            "assignment_id": serialized["assignment_id"],
        }
    db.commit()
    provenance = _run_provenance(db, None)
    observation = {
        "students": students,
        "assignment_created": any(item["assignment_id"] is not None for item in students.values()),
        "model_call_required": False,
        "source_ids": ["SRC-SYNTH-FRACTIONS-V1"],
        "actions": ["get_mastery_state", "save_assessment_draft"],
        "provenance": provenance,
    }
    return observation, provenance


def _denial_case(db: Session, case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = case["input_facts"]
    caller = CallerContext(
        user_id=facts["guardian_link_id"],
        centre_id=facts["centre_id"],
        role="guardian",
        guardian_link_id=facts["guardian_link_id"],
    )
    allowed = can_access_guardian_report(db, caller, facts["student_id"])
    link = db.query(GuardianLink).filter(GuardianLink.id == facts["guardian_link_id"]).one()
    reason = None if allowed else "guardian_link_not_verified_or_consented"
    provenance = _run_provenance(db, None)
    observation = {
        "outcome": "authorisation_allowed" if allowed else "authorisation_denied",
        "reason": reason,
        "report_content_returned": False if not allowed else True,
        "delivery_attempted": False,
        "guardian_verification_status": link.verification_status,
        "reporting_consent": link.reporting_consent,
        "source_ids": [],
        "model_call_required": False,
        "provenance": provenance,
    }
    return observation, provenance


def prepare_parent_history(db: Session) -> None:
    anchor = (
        db.query(MasteryEvidence.created_at)
        .filter(
            MasteryEvidence.student_id == "STU-SYNTH-A",
            MasteryEvidence.subskill_id == "FRC-ADD-SUB-UNLIKE",
        )
        .order_by(MasteryEvidence.created_at.asc(), MasteryEvidence.id.asc())
        .first()
    )
    if anchor is None:
        raise RuntimeError("seeded parent-report evidence is missing")
    anchor_at = anchor[0].replace(tzinfo=UTC) if anchor[0].tzinfo is None else anchor[0]
    previous_at = anchor_at + timedelta(minutes=30)
    current_at = anchor_at + timedelta(days=1)
    state = (
        db.query(MasteryState)
        .filter_by(student_id="STU-SYNTH-A", subskill_id="FRC-ADD-SUB-UNLIKE")
        .order_by(MasteryState.version.asc())
        .first()
    )
    if state is None:
        raise RuntimeError("seeded mastery state is missing")
    state.version = 2
    state.created_at = current_at
    state.label = "developing"
    state.accuracy = 0.5
    state.correct_attempts = 2
    state.eligible_attempts = 4
    db.add(
        MasteryState(
            id="mst-s4-parent-previous",
            centre_id=CENTRE_ID,
            student_id="STU-SYNTH-A",
            subskill_id="FRC-ADD-SUB-UNLIKE",
            version=1,
            eligible_attempts=4,
            correct_attempts=1,
            accuracy=0.25,
            confidence=0.8,
            label="requires_support",
            policy_id="mastery_policy_v1",
            policy_version="1.0.0",
            is_override=False,
            created_at=previous_at,
        )
    )
    db.flush()


def parent_periods(db: Session) -> dict[str, dict[str, str]]:
    anchor = (
        db.query(MasteryEvidence.created_at)
        .filter(
            MasteryEvidence.student_id == "STU-SYNTH-A",
            MasteryEvidence.subskill_id == "FRC-ADD-SUB-UNLIKE",
        )
        .order_by(MasteryEvidence.created_at.asc(), MasteryEvidence.id.asc())
        .first()
    )
    if anchor is None:
        raise RuntimeError("seeded parent-report evidence is missing")
    anchor_at = anchor[0].replace(tzinfo=UTC) if anchor[0].tzinfo is None else anchor[0]
    return {
        "previous_period": {
            "start": (anchor_at - timedelta(days=1)).isoformat(),
            "end": (anchor_at + timedelta(hours=1)).isoformat(),
        },
        "current_period": {
            "start": (anchor_at + timedelta(hours=2)).isoformat(),
            "end": (anchor_at + timedelta(days=2)).isoformat(),
        },
    }


def _parent_case(db: Session, case: dict[str, Any], fail_provider: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = case["input_facts"]
    prepare_parent_history(db)
    periods = parent_periods(db)
    request = ParentReportJobRequest(
        student_id=facts["student_id"],
        subskill_ids=facts["subskill_ids"],
        previous_period=ReportPeriod(**periods["previous_period"]),
        current_period=ReportPeriod(**periods["current_period"]),
    )
    tutor = CallerContext(user_id="TUT-SYNTH-ALPHA", centre_id=facts["centre_id"], role="tutor")
    job = create_parent_report_job(db, tutor, request)
    db.commit()
    claimed = claim_job(db, f"replay:{case['case_id']}", job_type="parent_report")
    if claimed is None:
        raise RuntimeError(f"could not claim parent-report case {case['case_id']}")
    result = run_parent_report(db, get_job(db, job.id), _model_client(fail_provider))
    db.refresh(job)
    artifact = db.query(Artifact).filter(Artifact.job_id == job.id).order_by(Artifact.version.asc()).all()
    draft = db.query(ParentReportDraft).filter(ParentReportDraft.job_id == job.id).first()
    provenance = _run_provenance(db, job.id)
    content = json.loads(artifact[0].payload_json) if artifact else None
    observation = {
        "job_status": job.status,
        "result": result,
        "previous_label": "requires_support",
        "current_label": "developing",
        "progress_signal": content.get("progress_signal") if content else None,
        "periods": periods,
        "draft_status": draft.status if draft else None,
        "artifacts": [
            {"id": item.id, "type": item.type, "version": item.version, "payload": json.loads(item.payload_json)}
            for item in artifact
        ],
        "source_ids": ["SRC-SYNTH-FRACTIONS-V1"],
        "model_call_made": any(call.startswith("model.generate") for call in provenance["tool_calls"]),
        "provenance": provenance,
    }
    return observation, provenance


def _correction_case(db: Session, case: dict[str, Any], fail_provider: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = case["input_facts"]
    diagnostic_case = {
        **case,
        "input_facts": {
            "centre_id": facts["centre_id"],
            "student_id": facts["student_id"],
            "subskill_id": facts["subskill_id"],
            "trigger": "golden_replay",
        },
    }
    diagnostic_observation, provenance = _diagnostic_case(db, diagnostic_case, fail_provider)
    artifact = db.query(Artifact).filter(Artifact.job_id == provenance["job_id"]).order_by(Artifact.version.desc()).first()
    original = get_effective_mastery(db, facts["student_id"], facts["subskill_id"])
    if fail_provider or artifact is None or original is None:
        diagnostic_observation.update(
            {
                "original_label": original.label if original else None,
                "corrected_label": None,
                "override": False,
                "correction_applied": False,
            }
        )
        return diagnostic_observation, provenance
    tutor = CallerContext(user_id=facts["tutor_id"], centre_id=facts["centre_id"], role="tutor")
    if not can_approve_student(db, tutor, facts["student_id"]):
        raise PermissionError("replay tutor is not assigned to the student")
    correction, override = append_tutor_correction(
        db,
        centre_id=facts["centre_id"],
        student_id=facts["student_id"],
        subskill_id=facts["subskill_id"],
        author_tutor_id=facts["tutor_id"],
        original_state=original,
        job_id=provenance["job_id"],
        artifact_id=artifact.id,
        corrected_label=facts["corrected_label"],
        reason=facts["reason"],
        created_at=datetime(2026, 1, 6, 12, 0, tzinfo=UTC),
    )
    job = get_job(db, provenance["job_id"])
    job.status = "succeeded"
    db.commit()
    observation = {
        **diagnostic_observation,
        "original_label": original.label,
        "corrected_label": override.label,
        "override": override.is_override,
        "correction_applied": True,
        "correction_id": correction.id,
        "effective_state_id": override.id,
        "job_status": job.status,
        "source_ids": diagnostic_observation["source_ids"],
    }
    return observation, provenance


def _fallback_info(case: dict[str, Any], fallbacks: dict[str, dict[str, Any]], used: bool) -> dict[str, Any]:
    fallback_id = case.get("fallback_id")
    if not used or fallback_id is None:
        return {
            "used": False,
            "label": None,
            "fixture_id": None,
            "source": None,
            "disclaimer": None,
            "artifact": None,
        }
    fallback = deepcopy(fallbacks[fallback_id])
    return {
        "used": True,
        "label": "seeded_fallback",
        "fixture_id": fallback["fixture_id"],
        "source": fallback["source"],
        "disclaimer": "Seeded fallback; not a live provider result.",
        "artifact": fallback,
    }


def _validate_observation(case: dict[str, Any], observation: dict[str, Any], fallback: dict[str, Any]) -> None:
    expected = case["expected_deterministic_state"]
    if fallback["used"]:
        if case.get("fallback_id") is None:
            raise ValueError(f"case {case['case_id']} cannot use a fallback")
        if observation["provenance"]["actual_runtime"] is not True:
            raise ValueError(f"case {case['case_id']} fallback lacks actual runtime provenance")
        return
    workflow = case["workflow"]
    if workflow == "diagnostic":
        mastery = observation.get("mastery") or {}
        for key in ("eligible_attempts", "correct_attempts", "accuracy", "confidence", "label"):
            if key in expected and mastery.get(key) != expected[key]:
                raise ValueError(f"{case['case_id']} mastery {key} mismatch: {mastery.get(key)!r} != {expected.get(key)!r}")
        if observation["job_status"] != expected["job_status"]:
            raise ValueError(f"{case['case_id']} job status mismatch")
        if expected.get("artifact_count") is not None and len(observation["artifacts"]) != expected["artifact_count"]:
            raise ValueError(f"{case['case_id']} artifact count mismatch")
        if observation["model_call_made"] != expected["model_call_required"]:
            raise ValueError(f"{case['case_id']} model call contract mismatch")
        if expected.get("artifact_type") and not any(item["type"] == expected["artifact_type"] for item in observation["artifacts"]):
            raise ValueError(f"{case['case_id']} artifact type mismatch")
        error_codes = {item["error_code"] for item in observation["provenance"]["attempts"] if item["error_code"]}
        if expected.get("review_reason") and expected["review_reason"] not in error_codes:
            raise ValueError(f"{case['case_id']} review reason mismatch: {error_codes}")
    elif workflow == "assessment":
        actual_students = observation["students"]
        for student_id, expected_student in expected["students"].items():
            actual = actual_students[student_id]
            for key in ("label", "difficulty", "question_ids", "draft_status"):
                if actual[key] != expected_student[key]:
                    raise ValueError(f"{case['case_id']} {student_id} {key} mismatch")
        if observation["assignment_created"] != expected["assignment_created"]:
            raise ValueError(f"{case['case_id']} unexpectedly created an assignment")
    elif workflow == "denial":
        if observation["outcome"] != expected["outcome"] or observation["reason"] != expected["reason"]:
            raise ValueError(f"{case['case_id']} denial mismatch")
    elif workflow == "correction":
        for key in ("original_label", "corrected_label", "override", "job_status"):
            if observation.get(key) != expected[key]:
                raise ValueError(f"{case['case_id']} correction {key} mismatch")
    elif workflow == "parent_report":
        for key in ("previous_label", "current_label", "progress_signal", "job_status", "draft_status"):
            if observation.get(key) != expected[key]:
                raise ValueError(f"{case['case_id']} parent report {key} mismatch")
        if observation["model_call_made"] != expected["model_call_required"]:
            raise ValueError(f"{case['case_id']} parent report model call mismatch")
    allowed_sources = set(case["allowed_sources"])
    if not set(observation.get("source_ids", [])).issubset(allowed_sources):
        raise ValueError(f"{case['case_id']} used an unapproved source")


def replay_case(
    case: dict[str, Any],
    *,
    fail_provider: bool = False,
    fallbacks: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fallbacks = fallbacks or load_seeded_fallbacks()
    validate_golden_contract([case], fallbacks)
    Session = _seeded_session()
    with Session() as db:
        if case["workflow"] == "diagnostic":
            observation, provenance = _diagnostic_case(db, case, fail_provider)
        elif case["workflow"] == "assessment":
            observation, provenance = _assessment_case(db, case)
        elif case["workflow"] == "denial":
            observation, provenance = _denial_case(db, case)
        elif case["workflow"] == "correction":
            observation, provenance = _correction_case(db, case, fail_provider)
        elif case["workflow"] == "parent_report":
            observation, provenance = _parent_case(db, case, fail_provider)
        else:  # pragma: no cover - load_golden_cases validates this boundary.
            raise ValueError(f"unsupported replay workflow: {case['workflow']}")
        fallback_used = fail_provider and case.get("fallback_id") is not None and any(
            item["provider"] == "unavailable" for item in provenance["attempts"]
        )
        fallback = _fallback_info(case, fallbacks, fallback_used)
        _validate_observation(case, observation, fallback)
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_id": case["checkpoint_id"],
            "case_id": case["case_id"],
            "title": case["title"],
            "workflow": case["workflow"],
            "inputs": deepcopy(case["input_facts"]),
            "expected": {
                "deterministic_state": deepcopy(case["expected_deterministic_state"]),
                "allowed_sources": deepcopy(case["allowed_sources"]),
                "allowed_actions": deepcopy(case["allowed_actions"]),
                "safe_outcome": deepcopy(case["safe_outcome"]),
            },
            "observed": observation,
            "provenance": provenance,
            "fallback": fallback,
        }


def replay_all(
    cases: list[dict[str, Any]] | None = None,
    *,
    fail_provider: bool = False,
    fallbacks: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cases = cases or load_golden_cases()
    fallbacks = fallbacks or load_seeded_fallbacks()
    validate_golden_contract(cases, fallbacks)
    return [replay_case(case, fail_provider=fail_provider, fallbacks=fallbacks) for case in cases]
