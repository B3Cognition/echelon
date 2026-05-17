# Phase: re-planning-0-preflight
# Read by: speckit-echelon-commander (COMMANDER)
# Type: commander_internal

## Preflight checks

### 1. constitution.md exists
Read `constitution.md` with Read tool. If not found: HARD STOP — "Run /speckit.echelon.re-retarget first to fill target decisions."

### 2. No unresolved [REQUIRES INPUT] markers

```bash
grep -r "\[REQUIRES INPUT\]" constitution.md migration-strategy.md risk-matrix.md gap-analysis.md adrs/ 2>/dev/null | wc -l
```

If count > 0: HARD STOP — "Found {N} unresolved [REQUIRES INPUT] markers. Run /speckit.echelon.re-retarget to fill them before planning."

### 3. Domain specs exist
Use Glob: `specs/NNN-re-*/spec.md`. If no files found: HARD STOP — "No re-* specs found. Run /speckit.echelon.re-extract first."

Preflight complete. Advance to `re-planning-1-plan`.
