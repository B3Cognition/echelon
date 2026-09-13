# SDD ledger — plan: docs/superpowers/plans/2026-09-13-managed-retarget-rewind-exclusion.md

## Scope and recovery

Prepared while preceding captured artifact audit is awaiting independent review. Do not dispatch until that phase is complete. Only this root owns this plan, brief and ledger. No implementation BASE yet. Offline existing worktree only, no installation, main mutation or stopped smoke. Retain until final whole-branch review and exhaustive rulings.

Spec: docs/superpowers/specs/2026-09-12-durable-element-identities-design.md, approved and fully read in this execution. Task is a bounded negative admission step, not all-writer integration or positive managed recovery.

## Preflight

| Task/interface pair | Producer versus consumer | Finding |
| --- | --- | --- |
| Task 1 self-consistency | Six named production owners, one new test module and storage documentation versus seven exact covering modules | No new controller/schema/publication protocol; existing tests unchanged. Native first-effect test establishes defect before implementation. |
| Task 1 spec query / prior execution guard | Empty run tuple with real selected spec versus existing nonempty run-only calls | Only spec-present empty tuple becomes valid; None plus empty still rejects; exact validation, indexed owner/orphan query and one read transaction unchanged. |
| Task 1 presence helper / old guard | Shared lstat/open versus existing metadata-first execution checks | Preserve truly absent authority compatibility and malformed-parent rejection; no inferred run IDs or initialization. |
| Task 1 retarget / locks and errors | Actual baseline/active state plus separate canonical selector versus three locked mutation owners | Place after existing rechecks but before first durable effect or early successful resume return; outside mutation exception handlers. Busy precedence remains. |
| Task 1 recovery / native hidden mutation | `_require_recovery_revision` identity checks versus its captured-receipt history advance | Gate before raw_graph reconciliation, not merely before outer restoration. Optional baseline state read must not create directories or treat a present broken entry as absent. |
| Task 1 CLI rewind / lower prepare | Actual locked runtime state versus native same-head applied=True and later state effects | Guard entire CLI including nominal preview; lower confirm=False stays unchanged and nonmutating. Confirmed library query precedes same-head success and all Git/file effects. |
| Task 1 scope / managed design | Negative guarded owners versus future managed transition/publication | No managed retarget/rewind enablement, full writer perimeter or enrollment lease claimed; native unrelated legacy paths retained. |

Ruling: 37 — Allow the existing query-only negative ownership method to accept an empty run tuple only with a real selected spec, and use it together with actual runtime witnesses to exclude managed retarget/rewind/recovery at their native effect owners. Guard the whole rewind CLI including nominal preview because its same-head native result can proceed to state effects; preserve the nonmutating lower-level preview and unrelated legacy behavior. — Those owners can otherwise bypass the delivery-loop exclusion and rewrite accepted source/history/graph/memory or claim completion without a managed transition; a spec-only command must not invent a run ID. — If wrong, narrow the inactive negative-admission APIs/placements and compatibility tests or integrate an explicit authenticated managed source/run transition; no IDs, revisions, graph keys, schema, journal receipts, canonical sources or live deployment need rewriting.

Task 1: prior captured artifact audit complete (implementation 0768a2ac, report 41c6fcdb, 821 tests, independent clean spec/quality review). Pending dispatch after committing this plan/brief/ledger; Ruling 37 selected, not implemented or reviewed. Placeholder scan found no matches; all six existing covering-test paths verified, seventh is the intentional new module.
