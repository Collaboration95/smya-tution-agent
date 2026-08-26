# ADR-0003 — S3 parent-report draft contract

## Context

S3-01 needs a parent progress draft grounded in approved structured history.
The draft must remain tenant-scoped, auditable, and reviewable without opening a
path to raw student conversations, unrestricted model prose, or external
delivery.

## Decision

- A `parent_report` job carries a verified `{centre_id, student_id}` scope,
  one to five sub-skills, two non-overlapping timezone-aware periods, and the
  frozen mastery-policy reference.
- The worker can call only the typed `get_mastery_history` tool. The tool
  selects one deterministic `MasteryState` snapshot per requested sub-skill
  and period, filters to the approved mastery policy, and returns source
  `MasteryEvidence` identifiers without raw attempts or chat.
- Period comparison is derived in application code from snapshot history. A
  model receives only the structured comparison contract and returns a closed
  vocabulary of progress signals and next-step codes; it cannot change the
  selected snapshots, evidence, or deterministic signal.
- Trusted code renders bounded report language from those validated codes.
  `ParentReportDraft` and the generic `parent_report_draft` artifact persist
  the content, selected snapshot references, evidence references, and the
  `pending_tutor_review` status.
- Every successful draft remains in `needs_tutor_review` job state. Invalid or
  unavailable model output becomes the same reviewable job outcome without
  persisting provider prose. Guardian consent, tutor delivery approval, and
  external messaging remain S3-02 scope.

## Consequences

The prototype can demonstrate period comparison and privacy boundaries using
the fake provider. Future delivery work can add approval and consent gates
without changing the history or draft contract.
