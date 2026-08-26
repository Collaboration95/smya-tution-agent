# S4-03 evaluation metrics

This directory records the bounded workload/cost benchmark for the synthetic
prototype. The raw fixture identifies the participant type, repeat count,
timing scope, manual-baseline method, cost policy, and limitations.

Run the benchmark with:

```sh
python3 scripts/run_benchmark.py
```

The command writes raw per-run evidence to
`evaluation/metrics/raw/s4-03-benchmark-results.json` and the readable summary
to `evaluation/metrics/S4-03-benchmark.md`. Use `--output` and `--summary` to
write a temporary run without replacing the committed evidence.

The current participant is a scripted engineering proxy. The manual baseline
is the typed human-selection service path, not measured human wall-clock time;
therefore net time saved is a local arithmetic result and must not be reported
as validated tutor workload reduction or ROI. Fake model cost is recorded as
zero, and infrastructure cost remains explicitly unavailable.
