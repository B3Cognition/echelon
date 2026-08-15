# Final Recovery Verification Report

Target authority: implementation base `057b0a7d408c11ca63640c8a52b04bea80677af4`; verified recovery head `f24d0587` before Task 5 compatibility repair. Git-first recovery remains authoritative over the exact sealed target ref, isolated index, complete target tree, blob modes/OIDs/digests, and pinned candidate manifest.

## Evidence

| Command | Result |
|---|---|
| focused recovery matrix | 1137 passed in 383.60s |
| expanded feature suite | 1727 passed in 380.83s |
| `tests/run-all.sh` | 1648 passed, 1 failed |
| deployment tests | 146 passed in 78.55s |
| dry run | 9 bundle checks passed |
| full pytest | 8882 passed, 9 skipped, 1 deselected, 4 failed in 1056.61s |
| compileall / diff check | exit 0 / exit 0 |

Crash/recovery coverage passes around journal fsync, every exchange boundary, ref update, index update, receipt replay, symlink/inode/mode drift, temporary residue, ref/index conflicts, and checkpoint preflight. Recovery verifies the exact target commit/ref/index/tree before completing; manifest preflight remains before mutation and SAGE PASS certification remains pinned and fail-closed.

Guided and banzai qualitative debt remains executable with exact authoritative issue/route evidence and `failed_gates: []`. Legacy outbox/receipt recovery remains fail-closed with operator guidance. The two deferred Tasks Lexicon defects remain unchanged: terminal `phase3-tasks-lexicon` suggests the wrong Phase 1 repair command, and the terminal summary can claim a published workspace spec when only run-local artifacts exist.

Full pytest reproduced the three known base failures: `tests/unit/test_extension_capability_policy.py::test_cost_tuned_agents_do_not_request_strong_capability`, `tests/unit/test_extension_capability_policy.py::test_high_risk_agents_keep_strong_capability`, and `tests/unit/test_prosaic_execution_policy.py::test_all_subagents_declare_approved_model_tier_and_effort`.

One additional failure is recorded, not concealed: `tests/kernel/test_squad_executors_journal.py::test_judgment_dispatch_replaces_null_journal_metadata`. Its minimal legacy WHY2 fixture defaults to proportional and is rejected by the authoritative SAGE gate before journal publication. The correct fixture-only correction is outside Tasks 1–4 scope, so it was not broadened here.

Task 5 repaired the corresponding in-scope regression: perfectionist callers without an authoritative assessment now receive the exact schema-v1 certificate path, while proportional callers continue to require the schema-v2 pinned SAGE assessment. Targeted GREEN: 13 passed; focused matrix GREEN: 1137 passed.

## Whole-branch review package

Final verified head: `f100788f`. The legacy journal fixture now explicitly selects perfectionist mode; its exact test and 106-test local file pass. Full pytest: 8883 passed, 9 skipped, 1 deselected, and exactly the three base-reproduced capability-policy failures in 1063.62s. Review range: `057b0a7d408c11ca63640c8a52b04bea80677af4..HEAD`. Review must explicitly verdict target commit/tree/modes; ref/index crash recovery; manifest preflight before mutation; SAGE PASS certification; guided/banzai qualitative debt; legacy outbox; and perfectionist behavior. Verdict: ready for whole-branch review; deferred Lexicon defects remain unchanged.
