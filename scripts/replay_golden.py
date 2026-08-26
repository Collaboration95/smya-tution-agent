#!/usr/bin/env python3
"""Replay the S4 golden cases into independent, inspectable checkpoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.evaluation.replay import (  # noqa: E402
    CHECKPOINT_SCHEMA_VERSION,
    load_golden_cases,
    load_seeded_fallbacks,
    replay_all,
    replay_case,
    validate_golden_contract,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="case_ids", help="Replay one case id; repeat for multiple cases.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "demo" / "checkpoints")
    parser.add_argument("--fail-provider", action="store_true", help="Exercise the labelled seeded fallback path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_golden_cases()
    fallbacks = load_seeded_fallbacks()
    validate_golden_contract(cases, fallbacks)
    selected = cases
    if args.case_ids:
        requested = set(args.case_ids)
        selected = [case for case in cases if case["case_id"] in requested]
        missing = requested - {case["case_id"] for case in selected}
        if missing:
            raise SystemExit(f"unknown golden case(s): {', '.join(sorted(missing))}")
    checkpoints = (
        replay_all(selected, fail_provider=args.fail_provider, fallbacks=fallbacks)
        if len(selected) > 1
        else [replay_case(selected[0], fail_provider=args.fail_provider, fallbacks=fallbacks)]
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for checkpoint in checkpoints:
        path = args.output_dir / f"{checkpoint['checkpoint_id']}.json"
        path.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        fallback = " seeded-fallback" if checkpoint["fallback"]["used"] else ""
        display_path = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"wrote {display_path} [{checkpoint['workflow']}{fallback}]")
    manifest = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_ids": [checkpoint["checkpoint_id"] for checkpoint in checkpoints],
        "case_ids": [checkpoint["case_id"] for checkpoint in checkpoints],
        "provider_mode": "unavailable-with-seeded-fallback" if args.fail_provider else "fake",
        "disclaimer": (
            "Seeded fallback checkpoints are not live provider results."
            if args.fail_provider
            else "Fake-provider replay; no live provider claim."
        ),
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
