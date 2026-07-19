# Reasoning-Layer Experiment — Pre-registration (BEFORE runs)

**Date:** 2026-07-19 (written before any arm-C/D corpus runs execute)
**Protocol:** dialectic design draft §Experimental protocol (commit 8d695b55)

## Corpus (smoke)

- **Spec 029** (`specs/029-builder-spec-workbench/spec.md`) — lexicon format;
  ground truth tier 2: committed v2 consensus stable findings + known issues.
- **Spec 064** (ru-sixth-sense eventlog-inline-edit) — markdown; ground truth
  tier 2/3: committed v1 findings (4 CONTRADICTED incl. FR-001×AC-5), blind
  adjudication for novel findings. Mutant tier deferred (cost) — recorded as
  a smoke-scale deviation from protocol.

## Seeds (arm C; from stable/committed findings)

1. 029 / REQ-002: "what the run list shows when the active-run pointer is
   absent or names a deleted run"
2. 029 / REQ-023+029: "how the workbench reliably detects an in-progress
   dispatch from a state file that may be unreadable at that moment"
3. 029 / REQ-010: "whether incremental journal loading is optional or
   mandatory, given the 2-second constraint and AC-010"
4. 064 / FR-025b: "which prompt a bare Esc with unsaved changes opens"
5. 064 / FR-001: "which operators are permitted to enter row-edit mode"
   (euthyphro run 1 already executed live: APORIA_CONTRADICTED in 1 turn)

Arm C: 5 seeds × 2 lenses (euthyphro, parmenides), ≤7 turns.
Stability: seed 5 euthyphro re-run ×2 (3 total incl. the live run).
Arm D (one-shot J-graph): 3 readers × {029, 064}.
Arm B gap-fill: v2 consensus on 064 (029 already has committed v2 data).

## Pre-registered expectations (falsifiable)

- **E1:** On contradiction seeds (1, 4, 5) arm C reaches APORIA_CONTRADICTED
  in ≤3 turns with both conflicting sources cited.
- **E2:** On the subtle seed 3 (SHOULD vs binding constraint) arm C needs ≥2
  turns and ends APORIA_UNDERDETERMINED or APORIA_CONTRADICTED; single-turn
  resolution would argue adaptivity adds nothing there.
- **E3:** Stability: ≥2 of 3 seed-5 euthyphro runs produce the identical
  operator sequence and terminal state.
- **E4:** Arm D links FR-001 and AC-5 as conflicting claims in ≥2 of 3
  readers (if it does, at ~1/10 of arm C's cost, outcome 2 of the decision
  rule gains ground).
- **E5:** Arm B on 064 reproduces ≥3 of v1's 4 CONTRADICTED findings as
  stable (support ≥2).
- **Risk noted in advance:** seed-5 live run ended in 1 turn — obvious
  contradictions may not exercise adaptivity at all; the seeds-mix (obvious +
  subtle) is deliberate so E1 and E2 separate sensitivity from adaptivity.

## Decision rule

As pre-registered in the protocol (three outcomes, matched-budget thresholds).
Adjudication of pooled deduplicated findings is BLIND to arm labels; primary
judge = operator, secondary = LLM panel.
