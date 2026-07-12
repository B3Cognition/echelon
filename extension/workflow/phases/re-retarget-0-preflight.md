# Phase: re-retarget-0-preflight
# Read by: speckit-echelon-commander (COMMANDER)
# Type: commander_internal

## Preflight checks

### 1. analysis.json exists
Read `{state.output_dir}/analysis.json` using Read tool. If not found: HARD STOP — "Run /speckit.echelon.re-extract first."

### 2. Strategic stubs exist
Check that `re/workspace/strategy/constitution.md` exists (created by re-extract Phase 7). If not found: HARD STOP - "Run /speckit.echelon.re-extract first to generate strategic artifacts."

### 3. Count [REQUIRES INPUT] markers

```bash
grep -r "\[REQUIRES INPUT\]" re/workspace/strategy/constitution.md re/workspace/strategy/migration-strategy.md re/workspace/strategy/risk-matrix.md re/workspace/strategy/gap-analysis.md re/workspace/strategy/adrs/ 2>/dev/null | wc -l
```

Report count to user: "Found {N} decisions needing human input."

Preflight complete. Advance to `re-retarget-1-input`.
