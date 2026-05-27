# Design: Squad Harness — Deterministic Routing for the Pre-Code Squad Run

**Date:** 2026-05-18
**Status:** Approved — ready for implementation plan

## Problem

The pre-code squad run (`echelon run`) uses an LLM (COMMANDER) as the routing engine. COMMANDER reads `workflow/definition.yaml` and decides which phase to execute next, when to stop iterating, and which transitions to follow. This produces a class of bugs where COMMANDER invents justifications to skip mandatory phases — most recently skipping `phase3-consensus` entirely using a fabricated "EVOI grounds" escape term.

The build harness (`src/harness/ralph.py`) solves the equivalent problem for the build phase with a Python state machine. Phase routing there is deterministic code; only the build work itself is LLM-executed. This design applies the same pattern to the pre-code squad run.

---

## Architecture

```
echelon run <spec_id>          /speckit.echelon.run
      │                               │
      └──────────────┬────────────────┘
                     ▼
             SquadController                    src/harness/squad.py
             (Python, ~600 lines)
                     │
         ┌───────────┼───────────────┐
         │           │               │
   PhaseGraph   StateStore     SquadCliProvider
  (reads           (reads/          (extends
  definition.yaml) writes           ClaudeCliProvider,
                  state.json)       adds exec_agent())
         │
         ▼
   PhaseExecutor                    dispatch, wait, parse
   ├── AgentExecutor                type: agent
   ├── StagedParallelExecutor       type: staged_parallel
   ├── ConditionalSequentialExec    type: conditional_sequential
   ├── CommanderInternalExecutor    type: commander_internal
   └── HumanGateExecutor            type: human_gate
         │
         ▼
   COMMANDER (slimmed, ~150 lines)  dispatched only for:
                                    escalation triage,
                                    contradictory outputs,
                                    complex context assembly,
                                    human gate (guided mode)
```

**Data flow per phase:**
1. `SquadController` reads `state.json` → current phase id
2. `PhaseGraph` looks up the phase node in `definition.yaml`
3. Appropriate `PhaseExecutor` reads the phase's `spec_file`, assembles context pack, calls `SquadCliProvider.exec_agent()`
4. `SquadCliProvider` runs `<cli> -p <prompt>` as subprocess, streams output, captures `echelon_result:` YAML
5. `SquadController` evaluates `transitions[].condition` against `state.json` fields → next phase id
6. `StateStore` writes new phase + `last_dispatch` to `state.json`
7. Repeat until DONE or blocked

**Entry points:**
- `echelon run <spec_id>` CLI → `_cmd_run()` in `cli.py` → `SquadController.run()`
- `/speckit.echelon.run` slash command → `echelon.run.md` (~15 lines) → `bash echelon run $ARGUMENTS`

**Migration:** `echelon.run.md` is replaced entirely — clean break, no dual path.

---

## New files

| Path | Purpose |
|---|---|
| `src/harness/squad.py` | `SquadController` — main execution loop (~600 lines) |
| `src/harness/squad_state.py` | `StateStore` — atomic state.json reads/writes |
| `src/harness/phase_graph.py` | `PhaseGraph` — loads definition.yaml into typed nodes |
| `src/harness/condition_evaluator.py` | `ConditionEvaluator` — evaluates condition strings against state |
| `src/harness/squad_provider.py` | `SquadCliProvider` + `SquadAgentResult` |
| `tests/kernel/test_condition_evaluator.py` | Unit tests for condition evaluation |
| `tests/kernel/test_phase_graph.py` | Unit tests for phase graph loading |
| `tests/kernel/test_squad_state.py` | Unit tests for state store |
| `tests/integration/test_squad_controller.py` | Integration tests with mocked provider |
| `tests/unit/test-unit-squad-registry.sh` | Structural validation (bash) |

## Modified files

| Path | Change |
|---|---|
| `src/echelon/cli.py` | Add `_cmd_run()`, add `run` to CLI + SKILL_MAP |
| `extension/commands/echelon.run.md` | Replace with ~15-line launcher |
| `extension/agents/control/commander.md` | Slim from ~800 → ~150 lines |
| `src/harness/llm_provider.py` | Rename `ClaudeCliProvider` → `AICodingCliProvider` (final step) |
| `src/harness/ralph.py` + `coordinator.py` | Update import after rename |

---

## Component specifications

### `SquadController` — `src/harness/squad.py`

```python
class SquadController:
    def __init__(self, config: HarnessConfig, provider: SquadCliProvider,
                 state_store: StateStore, phase_graph: PhaseGraph): ...

    def run(self, user_message: str) -> SquadResult:
        self._init_state(user_message)
        while True:
            phase = self._state_store.current_phase()
            if phase in ("DONE", "terminal-blocked"):
                return SquadResult.from_state(self._state_store.load())
            if self._budget_exhausted():
                self._force_finalize("token_budget_exhausted")
                return SquadResult.from_state(self._state_store.load())
            if self._cancel_requested():
                return SquadResult.interrupted()
            node = self._phase_graph.get(phase)
            result = self._executors[node.type].execute(node, self._state_store)
            next_phase = self._evaluate_transitions(node, result)
            self._state_store.advance(phase, next_phase, result)
```

**Resumption:** On `echelon run` with existing `state.json` carrying `status: in_progress`, reads `current_phase()` and continues. No `post_dispatch_complete` sentinel needed — harness is not an LLM, no context compaction.

**Interruption:** SIGINT sets `cancel_requested` flag in `state.json`. Checked before each phase.

**Budget tracking:** `StateStore.increment_token_usage()` called after each `exec_agent()`. Checked against `echelon-config.yml budget.token_budget_k`.

---

### Phase executors

**`AgentExecutor`** (`type: agent`):
1. Evaluate `pre_dispatch` entries in order — check condition against state.json, `exec_agent()` if met
2. Assemble context pack: read `spec_file`, each `context_pack` file on disk, and `agent` .md file
3. Build prompt: agent file + spec_file + context pack
4. `exec_agent()` → `SquadAgentResult`
5. Apply `result.state_updates` to state.json

**`StagedParallelExecutor`** (`type: staged_parallel`, only `phase3-consensus`):
- Stage 1: `ThreadPoolExecutor(max_workers=2)` — submit WHY3 and ASSESS2 concurrently, wait for both
- Stage 2: after both complete, read `implementability-report.md` (BLOCKED if absent), dispatch PLAN2
- This phase cannot be skipped — there is no code path that bypasses Stage 1

**`ConditionalSequentialExecutor`** (`type: conditional_sequential`):
- For each agent entry: evaluate `entry.condition` against state.json, dispatch if met

**`CommanderInternalExecutor`** (`type: commander_internal`):
- Execute spec_file instructions via Bash subprocesses (mkdir, state.json init, belief-freshness-check.sh, constitution.md check)
- No LLM dispatch

**`HumanGateExecutor`** (`type: human_gate`):
- `banzai` / `semi`: auto-proceed, write `gate_result: auto_approved`
- `guided`: print checkpoint summary to terminal, read stdin

**COMMANDER judgment dispatch (any executor)**:
Any executor calls `self._judgment.dispatch(context, reason)` when:
- Agent returns BLOCKED
- Stage 1 agents produce contradictory verdicts
- `ConditionEvaluator` returns `None` (unrecognised condition)
- Human gate in guided mode

COMMANDER receives: phase id, trigger type, 2–3 relevant artifact files, journal slice. Returns `JudgmentResult(action, reasoning)`.

---

### `SquadAgentResult` and `SquadCliProvider` — `src/harness/squad_provider.py`

```python
@dataclass
class SquadAgentResult:
    exit_code: int
    echelon_result: dict | None   # parsed echelon_result: YAML block; None if absent
    raw_output: str
    duration_ms: int
    timed_out: bool

    @property
    def verdict(self) -> str | None: ...
    @property
    def state_updates(self) -> dict: ...
    @property
    def blocked(self) -> bool: ...
```

```python
class SquadCliProvider(ClaudeCliProvider):
    def exec_agent(self, project_root: str, prompt: str,
                   timeout_ms: int | None = None) -> SquadAgentResult:
        # Inherits _build_cmd() — no changes to CLI selection logic
        # claude: _run_streaming_captured() (prints live + captures text)
        # copilot/opencode: _run_plain_captured() (captures stdout)
        # Calls _extract_echelon_result(raw) on captured text
```

`_extract_echelon_result(raw)`: regex scan for `echelon_result:` block (fenced or bare), `yaml.safe_load`, return dict or None.

For claude's `--output-format stream-json`: `_run_streaming_captured` variant of the existing `_run_streaming` that accumulates `text` event payloads alongside live printing. Full text available after `proc.wait()`.

---

### `StateStore` — `src/harness/squad_state.py`

Atomic writes (write to `.tmp`, rename). Wraps `.specify/squad/state.json`.

```python
class StateStore:
    def current_phase(self) -> str
    def load(self) -> dict
    def advance(self, from_phase, to_phase, result: SquadAgentResult) -> None
    def set_blocked(self, reason: str) -> None
    def set_cancel_requested(self) -> None
    def is_cancel_requested(self) -> bool
    def token_usage(self) -> int
    def increment_token_usage(self, tokens: int) -> None
```

`last_dispatch` written by `advance()`:
```json
{
  "phase_id": "phase1-discover",
  "agent": "speckit-echelon-scout",
  "completed_at": "2026-05-18T...",
  "verdict": "DONE"
}
```

---

### `PhaseGraph` — `src/harness/phase_graph.py`

```python
@dataclass
class PhaseNode:
    id: str
    type: str                  # agent | staged_parallel | conditional_sequential | ...
    spec_file: str | None
    agent: str | None
    agents: list[dict]         # staged_parallel / conditional_sequential
    context_pack: list[str]
    pre_dispatch: list[dict]
    transitions: list[dict]    # [{to, condition}, ...]

class PhaseGraph:
    def __init__(self, definition_path: Path): ...
    def get(self, phase_id: str) -> PhaseNode
    def entry_phase(self) -> str
```

---

### `ConditionEvaluator` — `src/harness/condition_evaluator.py`

Evaluates `condition:` strings from `transitions[]` against state.json. No LLM.

| Pattern | Evaluation |
|---|---|
| `always` | `True` |
| `verdict = DONE` | `result.verdict == "DONE"` |
| `mode = brownfield` | `state["mode"] == "brownfield"` |
| `coverage_pct >= coverage_threshold` | numeric comparison of state fields |
| `quality_gates.pass OR convergence_detected` | reads `state["convergence_detected"]` |
| `why3-verdict = PASS AND assess2-verdict = PASS` | reads two state fields |
| `iteration >= max_iterations` | numeric comparison |
| `autonomy in [semi, banzai]` | membership check |

Returns `None` for unrecognised conditions → triggers COMMANDER judgment dispatch.
Coverage of all conditions in `definition.yaml` verified by scanning the YAML during implementation.

---

### `echelon.run.md` — 15-line launcher

```markdown
---
name: speckit.echelon.run
description: "Full autonomous cognitive squad run"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Launch

```bash
echelon run $ARGUMENTS
```

This command delegates entirely to the squad harness (`src/harness/squad.py`).
The harness drives phase routing deterministically. COMMANDER is dispatched
only for judgment calls (escalation, contradiction, human gate in guided mode).

Monitor progress: `.specify/squad/state.json` and `.specify/squad/reasoning-journal.jsonl`
```

---

### Slimmed COMMANDER — `extension/agents/control/commander.md`

Target: ~150 lines (from ~800). What remains:

| Section | Status |
|---|---|
| Role definition | ✅ keep |
| NEVER rules 1–11 | ✅ keep (tightened) |
| Post-Dispatch Protocol (journal writes) | ✅ keep |
| Evidence hierarchy | ✅ keep |
| Conflict resolution (Toulmin model) | ✅ keep |
| Human escalation procedure | ✅ keep |
| Journal entry schema | ✅ keep |
| 7-step execution loop | ❌ remove — harness owns the loop |
| Convergence rules (Rules 1–6) | ❌ remove — phase spec files + ConditionEvaluator |
| Pre-dispatch gate prose | ❌ remove — harness runs pre_dispatch deterministically |
| Endocrine system dispatch | ❌ remove — harness calls endocrine.sh directly |
| KB read/write protocol | ❌ remove — harness calls kb-*.sh directly |
| Token ledger management | ❌ remove — StateStore owns token tracking |

---

### `AICodingCliProvider` rename (final step)

After squad harness is working and tests pass:
- `ClaudeCliProvider` → `AICodingCliProvider` (rename class and file `llm_provider.py` → `ai_coding_provider.py`)
- `SquadCliProvider` inherits from `AICodingCliProvider`
- `ralph.py`, `coordinator.py` updated to import from new name
- Single commit, no behaviour change

---

## Testing

### Unit tests (pytest, no LLM)

**`tests/kernel/test_condition_evaluator.py`:**
```python
def test_always_returns_true()
def test_verdict_done()
def test_mode_brownfield()
def test_numeric_comparison_gte()
def test_boolean_and_or()
def test_autonomy_membership()
def test_unknown_condition_returns_none()
def test_iteration_limit()
```

**`tests/kernel/test_phase_graph.py`:**
```python
def test_loads_all_phases()
def test_get_unknown_phase_raises()
def test_staged_parallel_node_has_two_stage1_agents()
def test_pre_dispatch_conditions_parsed()
```

**`tests/kernel/test_squad_state.py`:**
```python
def test_advance_writes_last_dispatch()
def test_resume_reads_current_phase()
def test_cancel_requested_flag()
def test_token_budget_exhausted()
def test_atomic_write_no_partial_state()
```

### Integration tests (mocked provider)

**`tests/integration/test_squad_controller.py`** — mock `SquadCliProvider`, canned `SquadAgentResult` fixtures:

```python
def test_full_greenfield_run_reaches_done()
def test_staged_parallel_dispatches_both_stage1_agents()
def test_consensus_cannot_be_skipped()      # regression test — most important
def test_resume_from_interrupted_phase()
def test_budget_exhaustion_triggers_finalize()
def test_blocked_agent_dispatches_commander()
def test_condition_none_dispatches_commander()
```

`test_consensus_cannot_be_skipped`: mock WHY3 + ASSESS2 return PASS, assert PLAN2 is dispatched before `checkpoint-plan`. Test fails if any path skips `phase3-consensus`.

### Structural validation

**`tests/unit/test-unit-squad-registry.sh`** (bash):
- All phase types in definition.yaml have a registered executor
- ConditionEvaluator covers all conditions present in definition.yaml
- `echelon.run.md` ≤ 20 lines
- `commander.md` ≤ 200 lines
- No remaining `ClaudeCliProvider` references after rename

---

## Out of scope

- Visual validation (VisualRalphController) — no equivalent in pre-code run
- Review loop (ReviewLoopController) — no equivalent in pre-code run
- Multi-strategy fanout (coordinator.py) — squad run is single-strategy; parallel squad strategies are a future option
- Changes to the build harness — ralph.py, coordinator.py are untouched except for the AICodingCliProvider rename
