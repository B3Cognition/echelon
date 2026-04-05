# Code Review Report — Spec 017 NS-003 + U-CA-004

**Build run**: squad-1775169176 (continued)
**Date**: 2026-04-03


## CODE REVIEW — T-001 through T-019 Batch

**Overall verdict**: CHANGES_REQUESTED (2 fixes required before experiment run)

### Issue 1 (CRITICAL, Confidence 92%) — FR-NS3A-001: jsonschema library not called

`ns003_critic.py` declares `jsonschema` in requirements but never calls `jsonschema.validate()`. The deterministic component uses custom KV-extraction + field presence only. Enum/type constraints in schemas are unenforced. FIX: integrate `jsonschema.validate()` against extracted dict.

### Issue 2 (IMPORTANT, Confidence 88%) — scope_conflict over-fires

`ns003_agm.py` line 544-547: fires `scope_conflict` whenever incoming assertion has ANY scope term (`only`, `all`, `none`, `any`, `within`, `excluding`) and existing does not — regardless of semantic compatibility. Will inflate FPR above 0.20 target. FIX: remove unilateral fire; require both sides to have scope terms.

### Issue 3 (MINOR, Confidence 90%) — pyyaml unused

Remove `pyyaml` from requirements.txt.

**Non-issues confirmed**: P-014 (no credentials), FR-DEP-002 (--help works), ADR-001 (pre-commit notice), ADR-004 (fixed prompt, SHA-256 hash), P-020 (binary verdict), P-022 (dual FPCR threshold), FR-NS3B-ERR-002 (atomic write).
