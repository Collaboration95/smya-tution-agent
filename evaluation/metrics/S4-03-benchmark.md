# S4-03 Workload and cost benchmark

Benchmark: `S4-03-SCRIPTED-PROXY-V1`
Generated: `2026-08-26T13:17:16.983288+08:00`
Participant type: `scripted_engineering_proxy`
Data scope: `synthetic seeded centre only`

This is a scripted engineering proxy over the synthetic seeded centre. It is repeatability evidence, not a tutor study or validated tutor workload reduction, ROI claim, or market estimate.

## Measured summary

Times are seconds. Net time saved is calculated exactly as `manual baseline - total assisted`; negative values mean the assisted path took longer in this local run.

| Task | Runs | Manual baseline mean | Assisted processing mean | Tutor review/edit mean | Total assisted mean | Net time saved mean | Model cost total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Create five-item differentiated practice for Students A and B | 3 | 0.013260 | 0.008830 | 0.010926 | 0.019756 | -0.006496 | not available |
| Draft a parent progress update from selected history | 3 | 0.004247 | 0.023593 | 0.003820 | 0.027414 | -0.023167 | 0.000000 |

## Material changes recorded

- Differentiated practice ends with five approved items per student, retains separate Student A/B selections, and does not create an assignment during the benchmark.
- Parent progress produces a structured draft, records the improved signal from selected periods, exercises tutor approval, and does not deliver to a guardian.
- The raw JSON records every run, both timing paths, material changes, provider/model/run IDs, model cost where available, and `null` infrastructure cost when it was not measured.

## Limitations

- The participant is a scripted engineering proxy, not a tutor or centre operator.
- Manual baseline timing measures the typed-selection service path, not human wall-clock work.
- The fake provider reports zero model cost; no live provider or hosting cost is measured.
- Results are synthetic repeatability evidence, not validated tutor outcomes, ROI, or market pricing.
- In-memory SQLite and local process timing do not represent production latency, concurrency, hosting cost, or provider quotas.
- A real tutor/centre participant and repeated manual wall-clock observations are still required before making a workload or ROI claim.

## Reproduction

```sh
python3 scripts/run_benchmark.py
python3 scripts/run_benchmark.py --repeats 1 --output /tmp/smya-s4-03-results.json --summary /tmp/smya-s4-03-summary.md
```

Raw evidence: `evaluation/metrics/raw/s4-03-benchmark-results.json`.
