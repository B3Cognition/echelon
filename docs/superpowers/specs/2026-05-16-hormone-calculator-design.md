# Hormone calculator — design

**Date:** 2026-05-16
**Status:** approved (brainstorm), pending implementation plan
**Author:** Claude (continuing the post-endocrine-archetype-coherence work)
**Prior context:** DEP-FIX T2 (`df99b73`) just resurrected the static endocrine baselines; this design tackles the dynamic layer.

## Context

Today the Echelon endocrine system is **statically archetype-differentiated but temporally frozen**. After this morning's DEP-FIX T2 fix, every agent correctly seeds at its archetype baseline at `endocrine.sh init`. But once seeded, hormone values never move during a run:

- `endocrine.sh` exposes ~17 mutation primitives (`decay_hormones`, `on_gate_pass`, `on_gate_fail`, `on_quality_*`, `broadcast_adrenaline`, `propagate_cortisol_contagion`, etc.) — the deltas the squad's designers already committed.
- `commander.md §566-600` prescribes COMMANDER to call these per dispatch as part of a Pre/Post-Dispatch Protocol.
- **The reasoning journal shows zero such calls across many runs.** Only `endocrine_initialized` ever fires. LLM judgment is unreliable for repetitive bookkeeping under cognitive load.

So agents receive a frozen `[ENDOCRINE — <archetype> archetype]` block at every dispatch, showing the same hormone values across the entire run.

This design adds a **deterministic hormone calculator** modeled on `src/understanding/` — pure Python, observable signals in, hormone deltas out. A thin bash hook invokes it as part of the Post-Dispatch Protocol, removing LLM discretion entirely. Inspired by the same "take it out of model judgment, put it in deterministic bash/Python" pattern as the BUG-1 `kb-read-init.sh` and BUG-2 `endocrine.sh init` fixes.

## Goals

- Hormone state actually shifts during a run, reflecting observable squad events.
- 12 existing `on_*` handlers + 4 new dynamics (budget pressure, iteration pressure, task complexity, decay) fire deterministically.
- Reproducibility: same observable state in → same trigger list out, every time.
- Zero LLM discretion in the dynamics layer.
- Magnitudes for new dynamics live in `echelon-config.yml endocrine.dynamics` (tunable without code change). Existing-handler magnitudes stay in `endocrine.sh` (single source of truth).
- Per-trigger journal logging for AUDITOR / ADAPTIVE / future observability (`type: endocrine_event`).

## Non-goals

- Adding new agent-level behavioural overlays (handled by the archetype-coherence work).
- Redesigning `endocrine.sh`'s mutation primitives or delta magnitudes.
- Adding new hormones (sticking with the 6 already in the system).
- Per-hormone interpretation prose changes (out of scope; see archetype-coherence design).
- Cross-run hormone persistence (each run still starts from archetype baselines).
- Property-based testing (deferred — finite-enumerable input space).

## Section 1 — Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│  Caller (commander.md §566 — replaces narrative pre/post-dispatch)│
│  After every Agent dispatch returns:                              │
│    bash scripts/bash/post-dispatch-hormone-update.sh \            │
│      --agent SAGE --dispatch-id D-007 \                           │
│      --result-file /tmp/echelon-result-D-007.yaml                 │
└──────────────────────────────────────┬────────────────────────────┘
                                       │
┌──────────────────────────────────────▼────────────────────────────┐
│  scripts/bash/post-dispatch-hormone-update.sh   (~50 LOC)         │
│  1. Check state.endocrine_state.applied_dispatches — skip if      │
│     dispatch_id already applied (idempotency).                    │
│  2. Run hormone-calc compute  → captures stdout trigger list.     │
│  3. For each trigger line:                                        │
│     a. Translate to endocrine.sh subcommand                       │
│     b. Execute it                                                 │
│     c. Append `endocrine_event` journal entry via Bash >>         │
│  4. Atomically append dispatch_id to applied_dispatches[].        │
└──────────────────────────────────────┬────────────────────────────┘
                                       │
┌──────────────────────────────────────▼────────────────────────────┐
│  hormone-calc   (new CLI: src/hormone_calc/)                      │
│                                                                   │
│  src/hormone_calc/cli.py                                          │
│    hormone-calc compute --agent X --dispatch-id Y --result-file Z │
│      → reads observable state (state.json + journal + result)     │
│      → runs each trigger module's detect(observable) function     │
│      → emits trigger list to stdout, one trigger per line         │
│                                                                   │
│  src/hormone_calc/observable.py                                   │
│    ObservableState dataclass: agent, archetype, dispatch_id,      │
│    result, state, iteration, token_ratio, recent_dispatches,      │
│    quality_score_series, upstream_agent (derived), current_       │
│    hormones                                                       │
│                                                                   │
│  src/hormone_calc/config.py                                       │
│    DynamicsConfig — read from echelon-config.yml                  │
│    endocrine.dynamics block, fallback to DEFAULT_DYNAMICS         │
│                                                                   │
│  src/hormone_calc/upstream.py                                     │
│    derive_upstream(observable) — walks journal-index for the      │
│    most recent dispatch in this phase whose output_files appear   │
│    in current agent's context_pack                                │
│                                                                   │
│  src/hormone_calc/triggers/                                       │
│    verdict.py          → on_gate_pass | on_gate_fail | …          │
│    quality.py          → on_quality_improvement | …               │
│    dispatch_chain.py   → propagate_*, peer_accept/reject          │
│    budget_pressure.py  → hormone_update <agent> adr +X            │
│    iteration_pressure.py                                          │
│    task_complexity.py                                             │
│    innovate.py                                                    │
│    decay.py            → decay_hormones <agent>                   │
│                                                                   │
│  src/hormone_calc/output.py                                       │
│    serialize Trigger objects to one-per-line text                 │
└──────────────────────────────────────┬────────────────────────────┘
                                       │
┌──────────────────────────────────────▼────────────────────────────┐
│  endocrine.sh   (existing, unchanged — mutation primitives)       │
│  Called by the hook to apply each emitted trigger.                │
│  Every emitted trigger maps to an existing subcommand.            │
└───────────────────────────────────────────────────────────────────┘
```

**Properties:**
- **Calculator is a pure function:** takes Observable in, emits Triggers out. No side effects. Trivially testable.
- **Hook is dumb:** pipes Python output → bash subcommands → journal logs. Easy to inspect.
- **endocrine.sh is unchanged:** all delta magnitudes stay where they already live. Single source of truth.
- **commander.md change is minimal:** replace ~35 lines of narrative dispatch-protocol prose with ~12 lines invoking the hook as a NEVER-rule.

**Sole-writer contract preserved:** the bash hook runs *on behalf of* COMMANDER (it's part of the Post-Dispatch Protocol), so journal writes via `>>` redirection from the hook respect the commander.md §92-159 sole-writer contract. The Python calculator never writes to `reasoning-journal.jsonl` directly.

## Section 2 — Observable inputs

```python
@dataclass
class ObservableState:
    # --- about the just-completed dispatch ---
    agent: str                       # codename, e.g. "SAGE"
    dispatch_id: str                 # e.g. "D-007"
    result: dict                     # parsed echelon_result block
    archetype: str                   # from endocrine.sh get_archetype <agent>

    # --- about the squad-run state ---
    state: dict                      # full state.json
    iteration: int                   # state.iteration
    token_ratio: float               # state.token_ledger.total / (token_budget_k * 1000)
    autonomy_mode: str               # banzai | semi | guided

    # --- about recent history (last 50 journal entries) ---
    recent_dispatches: list[dict]
    quality_score_series: list[float]
    prior_verdict_for_agent: str | None
    upstream_agent: str | None       # derived deterministically; see upstream.py

    # --- about current hormone state ---
    current_hormones: dict[str, float]
```

| Field | Source |
|---|---|
| `state` | `.specify/squad/state.json` (or `ENDOCRINE_STATE_FILE` env) |
| `agent` / `dispatch_id` | CLI args from the hook |
| `result` | `--result-file <path>` — temp file with echelon_result YAML |
| `archetype` | `bash endocrine.sh get_archetype <agent>` |
| `recent_dispatches` | `.specify/squad/reasoning-journal.jsonl` — last 50 entries |
| `quality_score_series` | `state.quality_scores[*].overall` |
| `prior_verdict_for_agent` | scan recent_dispatches for last entry with `agent == X` |
| `upstream_agent` | `derive_upstream(observable)` — see `upstream.py` |
| `current_hormones` | `state.endocrine_state.agents.<agent>.hormones` |
| `token_ratio` | `state.token_ledger.total / (analysis.token_budget_k * 1000)` |

**Performance budget:** each `hormone-calc compute` completes in **<500 ms** for journals up to 10,000 entries. Most triggers are O(1) lookups; verdict-history scans bounded at N=50.

## Section 3 — Trigger detection rules

15 rules grouped into 6 categories (4 verdict, 2 quality, 4 dispatch-chain, 1 innovation, 1 always-on, 3 new dynamics). Each module under `src/hormone_calc/triggers/` implements `detect(observable: ObservableState) -> list[Trigger]`. Triggers compose — a single dispatch can fire many.

### A. Verdict-driven (uses existing handlers)

| Rule | Fires when | Emits |
|---|---|---|
| **T-GATE-PASS** | `result.verdict ∈ PASS_VERDICTS` | `on_gate_pass <agent>` |
| **T-GATE-FAIL** | `result.verdict ∈ FAIL_VERDICTS` | `on_gate_fail <agent>` |
| **T-REWORK** | Same agent had non-PASS verdict in last ≤3 dispatches AND current also non-PASS | `on_rework <agent>` |
| **T-LOW-CONFIDENCE** | `result.data.confidence < 0.5` OR `verdict ∈ SOFT_FAIL_VERDICTS` | `on_low_confidence <agent>` |

### B. Quality-driven (uses existing handlers)

| Rule | Fires when | Emits |
|---|---|---|
| **T-QUALITY-IMPROVE** | `quality_score_series[-1] - [-2] ≥ +0.05` (skip if < 2 entries) | `on_quality_improvement` |
| **T-QUALITY-REGRESS** | `quality_score_series[-1] - [-2] ≤ -0.05` (skip if < 2 entries) | `on_quality_regression` |

### C. Dispatch-chain (uses existing handlers)

If `upstream_agent is None`, all C rules skip.

| Rule | Fires when | Emits |
|---|---|---|
| **T-PROPAGATE-DOWNSTREAM** | `upstream_agent is not None` | `propagate_downstream <upstream> <agent>` |
| **T-CORTISOL-CONTAGION** | `upstream.cortisol > 0.8` | `propagate_cortisol_contagion <upstream> <agent>` |
| **T-PEER-ACCEPT** | `agent ∈ GATE_AGENTS` AND verdict ∈ PASS_VERDICTS | `on_peer_accept <upstream> <agent>` |
| **T-PEER-REJECT** | `agent ∈ GATE_AGENTS` AND verdict ∈ FAIL_VERDICTS | `on_peer_reject <upstream> <agent>` |

### D. Innovation (uses existing handler)

| Rule | Fires when | Emits |
|---|---|---|
| **T-INNOVATE-SUMMON** | `agent == "MAVERICK"` | `on_innovate_summon` |

### E. Always-on

| Rule | Fires when | Emits |
|---|---|---|
| **T-DECAY** | every dispatch | `decay_hormones <agent>` |

### F. NEW dynamics — configurable via `echelon-config.yml endocrine.dynamics`

```yaml
endocrine:
  ...
  dynamics:                 # NEW — driven by hormone-calc
    budget_pressure:
      # token_ratio = total_estimated / (token_budget_k * 1000)
      # Each band [a, b) adds the corresponding delta to current agent's adrenaline.
      bands:
        - { upto: 0.40, delta: 0.00 }
        - { upto: 0.60, delta: 0.02 }
        - { upto: 0.80, delta: 0.05 }
        - { upto: 0.95, delta: 0.10 }
        - { upto: 1.00, delta: 0.15 }
      critical_broadcast: 0.05   # extra broadcast_adrenaline when token_ratio >= 0.95

    iteration_pressure:
      # ratio = state.iteration / max_squad_iterations (default 10)
      bands:
        - { upto: 0.50, delta: 0.00 }
        - { upto: 0.75, delta: 0.03 }
        - { upto: 1.00, delta: 0.08 }

    task_complexity:
      # delta = (complexity - 0.5) * multiplier
      # complexity = archetype_base[archetype] + agent_bump.get(agent, 0), clamped [0, 1]
      multiplier: 0.15
      archetype_base:
        exploration: 0.40
        validation:  0.50
        feasibility: 0.60
        solution:    0.70
        build:       0.80
        innovation:  0.50
        learning:    0.30
        control:     0.40
      agent_bump:
        IMPLEMENTER: 0.10
        DEBUGGER:    0.15
        ARCHITECT:   0.10
        GATEKEEPER:  0.10
```

**Config loading semantics:**
- `hormone_calc.config.load(yaml_path)` returns a `DynamicsConfig` dataclass.
- If `endocrine.dynamics` is absent from config, fall back to a built-in `DEFAULT_DYNAMICS` constant with the same shape and the same numbers above.
- Tests can construct `DynamicsConfig(...)` directly — no YAML required.

### Verdict normalization (full sets)

```python
PASS_VERDICTS       = {"PASS", "APPROVED", "DONE", "COMPLETE", "STABLE"}
FAIL_VERDICTS       = {"FAIL", "CHANGES_REQUESTED", "REJECTED", "KILL", "INSTABILITY"}
SOFT_FAIL_VERDICTS  = {"DONE_WITH_CONCERNS", "DEFER", "NEEDS_CONTEXT", "BLOCKED"}
# Anything else → logged as unknown_verdict, treated as SOFT_FAIL.

GATE_AGENTS = {
    "SAGE", "CHECKPOINT", "GATEKEEPER", "SPEC_GUARD",
    "CODE_REVIEWER", "TEST_GUARDIAN", "VALIDATOR",
    "GUARDIAN", "MONITOR", "INTEGRATOR",
}
```

### Trigger ordering (deterministic)

When multiple triggers fire on one dispatch, the hook applies them in this fixed order:

1. **Decay** — pull current state back toward baseline
2. **F-dynamics** (budget, iteration, complexity) — environmental pressure
3. **C-dispatch-chain** (propagate_*, peer_*) — upstream effects
4. **A-verdict** (gate_pass/fail/rework/low_confidence) — outcome
5. **B-quality** (system-wide) — squad signal
6. **D-innovate-summon** — MAVERICK-specific

Within each category, alphabetical order by trigger name. Fully reproducible.

### Idempotency

Each dispatch is identified by its `dispatch_id`. The hook writes a sentinel to `state.json.endocrine_state.applied_dispatches[]` after firing all triggers. Re-runs for the same `dispatch_id` skip (no double-application).

### Per-trigger journal logging

For each trigger fired, the hook appends one journal entry:

```json
{
  "id": "RJ-NNN",
  "type": "endocrine_event",
  "agent": "COMMANDER",
  "phase": "<current>",
  "timestamp": "<ISO-8601>",
  "data": {
    "trigger": "on_gate_fail",
    "target": "IMPLEMENTER",
    "dispatch_id": "D-007",
    "source_event": "verdict=FAIL"
  }
}
```

### Cold-start

- First dispatch of a run: T-DECAY fires (no-op against fresh baseline state). F-dynamics fire normally. Other triggers skip (insufficient history).
- No journal entries yet → T-REWORK, T-QUALITY-* skip silently.
- No `applied_dispatches` field yet → hook creates it on first use.

### Trigger composition example

IMPLEMENTER returns `verdict: FAIL` on a rework attempt, with `token_ratio=0.7`, `iteration=7/10`, `upstream=SPEC_GUARD` (cortisol 0.9). Triggers fired in order:

```
decay_hormones IMPLEMENTER                        # E
hormone_update IMPLEMENTER adrenaline +0.05       # F1 budget moderate
hormone_update IMPLEMENTER adrenaline +0.03       # F2 iteration mid
hormone_update IMPLEMENTER norepinephrine +0.045  # F3 complexity
propagate_downstream SPEC_GUARD IMPLEMENTER       # C
propagate_cortisol_contagion SPEC_GUARD IMPLEMENTER  # C (upstream > 0.8)
on_gate_fail IMPLEMENTER                          # A: dopamine -0.20, cortisol +0.10
on_rework IMPLEMENTER                             # A: cortisol +0.10
on_low_confidence IMPLEMENTER                     # A: cortisol +0.20
```

Net IMPLEMENTER shift: cortisol +0.45 (huge), dopamine -0.20 + upstream-carry, adrenaline +0.08, norepinephrine +0.045. Decay applied first. Next dispatch sees high-cortisol + elevated-adrenaline state → triggers the build archetype's `adrenaline_high` overlay in the multi-line modifier from the archetype-coherence work.

## Section 4 — Output format + dispatch-time data flow

### Emission contract — one trigger per line, space-separated args

```
decay_hormones IMPLEMENTER
hormone_update IMPLEMENTER adrenaline +0.05
hormone_update IMPLEMENTER adrenaline +0.03
hormone_update IMPLEMENTER norepinephrine +0.045
propagate_downstream SPEC_GUARD IMPLEMENTER
propagate_cortisol_contagion SPEC_GUARD IMPLEMENTER
on_gate_fail IMPLEMENTER
on_rework IMPLEMENTER
on_low_confidence IMPLEMENTER
```

### Mapping table — emitted line → endocrine.sh subcommand

| Emitted | Hook executes |
|---|---|
| `on_gate_pass <A>` | `bash endocrine.sh on_gate_pass <A>` |
| `on_gate_fail <A>` | `bash endocrine.sh on_gate_fail <A>` |
| `on_rework <A>` | `bash endocrine.sh on_rework <A>` |
| `on_low_confidence <A>` | `bash endocrine.sh on_low_confidence <A>` |
| `on_quality_improvement` | `bash endocrine.sh on_quality_improvement` |
| `on_quality_regression` | `bash endocrine.sh on_quality_regression` |
| `on_innovate_summon` | `bash endocrine.sh on_innovate_summon` |
| `on_peer_accept <F> <T>` | `bash endocrine.sh on_peer_accept <F> <T>` |
| `on_peer_reject <F> <T>` | `bash endocrine.sh on_peer_reject <F> <T>` |
| `propagate_downstream <F> <T>` | `bash endocrine.sh propagate_downstream <F> <T>` |
| `propagate_cortisol_contagion <F> <T>` | `bash endocrine.sh propagate_cortisol_contagion <F> <T>` |
| `hormone_update <A> <hormone> <delta>` | `bash endocrine.sh update_hormone <A> <idx> <delta>` (hook maps name→index) |
| `broadcast_adrenaline <delta>` | `bash endocrine.sh broadcast_adrenaline <delta>` |
| `decay_hormones <A>` | `bash endocrine.sh decay_hormones <A>` |

### Dispatch-time sequence (end-to-end)

```
COMMANDER calls Agent tool
  ↓
Agent returns response with trailing ```echelon_result block
  ↓
Existing Post-Dispatch Protocol (commander.md §92-159):
   A. Parse echelon_result block
   B. Write journal entries
   C. Apply state.json state_updates
   D. Set last_dispatch.post_dispatch_complete: true
  ↓
NEW STEP E: invoke hormone-update hook
   bash scripts/bash/post-dispatch-hormone-update.sh \
     --agent {AGENT_CODENAME} \
     --dispatch-id {DISPATCH_ID} \
     --result-file {path}
  ↓
Hook:
   1. Check state.endocrine_state.applied_dispatches — skip if dispatch_id present
   2. hormone-calc compute   → trigger list
   3. For each trigger: translate to endocrine.sh subcommand, execute, log endocrine_event
   4. Atomically append dispatch_id to applied_dispatches[]
  ↓
COMMANDER proceeds to next routing decision
```

Crash recovery: each step is independently re-runnable. Idempotency check at step 1 prevents double-application; partial application is harmless because endocrine.sh's `update_hormone` clamps via existing circuit breakers (max change per cycle = 0.4).

### Commander.md integration — NEVER-rule replacement

Replace the narrative pre/post-dispatch endocrine sections (commander.md §566-600, ~35 lines) with:

```markdown
### Endocrine Post-Dispatch Hook — MANDATORY (replaces §566-600 narrative)

**NEVER complete the Post-Dispatch Protocol without firing the hormone-update
hook.** Do NOT decide which hormone events fire from prose judgment — the
hook is deterministic and authoritative.

Immediately after the standard Post-Dispatch Protocol (steps A–D) writes
`last_dispatch.post_dispatch_complete: true`, COMMANDER MUST run:

  bash scripts/bash/post-dispatch-hormone-update.sh \
    --agent {AGENT_CODENAME} \
    --dispatch-id {DISPATCH_ID} \
    --result-file {path to file containing echelon_result block}

NEVER substitute a hand-crafted `endocrine.sh on_*` invocation for this hook.
The squad-1778937725 incident is the canonical reason: COMMANDER was
prescribed to call decay_hormones / on_gate_pass / on_quality_* after every
dispatch and fired them zero times across many runs. Hand-authoring this
protocol recreates that failure mode.

**Graceful skip:** if `endocrine.enabled: false` in echelon-config.yml,
the hook itself no-ops and exits 0. Safe to always invoke.
```

Mirrors §0.1 (BUG-1 fix) and §0.6 (BUG-2 fix) — same hard-stop language, same incident-cited rationale.

## Section 5 — Testing strategy

### Unit tests — one per trigger module

`tests/unit/hormone_calc/` mirrors the package structure:

```
tests/unit/hormone_calc/
├── conftest.py                       # ObservableState fixtures
├── test_verdict_triggers.py          # 12 cases
├── test_quality_triggers.py          # 6 cases
├── test_dispatch_chain_triggers.py   # 10 cases
├── test_budget_pressure.py           # 7 cases: each band boundary + critical broadcast
├── test_iteration_pressure.py        # 5 cases
├── test_task_complexity.py           # 12 cases: archetype × agent_bump matrix samples
├── test_innovate.py                  # 2 cases
├── test_decay.py                     # 1 case
├── test_upstream_inference.py        # 6 cases: clean chain / fork / cold start / missing
└── test_observable.py                # 5 cases: state.json + journal + result-file parsing
```

~75 unit tests. Each: construct `ObservableState` fixture → call `detect()` → assert `list[Trigger]` matches expected.

### Integration tests

`tests/integration/test_hormone_calc_end_to_end.py`:

1. **End-to-end-single-dispatch**: synthetic state.json + journal + result file → `hormone-calc compute` subprocess → verify stdout trigger list line-for-line.
2. **Hook end-to-end**: same fixtures → bash hook → verify (a) state.json reflects deltas, (b) journal has expected `endocrine_event` entries, (c) `applied_dispatches` contains dispatch_id.
3. **Idempotency**: run hook twice for same dispatch_id → second no-ops.
4. **Crash recovery**: simulate mid-application crash → re-run → completes correctly.
5. **Disabled mode**: `endocrine.enabled: false` → hook exits 0 with no side effects.

### Regression test — existing endocrine suite

After implementation, run the full endocrine test suite (10 files, all currently green post-DEP-FIX T2). No regression. Specifically:
- `test-endocrine-archetype-consistency.sh`: must still pass; `applied_dispatches[]` addition doesn't break the consistency assertions.
- `test-endocrine-baselines-load.sh`: independent; baselines still load.
- `test-endocrine-multiline-modifier.sh`: independent; modifier emission unchanged.
- `test-endocrine-engine/phase2/phase3.sh`: must remain all-green.

### Live-run validation

Final acceptance: `echelon run "self test"` end-to-end. Verify in the resulting journal:
- `type:endocrine_event` entries per dispatch.
- Hormone state in state.json shifts visibly between dispatches (not frozen at baselines).
- A high-cortisol agent's next dispatch shows the new value in the multi-line modifier.

Deliverable proof: the dynamic layer is alive.

### Test fixtures

`tests/fixtures/hormone_calc/`:
- `state-fresh.json` — post-init, archetype baselines
- `state-mid-run.json` — iteration=5, token_ratio=0.65, mixed hormone values
- `state-near-budget-cap.json` — token_ratio=0.97, iteration=9
- `journal-clean-chain.jsonl` — SCOUT → SYNTHESIZER → SAGE
- `journal-fork.jsonl` — parallel dispatch fork
- `result-gate-pass.yaml`, `result-gate-fail.yaml`, `result-low-confidence.yaml`, `result-rework.yaml`
- `result-implementer-done.yaml`, `result-architect-blocked.yaml`

~12 small fixture files. Tests mix and match.

## Migration / sequencing

1. **Add `endocrine.dynamics` block** to `extension/echelon-config.yml` with default values per Section 3F.
2. **Build `src/hormone_calc/`** package — observable, config, upstream, triggers/, output. Unit-tested as each module is added.
3. **Integration test** — `hormone-calc compute` against synthetic fixtures.
4. **Build the hook** `scripts/bash/post-dispatch-hormone-update.sh`. Hook integration tests.
5. **Update commander.md** — replace narrative §566-600 with the NEVER-rule replacement from Section 4. Sync to deployed copies (`.specify/extensions/echelon/agents/control/commander.md` + `.claude/agents/speckit-echelon-commander.md`).
6. **Add `pyproject.toml` entry**: `hormone-calc = "hormone_calc.cli:main"` under `[project.scripts]`.
7. **Verify against existing test suite**: all green, no regression.
8. **Live-run validation**: `echelon run "self test"` produces visible hormone dynamics.

Order matters: steps 1-3 are pure additions (no behavior change at runtime). Steps 4-5 wire the hook into the dispatch flow, which IS a behavior change. Step 5's commander.md edit is the load-bearing change; without it, hook never fires.

The migration is incremental: steps 1-3 land independently. Step 4 lands. Then step 5 turns it on.

## Rollback

Three independently revertible paths:

- **F-dynamics regression** (budget/iteration/complexity behaving wrong): edit `echelon-config.yml endocrine.dynamics` magnitudes to zero or revert to known-good values. No code change required.
- **Hook regression** (firing wrong events): rollback the commander.md NEVER-rule edit, restore the prior narrative §566-600. Hook stops firing; behavior reverts to today's "static at baselines" state.
- **Calculator regression** (specific trigger module misbehaving): revert that module's commit on the branch. Other triggers continue firing.

Hard rollback: revert the commander.md edit (single commit) — hook never invoked, all behavior reverts to baseline-only static state.

## Out of scope (future work)

- **D7 Phase-1 / Phase-3 enforcement.** `endocrine.phase` config still doesn't gate behavior anywhere; the calculator runs full Phase-3 dynamics regardless.
- **D8 Per-agent baseline overrides.** Some agents may want a baseline divergent from their archetype. Out of scope.
- **D10 Per-dispatch hormone snapshot in reasoning journal.** This design's `endocrine_event` entries are PER-EVENT; a per-dispatch SNAPSHOT (full hormone state of all 41 agents at dispatch time) would be additional. Considered useful for AUDITOR but adds journal volume — defer.
- **D11 `definition.yaml` endocrine integration.** Phase graph remains endocrine-agnostic. The hook is invoked from commander.md, not from `definition.yaml` directly.
- **Cross-run hormone persistence.** Hormone state resets to archetype baselines on every `endocrine.sh init`. A future design could let high-confidence agents start their next run with slightly elevated serotonin etc., but that's a separate cross-run-memory project.
- **Property-based testing.** Bounded input space here doesn't justify the `hypothesis` dependency. Revisit if invariants emerge.

## Open questions

None at this stage. Decisions settled. Implementation-plan stage may surface details (exact bash quoting in the hook, exact journal-index query for upstream inference) but no design-level questions remain.
