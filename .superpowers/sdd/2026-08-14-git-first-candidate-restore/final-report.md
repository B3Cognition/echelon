# Final Recovery Verification Report

Target authority: implementation base `057b0a7d408c11ca63640c8a52b04bea80677af4`; final verified code head `e8a5b09b`. Git-first recovery remains authoritative over the exact sealed target ref, isolated index, complete target tree, blob modes/OIDs/digests, and pinned candidate manifest.

## Evidence

| Command | Result |
|---|---|
| focused recovery matrix | 1139 passed in 383.61s |
| expanded feature suite | 1729 passed in 381.72s |
| `tests/run-all.sh` | 1649 passed, 0 failed |
| deployment tests | 146 passed in 79.11s |
| dry run | 9 bundle checks passed |
| full pytest | 8885 passed, 9 skipped, 1 deselected, exactly 3 known failures in 1058.51s |
| compileall / diff check | exit 0 / exit 0 |

Crash/recovery coverage passes around journal fsync, every exchange boundary, ref update, index update, receipt replay, symlink/inode/mode drift, temporary residue, ref/index conflicts, and checkpoint preflight. Recovery verifies the exact target commit/ref/index/tree before completing; manifest preflight remains before mutation and SAGE PASS certification remains pinned and fail-closed.

Guided and banzai qualitative debt remains executable with exact authoritative issue/route evidence and `failed_gates: []`. Legacy outbox/receipt recovery remains fail-closed with operator guidance. The two deferred Tasks Lexicon defects remain unchanged: terminal `phase3-tasks-lexicon` suggests the wrong Phase 1 repair command, and the terminal summary can claim a published workspace spec when only run-local artifacts exist.

Full pytest reproduced the three known base failures: `tests/unit/test_extension_capability_policy.py::test_cost_tuned_agents_do_not_request_strong_capability`, `tests/unit/test_extension_capability_policy.py::test_high_risk_agents_keep_strong_capability`, and `tests/unit/test_prosaic_execution_policy.py::test_all_subagents_declare_approved_model_tier_and_effort`.

## Historical discovery and authorized fix

The first verification run exposed the legacy journal fixture inheriting proportional SAGE policy. The authorized fixture correction explicitly selects perfectionist mode; its exact test and 106-test local file passed. Fix Round 1 also made public certificate construction v2-only, confined the explicit v1 builder to the mode-gated perfectionist branch, and made v1 currentness reject missing/default or explicit proportional mode. The evidence table above is the final current status.

## Whole-branch review package

Final verified code head: `e8a5b09b`; later commits are evidence-only. Review range: `057b0a7d408c11ca63640c8a52b04bea80677af4..HEAD`. Review must explicitly verdict target commit/tree/modes; ref/index crash recovery; manifest preflight before mutation; SAGE PASS certification; guided/banzai qualitative debt; legacy outbox; and perfectionist behavior. Verdict: ready for whole-branch review; deferred Lexicon defects remain unchanged.
