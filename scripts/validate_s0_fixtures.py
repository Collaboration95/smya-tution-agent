#!/usr/bin/env python3
"""Validate and deterministically materialise the S0 fractions fixture set.

The validator intentionally relies only on the Python standard library so the
contract remains testable before application scaffolding or provider choices
exist. It implements the structural invariants required by the local JSON
schema and the S0-specific semantic and golden-outcome checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "fixtures" / "fractions_contract_v1.json"
POLICY_PATH = ROOT / "domain" / "mastery_policy" / "mastery_policy_v1.json"
SEED_PATH = ROOT / "fixtures" / "seed" / "synthetic_centre_v1.json"
SCHEMA_PATH = ROOT / "fixtures" / "schema" / "s0_fixture.schema.json"


class FixtureError(ValueError):
    """Raised when an S0 fixture is structurally or semantically invalid."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureError(f"{path.relative_to(ROOT)} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise FixtureError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def require(record: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(key for key in keys if key not in record)
    if missing:
        raise FixtureError(f"{context} is missing required fields: {', '.join(missing)}")


def as_index(records: list[dict[str, Any]], context: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        require(record, {"id"}, context)
        record_id = record["id"]
        if not isinstance(record_id, str) or not record_id:
            raise FixtureError(f"{context} has an empty or non-string id")
        if record_id in index:
            raise FixtureError(f"{context} contains duplicate id {record_id}")
        index[record_id] = record
    return index


def decimal(value: float | int) -> Decimal:
    return Decimal(str(value))


def round_half_up(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalise_answer(value: str) -> str:
    return "".join(value.lower().split())


def validate_structural_schema(
    contract: dict[str, Any], policy: dict[str, Any], seed: dict[str, Any]
) -> None:
    """Validate the documented, dependency-free subset of the JSON schema."""

    schema = load_json(SCHEMA_PATH)
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise FixtureError("fixture schema must declare JSON Schema draft 2020-12")

    require(contract, {"contract_id", "version", "scope", "sources", "subskills", "question_templates", "questions", "mastery_policy"}, "contract")
    require(policy, {"policy_id", "version", "scope", "evidence_eligibility", "calculation", "outcomes", "selection"}, "policy")
    require(seed, {"seed_id", "contract_id", "mastery_policy_id", "entities", "approved_question_ids", "attempts", "evidence", "denials", "escalations", "artifacts", "golden_expectations"}, "seed")

    question_fields = set(schema["$defs"]["question"]["required"])
    for question in contract["questions"]:
        require(question, question_fields, "question")
        if question["difficulty"] not in {"foundation", "core", "stretch"}:
            raise FixtureError(f"question {question['id']} has an invalid difficulty")
        if question["answer_type"] != "objective_exact" or question["status"] != "approved":
            raise FixtureError(f"question {question['id']} must be an approved objective-exact question")


def outcome_for(attempt_count: int, correct_count: int, policy: dict[str, Any]) -> dict[str, Any]:
    calculation = policy["calculation"]
    confidence = round_half_up(
        min(
            decimal(calculation["confidence_cap"]),
            decimal(calculation["confidence_base"])
            + decimal(calculation["confidence_per_attempt"]) * attempt_count,
        )
    )
    accuracy = round_half_up(decimal(correct_count) / attempt_count) if attempt_count else 0.0

    for outcome in policy["outcomes"]:
        maximum_attempts = outcome.get("maximum_attempts_exclusive")
        if maximum_attempts is not None:
            if attempt_count < maximum_attempts:
                return {"eligible_attempts": attempt_count, "correct_attempts": correct_count, "accuracy": accuracy, "confidence": confidence, "label": outcome["label"]}
            continue
        if attempt_count < outcome.get("minimum_attempts", 0):
            continue
        min_accuracy = decimal(outcome.get("minimum_accuracy", 0))
        max_accuracy = outcome.get("maximum_accuracy_exclusive")
        if decimal(accuracy) >= min_accuracy and (
            max_accuracy is None or decimal(accuracy) < decimal(max_accuracy)
        ):
            return {"eligible_attempts": attempt_count, "correct_attempts": correct_count, "accuracy": accuracy, "confidence": confidence, "label": outcome["label"]}
    raise FixtureError("policy outcomes do not cover a computed mastery state")


def validate(contract: dict[str, Any], policy: dict[str, Any], seed: dict[str, Any]) -> None:
    validate_structural_schema(contract, policy, seed)
    if not contract.get("synthetic_only"):
        raise FixtureError("contract must declare synthetic_only=true")
    if contract["contract_id"] != seed["contract_id"]:
        raise FixtureError("seed contract_id does not match contract")
    if policy["policy_id"] != seed["mastery_policy_id"]:
        raise FixtureError("seed mastery_policy_id does not match policy")
    if contract["mastery_policy"]["policy_id"] != policy["policy_id"]:
        raise FixtureError("contract mastery policy reference does not match policy")
    # The policy scope deliberately excludes the contract's display-only topic fields.
    for key in ("subject_id", "level_id"):
        if contract["scope"][key] != policy["scope"][key]:
            raise FixtureError(f"contract and policy disagree on {key}")

    source_index = as_index(contract["sources"], "sources")
    subskill_index = as_index(contract["subskills"], "subskills")
    template_index = as_index(contract["question_templates"], "question templates")
    question_index = as_index(contract["questions"], "questions")
    if len(subskill_index) not in range(3, 6):
        raise FixtureError("contract must contain three to five sub-skills")
    for source in source_index.values():
        if source.get("kind") != "synthetic_self_authored" or not source.get("approved"):
            raise FixtureError(f"source {source['id']} is not an approved synthetic source")
    for question in question_index.values():
        if question["source_id"] not in source_index:
            raise FixtureError(f"question {question['id']} has an unknown source")
        if question["subskill_id"] not in subskill_index:
            raise FixtureError(f"question {question['id']} has an unknown sub-skill")
        if question["template_id"] not in template_index:
            raise FixtureError(f"question {question['id']} has an unknown template")
        if template_index[question["template_id"]]["subskill_id"] != question["subskill_id"]:
            raise FixtureError(f"question {question['id']} does not match its template sub-skill")

    entities = seed["entities"]
    required_entity_sets = {"centres", "tutors", "students", "classes", "enrolments", "guardian_links", "curriculum_chunks"}
    missing_entity_sets = required_entity_sets - entities.keys()
    if missing_entity_sets:
        raise FixtureError(f"seed is missing entity sets: {', '.join(sorted(missing_entity_sets))}")
    entity_indexes = {name: as_index(entities[name], name) for name in required_entity_sets}
    all_entity_ids: set[str] = set()
    for name in required_entity_sets:
        for record_id, record in entity_indexes[name].items():
            if record_id in all_entity_ids:
                raise FixtureError(f"duplicate entity id across entity sets: {record_id}")
            all_entity_ids.add(record_id)
            if name in {"centres", "tutors", "students", "guardian_links"}:
                if not record.get("is_synthetic") or not str(record.get("display_name", "")).startswith("Synthetic "):
                    raise FixtureError(f"{name} record {record_id} must be clearly synthetic")

    centre_ids = set(entity_indexes["centres"])
    tutor_ids = set(entity_indexes["tutors"])
    student_ids = set(entity_indexes["students"])
    class_ids = set(entity_indexes["classes"])
    if any(record["centre_id"] not in centre_ids for record in entity_indexes["tutors"].values()):
        raise FixtureError("a tutor references an unknown centre")
    if any(record["centre_id"] not in centre_ids for record in entity_indexes["students"].values()):
        raise FixtureError("a student references an unknown centre")
    for record in entity_indexes["classes"].values():
        if record["centre_id"] not in centre_ids or record["tutor_id"] not in tutor_ids:
            raise FixtureError("a class has an unknown centre or tutor")
        if record["subject_id"] != contract["scope"]["subject_id"] or record["level_id"] != contract["scope"]["level_id"]:
            raise FixtureError("class scope does not match the frozen contract")
    for record in entity_indexes["enrolments"].values():
        if record["class_id"] not in class_ids or record["student_id"] not in student_ids:
            raise FixtureError("an enrolment has an unknown class or student")
    for record in entity_indexes["guardian_links"].values():
        if record["student_id"] not in student_ids:
            raise FixtureError("a guardian link has an unknown student")
    for chunk in entity_indexes["curriculum_chunks"].values():
        if chunk.get("source_id") not in source_index or chunk.get("approval_status") != "approved":
            raise FixtureError(f"curriculum chunk {chunk['id']} is not from an approved contract source")
        if chunk.get("subskill_id") not in subskill_index:
            raise FixtureError(f"curriculum chunk {chunk['id']} has an unknown sub-skill")

    approved_question_ids = seed["approved_question_ids"]
    if len(approved_question_ids) != len(set(approved_question_ids)):
        raise FixtureError("approved_question_ids contains duplicates")
    if set(approved_question_ids) != set(question_index):
        raise FixtureError("approved_question_ids must be exactly the contract question bank")

    attempt_index = as_index(seed["attempts"], "attempts")
    evidence_index = as_index(seed["evidence"], "evidence")
    for attempt in attempt_index.values():
        if attempt.get("student_id") not in student_ids or attempt.get("question_id") not in question_index:
            raise FixtureError(f"attempt {attempt['id']} has an unknown student or question")
        if attempt.get("grading_status") != "graded":
            raise FixtureError(f"attempt {attempt['id']} must be deterministically graded")
    evidence_attempt_ids = set()
    for evidence in evidence_index.values():
        attempt_id = evidence.get("attempt_id")
        if attempt_id not in attempt_index or not evidence.get("immutable"):
            raise FixtureError(f"evidence {evidence['id']} must reference an immutable, known attempt")
        if attempt_id in evidence_attempt_ids:
            raise FixtureError(f"attempt {attempt_id} has duplicate evidence")
        evidence_attempt_ids.add(attempt_id)
    if evidence_attempt_ids != set(attempt_index):
        raise FixtureError("every seeded attempt must have exactly one evidence record")

    denial_index = as_index(seed["denials"], "denials")
    escalation_index = as_index(seed["escalations"], "escalations")
    artifact_index = as_index(seed["artifacts"], "artifacts")
    if not any(item.get("outcome") == "authorisation_denied" for item in denial_index.values()):
        raise FixtureError("seed must contain an authorisation-denied fixture")
    if not any(item.get("outcome") == "unsupported_content" for item in escalation_index.values()):
        raise FixtureError("seed must contain an unsupported-content escalation")
    for artifact in artifact_index.values():
        if artifact.get("student_id") not in student_ids or artifact.get("subskill_id") not in subskill_index:
            raise FixtureError(f"artifact {artifact['id']} has an unknown student or sub-skill")
        if artifact["type"] == "practice_draft" and artifact["status"] != "draft_pending_tutor_approval":
            raise FixtureError("practice artifacts must not be auto-assigned")

    eligible: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    allowed_sources = set(policy["evidence_eligibility"]["required_source_ids"])
    for attempt_id in evidence_attempt_ids:
        attempt = attempt_index[attempt_id]
        question = question_index[attempt["question_id"]]
        if question["source_id"] in allowed_sources and question["status"] == "approved":
            eligible[(attempt["student_id"], question["subskill_id"])].append(attempt)

    computed: dict[tuple[str, str], dict[str, Any]] = {}
    for expectation in seed["golden_expectations"]["mastery"]:
        key = (expectation["student_id"], expectation["subskill_id"])
        attempts = eligible[key]
        correct = sum(
            normalise_answer(attempt["submitted_answer"])
            == normalise_answer(question_index[attempt["question_id"]]["expected_answer"])
            for attempt in attempts
        )
        actual = outcome_for(len(attempts), correct, policy)
        computed[key] = actual
        for field in ("eligible_attempts", "correct_attempts", "accuracy", "confidence", "label"):
            if actual[field] != expectation[field]:
                raise FixtureError(f"golden mastery mismatch for {key[0]}/{key[1]} field {field}: expected {expectation[field]!r}, got {actual[field]!r}")

    outcome_by_label = {outcome["label"]: outcome for outcome in policy["outcomes"]}
    attempted_question_ids_by_student: dict[str, set[str]] = defaultdict(set)
    for attempt in attempt_index.values():
        attempted_question_ids_by_student[attempt["student_id"]].add(attempt["question_id"])
    selected_question_ids: list[str] = []
    for expectation in seed["golden_expectations"]["practice_divergence"]:
        key = (expectation["student_id"], expectation["requested_subskill_id"])
        actual = computed.get(key)
        if actual is None:
            raise FixtureError(f"practice divergence lacks a mastery expectation for {key[0]}/{key[1]}")
        if actual["label"] != expectation["expected_label"]:
            raise FixtureError(f"practice divergence label mismatch for {key[0]}")
        difficulty = outcome_by_label[actual["label"]]["practice_difficulty"]
        if difficulty != expectation["expected_difficulty"]:
            raise FixtureError(f"practice divergence difficulty mismatch for {key[0]}")
        candidates = sorted(
            (
                question
                for question in question_index.values()
                if question["subskill_id"] == key[1]
                and question["difficulty"] == difficulty
                and question["id"] not in attempted_question_ids_by_student[key[0]]
            ),
            key=lambda question: (question["selection_rank"], question["id"]),
        )
        if not candidates or candidates[0]["id"] != expectation["expected_question_id"]:
            actual_question = candidates[0]["id"] if candidates else "none"
            raise FixtureError(f"practice selection mismatch for {key[0]}: expected {expectation['expected_question_id']}, got {actual_question}")
        if expectation["expected_artifact_id"] not in artifact_index:
            raise FixtureError(f"practice divergence references missing artifact {expectation['expected_artifact_id']}")
        selected_question_ids.append(candidates[0]["id"])
    if len(set(selected_question_ids)) != len(selected_question_ids):
        raise FixtureError("Student A/B practice divergence did not select different questions")

    expected_counts = seed["golden_expectations"]["expected_counts"]
    actual_counts = {
        "centres": len(entities["centres"]),
        "tutors": len(entities["tutors"]),
        "students": len(entities["students"]),
        "classes": len(entities["classes"]),
        "enrolments": len(entities["enrolments"]),
        "guardian_links": len(entities["guardian_links"]),
        "curriculum_chunks": len(entities["curriculum_chunks"]),
        "approved_questions": len(approved_question_ids),
        "attempts": len(attempt_index),
        "evidence": len(evidence_index),
        "denials": len(denial_index),
        "escalations": len(escalation_index),
        "artifacts": len(artifact_index),
    }
    if expected_counts != actual_counts:
        raise FixtureError(f"golden count mismatch: expected {expected_counts}, got {actual_counts}")

    workflow_paths = {path["path"] for path in seed["golden_expectations"]["workflow_paths"]}
    required_paths = {"normal", "insufficient_evidence", "denied_authorisation", "unsupported_content"}
    if workflow_paths != required_paths:
        raise FixtureError("golden workflow paths must cover normal, insufficient-evidence, denied-authorisation, and unsupported-content")


def materialise_seed(contract: dict[str, Any], policy: dict[str, Any], seed: dict[str, Any]) -> dict[str, Any]:
    """Return the stable seed document a storage adapter can ingest later."""

    return {
        "contract_id": contract["contract_id"],
        "contract_version": contract["version"],
        "mastery_policy_id": policy["policy_id"],
        "mastery_policy_version": policy["version"],
        "seed_id": seed["seed_id"],
        "entities": seed["entities"],
        "questions": contract["questions"],
        "attempts": seed["attempts"],
        "evidence": seed["evidence"],
        "denials": seed["denials"],
        "escalations": seed["escalations"],
        "artifacts": seed["artifacts"],
        "golden_expectations": seed["golden_expectations"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-seed", action="store_true", help="print the canonical materialised seed JSON")
    args = parser.parse_args()
    contract = load_json(CONTRACT_PATH)
    policy = load_json(POLICY_PATH)
    seed = load_json(SEED_PATH)
    try:
        validate(contract, policy, seed)
    except FixtureError as exc:
        print(f"S0 fixture validation failed: {exc}", file=sys.stderr)
        return 1
    if args.render_seed:
        print(json.dumps(materialise_seed(contract, policy, seed), indent=2, sort_keys=True))
    else:
        print("S0 fixture validation passed: contract, policy, seed, golden outcomes, and workflow paths are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
