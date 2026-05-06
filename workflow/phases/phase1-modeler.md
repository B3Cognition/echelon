# Phase: phase1-modeler
# Source: echelon.run.md §2b.1 — Dispatch MODELER
# Agent: MODELER
# Read by: COMMANDER before dispatching MODELER

## 2b.1 Dispatch MODELER — Initial Codebase Map

Dispatch MODELER to build the initial queryable codebase map from SYNTHESIZER's output. This gives ARCHITECT a pre-built entity graph instead of requiring re-analysis.

**Agent:** MODELER

**Input context pack:**

- `.specify/squad/synthesis.md` (SYNTHESIZER output)
- `.specify/squad/staging/` (all discovery artifacts)
- Codebase file structure (from `state.json.mode`: for brownfield, also include `state.json.golddigger_artifacts`)

**Output required:** `.specify/squad/mental-model-code.md` — entity graph, contract map, data flow trace, and invariants list.

**Verdict:** Must be `COMPLETE`. If MODELER returns any invariant violations in its output, COMMANDER logs them as ALERT-level journal entries but does NOT block — the map is new and violations may be expected at this stage.

**State update:** Set `state.json.last_dispatch.agent` to `"MODELER"` using standard Pre-Dispatch Protocol before dispatching.

**Transition:** `phases[phase1-tracker]` — see `workflow/definition.yaml`
