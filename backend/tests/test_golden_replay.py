from __future__ import annotations

import json
from pathlib import Path

from backend.app.evaluation.replay import (
    CHECKPOINT_SCHEMA_VERSION,
    FALLBACKS_PATH,
    CASES_PATH,
    load_golden_cases,
    load_seeded_fallbacks,
    replay_all,
    validate_golden_contract,
)


ROOT = Path(__file__).resolve().parents[2]


def test_golden_contract_has_independent_cases_for_every_required_state():
    cases = load_golden_cases()
    fallbacks = load_seeded_fallbacks()
    validate_golden_contract(cases, fallbacks)

    assert len(cases) == 7
    assert {case["workflow"] for case in cases} == {
        "assessment",
        "correction",
        "denial",
        "diagnostic",
        "parent_report",
    }
    assert len({case["checkpoint_id"] for case in cases}) == len(cases)
    assert CASES_PATH.exists()
    assert FALLBACKS_PATH.exists()


def test_default_replay_produces_actual_provenance_and_safe_outcomes():
    checkpoints = replay_all()

    assert len(checkpoints) == 7
    assert all(item["schema_version"] == CHECKPOINT_SCHEMA_VERSION for item in checkpoints)
    assert all(item["provenance"]["actual_runtime"] is True for item in checkpoints)
    assert all("prompt" not in json.dumps(item).lower() for item in checkpoints)

    by_case = {item["case_id"]: item for item in checkpoints}
    assert by_case["S4-GOLDEN-DENIED-GUARDIAN-B-REPORT"]["observed"]["outcome"] == "authorisation_denied"
    assert by_case["S4-GOLDEN-UNSUPPORTED-DECIMALS"]["observed"]["model_call_made"] is False
    assert by_case["S4-GOLDEN-DIVERGENCE-A-B-ASSESSMENT"]["observed"]["assignment_created"] is False
    assert by_case["S4-GOLDEN-TUTOR-CORRECTION-A-ADD"]["observed"]["override"] is True
    assert by_case["S4-GOLDEN-PARENT-PERIOD-A-ADD"]["observed"]["progress_signal"] == "improved"


def test_provider_failure_uses_only_explicitly_labelled_seeded_fallbacks():
    checkpoints = replay_all(fail_provider=True)
    fallback_cases = [item for item in checkpoints if item["fallback"]["used"]]

    assert {item["workflow"] for item in fallback_cases} == {"diagnostic", "correction", "parent_report"}
    assert all(item["fallback"]["label"] == "seeded_fallback" for item in fallback_cases)
    assert all(item["fallback"]["disclaimer"] == "Seeded fallback; not a live provider result." for item in fallback_cases)
    assert all(item["provenance"]["provider"] == "unavailable" for item in fallback_cases)
    assert all(item["provenance"]["attempts"] for item in fallback_cases)

    deterministic_cases = [item for item in checkpoints if not item["fallback"]["used"]]
    assert {item["workflow"] for item in deterministic_cases} == {"assessment", "denial", "diagnostic"}
    unsupported = next(item for item in deterministic_cases if item["case_id"] == "S4-GOLDEN-UNSUPPORTED-DECIMALS")
    assert unsupported["observed"]["model_call_made"] is False


def test_committed_checkpoints_are_independently_openable():
    cases = load_golden_cases()
    for case in cases:
        path = ROOT / "demo" / "checkpoints" / f"{case['checkpoint_id']}.json"
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        assert checkpoint["schema_version"] == CHECKPOINT_SCHEMA_VERSION
        assert checkpoint["checkpoint_id"] == case["checkpoint_id"]
        assert checkpoint["case_id"] == case["case_id"]
        assert checkpoint["inputs"] == case["input_facts"]
        assert checkpoint["provenance"]["actual_runtime"] is True
        serialized = json.dumps(checkpoint).lower()
        assert "raw provider output" not in serialized
        assert "hidden reasoning" not in serialized
