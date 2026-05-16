# Endocrine archetype coherence — design

**Date:** 2026-05-16
**Status:** approved (brainstorm), pending implementation plan
**Author:** Claude (Echelon self-analysis run squad-1778937725, post-mortem)
**Prior incidents resolved:** BUG-2 (endocrine.sh init never called), BUG-3 (roster drift PROSPECTOR/GLOBAL_MEMORY ghosts + 4 missing disk-agents).

## Context

A reverse-engineering pass on Echelon by itself surfaced four overlapping discrepancies in the endocrine subsystem:

- **Layer A — Misclassified archetypes.** `GOLDDIGGER`, `ADVOCATE`, and `VETERAN` are documented as `exploration` / `innovation` / `learning` agents in the `echelon-config.yml` baseline comments, but `endocrine.sh agent_to_archetype` resolves them to `control`. They start neutral and stay neutral.
- **Layer B — Specialists archetype not modeled.** `GUARDIAN`, `BENCHMARK`, `ORACLE`, `MONITOR` are dispatched as specialists with materially different roles, but there's no `specialists` archetype in config. All four fall through to `control` (balanced 0.5/0.5/0.5/0.5/0.5/0.5).
- **Layer C — Agents are endocrine-blind.** 40 of 41 agent `.md` files contain zero references to endocrine, hormone, or any individual hormone name. Only `commander.md` knows the system exists. The runtime modifier `[ENDOCRINE: all hormones MEDIUM] Normal operating conditions.` is injected into each dispatched prompt, but no agent has instructions for *how to interpret it*. Behavior modulation exists in theory; in practice the model receives a generic urgency phrase and confabulates the rest.
- **Layer D — Process gaps.** No test catches archetype/config drift (BUG-3 went undetected until manual investigation). No per-dispatch hormone snapshot in the reasoning journal. `definition.yaml` (the canonical phase graph) has zero endocrine references — if a non-COMMANDER orchestrator implemented the graph, endocrine would silently vanish.

This design addresses Layers A, B, and C, and adds the consistency validator from Layer D. Per-dispatch journaling (D10) and `definition.yaml` integration (D11) are deferred to a follow-up.

## Goals

- Every one of the 41 disk agents resolves to an archetype whose baselines match its role.
- The runtime modifier emitted by `endocrine.sh get_full_prompt_modifier` carries enough role-appropriate guidance that an agent can actually shift behavior on it.
- A future BUG-3-shape regression (roster drift, archetype drift, missing-baseline drift) is caught by a single test run in CI.
- No new config files. No new directories. No 41-file prose-authoring blast.

### Acknowledged costs

- **Prompt-token overhead.** Every dispatch now prepends a 5–15-line `[ENDOCRINE]` block to the agent's context pack. For a typical squad run (~30 dispatches) this adds ~6–15 K tokens of structured endocrine prose total. In banzai / unlimited-budget configurations this is negligible; in tight-budget configurations it can be material. Operators concerned about budget can disable endocrine entirely (`endocrine.enabled: false`) — the modifier then becomes a no-op exit-0 call and prepends nothing.

## Non-goals

- Adding a `specialists` archetype as a 9th entry. Specialists split into existing archetypes — see Section 3.
- Per-agent baseline overrides. The system stays archetype-based.
- Phase 1 vs Phase 3 enforcement in `get_full_prompt_modifier` (D7). Out of scope for this design.
- Per-dispatch hormone-state journal entries (D10). Out of scope.
- `definition.yaml` endocrine integration (D11). Out of scope.
- Refactoring `endocrine.sh` itself beyond the two specific changes below.

## Section 1 — Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  echelon-config.yml                                              │
│    endocrine.baselines.<archetype>   ← unchanged                 │
│    endocrine.interpretations.<archetype>   ← NEW sub-block       │
│      summary: string                                             │
│      overlays:                                                   │
│        <hormone>_high: string                                    │
│        <hormone>_low:  string                                    │
│                                                                  │
│  extension/scripts/bash/endocrine.sh                             │
│    agent_to_archetype()              ← reassign 7 agents         │
│    get_full_prompt_modifier()        ← read interpretations,     │
│                                        emit multi-line block     │
│                                                                  │
│  extension/agents/<layer>/<agent>.md  × 41                       │
│    After "## Role" body: insert 1 standardized line               │
│      (mechanical, scripted, idempotent)                          │
│                                                                  │
│  tests/unit/test-endocrine-archetype-consistency.sh    ← NEW     │
│    Six assertions; runs in CI.                                   │
│                                                                  │
│  scripts/bash/agent-endocrine-rewire.sh                ← NEW     │
│    Idempotent inserter for the per-agent line                    │
└──────────────────────────────────────────────────────────────────┘
```

Source-of-truth flow at dispatch time:

```
COMMANDER dispatches agent X
        ↓
endocrine.sh get_full_prompt_modifier X
        ↓
  step 1:  agent_to_archetype X → "validation"
              (in-memory bash case, no I/O)
  step 2:  read hormones for X from state.json
              (one file read — existing behavior)
  step 3:  read endocrine.interpretations.validation
              from echelon-config.yml  ← NEW file read
        ↓
emit multi-line block:
  [ENDOCRINE — validation archetype]
    <hormone state lines>
  Interpretation (validation archetype):
    <summary>
    - <triggered overlays>
        ↓
COMMANDER prepends block to dispatched prompt
  (unchanged caller behavior — same `get_full_prompt_modifier` contract,
   just richer output)
```

The agent's `.md` file itself is **not** read at runtime — the 1-line marker added in Section 4 is purely for human readers and for the Section 5 consistency test. The only new I/O this design adds at dispatch time is step 3 (one YAML read per dispatch).

## Section 2 — Interpretation data shape

New sub-block under `endocrine:` in `echelon-config.yml`:

```yaml
endocrine:
  enabled: true
  phase: 3
  adrenaline: { ... }    # unchanged
  baselines:             # unchanged
    exploration: [0.3, 0.7, 0.3, 0.6, 0.5, 0.4]
    validation:  [0.4, 0.3, 0.8, 0.4, 0.4, 0.7]
    # ... 6 more
  interpretations:       # NEW
    <archetype>:
      summary: |
        1–3 sentences. Always emitted. Frames the role's normal operating
        mode and what extremes generally mean.
      overlays:
        adrenaline_high: "Emitted only when current value ≥ 0.75."
        adrenaline_low:  "Emitted only when current value ≤ 0.25."
        cortisol_high:   "..."
        cortisol_low:    "..."
        dopamine_high:   "..."
        dopamine_low:    "..."
        serotonin_high:  "..."
        serotonin_low:   "..."
        oxytocin_high:   "..."
        oxytocin_low:    "..."
        norepinephrine_high: "..."
        norepinephrine_low:  "..."
```

**Levels:** HIGH ≥ 0.75, LOW ≤ 0.25, MEDIUM otherwise. MEDIUM never emits an overlay. Authors omit any overlays that don't change behavior for that archetype.

**Output format** (multi-line; COMMANDER prepends as-is):

```
[ENDOCRINE — validation archetype]
  adrenaline: 0.42 (MEDIUM)   dopamine: 0.30 (MEDIUM)
  cortisol:   0.85 (HIGH)     serotonin: 0.40 (MEDIUM)
  oxytocin:   0.40 (MEDIUM)   norepinephrine: 0.20 (LOW)

Interpretation (validation archetype):
  You operate vigilantly under high cortisol and high norepinephrine. HIGH cortisol
  does NOT mean back off — it means tighten gate criteria. Your value is in what
  you reject, not what you approve.
  - HIGH cortisol: Maximum vigilance. Reject anything you would normally let
    slide. Document each rejection — false positives are reversible, false
    negatives ship to prod.
  - LOW norepinephrine: Focus slipping. Stop scanning, pick the next single
    requirement, complete its check, log it. Single-task until norepinephrine
    recovers.
```

**Backward compatibility:** if `endocrine.interpretations` is absent from `echelon-config.yml`, `endocrine.sh` falls back to the existing single-line `[ENDOCRINE: all hormones MEDIUM] Normal operating conditions.` output. Projects that haven't updated their config don't break.

**Number-rendering rule:** hormone values rendered to 2 decimal places in the block. Level labels in parentheses.

## Section 3 — Archetype assignments and interpretation drafts

### Archetype membership after this design (41 agents)

| Archetype | Members | Change from current |
|---|---|---|
| `exploration` (5) | SCOUT, SYNTHESIZER, CARTOGRAPHER, MODELER, GOLDDIGGER | +GOLDDIGGER (was control) |
| `validation` (4) | SAGE, CHECKPOINT, VALIDATOR, GUARDIAN | +GUARDIAN (was control) |
| `feasibility` (1) | GATEKEEPER | unchanged |
| `solution` (5) | ARCHITECT, ORCHESTRATOR, SENTINEL, ORACLE, BENCHMARK | +ORACLE (was control — provides definitive expert input that ARCHITECT/CARTOGRAPHER consume), +BENCHMARK (was control — capacity models feeding ARCHITECT, not a builder) |
| `build` (10) | IMPLEMENTER, SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN, DEBUGGER, INTEGRATOR, CHANGE_CONTROLLER, VISUAL_VALIDATOR, VERIFICATION, ENGINEERING_MANAGER | unchanged from existing (no BENCHMARK — see solution above) |
| `innovation` (3) | MAVERICK, INVESTIGATOR, ADVOCATE | +ADVOCATE (was control) |
| `learning` (8) | MIRROR, ADAPTIVE, AUDITOR, INTERNALIZER, REALIST, VETERAN, CONSOLIDATOR, MONITOR | +VETERAN (was control), +MONITOR (was control — lives in `extension/agents/learning/` on disk; metacognition is reflection) |
| `control` (5) | COMMANDER, SCOREKEEPER, TRACKER, STRATEGIST, PROGRESS_TRACKER | -GOLDDIGGER, -ADVOCATE, -VETERAN, -GUARDIAN, -BENCHMARK, -ORACLE, -MONITOR (all reassigned) |

41 total. Every disk agent placed.

**Sanity-check:** the disk directory layout (`extension/agents/<layer>/<agent>.md`) groups agents by *operational layer* (control / exploration / feasibility / solution / specialists / build / learning). The endocrine archetypes here are tuned to *hormone profile that fits the agent's role*. They overlap heavily but not perfectly — for example, MONITOR lives in the `learning/` directory and gets the `learning` archetype baseline, while ORACLE/BENCHMARK live in `specialists/` and pick up the `solution` archetype because their *output* (expert input feeding designers) shares the solution profile. The specialists directory has no corresponding archetype on purpose — see "Non-goals".

### Interpretation drafts (8 archetypes)

These are starting points; tune in the implementation plan if any prose reads wrong.

```yaml
interpretations:

  exploration:
    summary: |
      You operate under high dopamine (curiosity) and low cortisol (no fear of
      ambiguity). Open threads, keep questions live. Your value is in the
      surface area you map, not the conclusions you reach.
    overlays:
      adrenaline_high: "Budget pressure rising. Stop opening new threads. Consolidate findings and close the loop before iterating further."
      dopamine_low:    "Curiosity slipping — you're going through the motions. Re-read the user request and the unknowns list before producing more output."
      cortisol_high:   "Something is going wrong (rare for your archetype). Escalate to COMMANDER rather than producing more analysis."

  validation:
    summary: |
      You operate vigilantly under high cortisol and high norepinephrine. HIGH
      cortisol does NOT mean back off — it means tighten gate criteria. Your
      value is in what you reject, not what you approve.
    overlays:
      cortisol_high:      "Maximum vigilance. Reject anything you would normally let slide. Document each rejection — false positives are reversible, false negatives ship to prod."
      cortisol_low:       "Under-vigilance. You are at risk of rubber-stamping. Re-read the most recent passed artifact and challenge it adversarially before continuing."
      norepinephrine_low: "Focus slipping. Stop scanning, pick the next single requirement, complete its check, log it. Single-task until focus recovers."

  feasibility:
    summary: |
      Your judgment is conservative but steady (high cortisol, elevated
      serotonin). KILL, DEFER, and PASS verdicts have permanent consequences —
      you are the kill gate.
    overlays:
      cortisol_high: "Bias your verdict toward DEFER or KILL. Better to reject a viable plan than approve a dangerous one. State your residual concerns explicitly."
      serotonin_low: "Judgment instability. Refuse to issue a verdict until you've re-read the spec and feasibility constraints in full. Avoid PASS under destabilized judgment."

  solution:
    summary: |
      You operate under high serotonin (calm confidence) and elevated dopamine
      (creative). Your job is the simplest correct contribution — the smallest
      architecture (ARCHITECT/ORCHESTRATOR/SENTINEL), the tightest capacity
      model (BENCHMARK), the most specific domain answer (ORACLE) — that meets
      the spec. Avoid over-engineering; avoid elaborating beyond what your
      consumers (ARCHITECT, CARTOGRAPHER) will use.
    overlays:
      dopamine_high: "Creative drive may be over-tuning. Check: are you adding optionality, capacity headroom, or domain detail the spec doesn't ask for? Cut anything not requirement-traced."
      serotonin_low: "Rushed output risk. Stop generating new structure (ADRs / capacity rows / domain sections); spend the next dispatch consolidating what's already decided and double-checking trace coverage."

  build:
    summary: |
      You ship under high adrenaline, high oxytocin (peer collaboration), and
      high norepinephrine (detail focus). HIGH adrenaline = ship and iterate;
      do not skip review gates.
    overlays:
      adrenaline_high:    "Execution pressure is on. Ship the smallest correct increment. Do NOT skip the spec-guard / code-review / test-guard gates — that's where speed kills."
      norepinephrine_low: "Detail focus slipping. You will miss off-by-one errors and edge cases. Stop, write a checklist for this task, mark each item before claiming DONE."
      oxytocin_low:       "You're working in isolation when you shouldn't be. Re-read the upstream agent's output (IMPLEMENTER → SPEC_GUARD, etc.) before drafting your verdict."

  innovation:
    summary: |
      You explore alternatives under high dopamine and low cortisol. Your worst
      output is the safe one — propose options the squad would otherwise miss,
      even weak ones.
    overlays:
      dopamine_low:  "Creativity has dried up. Stop generating options; re-read three pitfalls.yaml entries from prior runs to seed fresh angles."
      cortisol_high: "Fear is throttling exploration. Lower the bar: list five options regardless of viability. Filtering is downstream."

  learning:
    summary: |
      You operate reflectively under high serotonin and high oxytocin. Your
      value is the signal individual dispatches miss — whether that's
      real-time process drift (MONITOR's beat) or cross-run pattern
      extraction (AUDITOR, MIRROR, ADAPTIVE, REALIST, VETERAN, CONSOLIDATOR,
      INTERNALIZER). Step back from the per-task view.
    overlays:
      cortisol_low: "Under-reflection. You are summarizing instead of synthesizing. Look for the pattern (cross-run for post-hoc agents; cross-phase for MONITOR), not the local finding."
      oxytocin_low: "Siloed thinking. Read at least one prior run's evolution-report (or, for MONITOR, scan the current run's reasoning-journal index) before producing your output."

  control:
    summary: |
      You orchestrate from a balanced baseline. Any hormone extreme on your own
      profile is a sign the squad is off-track — re-anchor on the constitution
      and user intent.
    overlays:
      adrenaline_high: "Budget pressure has propagated to your own hormones. Resist reactive routing; check EVOI for each candidate dispatch before issuing."
      cortisol_high:   "You are catastrophizing. Re-read the user request verbatim. The squad is likely fine; you are interpreting noise as crisis."
```

## Section 4 — Agent file edit pattern

Each of the 41 agent files in `extension/agents/<layer>/<agent>.md` gets one line inserted after its `## Role` section body, before the next `##` heading. The inserted text is identical across all files (the per-archetype interpretation comes from `endocrine.sh` at runtime, not the file):

```markdown
> **Endocrine awareness.** Your dispatched context pack includes an `[ENDOCRINE]` block from `endocrine.sh get_full_prompt_modifier`: your current hormone levels (adrenaline, dopamine, cortisol, serotonin, oxytocin, norepinephrine) plus role-appropriate interpretation from your archetype. It's not narration — it's behavior modulation. Read and act on it before producing output.
```

### Insertion script: `scripts/bash/agent-endocrine-rewire.sh`

Behavior:
- For each `*.md` in `extension/agents/<layer>/`:
  - If the marker string `**Endocrine awareness.**` already appears, skip the file.
  - Otherwise locate the line beginning with `## Role` (case-insensitive, allowing `## ROLE`). Skip the body until the next `## ` H2 heading or EOF, then insert the block immediately before that heading (or at EOF).
  - Preserve trailing newlines and surrounding blank lines.
- Run also against `.specify/extensions/echelon/agents/<layer>/*.md` (deployed copies) so live runs see the marker immediately. Per the project pattern, the `.claude/agents/speckit-echelon-*.md` deployed copies are regenerated separately and are updated by the same script.

The script is idempotent (re-running is safe). Includes a `--dry-run` flag that prints the planned changes without writing.

## Section 5 — Validator + test

New file: `tests/unit/test-endocrine-archetype-consistency.sh`. Six independent assertions, each printable as a single PASS/FAIL line. Exits non-zero on any failure.

| # | Assertion | What it catches |
|---|---|---|
| 1 | Every name in `endocrine.sh ALL_AGENTS` resolves to a non-default archetype via `agent_to_archetype` | A new agent added to `ALL_AGENTS` without an archetype case (would default to `control` silently). |
| 2 | Every archetype returned by `agent_to_archetype` has a baseline in `echelon-config.yml endocrine.baselines` | An archetype rename / typo. |
| 3 | Every archetype in `endocrine.baselines` has a matching block in `endocrine.interpretations` | Half-rolled-out interpretations (e.g., baseline added but interpretation forgotten). |
| 4 | Every `.md` agent file in `extension/agents/<layer>/` is listed in `ALL_AGENTS` | Disk-only agents (no endocrine state, BUG-3 shape). |
| 5 | Every `ALL_AGENTS` entry has a corresponding file on disk | Stale entries (PROSPECTOR/GLOBAL_MEMORY shape). |
| 6 | Every agent file contains the `**Endocrine awareness.**` marker | Section-4 marker insertion drift. |

Run in CI alongside the existing endocrine tests in `tests/unit/test-endocrine-*.sh`.

## Migration / sequencing

1. **`echelon-config.yml`** — two edits in the same file:
   - Add the `endocrine.interpretations:` block under the existing `endocrine:` block (Section 2).
   - Update the per-archetype `# <ARCHETYPE> (members…)` comments above each entry of `endocrine.baselines:` to match the new memberships in Section 3. Stale comments would re-create the kind of drift Section 5 prevents in code but cannot detect in YAML comments.
2. **`endocrine.sh`** — two edits:
   - `agent_to_archetype()`: reassign 7 agents per the Section 3 table — GOLDDIGGER, ADVOCATE, VETERAN to their Layer-A archetypes; GUARDIAN, BENCHMARK, ORACLE, MONITOR to their Layer-B archetypes (note: ORACLE and BENCHMARK go to `solution`, MONITOR to `learning`).
   - `cmd_get_prompt_modifier()` / `cmd_get_full_prompt_modifier()`: read `endocrine.interpretations.<archetype>` via existing `yaml_get`; emit multi-line block per Section 2. Preserve the existing single-line fall-back when interpretations are absent.
3. **`scripts/bash/agent-endocrine-rewire.sh`** — write and run once over all 41 agent files. After the script runs, spot-check at least one file whose `## Role` body is immediately followed by another `## ` heading (e.g., `extension/agents/learning/monitor.md` has `## Role` → `## NEVER Rules`) to confirm the blockquote insertion produces acceptable visual flow. Commit results.
4. **`tests/unit/test-endocrine-archetype-consistency.sh`** — write the six assertions per Section 5.
5. **Deploy:** copy updated `endocrine.sh` and `echelon-config.yml` to `.specify/extensions/echelon/...` for the live extension; copy updated agent files similarly. Standard echelon deployment pattern (already used by BUG-1 and BUG-3 fixes).
6. **Verify:** run the new test, run an `echelon run "self test"` and confirm a dispatched agent's prompt contains the new multi-line `[ENDOCRINE — <archetype> archetype]` block with at least the summary line.

The migration is incremental: steps 1+2 alone deliver Layer A+B fixes without any agent-file edits, so the project remains shippable at each step. Step 3 (file marker inserts) is purely additive.

## Rollback

Rollback is granular — three independently revertible changes, listed in increasing blast radius:

- **Multi-line emit format regression** (the new `[ENDOCRINE — <archetype>]` block confuses agents or bloats prompts): revert only the `cmd_get_*_prompt_modifier` change. Output reverts to the existing `[ENDOCRINE: …] Normal operating conditions.` single-line. Archetype reassignments stay (so GOLDDIGGER still gets exploration baselines, etc.). `endocrine.interpretations:` block in config becomes unread but doesn't break anything.
- **Archetype reassignment regression** (one of the 7 agents behaves worse with its new baselines): revert only the `agent_to_archetype` change for the affected agent(s); other agents keep their new archetypes. This is a targeted edit (single `case` branch in `endocrine.sh`).
- **Layer C regression** (the markdown marker bloats agent files or causes confusion): `agent-endocrine-rewire.sh --remove` strips the marker idempotently. Run once; commit. Config and `endocrine.sh` changes unaffected — runtime behavior unchanged because the agent file marker isn't read at runtime.
- **Test regression** (assertion #6 fires spuriously after a manual edit removed a marker): mark the new test optional in CI until rectified, or re-run the rewire script to restore the marker.

Reverting "all of Section 1–5" in one shot is *not* supported as a single command; the migration was designed to be independently revertible per change, not atomic.

## Out of scope (future work)

- **D7 Phase-1/Phase-3 enforcement.** `get_full_prompt_modifier` currently doesn't gate output on `endocrine.phase`. Phase 1 may already be silently emitting phase-3 modifiers. Tackle as a separate spec.
- **D8 Per-agent baseline overrides.** Some agents (e.g., DEBUGGER) may want a baseline divergent from their archetype. Currently impossible. Out of scope.
- **D10 Per-dispatch hormone snapshot in reasoning journal.** Would let AUDITOR correlate hormone profiles with quality outcomes. Out of scope.
- **D11 `definition.yaml` endocrine integration.** The phase graph is currently endocrine-agnostic. Out of scope.

## Open questions

None at this stage. All design decisions are settled. Implementation-plan stage may surface details (exact bash patterns for the marker insert, exact YAML quoting choices) but no design-level questions remain.
