#!/usr/bin/env python3
"""Run the bounded S4-03 workload/cost benchmark and write raw evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.evaluation.benchmark import load_benchmark_inputs, run_benchmark  # noqa: E402


DEFAULT_OUTPUT = ROOT / "evaluation" / "metrics" / "raw" / "s4-03-benchmark-results.json"
DEFAULT_SUMMARY = ROOT / "evaluation" / "metrics" / "S4-03-benchmark.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, help="Override the repeat count in the raw benchmark fixture.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


def _number(value: float | None) -> str:
    return "not available" if value is None else f"{value:.6f}"


def render_summary(result: dict) -> str:
    lines = [
        "# S4-03 Workload and cost benchmark",
        "",
        f"Benchmark: `{result['benchmark_id']}`",
        f"Generated: `{result['generated_at']}`",
        f"Participant type: `{result['participant_type']}`",
        f"Data scope: `{result['data_scope']}`",
        "",
        "This is a scripted engineering proxy over the synthetic seeded centre. It is repeatability evidence, not a tutor study or validated tutor workload reduction, ROI claim, or market estimate.",
        "",
        "## Measured summary",
        "",
        "Times are seconds. Net time saved is calculated exactly as `manual baseline - total assisted`; negative values mean the assisted path took longer in this local run.",
        "",
        "| Task | Runs | Manual baseline mean | Assisted processing mean | Tutor review/edit mean | Total assisted mean | Net time saved mean | Model cost total |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in result["tasks"]:
        summary = item["summary"]
        lines.append(
            "| {name} | {repeats} | {manual} | {processing} | {review} | {total} | {saved} | {cost} |".format(
                name=summary["name"],
                repeats=summary["repeats"],
                manual=_number(summary["manual_baseline_seconds_mean"]),
                processing=_number(summary["assisted_processing_seconds_mean"]),
                review=_number(summary["tutor_review_edit_seconds_mean"]),
                total=_number(summary["total_assisted_seconds_mean"]),
                saved=_number(summary["net_time_saved_seconds_mean"]),
                cost=_number(summary["model_cost_usd_total"]),
            )
        )
    lines.extend(
        [
            "",
            "## Material changes recorded",
            "",
            "- Differentiated practice ends with five approved items per student, retains separate Student A/B selections, and does not create an assignment during the benchmark.",
            "- Parent progress produces a structured draft, records the improved signal from selected periods, exercises tutor approval, and does not deliver to a guardian.",
            "- The raw JSON records every run, both timing paths, material changes, provider/model/run IDs, model cost where available, and `null` infrastructure cost when it was not measured.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in result["limitations"])
    lines.extend(
        [
            "- In-memory SQLite and local process timing do not represent production latency, concurrency, hosting cost, or provider quotas.",
            "- A real tutor/centre participant and repeated manual wall-clock observations are still required before making a workload or ROI claim.",
            "",
            "## Reproduction",
            "",
            "```sh",
            "python3 scripts/run_benchmark.py",
            "python3 scripts/run_benchmark.py --repeats 1 --output /tmp/smya-s4-03-results.json --summary /tmp/smya-s4-03-summary.md",
            "```",
            "",
            "Raw evidence: `evaluation/metrics/raw/s4-03-benchmark-results.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    fixture = load_benchmark_inputs()
    result = run_benchmark(fixture, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.summary.write_text(render_summary(result), encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"wrote {args.summary}")
    for item in result["tasks"]:
        summary = item["summary"]
        print(
            f"{summary['task_id']}: manual={summary['manual_baseline_seconds_mean']:.6f}s "
            f"assisted={summary['total_assisted_seconds_mean']:.6f}s "
            f"net={summary['net_time_saved_seconds_mean']:.6f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
