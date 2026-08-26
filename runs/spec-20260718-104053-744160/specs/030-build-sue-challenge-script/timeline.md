# Timeline

## Development History

| Component | Last Modified | Evidence | Notes |
|-----------|---------------|----------|-------|
| `scripts/` (host tooling, SUE's target home) | 2026-07-17 | git log for `scripts/` (runtime/release commits through 2026-07-17) | Actively maintained; `contradiction-scanner.py` is the standalone-script precedent |
| SUE challenge script | not yet created | No `sue_challenge` matches anywhere in `scripts/`, `src/`, or `tests/` | Greenfield deliverable inside a brownfield repo |
| Design doc `docs/superpowers/specs/2026-07-18-sue-challenge-script-design.md` | 2026-07-18 (dated) | IN-REQ-DA5A2A3AEAB5; commit 07828312 "docs: SUE challenge script v1 design" | Approved same day this run started — fresh, no staleness concern |
| `specs/029-builder-spec-workbench/` (acceptance target) | current at base commit ef2643c9 | A-004 anchor verification; recent commits 75789a02/3f36d19a touch spec-workbench area | Active spec — see drift risk on acceptance anchors |

## Velocity Trends

| Area | Trend | Evidence | Implication |
|------|-------|----------|-------------|
| Repo overall | increasing | Commits/month: 233 (2026-03), 262 (04), 624 (05), 462 (06), 708 (07 to date) | High-velocity repo; conventions SUE relies on (pytest config, scripts/ shape) are live today but could shift — pin against current base commit |
| Spec-workbench / spec tooling | active focus | Specs 028/029 active; recent fix commits reference CARTOGRAPHER/checkpoints | The acceptance target sits in the most actively changed area — reinforces the freeze-fixture mitigation |

## Stale Modules

| Module | Staleness Signal | Risk | Follow-up |
|--------|------------------|------|-----------|
| (none relevant to this feature) | `scripts/`, `tests/unit/`, and `pyproject.toml` all show current activity | — | — |
