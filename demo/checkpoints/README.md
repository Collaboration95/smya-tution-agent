# S4 replay checkpoints

Each JSON file in this directory is an independently openable checkpoint with
a stable `checkpoint_id`, the golden input facts, expected controls, observed
state, and actual fake-provider/run provenance. Runtime job, run, artifact, and
timestamp fields are intentionally retained as evidence rather than presented
as stable fixture identifiers.

Regenerate the default fake-provider checkpoints from a clean seeded database:

```sh
python3 scripts/replay_golden.py
```

Exercise the provider/runtime fallback into a separate directory so the
committed fake-provider evidence is not overwritten:

```sh
python3 scripts/replay_golden.py --fail-provider --output-dir /tmp/smya-s4-fallback-checkpoints
```

Fallback checkpoints are labelled `seeded_fallback` and explicitly state that
they are not live provider results. No checkpoint contains raw prompts, hidden
reasoning, or real personal data.
