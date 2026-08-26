# ADR-0004 — S3 consent-gated parent-report delivery

## Context

S3-01 produces a bounded parent-report draft from approved mastery history. A
draft must not become an external communication merely because a worker or
tutor requested it. Recipient identity, reporting consent, and human approval
are separate gates and must remain durable, inspectable, and tenant-scoped.

## Decision

- `ParentReportDraft` owns the workflow state:
  `pending_tutor_review → approved → queued_for_delivery → delivered`.
  Rejected and blocked states are durable outcomes for that attempt; a blocked
  draft may be reviewed again after its recipient or consent issue is corrected.
- Approval is available only to an administrator or the tutor assigned to the
  student. The selected `GuardianLink` must belong to the same centre and
  student, be `verified`, and have `reporting_consent=true`.
- Queueing revalidates the guardian link and consent. It is only allowed from
  `approved`, and it creates one `ParentReportDelivery` record containing an
  immutable approved-content snapshot and a stable idempotency key.
- Sending revalidates the guardian link and consent again. The only delivery
  implementation in the prototype is `SimulatedDeliveryAdapter`; it produces a
  deterministic provider message ID and never contacts Telegram, email, or a
  real messaging provider.
- Delivery status transitions, actor identity, recipient identity, content
  hashes, and provider identifiers are written to `AuditEvent`. Raw model
  prompts, hidden reasoning, and provider credentials are not persisted.
- The generic diagnostic tutor-decision endpoint cannot operate on a
  `parent_report` job. Report approval, rejection, queueing, and delivery use
  the dedicated communication service and API routes.

## Consequences

The prototype can demonstrate both denial and successful-delivery paths without
creating an external side effect. A future channel adapter must preserve the
same service gate and idempotency contract; adding credentials or autonomous
sending is a separate decision.
