# ADR-0001: Use self-authored synthetic fractions content until S0-02 closes

- Status: accepted for the prototype fixture boundary
- Date: 2026-08-24
- Owners: SMYA prototype team
- Related issues: S0-02, S0-03, S0-04

## Context

S0-03 needs a frozen curriculum and question-source contract. S0-02, which
will confirm the hackathon's external-provider, licence, and submission rules,
is deliberately deferred. The fixture and seed work must therefore be usable
without copying, ingesting, or relying on any external educational content.

## Decision

For the S0-03/S0-04 prototype boundary, the sole approved corpus is
`SRC-SYNTH-FRACTIONS-V1`: short, self-authored Mathematics prompts and answers
stored in this repository. It is synthetic test content, not a claim of
curriculum alignment, an external provider integration, or licensed classroom
material. The exact records are frozen in
`fixtures/fractions_contract_v1.json`.

No network retrieval, external question provider, model-generated question, or
third-party curriculum text may enter the seed or golden tests. Any content
outside the source ID is rejected and produces the deterministic
`unsupported_content` escalation fixture.

## Consequences

- S0-03 and S0-04 can proceed reproducibly with no external licence decision.
- The demo may describe the material only as synthetic, self-authored fixture
  content; it must not state it is MOE-, centre-, or provider-approved.
- S0-02 remains a release gate. Before real-model integration, deployment,
  final submission, or introducing external content, the team must replace or
  explicitly approve this source policy after S0-02 resolves the relevant
  licence, provider, data, and submission constraints.
