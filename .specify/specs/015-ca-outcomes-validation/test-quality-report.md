# Test Quality Report — Spec 015 (ca-outcomes-validation)
**Build run**: build-1775162749 | **Verified by**: VERIFICATION (live execution)

## TASK-006: token-logger.py

| Test | Result |
|------|--------|
| T1: --help exits 0 | PASS |
| T2: script exits 0 on valid fixture journal | PASS |
| T3: all required top-level keys present | PASS |
| T4: per_agent_type has mean/median/p90/count | PASS |
| T5: collection_method is valid | PASS |
| T6: invocations array is non-empty | PASS |
| T7: pipeline_total has all three token fields | PASS |
| T8: invocations[0] has all 5 AC-003-001 fields (agent, prompt_tokens, completion_tokens, spec_run_id, codebase_id) | PASS |
| T9: expected agents present in per_agent_type | PASS |

**Suite result: 9/9 PASS** — Live-confirmed by VERIFICATION agent (build-1775162749)

## TASK-007: contradiction-scanner.py

| Test | Result |
|------|--------|
| T1: --help exits 0 | PASS |
| T2: exits 0 on clean fixture | PASS |
| T3: output is valid JSON with required top-level keys | PASS (all keys present: spec_ids_scanned, assertion_pairs_checked, contradictions_detected, contradiction_rate, bound_type, per_spec_results, per_pair_rates, contradictions, manual_precision_sample) |
| T4: dirty fixture — injected count contradiction detected | PASS (42 vs 19 caught) |
| T5: clean fixture — contradictions_detected is 0 | PASS |
| T6: bound_type is 'upper_bound' | PASS |
| T7: manual_precision_sample entries have verified=null | PASS |

**Suite result: 21/21 PASS** — Live-confirmed by VERIFICATION agent (build-1775162749)

## AC-003-001 Compliance (token-logger.py)

All 5 required per-invocation fields verified present:
- `agent` ✓
- `prompt_tokens` ✓
- `completion_tokens` ✓
- `spec_run_id` ✓ (added in fix cycle 2)
- `codebase_id` ✓ (added in fix cycle 1)
