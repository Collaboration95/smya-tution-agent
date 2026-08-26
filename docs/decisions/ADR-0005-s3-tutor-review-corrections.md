# ADR-0005 — S3 durable tutor corrections and escalation

- Status: accepted
- Date: 2026-08-26
- Owners: SMYA prototype team
- Related issues: S3-03 (#21), EPIC-S3 (#4)

## Context

The diagnostic worker can produce a low-evidence, conflicting, or unsupported
case. A tutor must be able to correct the proposal or exclude bad evidence
without erasing the original artifact or making an unsupported result look
approved. The decision must remain tenant-scoped, auditable, and deterministic
for the next mastery calculation.

## Decision

- Tutor corrections and evidence exclusions are append-only review records.
  Each record stores its author, reason, job/artifact context, and the state or
  evidence it supersedes. Tutor decisions link the corresponding correction,
  exclusion, or alert-resolution event.
- Excluding evidence creates a new deterministic mastery-state version. Editing
  a proposal creates a new versioned override while retaining the prior state
  and original proposal in history. Effective mastery continues to prefer the
  latest tutor override, and no correction changes the policy or model.
- Low-evidence, conflicting, and unsupported cases create `TutorAlert` rows.
  Alerts have an explicit open/resolved lifecycle and resolution reason. An
  alert resolution acknowledges the human review but does not authorize an
  answer, parent delivery, or any other external action.
- The diagnostic worker checks approved curriculum before model generation. If
  no approved curriculum exists, it records `unsupported_content`, creates a
  tutor alert, persists no artifact, and remains in `needs_tutor_review`.
- Tutor review APIs and trace responses are tenant- and assignment-scoped.
  The prototype exposes only synthetic data and does not send real messages or
  persist hidden model reasoning.

## Consequences

Migration `0009_s3_review_escalations` adds the durable links, alert lifecycle,
and evidence-exclusion table. Mastery recomputation remains a pure application
of the checked-in policy and can be verified with SQLite and PostgreSQL
migration tests. A future review workflow may add more resolution types, but
it must preserve the append-only history and explicit authorization gates.
