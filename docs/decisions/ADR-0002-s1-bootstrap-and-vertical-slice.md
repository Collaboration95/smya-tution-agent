# ADR-0002: S1 bootstrap and first agentic vertical slice

- Status: accepted
- Date: 2026-08-25
- Owners: SMYA prototype team
- Related issues: S1-01, S1-02, S1-03, S1-04, S1-05, S1-06, EPIC-S1 (#2)

## Context

Epic S1 must deliver the earliest credible agentic slice: a durable learning event creates a bounded diagnostic job, produces an evidence-backed artifact, and pauses for tutor review. S0 has frozen the Primary 5 fractions contract, mastery policy, and synthetic centre seed. S1 must not add broad CRUD or distributed infrastructure, must keep deterministic scoring/permission logic outside the LLM, and must remain demonstrable with a fake model before any real provider is introduced.

S1-01 is the smallest runnable boundary that the five later issues can extend without rework. The decisions below lock the stack and boundaries for the remaining S1 work so that tenant scope, mastery state, job lifecycle, and tutor review can share one database and one model boundary.

## Decision

### S1-01 — Application boundary

- **Backend:** Python 3.11+, FastAPI + Pydantic v2, SQLAlchemy 2.0 (sync engine). `pydantic-settings` for env. No ORM async, no Celery/Kafka, no fine-tuning.
- **Frontend:** Next.js 14 App Router + TypeScript + Tailwind (minimal). Student view and tutor trace are channel-specific; business logic stays in the API.
- **Database:** PostgreSQL 16 is the source of truth. `docker-compose.yml` provides a local Postgres (with `pgvector` available but not required for S1). For zero-dependency local and CI runs, `DATABASE_URL` may point at SQLite (`sqlite:///./smya.db` or `sqlite+pysqlite:///:memory:`) — the code uses the same SQLAlchemy metadata. No Mongo/S3 in S1.
- **Migrations:** Alembic is the migration path (`backend/alembic/` + `alembic.ini`). For S1-01 the initial migration creates the empty schema; `Base.metadata.create_all` is also usable for ephemeral test databases. All later S1 tables are added via incremental Alembic revisions.
- **Configuration:** `.env.example` documents `DATABASE_URL`, `APP_ENV`, `MODEL_PROVIDER=fake`, `MODEL_ID=fake-diagnostic-v1`. No secrets are committed; provider keys stay out of source.
- **Health:** `GET /health` returns `{status, version, env, db}` and performs a `SELECT 1`. `GET /` returns service info. Both are unauthenticated.
- **Model boundary:** `ModelClient` is a small Python interface behind `backend/app/models/client.py`. `FakeModelClient` validates structured output against Pydantic schemas and never makes a network call. Only `FakeModelClient` is wired in S1; Groq/Bedrock adapters are deferred to S4 behind the same interface.
- **Seed:** `backend/scripts/seed.py` loads `fixtures/fractions_contract_v1.json` + `fixtures/seed/synthetic_centre_v1.json` into the database deterministically. It is idempotent and requires no secrets or network.
- **Tests / verification:** `pytest` is the command. `backend/tests/test_health.py` and `backend/tests/test_fake_model.py` are the S1-01 smoke tests. Frontend smoke is `npm run build`. Root `make`/`README` documents the three commands.

### S1-02 — Tenant-scoped learning records

- Every centre-owned row carries `centre_id` (and where appropriate `student_id`/`class_id`). All queries scope by centre; cross-centre reads are denied at the query layer, not in the prompt.
- Content and learning rows created by the synthetic loader are explicitly centre-scoped; only approved global curriculum/question rows may use a nullable centre scope.
- `attempts` and `attempt_answers` are immutable factual inputs. Updates are rejected at the service layer.
- `mastery_evidence` is append-only and stores `policy_id`, `policy_version`, `is_correct`, `evidence_id`. Derived state lives in `mastery_states` / `mastery_state_history` with `(student_id, subskill_id, version)` history; history enables period comparison in S3 without mutating past rows.
- Deterministic policy is `domain/mastery_policy/mastery_policy_v1.json`. `backend/app/services/mastery.py` implements the exact calculation from the fixture validator (accuracy, confidence = min(0.90, 0.20 + 0.15*n), rounding half-up, threshold labels). Policy thresholds and history have unit tests; no LLM touches these numbers.
- Tutor overrides (`tutor_corrections` / `tutor_observations`) are versioned and take precedence over the latest deterministic row for "effective" state, but the original deterministic row remains in history for audit.

### S1-03 — RBAC and tool trust boundaries

- `CallerContext` is derived server-side from the authenticated principal (seeded demo users in S1). No client-provided centre_id or role is trusted.
- Roles: `admin | tutor | student | guardian | worker`. Worker is the job runner's server-scoped principal.
- Typed tools: each tool has a Pydantic `Request`/`Response` and is invoked through `backend/app/tools/registry.py` with explicit allow-lists per job type. The registry checks `CallerContext` scope, `centre_id` ownership, approved-source filters, and approval state before any read/write. Tools never expose arbitrary SQL, shell, or messaging.
- Approval gate: assessment jobs require an explicit `approval_status=approved` (or equivalent `status=approved`) input. Draft or missing approval is rejected at the service/API boundary; the diagnostic allow-list has no assessment-draft write tool.
- Approved-source filtering: `retrieve_approved_curriculum` and `find_question_candidates` filter by `source_id ∈ {approved}` and `approval_status=approved` plus `centre_id`. Prompt-injection style inputs cannot bypass this — verified by denial tests.
- Audit: every tool invocation and every approval/reject writes an `audit_events` row with actor, event, entity, timestamp, before/after.

### S1-04 — Job and model lifecycle

- `agent_jobs` states: `queued | claimed | running | succeeded | needs_tutor_review | failed_retryable | failed_terminal | cancelled`. Transitions are enforced atomically with optimistic claim (`claimed_by`, `claimed_at`, `heartbeat_at`).
- `agent_runs` is per-attempt trace; `tool_calls` stores bounded summaries. Idempotency keys are stable hashes of `(type, input)`. Artifact reconciliation ensures crash-retry does not duplicate artifacts.
- `FakeModelClient` validates structured output; invalid JSON becomes `failed_retryable` once (one conservative repair attempt) then `needs_tutor_review` / `failed_terminal`. No token/cost is invented; fake runs record zero cost but still record `provider/model/duration`.
- Stale claimed/running jobs close any active run with a timeout outcome before requeue/terminal transition. `backend/scripts/worker.py` is the single bounded table-polled worker entry point; AgentCore is deferred to S4.

### S1-05 — Diagnostic worker

- Trigger is a completed attempt batch (or manual request) that creates/deduplicates a `diagnostic` job.
- The worker reads bounded evidence (eligible attempts for the student/subskill), loads sub-skill definitions, optionally retrieves approved curriculum, calls `ModelClient` through the typed tool boundary, validates `MasteryProposal` (label/confidence must match deterministic state/policy_version), persists the proposal version with evidence IDs, and creates a `tutor_alert` for low/conflicting evidence.
- The S1 diagnostic bound is the four explicitly named data tools (`get_student_snapshot`, `get_attempt_evidence`, `get_mastery_state`, `retrieve_approved_curriculum`) plus one model call, with at most one repair call. The issue discussion's separate “≤3 tool calls” phrase is inconsistent with that explicit list and should be clarified before changing the implementation.
- Low-evidence (`eligible < 3`) and conflicting evidence produce `needs_tutor_review` rather than an invented answer. Retry does not duplicate the proposal.

### S1-06 — Tutor trace

- `GET /api/tutor/jobs/{id}` + `GET /api/tutor/jobs` return the scoped trace: job ID, trigger, type, input snapshot, state, run attempts, provider/model, duration/cost, tool summaries, artifact/evidence/source refs, validation result, stop reason, retry provenance, and actions (`accept | edit | reject | more_evidence`). Decisions are persisted in `tutor_decisions` as well as audit events; edit creates a versioned tutor correction and override state. Raw chain-of-thought and out-of-scope student data are never exposed.

## Alternatives considered

- **Per-service databases or S3 as primary store:** rejected — Postgres is the single source of truth for workflow; S3 is deferred to S2/S3 artifacts.
- **Async SQLAlchemy / separate worker queue:** rejected for S1 — sync engine and table-polled jobs are simpler and sufficient for the bounded demo.
- **LangGraph/CrewAI orchestration in S1:** rejected — plain Python state transitions with explicit budgets are more auditable and do not require a new framework until S2.
- **SQLite-only:** rejected — Postgres is needed for realistic multi-user tenure and `pgvector` later; SQLite remains only a lightweight fallback.

## Consequences

- All S1 issues share one database, one `CallerContext`, one `ModelClient` interface, and one job table. Later epics can extend without re-platforming.
- Deterministic logic and permission checks are testable without any model call; fake-model tests cover the agent contract.
- The seeded demo runs with `DATABASE_URL=sqlite:///./smya.db` or Postgres, `MODEL_PROVIDER=fake`, and no secrets — satisfying S1-01's "without secrets" requirement.
- The `unsupported_content` and `authorisation_denied` seeded fixtures remain the canonical escalation/denial proofs; no prompt can bypass them.
- Before any real provider or external curriculum is introduced (S4), S0-02 must explicitly approve the replacement of `SRC-SYNTH-FRACTIONS-V1` per ADR-0001.
