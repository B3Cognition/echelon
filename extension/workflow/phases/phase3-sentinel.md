# Phase: phase3-sentinel
# Source: echelon.run.md §9 — TEST echelon-architect (ARCHITECT) Phase
# Agent: echelon-sentinel (SENTINEL)
# Read by: echelon-commander (COMMANDER) before dispatching echelon-sentinel (SENTINEL)

## 9. TEST echelon-architect (ARCHITECT) Phase (Mandatory)

### Context Pack Assembly

Read and include in the subagent prompt:

- `plan.md` + `data-model.md`
- `spec.md` (acceptance criteria)
- `contracts/`
- `quality-gates.md` — specifically the "Testability Sub-Metrics" section (hard_constraint_ratio, constraint_density, negative_space_coverage) for testability-informed test strategy
- `extension/templates/test-strategy-template.md`
- `extension/templates/test-architecture-template.md`
- `extension/templates/coverage-map-template.md`
- `reasoning-journal.jsonl`

### Dispatch

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include plan.md, data-model.md, spec.md, contracts/, quality-gates.md, sentinel output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are SENTINEL. Read agents/solution/sentinel.md for your complete protocol. When Product Input Contract paths are present, confirm each included `IN-REQ-*` unit reaches at least one mapped acceptance criterion; return corrective `product_input_updates` using the exact canonical fields `input_unit_id`, `disposition`, `rationale`, `spec_ids`, `task_ids`, and `targets`, rather than editing the ledger. PLAN has not run yet, so always return `task_ids: []`; ORCHESTRATOR adds task ownership in the next phase.
  Produce a comprehensive test strategy from plan.md + data-model.md + spec.md acceptance criteria. Use the testability sub-metrics from quality-gates.md (hard_constraint_ratio, constraint_density, negative_space_coverage) to identify which testability dimension is weakest and prioritize test effort accordingly. Map every acceptance criterion to a test approach. Define the test pyramid. Identify boundary value cases. If acceptance criteria have no testable form, flag them for routing back to echelon-cartographer (CARTOGRAPHER). Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "echelon-sentinel (SENTINEL): testability-informed test strategy and coverage mapping"

### Precondition: `plan.md` Availability

`plan.md` is the canonical input to echelon-sentinel (SENTINEL). It is produced by echelon-architect (ARCHITECT) in phase3-how.

- **If `plan.md` exists** → proceed normally with the full context pack.
- **If `plan.md` is absent** → this is a phase failure in phase3-how. Return a
  `BLOCKED` verdict naming the missing artifact so COMMANDER/harness can repair or
  replay phase3-how. Never substitute `architecture.md`: doing so would create a
  test strategy against an incomplete implementation contract.

### Expected Outputs — ALL THREE REQUIRED

The phase produces exactly three files in `{spec_dir}/`. Skipping any of them is a phase failure.

- `test-strategy.md` — overall strategy, pyramid, prioritization
- `test-architecture.md` — per-module test layout, harness configuration, fixture topology
- `coverage-map.md` — every acceptance criterion → test approach mapping

**Verification (run before transition):**

```bash
for f in test-strategy.md test-architecture.md coverage-map.md; do
  [ -f "{spec_dir}/$f" ] || { echo "ERROR: echelon-sentinel (SENTINEL) missing $f" >&2; exit 1; }
done
```

### Gate Check

If TEST echelon-architect (ARCHITECT) flags untestable acceptance criteria → route back to WHAT for amendment. Increment iteration. Check limits.

The controller-owned `phase3-solution` timing window remains open through PLAN.
It closes after successful `phase3-plan` execution before deterministic
Understanding and consensus dispatch.

**Transition:** `phases[phase3-plan]` — see `workflow/definition.yaml`
