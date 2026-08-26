from __future__ import annotations

import json
from pathlib import Path

from backend.app.evaluation.benchmark import load_benchmark_inputs, run_benchmark


ROOT = Path(__file__).resolve().parents[2]


def test_benchmark_fixture_discloses_proxy_participant_and_cost_boundaries():
    fixture = load_benchmark_inputs()

    assert fixture["participant_type"] == "scripted_engineering_proxy"
    assert fixture["repeats"] == 3
    assert {task["workflow"] for task in fixture["tasks"]} == {"assessment", "parent_report"}
    assert fixture["cost_policy"]["fake_model_cost_usd"] == 0.0
    assert fixture["cost_policy"]["infrastructure_cost_usd"] is None
    assert any("not a tutor" in limitation.lower() for limitation in fixture["limitations"])


def test_benchmark_records_raw_timings_material_changes_and_exact_savings():
    result = run_benchmark(repeats=1)

    assert result["schema_version"] == "s4_benchmark_results_v1"
    assert len(result["tasks"]) == 2
    for task_result in result["tasks"]:
        run = task_result["runs"][0]
        assert run["participant_type"] == "scripted_engineering_proxy"
        assert run["manual_baseline_seconds"] >= 0
        assert run["assisted_processing_seconds"] >= 0
        assert run["tutor_review_edit_seconds"] >= 0
        assert run["total_assisted_seconds"] == round(
            run["assisted_processing_seconds"] + run["tutor_review_edit_seconds"],
            6,
        )
        assert run["net_time_saved_seconds"] == round(
            run["manual_baseline_seconds"] - run["total_assisted_seconds"],
            6,
        )
        assert run["infrastructure_cost_usd"] is None

    practice = next(item for item in result["tasks"] if item["task"]["workflow"] == "assessment")
    final_drafts = practice["runs"][0]["assisted_material"]["final_drafts"]
    assert all(len(draft["question_ids"]) == 5 for draft in final_drafts.values())
    assert all(draft["assignment_id"] is None for draft in final_drafts.values())
    assert practice["runs"][0]["assisted_material"]["students_diverge"] is True
    assert practice["runs"][0]["model_cost_usd"] is None

    parent = next(item for item in result["tasks"] if item["task"]["workflow"] == "parent_report")
    parent_run = parent["runs"][0]
    assert parent_run["provider_provenance"]["provider"] == "fake"
    assert parent_run["model_cost_usd"] == 0.0
    assert parent_run["assisted_material"]["progress_signal"] == "improved"
    assert parent_run["assisted_material"]["guardian_delivery"] is False


def test_committed_benchmark_evidence_has_three_raw_runs_and_limitations():
    raw_path = ROOT / "evaluation" / "metrics" / "raw" / "s4-03-benchmark-results.json"
    summary_path = ROOT / "evaluation" / "metrics" / "S4-03-benchmark.md"
    result = json.loads(raw_path.read_text(encoding="utf-8"))
    summary = summary_path.read_text(encoding="utf-8")

    assert all(len(task["runs"]) == 3 for task in result["tasks"])
    assert result["participant_type"] == "scripted_engineering_proxy"
    assert "not a tutor study" in summary
    assert "validated tutor workload reduction" in summary
    assert "infrastructure_cost_usd" in json.dumps(result)
