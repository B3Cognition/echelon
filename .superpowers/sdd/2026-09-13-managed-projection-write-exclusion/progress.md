# SDD ledger — plan: docs/superpowers/plans/2026-09-13-managed-projection-write-exclusion.md

Spec: docs/superpowers/specs/2026-09-12-durable-element-identities-design.md, approved and fully read. Existing isolated delivery-controller-contract worktree only. No merge, global installation, stopped smoke or live activation. Retain workspace through final whole-branch review and exhaustive chronological rulings.

Task 1: ready for dispatch; prior managed-spec-memory-exclusion complete after595-test code cover and29-test strengthened module, two review test findings addressed with fresh clean scoped re-review. Prior checkpointd73739ae. No implementation BASE yet. Root owns this plan, brief and ledger.

## Preflight

| Task/interface pair | Producer versus consumer | Finding |
| --- | --- | --- |
| Task 1 self-consistency | Six production modules plus documentation/new tests versus eight exact covering modules | All seven existing test paths verified, eighth intentionally new. Existing tests unchanged; no schema, serializer or output-key changes. |
| Task 1 global query / existing spec query | Any retained managed row or indexed registration operation versus aggregate workspace outputs | Canonical enumeration would miss managed run-local specs. Constant bounded presence queries do not decode ownership/history or scan all operations. Existing scoped query stays unchanged. |
| Task 1 guard helper / existing entry order | Explicit no-selector workspace wrapper versus existing spec/run public calls | Private unused no-spec/no-run branch can select global query; preserve exact metadata/presence/claim/open ordering for old callers. No fabricated identifiers or new epoch. |
| Task 1 workspace helper / direct outputs and refresh | WorkspaceGraphError translator versus native CLI catches and per-domain outcomes | Direct writers guard before output effects; refresh must guard before RE, outside outcome handlers. No mutation permitted before global refusal, no partial-success conversion. |
| Task 1 spec CLI / prior memory helper | Selected/physical identities versus graph commit and memory report owners | Reuse bounded prior helper; preserve pure computations and native error handling before the gate. Unrelated legacy spec writes remain permitted despite other managed specs. |
| Task 1 serializer boundary / approved source publication | Rootless low-level byte writers versus actual rootful command/aggregate owners | No fabricated root or API signature migration. These helpers are not authenticated publication and the task does not claim arbitrary-file access confinement. |
| Task 1 design / remaining integration | Negative output exclusion versus positive managed graph/runtime | Read diagnostics remain available; standalone RE is not globally blocked. Positive source/projection/runtime ownership still required, no live integration claim. |

Ruling: 44 — Add explicit any-retained-managed-workspace negative admission for rootful aggregate graph writers and pre-upstream aggregate refresh, while protecting selected-spec CLI graph/report output owners and retaining rootless serializers as nonauthoritative trusted-caller primitives. — Aggregate refresh can mutate RE before reaching guarded spec leaves and can continue graph writes after per-domain failures; canonical enumeration misses managed run-local specs. Inferring an orchestration root from arbitrary output ancestors or globally blocking unrelated spec/RE operations would introduce unsupported ownership policy. — If wrong, revise these inactive query/guard/owner placements and native compatibility tests or integrate an authenticated managed projection owner; no IDs, revisions, graph keys, schemas, journal receipts, accepted sources or live deployment need rewriting.

Task 1: selected design decision is not implemented or reviewed. Root used the writing-plans contract; no follow-up approval requested because automatic phased execution is already authorized. Wait for prior task completion before committing an implementation BASE and dispatching one fresh implementer.

Task 1: placeholder scan found no matches; previous phase is now complete. Root preflight confirms prior private spec-memory helper retains its planned signature. Commit exact plan/brief/ledger before recording BASE and dispatching one fresh implementer. No global query or projection production edit exists yet.
