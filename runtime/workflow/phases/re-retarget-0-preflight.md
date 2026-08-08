# Phase: re-retarget-0-preflight
# Read by: echelon.commander (COMMANDER)
# Type: commander_internal

## Preflight checks

### 1. analysis.json exists
The harness verifies `{state.output_dir}/analysis.json`. If it is absent, stop
with: "Run Echelon reverse engineering first."

### 2. Strategic stubs exist
The harness verifies that `re/workspace/strategy/constitution.md` exists. If it
is absent, stop with: "Run Echelon reverse engineering first to generate
strategic artifacts."

### 3. Inventory unresolved decisions

The harness calls its retarget marker discovery over the four canonical
strategy files:

- `re/workspace/strategy/constitution.md`
- `re/workspace/strategy/migration-strategy.md`
- `re/workspace/strategy/risk-matrix.md`
- `re/workspace/strategy/gap-analysis.md`
- `re/workspace/strategy/adrs/**/*.md`

It supplies a sorted
inventory containing `path`, `line`, `occurrence`, and `context` for every
exact `[REQUIRES INPUT]` marker.

Report its count to the user: "Found {N} decisions needing human input."

Preflight complete. Advance to `re-retarget-1-input`.
