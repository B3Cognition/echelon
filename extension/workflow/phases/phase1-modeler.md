# Phase: phase1-modeler
# Source: echelon.run.md §2b.1 — Dispatch speckit-echelon-modeler (MODELER)
# Agent: speckit-echelon-modeler (MODELER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-modeler (MODELER)

## 2b.1 Dispatch speckit-echelon-modeler (MODELER) — Initial Codebase Map

Dispatch speckit-echelon-modeler (MODELER) to build the initial queryable codebase map from speckit-echelon-synthesizer (SYNTHESIZER)'s output. This gives speckit-echelon-architect (ARCHITECT) a pre-built entity graph instead of requiring re-analysis.

**Agent:** speckit-echelon-modeler (MODELER)

**Input context pack:**

- `.specify/squad/synthesis.md` (speckit-echelon-synthesizer (SYNTHESIZER) output)
- `.specify/squad/staging/` (all discovery artifacts)
- Codebase file structure (from `state.json.mode`: for brownfield, also include `state.json.golddigger_artifacts`)

**Output required:** `.specify/squad/mental-model-code.md` — entity graph, contract map, data flow trace, and invariants list.

**Verdict:** Must be `COMPLETE`. If speckit-echelon-modeler (MODELER) returns any invariant violations in its output, speckit-echelon-commander (COMMANDER) logs them as ALERT-level journal entries but does NOT block — the map is new and violations may be expected at this stage.

**State update:** Set `state.json.last_dispatch.agent` to `"speckit-echelon-modeler (MODELER)"` using standard Pre-Dispatch Protocol before dispatching.

**Transition:** `phases[phase1-tracker]` — see `workflow/definition.yaml`
