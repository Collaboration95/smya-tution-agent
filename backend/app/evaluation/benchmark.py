from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import statistics
import time
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agents.parent_report import run_parent_report
from backend.app.auth.context import CallerContext
from backend.app.communication.delivery import approve_parent_report
from backend.app.db.base import Base
from backend.app.db.models import AgentRun, AssessmentDraft, Artifact
from backend.app.evaluation.replay import parent_periods, prepare_parent_history
from backend.app.models.client import FakeModelClient
from backend.app.practice.service import (
    approve_draft,
    create_assessment_draft,
    create_assessment_draft_from_selection,
    edit_draft,
)
from backend.app.reports.service import create_parent_report_job
from backend.app.schemas.reports import ParentReportJobRequest, ReportPeriod
from backend.app.services.jobs import claim_job, get_job
from backend.app.services.mastery import load_policy
from backend.app.services.seed import seed_db
from backend.app.tools.contracts import GetMasteryHistoryRequest
from backend.app.tools.history import get_mastery_history


ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_INPUTS_PATH = ROOT / "evaluation" / "metrics" / "benchmark_inputs.json"
CENTRE_ID = "CTR-SYNTH-NORTHSTAR"
TUTOR_ID = "TUT-SYNTH-ALPHA"
CLASS_ID = "CLS-SYNTH-P5-FRACTIONS"


def load_benchmark_inputs(path: Path = BENCHMARK_INPUTS_PATH) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "benchmark_id", "participant_type", "repeats", "tasks", "cost_policy", "limitations"}
    if not isinstance(document, dict) or not required.issubset(document):
        raise ValueError("benchmark input fixture is incomplete")
    if document["participant_type"] != "scripted_engineering_proxy":
        raise ValueError("benchmark participant type must disclose the proxy limitation")
    if not isinstance(document["tasks"], list) or not document["tasks"]:
        raise ValueError("benchmark input fixture must contain tasks")
    task_ids: set[str] = set()
    for task in document["tasks"]:
        if not isinstance(task, dict) or "task_id" not in task or task["task_id"] in task_ids:
            raise ValueError("benchmark task ids must be unique")
        task_ids.add(task["task_id"])
    return document


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


def _seconds(start: float) -> float:
    return round(time.perf_counter() - start, 6)


def _tutor(task: dict[str, Any]) -> CallerContext:
    return CallerContext(user_id=TUTOR_ID, centre_id=task["centre_id"], role="tutor")


def _manual_practice(task: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    Session = _seeded_session()
    with Session() as db:
        tutor = _tutor(task)
        policy = load_policy()
        started = time.perf_counter()
        drafts: dict[str, dict[str, Any]] = {}
        for student_id in task["student_ids"]:
            draft = create_assessment_draft_from_selection(
                db,
                caller=tutor,
                student_id=student_id,
                subskill_id=task["subskill_id"],
                question_ids=task["manual_question_ids"][student_id],
                selection_policy_version="1.0.0",
                policy_version=policy["version"],
                class_id=CLASS_ID,
            )
            approve_draft(db, caller=tutor, draft_id=draft.id, reason="Manual baseline review")
            drafts[student_id] = {
                "question_ids": json.loads(draft.question_ids_json),
                "status": draft.status,
                "assignment_id": None,
            }
        elapsed = _seconds(started)
        db.commit()
        return elapsed, {"drafts": drafts, "provider": None, "model_cost_usd": None}


def _assisted_practice(task: dict[str, Any]) -> tuple[float, float, dict[str, Any]]:
    Session = _seeded_session()
    with Session() as db:
        tutor = _tutor(task)
        started_processing = time.perf_counter()
        drafts: dict[str, AssessmentDraft] = {}
        initial_selections: dict[str, list[str]] = {}
        for student_id in task["student_ids"]:
            draft = create_assessment_draft(
                db,
                caller=tutor,
                student_id=student_id,
                subskill_id=task["subskill_id"],
                item_count=task["assisted_initial_item_count"],
                class_id=CLASS_ID,
            )
            drafts[student_id] = draft
            initial_selections[student_id] = json.loads(draft.question_ids_json)
        processing_seconds = _seconds(started_processing)

        started_review = time.perf_counter()
        for student_id, draft in drafts.items():
            edit_draft(
                db,
                caller=tutor,
                draft_id=draft.id,
                question_ids=task["manual_question_ids"][student_id],
                reason="Tutor expanded the selected scaffold to five items.",
            )
            approve_draft(db, caller=tutor, draft_id=draft.id, reason="Reviewed five-item differentiated draft")
        review_edit_seconds = _seconds(started_review)
        db.commit()
        material = {
            "initial_selections": initial_selections,
            "final_drafts": {
                student_id: {
                    "question_ids": json.loads(draft.question_ids_json),
                    "status": draft.status,
                    "assignment_id": None,
                }
                for student_id, draft in drafts.items()
            },
            "students_diverge": initial_selections["STU-SYNTH-A"] != initial_selections["STU-SYNTH-B"],
        }
        return processing_seconds, review_edit_seconds, {
            "material_changes": material,
            "provider": None,
            "model_id": None,
            "run_ids": [],
            "model_cost_usd": None,
        }


def _parent_request(db: Session, task: dict[str, Any]) -> ParentReportJobRequest:
    periods = parent_periods(db)
    return ParentReportJobRequest(
        student_id=task["student_id"],
        subskill_ids=task["subskill_ids"],
        previous_period=ReportPeriod(**periods["previous_period"]),
        current_period=ReportPeriod(**periods["current_period"]),
    )


def _manual_parent_report(task: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    Session = _seeded_session()
    with Session() as db:
        prepare_parent_history(db)
        request = _parent_request(db, task)
        tutor = _tutor(task)
        started = time.perf_counter()
        history = get_mastery_history(
            db,
            tutor,
            GetMasteryHistoryRequest(
                student_id=request.student_id,
                subskill_ids=request.subskill_ids,
                previous_period_start=request.previous_period.start,
                previous_period_end=request.previous_period.end,
                current_period_start=request.current_period.start,
                current_period_end=request.current_period.end,
            ),
        )
        previous = history.previous_period[0]
        current = history.current_period[0]
        # This is the manual baseline proxy: a tutor-like structured summary
        # assembled from the selected history without a model or worker job.
        manual_content = {
            "student_id": request.student_id,
            "progress_signal": "improved",
            "previous_snapshot_id": previous.id,
            "current_snapshot_id": current.id,
            "next_step": "Continue focused practice on the core skill.",
        }
        elapsed = _seconds(started)
        return elapsed, {"content": manual_content, "provider": None, "model_cost_usd": None}


def _assisted_parent_report(task: dict[str, Any]) -> tuple[float, float, dict[str, Any]]:
    Session = _seeded_session()
    with Session() as db:
        prepare_parent_history(db)
        request = _parent_request(db, task)
        tutor = _tutor(task)
        started_processing = time.perf_counter()
        job = create_parent_report_job(db, tutor, request)
        db.commit()
        claimed = claim_job(db, f"benchmark-parent-{task['task_id']}", job_type="parent_report")
        if claimed is None:
            raise RuntimeError("parent report benchmark job could not be claimed")
        result = run_parent_report(db, get_job(db, job.id), FakeModelClient())
        processing_seconds = _seconds(started_processing)
        draft = db.query(Artifact).filter(Artifact.job_id == job.id).one()

        started_review = time.perf_counter()
        from backend.app.db.models import ParentReportDraft

        report_draft = db.query(ParentReportDraft).filter(ParentReportDraft.job_id == job.id).one()
        approve_parent_report(
            db,
            tutor,
            report_draft.id,
            "GRD-SYNTH-A-VERIFIED",
            reason="Reviewed the selected history and approved the synthetic draft.",
        )
        review_edit_seconds = _seconds(started_review)
        db.commit()
        latest_run = db.query(AgentRun).filter(AgentRun.job_id == job.id).order_by(AgentRun.attempt.desc()).first()
        return processing_seconds, review_edit_seconds, {
            "material_changes": {
                "progress_signal": json.loads(draft.payload_json)["progress_signal"],
                "draft_status_before_review": "pending_tutor_review",
                "draft_status_after_review": report_draft.status,
                "guardian_delivery": False,
                "artifact_id": draft.id,
                "draft_id": report_draft.id,
                "result_status": result["status"],
            },
            "provider": latest_run.provider if latest_run else None,
            "model_id": latest_run.model_id if latest_run else None,
            "run_ids": [latest_run.id] if latest_run else [],
            "model_cost_usd": latest_run.cost_usd if latest_run else None,
        }


def _run_task(task: dict[str, Any], run_index: int) -> dict[str, Any]:
    if task["workflow"] == "assessment":
        manual_seconds, manual_material = _manual_practice(task)
        processing_seconds, review_seconds, assisted = _assisted_practice(task)
    elif task["workflow"] == "parent_report":
        manual_seconds, manual_material = _manual_parent_report(task)
        processing_seconds, review_seconds, assisted = _assisted_parent_report(task)
    else:
        raise ValueError(f"unsupported benchmark workflow: {task['workflow']}")
    assisted_total = round(processing_seconds + review_seconds, 6)
    return {
        "run_index": run_index,
        "participant_type": "scripted_engineering_proxy",
        "manual_baseline_seconds": manual_seconds,
        "assisted_processing_seconds": processing_seconds,
        "tutor_review_edit_seconds": review_seconds,
        "total_assisted_seconds": assisted_total,
        "net_time_saved_seconds": round(manual_seconds - assisted_total, 6),
        "manual_material": manual_material,
        "assisted_material": assisted["material_changes"],
        "provider_provenance": {
            "provider": assisted["provider"],
            "model_id": assisted["model_id"],
            "run_ids": assisted["run_ids"],
        },
        "model_cost_usd": assisted["model_cost_usd"],
        "infrastructure_cost_usd": None,
    }


def _summary(task: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(key: str) -> float:
        return round(statistics.mean(run[key] for run in runs), 6)

    model_costs = [run["model_cost_usd"] for run in runs if run["model_cost_usd"] is not None]
    return {
        "task_id": task["task_id"],
        "name": task["name"],
        "repeats": len(runs),
        "participant_type": "scripted_engineering_proxy",
        "manual_baseline_seconds_mean": mean("manual_baseline_seconds"),
        "assisted_processing_seconds_mean": mean("assisted_processing_seconds"),
        "tutor_review_edit_seconds_mean": mean("tutor_review_edit_seconds"),
        "total_assisted_seconds_mean": mean("total_assisted_seconds"),
        "net_time_saved_seconds_mean": mean("net_time_saved_seconds"),
        "model_cost_usd_total": round(sum(model_costs), 6) if model_costs else None,
        "infrastructure_cost_usd": None,
        "limitations": [
            "This is a scripted engineering proxy, not a tutor timing study.",
            "Synthetic in-memory database timings do not represent production latency.",
            "Fake-provider cost is zero; live model and hosting costs are not measured.",
        ],
    }


def run_benchmark(
    fixture: dict[str, Any] | None = None,
    *,
    repeats: int | None = None,
) -> dict[str, Any]:
    fixture = fixture or load_benchmark_inputs()
    repeat_count = repeats if repeats is not None else fixture["repeats"]
    if repeat_count < 1:
        raise ValueError("benchmark repeats must be at least one")
    task_results = []
    for task in fixture["tasks"]:
        runs = [_run_task(task, run_index) for run_index in range(1, repeat_count + 1)]
        task_results.append({"task": task, "runs": runs, "summary": _summary(task, runs)})
    return {
        "schema_version": "s4_benchmark_results_v1",
        "benchmark_id": fixture["benchmark_id"],
        "generated_at": datetime.now().astimezone().isoformat(),
        "participant_type": fixture["participant_type"],
        "data_scope": fixture["data_scope"],
        "measurement_policy": fixture["measurement_policy"],
        "cost_policy": fixture["cost_policy"],
        "limitations": fixture["limitations"],
        "tasks": task_results,
    }
