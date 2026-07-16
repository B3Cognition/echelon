# Phase: phase1-modeler
# Source: echelon.run.md §2b.1 — Dispatch speckit-echelon-modeler (MODELER)
# Agent: speckit-echelon-modeler (MODELER)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-modeler (MODELER)

## 2b.1 Dispatch speckit-echelon-modeler (MODELER) — Initial Codebase Map

Dispatch speckit-echelon-modeler (MODELER) to build the initial queryable codebase map from speckit-echelon-synthesizer (SYNTHESIZER)'s output. This gives speckit-echelon-architect (ARCHITECT) a pre-built entity graph instead of requiring re-analysis.

**Agent:** speckit-echelon-modeler (MODELER)

**Input context pack:**

- `${STAGING_DIR}/mental-model.md` (unified speckit-echelon-synthesizer (SYNTHESIZER) entity model)
- `${STAGING_DIR}/boundaries.md` (unified system boundary map)
- `${STAGING_DIR}/contradictions-and-gaps.md` (cross-source contradiction and gap analysis)
- `${STAGING_DIR}/` (all discovery and synthesis artifacts)
- `extension/templates/mental-model-code-template.md`
- Codebase file structure (from `state.json.mode`; for brownfield, also include the immutable `state.json.published_re_context` snapshot when attached)

**Output required:** `${STAGING_DIR}/mental-model-code.md` using the provided template — entity graph, contract map, data flow trace, and invariants list.

**Verdict:** Must be `COMPLETE`. If speckit-echelon-modeler (MODELER) returns any invariant violations in its output, speckit-echelon-commander (COMMANDER) logs them as ALERT-level journal entries but does NOT block — the map is new and violations may be expected at this stage.

**State update:** Before dispatch, return the standard Pre-Dispatch Protocol metadata in `echelon_result.state_updates`, including the full `last_dispatch` object because harness state updates are shallow top-level merges:

```yaml
last_dispatch:
  agent: "speckit-echelon-modeler (MODELER)"
```

**Transition:** `phases[phase1-tracker]` — see `workflow/definition.yaml`
