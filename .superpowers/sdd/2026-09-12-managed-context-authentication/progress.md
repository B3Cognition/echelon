# SDD ledger — plan: docs/superpowers/plans/2026-09-12-managed-context-authentication.md

## Preflight

| Tasks | Shared interface or self-check | Result |
| --- | --- | --- |
| 1 / record validation and selected IDs | Completed state validator supplies an exact detached ten-string record, not provenance. | New check takes independent spec/run arguments and requires exact equality with actual retained genesis; no deriving selection from the claim or rewriting original source metadata. |
| 1 / durable reads | Existing managed read already validates original source and current source integrity; source read returns current receipt. | Compose both under one query-only existing transaction, accept the extra bounded shared source read instead of refactoring existing API. No state/publication locks inside. |
| 1 / source history | Original source registration hash differs legitimately from a later accepted head. | Return separate genesis/current source records; prepared/applied/released observation follows existing source owner and proves neither release nor physical freshness. |
| 1 / runtime boundary | Overall design requires runtime managed selection independent of mutable output. | This explicit managed-only checker errors on absent genesis/record and has no legacy classification or live caller. Deleted state, later runs, physical isolation and complete startup/completion remain subsequent integration, not claimed here. |
| 1 / performance and authority | Existing managed/source lookups are indexed and full history audit is separate. | Query-only checks must not scan child identity/history or perform repair/enrollment/upgrade. Test actual authorizer/index plans with mixed-family history, not another capacity run. |
| 1 / errors | Latest state review found suppressed display differs from retained hostile exception context. | Explicit short bounded IdentityStoreError after exception handler, BaseException preserved; closed-input and retained-context assertions required. No policy change to other existing methods. |
| 1 / first RED and final tests | Real capture and registration must reach the missing new method. | Local scoped POSIX fixture required, pure tests independent; verified actual existing source test filename test_element_identity_source_store.py. Five named modules once, no controller/full-unit/capacity/live repeat. |

Main read approved durable-element-identities design, full66-line new plan, actual IdentityStore transaction/open/namespace and managed/source entry points, full managed read and source head composition, pure state record validator and existing managed test helpers/frozen schema5 setup. One bounded composition task, no schema or live routing interface. The architectural design is already approved and user requested automatic phased continuation. No new policy ruling: this is explicit claim-versus-existing-authority verification within that approved design, not managed/legacy selection or source relocation.

Preceding managed-state preservation completed with clean scoped review at e5130edc, root checkpoint ee456a38. Main read the complete66-line plan after correcting the actual source-store module name; placeholder scan found none, diffcheck clean. One opt-in composition method requires standard integration judgment rather than new architecture; choose fresh Sol/high implementer and same-risk reviewer. Root owns this plan/workspace. Retain artifacts for final whole-branch review and exhaustive chronological rulings handoff.

Task1 ready for plan/brief commit and first implementation dispatch. No new production change yet. No live rollout or remaining-stage completion claim.
