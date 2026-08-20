# Phase: phase1-modeler
# Source: echelon.run.md §2b.1 — Dispatch echelon.modeler (MODELER)
# Agent: echelon.modeler (MODELER)
# Read by: echelon.commander (COMMANDER) before dispatching echelon.modeler (MODELER)

## 2b.1 Dispatch echelon.modeler (MODELER) — Initial Codebase Map

Dispatch echelon.modeler (MODELER) to build the initial queryable codebase map from echelon.synthesizer (SYNTHESIZER)'s output. This gives echelon.architect (ARCHITECT) a pre-built entity graph instead of requiring re-analysis.

Write canonical Phase A artifacts under `{spec_dir}` (`ACTIVE_SPEC_DIR`).
`${STAGING_DIR}` is reserved for controller inputs and transient dispatch
material; do not place canonical artifacts there.

**Agent:** echelon.modeler (MODELER)

**Input context pack:**

- `{spec_dir}/mental-model.md` (unified echelon.synthesizer (SYNTHESIZER) entity model)
- `{spec_dir}/boundaries.md` (unified system boundary map)
- `{spec_dir}/contradictions-and-gaps.md` (cross-source contradiction and gap analysis)
- `{spec_dir}/` (all discovery and synthesis artifacts)
- `.echelon/runtime/templates/mental-model-code-template.md`
- Codebase file structure (from `state.json.mode`; for brownfield, also include the immutable `state.json.published_re_context` snapshot when attached)

**Output required:** `{spec_dir}/mental-model-code.md` using the provided template — entity graph, contract map, data flow trace, and invariants list.

**Verdict:** Must be `COMPLETE`. If echelon.modeler (MODELER) returns any invariant violations in its output, echelon.commander (COMMANDER) logs them as ALERT-level journal entries but does NOT block — the map is new and violations may be expected at this stage.

**State update:** Before dispatch, return the standard Pre-Dispatch Protocol metadata in `echelon_result.state_updates`, including the full `last_dispatch` object because harness state updates are shallow top-level merges:

```yaml
last_dispatch:
  agent: "echelon.modeler (MODELER)"
```

**Transition:** `phases[phase1-tracker]` — see `workflow/definition.yaml`
