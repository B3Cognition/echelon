# Spec 019 — SOAR Seed Rule Upgrade: Actionable Dispatch Guidance

**Date**: 2026-04-03  
**Mode**: brownfield  
**Upstream**: spec 018 (SOAR overlay, built + verified)  
**WHY2**: PASS (manual — focused brownfield amendment, not a full spec run)

---

## Summary

Spec 018 built the SOAR overlay with `soar_state_hint` observer labels in seed rule actions. SCIENTIST investigation confirmed two issues:

1. **Q1 delivery gap**: `soar_state` is injected into COMMANDER's Python `context_pack` dict but is never serialized into agent prompt text. Agents cannot read it.
2. **Q2 payload weakness**: Current `soar_state_hint` values are context descriptors, not behavioral directives.

This spec closes both gaps.

---

## Functional Requirements

- **FR-019-001**: COMMANDER must serialize `soar_state` into each agent's prompt text as a structured block — analogous to the endocrine modifier injection pattern. The block must appear immediately before the agent's context pack file list. Format:

  ```
  [SOAR DISPATCH GUIDANCE]
  dispatch_mode: {value}
  guidance: {value}
  cycle: {value}
  impasse: {value}
  ```

  When `soar_state` is absent (e.g., SOAR overlay raised an exception), the block is omitted entirely — never injected with empty or None values.

- **FR-019-002**: `SEED_RULES` in `scripts/ca/soar.py` must be upgraded so every rule's `actions` dict contains exactly two behavioral fields: `dispatch_mode` (one of five canonical values) and `guidance` (a behavioral instruction string, not an observer label). `soar_state_hint` is removed.

- **FR-019-003**: All five seed rule payloads must satisfy `len(json.dumps(soar_state)) <= 200` at all realistic cycle values (tested at cycle=1 through cycle=100, wme_count=1 through wme_count=5). seed-004 guidance must be ≤71 chars due to its 199-char baseline at cycle=1.

- **FR-019-004**: `tests/unit/test_soar_seed_rules.py` must be created with the 10 tests designed in investigation.md (TEST-019-001 through TEST-019-010).

---

## Canonical dispatch_mode Values

| mode | When | Agent instruction |
|------|------|-------------------|
| `exploratory` | active_goal only | No prior artifacts. Cast wide. Surface unknowns. |
| `focused` | goal + actr_buffers | ACT-R buffers loaded. Use retrieved excerpts. Be specific. |
| `incremental` | goal + gwt_workspace | Workspace history present. Build on it, don't repeat it. |
| `convergent` | all Tier 1+2 | Full context + prior artifact. Resolve open items. |
| `reactive` | goal + lida_broadcast | Broadcast overrides priority. Process it first. |

---

## Upgraded SEED_RULES (final payloads, budget-verified)

```python
# seed-001: active_goal only
"actions": {
    "dispatch_mode": "exploratory",
    "guidance": "No prior artifacts. Cast wide; surface unknowns over depth.",
}
# worst-case chars (cycle=100, wme_count=1): 191 ✓

# seed-002: goal + actr_buffers  
"actions": {
    "dispatch_mode": "focused",
    "guidance": "ACT-R buffers loaded. Use retrieved excerpts; be specific.",
}
# worst-case chars (cycle=100, wme_count=2): 193 ✓

# seed-003: goal + gwt_workspace
"actions": {
    "dispatch_mode": "incremental",
    "guidance": "Workspace loaded. Build on prior context; avoid repetition.",
}
# worst-case chars (cycle=100, wme_count=2): 196 ✓

# seed-004: full Tier 1+2 (guidance capped at 71 chars — critical)
"actions": {
    "dispatch_mode": "convergent",
    "guidance": "Full context. Target depth; resolve open unknowns.",
}
# worst-case chars (cycle=100, wme_count=5): 197 ✓

# seed-005: goal + lida_broadcast
"actions": {
    "dispatch_mode": "reactive",
    "guidance": "Broadcast active. Treat it as high-priority context override.",
}
# worst-case chars (cycle=100, wme_count=2): 192 ✓
```

---

## Test Plan (10 tests)

See `investigation.md` Q5 for full test designs. Tests live in `tests/unit/test_soar_seed_rules.py`.

| Test | Assertion | What it proves |
|------|-----------|----------------|
| TEST-019-001 | Each seed rule fires on correct input | Coverage, no cross-fire |
| TEST-019-002 | dispatch_mode present in soar_state | Payloads survive _apply_operator |
| TEST-019-003 | guidance non-empty after cap check | Guidance not truncated to mandatory-only |
| TEST-019-004 | 200-char cap at cycle=100 | Budget safety across realistic runs |
| TEST-019-005 | dispatch_mode values are unique | Semantic distinctness |
| TEST-019-006 | Impasse on empty pack → no dispatch_mode | Impasse path is clean |
| TEST-019-007 | seed-004 fires only with all 4 conditions | Condition strictness |
| TEST-019-008 | Chunking path preserves dispatch_mode | Chunking inherits action payload |
| TEST-019-009 | All prior overlay keys preserved | AC-1.5 still holds |
| TEST-019-010 | COMMANDER.md injection block present | Delivery gap is closed |

---

## Out of Scope

- Changing SEED_RULES condition schemas (conditions are correct from spec 018)
- Enabling chunking
- Modifying any overlay other than soar.py (seed rules) and COMMANDER.md (injection block)
