# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [1.0.0] - 2026-04-25

### Added

- **harness consolidated** — `echelon-harness` repo merged into `echelon`; `echelon-harness` is deprecated
  - `src/harness/` — full execution substrate (38 Python modules: docker sandbox, GitOps, ralph-loop, review loop, GC, CLI, skills)
  - `extension/commands/harness.{init,run,status,resume}.md` — 4 harness skill commands
  - `network/` — Squid proxy config assets for sandbox network policy
  - `scripts/docker-{gc,network,sandbox}.sh`, `sandbox-exec.sh` — sandbox lifecycle helpers
  - All harness tests migrated: unit (33), integration (11), contract (1), shim (5), e2e (6), fixtures
  - `harness = "harness.cli:main"` entry point in `pyproject.toml`
- **Single config file** — `harness:` section added to `echelon.yml`; `harness-config.yml` eliminated
  - `harness init` writes into the `harness:` section of `echelon.yml` (merging with existing squad settings)
  - `harness.llm.config_dir` — sets `CLAUDE_CONFIG_DIR` for Claude invocations (persistent alternative to env var)
- `docs/soar-delivery.md` — FR-019-001 SOAR state delivery documentation (delivery gate)
- `codegen` CLI absorbed into echelon (`src/codegen/`) — SOAR-powered build pipeline now bundled
- `understanding` CLI absorbed into echelon (`src/understanding/`) — 31-metric requirements quality analysis now bundled
- `scripts/install.sh` — single installer: downloads SOAR 9.6.4, creates `~/.echelon/venv/`, installs all 4 CLIs
- `INSTALLATION.md` — prerequisites, verify, upgrade, uninstall instructions
- 5 `speckit.echelon.understanding-*` commands added to extension (`scan`, `validate`, `energy`, `diagram`, `batch`)
- `before_plan` hook: `speckit.echelon.understanding-scan` (runs quality scan before planning)
- Single extension registration: `specify extension add --dev ~/echelon/extension`

### Changed

- `scripts/install.sh` — harness now installed from main package; sibling-dir lookup removed; all 4 CLIs installed unconditionally
- `extension/extension.yml` — 4 harness commands + docker/git tool requirements + single `echelon.yml` config entry
- Extension assets consolidated into `extension/`: `config-template.yml`, `agents.yaml`, `echelon-config.yml`, `.extensionignore` — root duplicates removed
- `*.egg-info/` added to `.gitignore`
- Extension moved from root to `extension/` subfolder (`agents/`, `commands/`, `extension.yml`)
- Runtime state directory: `~/.codegen/` → `~/.echelon/` (memory, SOAR binary, venv, config)
- `pyproject.toml` added — unified package with all 4 CLI entry points
- Understanding v3.6 integration: Depth quality gate (>= 0.30) in config-template and SAGE
- SAGE references updated from 31 to 34 metrics (Understanding v3.6 adds Depth category)
- Build and verify command guidance updated (dependency-safe lanes, QA entry gate, deterministic QA completion)

### Fixed

- `test_belief_parser.py` — fixture expiry dates were in the past (×2)
- `test_soar_seed_rules.py` — expected `COMMANDER.md` at repo root; delivery doc moved to `docs/soar-delivery.md`
- `test_llm_provider.py` — `shutil.which` PATH resolution made tests environment-dependent (×2); `shutil.which` now mocked
- `dry-run.sh` and `kb-validate-evolution.sh` — `agents.yaml` path updated after move to `extension/`

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
