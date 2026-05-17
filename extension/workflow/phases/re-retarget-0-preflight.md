# Phase: re-retarget-0-preflight
# Read by: speckit-echelon-commander (COMMANDER)
# Type: commander_internal

## Preflight checks

### 1. analysis.json exists
Read `.specify/echelon/re/analysis.json` using Read tool. If not found: HARD STOP — "Run /speckit.echelon.re-extract first."

### 2. Strategic stubs exist
Check that `constitution.md` exists (created by re-extract Phase 7). If not found: HARD STOP — "Run /speckit.echelon.re-extract first to generate strategic artifacts."

### 3. Count [REQUIRES INPUT] markers

```bash
grep -r "\[REQUIRES INPUT\]" constitution.md migration-strategy.md risk-matrix.md gap-analysis.md adrs/ 2>/dev/null | wc -l
```

Report count to user: "Found {N} decisions needing human input."

Preflight complete. Advance to `re-retarget-1-input`.
