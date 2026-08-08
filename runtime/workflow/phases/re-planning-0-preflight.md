# Phase: re-planning-0-preflight
# Read by: echelon.commander (COMMANDER)
# Type: commander_internal

## Preflight Checks

1. Read `re/workspace/strategy/constitution.md`. If absent, hard stop: run `speckit.echelon.re-retarget` after extraction.
2. Search `re/workspace/strategy/constitution.md`, migration strategy, risk matrix, gap analysis, and `adrs/` for `[REQUIRES INPUT]`. Hard stop while any remain.
3. Require at least one `re/sources/{source-id}/specs/{domain-id}/spec.md`. An all-empty workspace has no implementation domains and planning completes as a no-op.

Preflight complete. Advance to `re-planning-1-plan`.
