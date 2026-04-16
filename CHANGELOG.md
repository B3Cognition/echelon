# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- `codegen` CLI absorbed into echelon (`src/codegen/`) — SOAR-powered build pipeline now bundled
- `understanding` CLI absorbed into echelon (`src/understanding/`) — 31-metric requirements quality analysis now bundled
- `scripts/install.sh` — single installer: downloads SOAR 9.6.4, creates `~/.echelon/venv/`, installs both CLIs
- `INSTALLATION.md` — prerequisites, verify, upgrade, uninstall instructions
- 5 `speckit.echelon.understanding-*` commands added to extension (`scan`, `validate`, `energy`, `diagram`, `batch`)
- `before_plan` hook: `speckit.echelon.understanding-scan` (runs quality scan before planning)
- Single extension registration: `specify extension add --dev ~/echelon/extension`

### Changed

- Extension moved from root to `extension/` subfolder (`agents/`, `commands/`, `extension.yml`)
- Runtime state directory: `~/.codegen/` → `~/.echelon/` (memory, SOAR binary, venv, config)
- `extension.yml`: external `understanding` tool requirement replaced with bundled note; SOAR requirement added
- `pyproject.toml` added — unified package with `codegen` and `understanding` entry points
- Understanding v3.6 integration: Depth quality gate (>= 0.30) in config-template and SAGE
- v0.4.0 BUILD/QA split workflow artifacts under `specs/002-build-qa-phase-split/`
- Deterministic BUILD light-gate evaluator and US1/US2/US3 test harnesses
- Split-phase state schema fields and rework telemetry checkpoints
- SAGE references updated from 31 to 34 metrics (Understanding v3.6 adds Depth category)
- run-understanding.sh fixed: added missing `scan` subcommand
- Build command guidance now includes dependency-safe lane execution and QA handoff policy
- Verify command guidance now includes QA entry gate and deterministic QA completion criteria

## [0.3.0] - 2026-03-21

### Added

- 7-layer agent architecture: Control, Exploration, Feasibility, Solution, Specialists, Build, Learning
- 35 agents with codename system (SCOUT, SAGE, CARTOGRAPHER, GATEKEEPER, ARCHITECT, ORCHESTRATOR, etc.)
- Fallback mode with graceful degradation when spec-kit unavailable
- Knowledge base management: locking, checksums, pending queue, recovery
- KB schema validation (kb-schema.md) and evolution validation (kb-validate-evolution.sh)
- BUILD/QA split workflow with deterministic light gates
- Phase timing telemetry with budget tracking and anomaly detection
- Dry-run health check script (dry-run.sh)
- Preflight dependency detection (preflight-speckit.sh)
- Unit tests (80+), integration tests (41+), benchmarks
- NEVER rules in agent prompt files for role separation enforcement
- TRACKER dispatch for user-intent alignment
- state.json split_metrics initialization (prevents stale data carry-forward)
- Pre-dispatch enforcement gate (Tier 1, bash-based)

### Changed

- Extension version: 0.2.0 → 0.3.0
- Agent naming: functional names (DISCOVER, WHY, WHAT) → codenames (SCOUT, SAGE, CARTOGRAPHER)
- agent-scores.yaml: migrated to codename keys
- calibration-profile.yaml correction_factor_max: 3.0 → 6.0
- Staging directory cleared on init to prevent cross-run contamination

### Fixed

- dry-run.sh false failures (14) caused by old functional names in FLOW array
- GATEKEEPER intent-check NEVER rule now has required user-intent.md input
- loc-estimation correction factor uncapped (was 3.0, observed need ~5x)

## [0.1.0] - 2026-03-16

### Added

- Initial release
- 7 core agents: MANAGER, DISCOVER, WHAT, WHY, ASSESS, HOW, PLAN
- 7 specialist agents: SCIENTIST, SECURITY, TEST ARCHITECT, DOMAIN EXPERT, UX/A11Y, PERFORMANCE, INNOVATE
- 4 learning layer agents: REFLECT, EVOLVE, CALIBRATE, GROUND
- FEEDBACK intake for post-implementation learning
- 7 slash commands: run, status, innovate, investigate, ground, feedback, resume
- Reasoning journal (JSON) for inter-agent communication
- YAML knowledge base with patterns, estimates, pitfalls, calibration
- Evidence quality grading system (A-E)
- State machine with convergence detection and human escalation
- Brownfield support via spec-kit-revenge
- Greenfield support via domain research pipeline
- Implementability check in ASSESS2 consensus phase

### Requirements

- Spec Kit: >=0.3.0
- Optional: Understanding CLI >=3.4.0
- Optional: spec-kit-revenge >=1.0.0

[Unreleased]: https://github.com/Testimonial/echelon/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Testimonial/echelon/releases/tag/v0.1.0
