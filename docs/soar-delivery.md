# COMMANDER — SOAR State Delivery (FR-019-001)

This document closes the Q1 delivery gap: `soar_state` was computed by the SOAR cognitive architecture
but never serialized into agent prompts. FR-019-001 requires COMMANDER to inject it.

## Delivery Mechanism

After each Match-Select-Apply cycle, `scripts/ca/soar.py:run_cycle()` returns an enriched
`context_pack` with a `soar_state` key. COMMANDER reads this key and injects the SOAR dispatch
guidance block into every agent prompt before dispatch.

### [SOAR DISPATCH GUIDANCE] injection block

```
[SOAR DISPATCH GUIDANCE]
dispatch_mode : {soar_state[dispatch_mode]}
guidance      : {soar_state[guidance]}
cycle         : {soar_state[cycle]}
rule_id       : {soar_state[rule_id]}
```

COMMANDER serializes this block as plain text and prepends it to the agent's working-memory
section. The block is capped at 200 characters (enforced by `_apply_operator`); if the full
`soar_state` exceeds the cap, only `dispatch_mode` and `guidance` are included.

### dispatch_mode values

| Value | Meaning |
|-------|---------|
| `exploratory` | No prior artifacts — cast wide, surface unknowns |
| `focused` | ACT-R buffers available — use retrieved excerpts specifically |
| `incremental` | Prior workspace context — build on it, avoid repetition |
| `convergent` | Full context — target depth, resolve open unknowns |
| `reactive` | High-priority broadcast — process this override first |

On SOAR impasse (Ψ < 0.70), no `dispatch_mode` is emitted. COMMANDER proceeds without the
guidance block and logs `soar_impasse: true` in `state.json`.
