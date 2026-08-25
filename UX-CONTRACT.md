# UX Contract

## Product context

- **Audience:** Synthetic students and tutors in a small tuition-centre prototype.
- **Primary jobs:** Complete assigned objective practice; review and approve evidence-backed practice drafts.
- **Target market(s):** Singapore tuition-centre workflow; no real personal data.
- **Active locales:** English; browser locale for dates and numbers.
- **Language/content register:** Plain, sentence-case action copy. No chat persona or hidden model reasoning.
- **Timezone/calendar policy:** Display browser-local dates for demo records; store timestamps server-side in UTC.
- **Accessibility target:** WCAG 2.2 AA.

## Business-context sources

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| Permission model | `backend/app/auth/permissions.py` | Server policy | 2026-08-25 |
| Data lifecycle | `backend/app/db/models.py`, `backend/app/services/jobs.py` | Domain/API implementation contract | 2026-08-25 |
| Practice and approval workflow | `context.md` §§6–8; Issues #16–#18 | Product context / issue contract | 2026-08-25 |
| Synthetic data and source approval | `docs/decisions/ADR-0001-synthetic-fractions-content.md` | ADR | 2026-08-25 |
| UI identity | `DESIGN.md` | Project design context | 2026-08-25 |

## Visual contract

- **Project `DESIGN.md`:** Root `DESIGN.md`.
- **Token ownership model:** Existing runtime CSS is canonical; `DESIGN.md` mirrors accepted semantic values.
- **Runtime source:** `frontend/app/globals.css`.
- **Mapping:** CSS custom properties → feature classes/Tailwind `var(...)` adapters → shared route components.
- **Token drift gate:** `npx -p @google/design.md designmd lint DESIGN.md` plus review of changed CSS variables.
- **Supported themes:** Light theme; forced-colors defers to the platform.
- **Design-context owner:** Repository maintainer reviews durable changes with the feature PR.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Table Selection | Not applicable to S2 student flow | — | — | — |
| Select/Listbox | Native select in existing tutor demo | `DESIGN.md` | native | keyboard/manual popup check |
| Date | Not applicable | — | — | — |
| Form | Route-owned labeled answer form; shared behavior rules below | this contract + API schemas | practice answer | unit + browser |
| Scrollbar | `frontend/app/globals.css` global baseline | `DESIGN.md` | stable gutter only | computed-style/manual |
| Toast | Inline status region for this prototype | this contract | success/warning/error | browser live-region check |
| CRUD | Assessment/practice service and route contracts | `backend/app/practice/service.py` | approve/assign/start/close | API integration tests |

## Component behavior

| Component | Default | Hover | Focus | Active | Disabled | Busy | Error |
|---|---|---|---|---|---|---|---|
| Button | labeled action | darkens slightly | visible coral ring | pressed scale-free | muted, no pointer | stable width + `aria-busy` | remains available with inline error |
| Input | labeled, empty or answer value | border accent | coral ring | n/a | read-only when session closed | submit button owns busy state | inline text + `aria-invalid` |
| Practice card | current question and source metadata | n/a | n/a | n/a | unavailable state | stable loading region | retry or return path |
| Status region | polite text | n/a | n/a | n/a | n/a | “Checking answer…” | persistent correction guidance |

## Dataset navigation

- **Admin tables:** Existing tutor job list is bounded by the API response; no new table is introduced here.
- **Exploratory lists:** Not applicable.
- **URL state:** Practice session identity is in the route; question position is server state, not a client-only query parameter.
- **Empty/no-results/error/loading:** Stable inline regions explain whether there is no assignment, the API is unavailable, or the session is complete; each applicable failure has a retry/back link.
- **Back/scroll restoration:** Browser Back returns to the assignment list; the practice page keeps natural document scroll.
- **Selection scope:** Not applicable.

## Flow ledger

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome | Source ref |
|---|---|---|---|---|---|---|---|
| Create draft | Tutor requests practice | Stable API status | Draft review response | “Draft ready for review” | Preserve request; show inline error | Draft heading | Issue #16 |
| Approve draft | Tutor selects Approve | Button busy; server-confirmed | Draft detail | “Draft approved” | Keep detail open with error | Status heading | Issue #17 |
| Assign draft | Tutor selects Assign | Button busy; server-confirmed | Assignment detail | “Practice assigned” | Keep draft detail open | Assignment status | Issue #17 |
| Start practice | Student selects Start practice | Stable loading region | `/student/practice/[assignmentId]` | “Practice started” | Retry or return to assignments | Question heading | Issue #18 |
| Check answer | Student submits answer | Button busy; input preserved | Same question/next question | Correct/try-again feedback | Inline server error + retry | Feedback or next question | Issue #18 |
| Cancel/back | Student selects Back to assignments | None | `/student` | None | Unsaved answer is not submitted | Back link | Issue #18 |

## Navigation and responsive behavior

- **Route document title:** `{Page} — SMYA Co-Tutor`; loading/error pages use honest titles.
- **Route error / 403:** Explain unavailable access without leaking other students; offer `/student` or `/` navigation.
- **Breadcrumb/tab policy:** A text back link is used for the short student flow; no tabs.
- **Responsive transformation:** Single-column question card; actions wrap at narrow widths; no hidden required fields.
- **Truncation/full-value access:** Question text, answers, and source labels wrap; IDs may use `break-all` in metadata blocks.
- **Focus restoration:** Submit returns focus to feedback/next question; permission/error state keeps the route chrome reachable.

## Overlays and feedback

- **Dialog primitive:** None for S2 student flow.
- **Destructive confirmation:** No destructive student action.
- **Toast:** Inline `role="status"`/`role="alert"` regions; critical copy is not toast-only.
- **Alert/banner:** API degradation and authorization errors remain persistent on the affected route.
- **Tooltip:** Not required; visible labels carry essential meaning.
- **Unsaved changes:** An unsubmitted answer is local transient state and is not silently persisted.
- **Layer contract:** Not applicable.

## Async and resilience

- **Mutation default:** Pessimistic for approval, assignment, answer submission, and session transitions.
- **Idempotency:** Assignment creation uses a stable draft idempotency key; answer submissions reject duplicate question responses.
- **Auto-save/draft recovery:** No autosave of answer text; preserve it after a failed submission in the mounted form.
- **Offline/read-stale/write:** Read failure offers retry; writes are not queued because the prototype has no conflict/storage contract.
- **Retry/backoff/timeout:** Bounded manual retry; no indefinite client retry loop.
- **Version conflict:** Server-owned session position prevents stale clients from overwriting a newer answer.
- **Session expiry:** 401/403 is shown as an access boundary with a route back to the student home.
- **Long-running progress:** Not expected; initial loads reserve a stable status region.
- **Stale requests:** `AbortController` cancels route-load requests on unmount or identity changes.
- **Mutation failure:** Keep input and route context; render an inline retryable status.

## Validation

- **Schema layer:** Pydantic request models and server-side domain validation.
- **Trigger timing:** Submit for answer validation; do not shout on initial typing.
- **Error policy:** Inline message associated with the answer field plus a route-level status for server failures.
- **Server mapping:** Preserve non-sensitive answer text and show a plain correction.
- **Sensitive values:** No secrets or personal data in the practice form.
- **Form rules:** `noValidate`, stable submit button, `aria-invalid`, `aria-describedby`, duplicate-submit prevention.

## Permission and clipboard

- **Permission UI:** Server returns 403; the route explains that the assignment is unavailable and links to the student home.
- **Clipboard:** Not used in S2.
- **Disabled explanation:** Disabled controls include visible reason text when the reason is not obvious.

## Verification

- **Static:** Ruff, `pytest`, frontend lint/build, Alembic upgrade, and `audit_project.py --mode strict`.
- **Browser:** Student A and Student B, success, wrong answer, hint, loading, error, narrow viewport, keyboard, and reduced-motion checks.
- **Accessibility:** Native semantics, labels, status announcements, focus-visible, 44px primary touch targets, no native dialogs.
- **Canonical sibling:** Existing tutor trace route and seeded API authorization tests.
- **Project audit:** Record the actual strict audit result in the feature handoff.
