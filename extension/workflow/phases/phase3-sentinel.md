# Phase: phase3-sentinel
# Source: echelon.run.md §9 — TEST speckit-echelon-architect (ARCHITECT) Phase
# Agent: speckit-echelon-sentinel (SENTINEL)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-sentinel (SENTINEL)

## 9. TEST speckit-echelon-architect (ARCHITECT) Phase (Mandatory)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `data-model.md`
- `spec.md` (acceptance criteria)
- `contracts/`
- `quality-gates.md` — specifically the "Testability Sub-Metrics" section (hard_constraint_ratio, constraint_density, negative_space_coverage) for testability-informed test strategy
- `reasoning-journal.jsonl`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include plan.md, data-model.md, spec.md, contracts/, quality-gates.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are SENTINEL. Read agents/solution/sentinel.md for your complete protocol.
  Produce a comprehensive test strategy from plan.md + data-model.md + spec.md acceptance criteria. Use the testability sub-metrics from quality-gates.md (hard_constraint_ratio, constraint_density, negative_space_coverage) to identify which testability dimension is weakest and prioritize test effort accordingly. Map every acceptance criterion to a test approach. Define the test pyramid. Identify boundary value cases. If acceptance criteria have no testable form, flag them for routing back to speckit-echelon-cartographer (CARTOGRAPHER). Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.jsonl`.
  </instructions>
  ```

- **description:** "speckit-echelon-sentinel (SENTINEL): testability-informed test strategy and coverage mapping"

### Precondition: `plan.md` Availability

`plan.md` is the canonical input to speckit-echelon-sentinel (SENTINEL). It is produced by speckit-echelon-architect (ARCHITECT) in phase3-how.

- **If `plan.md` exists** → proceed normally with the full context pack.
- **If `plan.md` is absent** (consequence of speckit-echelon-architect (ARCHITECT) omitting it — see Medium issue #33 in [docs/echelon-run-analysis-05-08.md](../../../../docs/echelon-run-analysis-05-08.md)) → read `architecture.md` as a proxy and append a `degraded_input` journal entry:

  ```json
  {"type": "degraded_input", "agent": "speckit-echelon-sentinel (SENTINEL)", "missing_artifact": "plan.md", "fallback": "architecture.md", "phase": "phase3-sentinel"}
  ```

  Always proceed with reduced confidence. Do not block. A future hardening will route back to phase3-how when this happens; for now speckit-echelon-sentinel (SENTINEL) falls back gracefully.

### Expected Outputs — ALL THREE REQUIRED

The phase produces exactly three files in `specs/{NNN}-{feature}/`. Skipping any of them is a phase failure.

- `test-strategy.md` — overall strategy, pyramid, prioritization
- `test-architecture.md` — per-module test layout, harness configuration, fixture topology
- `coverage-map.md` — every acceptance criterion → test approach mapping

**Verification (run before transition):**

```bash
for f in test-strategy.md test-architecture.md coverage-map.md; do
  [ -f "specs/${SPEC_DIR}/$f" ] || { echo "ERROR: speckit-echelon-sentinel (SENTINEL) missing $f" >&2; exit 1; }
done
```

### Gate Check

If TEST speckit-echelon-architect (ARCHITECT) flags untestable acceptance criteria → route back to WHAT for amendment. Increment iteration. Check limits.

**MANDATORY — run before transitioning to phase3-plan:**

```bash
# Budget: definition.yaml phases[phase3-specialists].timing_window_transition.open_budget_seconds = 2400
# Ensure phase3-solution is open (idempotent — skips if already started)
bash "${ECHELON_EXT}/scripts/bash/phase-timing.sh" start_phase phase3-solution 2400
```

phase3-solution stays open through PLAN. It closes in phase3-plan before consensus dispatch.

**Transition:** `phases[phase3-plan]` — see `workflow/definition.yaml`
