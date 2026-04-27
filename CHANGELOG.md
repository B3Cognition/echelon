# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [1.5.0] - 2026-04-27

### Added

- **MemPalace requirements memory** — wing-scoped, per-project semantic memory store backed by ChromaDB
  - `MemPalaceContext` dataclass — single source of truth for `wing`, `run_id`, and `palace_path` across the entire memory subsystem
  - `codegen requirements mine <spec>` — parse spec files (FR/NFR/AC/ADR/US IDs) and write drawers with real `source_file` paths for traceability
  - `codegen requirements search <query> --wing <name>` — semantic retrieval from mined requirements
  - `codegen requirements clean --from-wing <name>` — remove stale drawers by project path prefix; `--dry-run` preview support
  - `check_wing_collision()` — detects when a wing name is already used by a different project (checked at init time and mine time)
- **`echelon init` wing provisioning** — new step added to `echelon init` flow
  - Auto-suggests wing name from `git remote get-url origin` slug (fallback: `{dirname}-{hash6}`)
  - Interactive confirm with collision check; force-accept by entering same name twice
  - Idempotent: skips if `mempalace.wing` already set in `echelon.yml`
  - Wing written to `echelon.yml` and committed with the project — all clones inherit it automatically
- **Endocrine system fully enabled by default** — opt-out model (was opt-in)
  - `endocrine.sh get_enabled()` defaults to `"true"` when key absent; explicitly disable with `enabled: false`
  - `echelon.run.md` endocrine call is now unconditional
  - `config-template.yml` updated belief: phase 3 (all 6 hormones) is the validated default
- Integration tests: 7 tests covering MemPalace mine/search round-trip, wing isolation, SHA256 drawer ID format, collision detection, requirements clean
- E2E tests: 17 tests covering CLI subprocess mine/search/clean and PipelineEngine wing threading with mocked SOAR bridge
- `docs/superpowers/specs/2026-04-27-mempalace-integration-fix-design.md` — design doc
- `docs/superpowers/plans/2026-04-27-mempalace-integration-fix.md` — implementation plan
- `tests/fixtures/mempalace/spec-alpha.md`, `spec-beta.md` — fixture specs for integration/e2e tests

### Fixed

- **SHA256 drawer_id** (Critical) — `MemPalaceWriter._write_drawer()` was using MD5[:16] while `add_drawer` uses SHA256[:24]; drawer IDs never matched, making `backfill_run_outcome()` and `backfill_status()` completely broken
- **Deterministic chunk_index** (Medium) — replaced `hash(run_id) & 0xFFFF` (non-deterministic across process restarts due to Python hash randomisation) with `int(sha256(run_id).hexdigest(), 16) & 0xFFFF`
- **Wing collision** (Critical) — `PipelineEngine._get_mempalace_writer()` was deriving wing from `state_file.parent.name` which returns `""` for a relative path, falling back to `"codegen"` — all projects shared the same wing
- **Dead memory-config.yml** (Low) — `install.sh` was writing `~/.echelon/memory-config.yml` which `MempalaceConfig()` never read (reads `~/.mempalace/config.json`); dead write removed
- `PhaseGateRunner` wing derivation via dead `_memory_config.wing` replaced with state-file read (`state.get("wing")`)
- `MemPalaceReader`, `MemPalaceWriter`, `RequirementsMiner`, `PipelineEngine`, `PhaseGateRunner`, `codegen CLI` all use `MemPalaceContext` — no more scattered `wing=` / `run_id=` kwargs
- `_read_state()` in `PipelineEngine` now deserialises `wing` field from `codegen-state.json` (resume preserves wing)
- `RequirementsMiner` now passes actual `source_file` path to `MemPalaceWriter.write()` — enables `requirements clean` to correctly identify and delete project-specific drawers

### Changed

- `MemPalaceReader.__init__` — takes `ctx: MemPalaceContext` instead of `wing: str`; uses `ctx.palace_path` directly
- `MemPalaceWriter.__init__` — takes `ctx: MemPalaceContext` instead of `(wing, run_id)`; methods renamed `_mcp_write` → `_write_drawer`, `_mcp_update_metadata` → `_update_drawer_metadata`
- `RequirementsMiner.__init__` — takes `(ctx: MemPalaceContext, project_dir: Path)` instead of `(wing, run_id)`
- `PipelineEngine` — new `set_context(ctx)` method; `wing` field added to `PipelineState`; `run_re_phase` and `search_requirements` take `ctx` instead of `wing`
- `echelon.codegenlight.md` — `WING=$(basename $(pwd))` replaced with python snippet reading `mempalace.wing` from `echelon.yml`
- `extension/echelon-config.yml`, `extension/config-template.yml` — `mempalace: { wing: "" }` block added
- `README.md` — new `### MemPalace requirements memory` subsection under Codegen Pipeline
- `INSTALLATION.md` — new `Per-project setup: wing provisioning` and `Mine requirements into MemPalace` sections

### Migration

Existing projects with drawers stored under wing `"codegen"` (the broken default):

```bash
# 1. Set wing in echelon.yml
echelon init

# 2. Re-mine specs under correct wing
codegen requirements mine specs/*.md

# 3. Optional: remove old "codegen" wing drawers
codegen requirements clean --from-wing codegen --project-dir .
```

## [1.0.0] - 2026-04-25

### Added

- **harness consolidated** — `echelon-harness` repo merged into `echelon`; `echelon-harness` is deprecated
  - `src/harness/` — full execution substrate (38 Python modules: docker sandbox, GitOps, ralph-loop, review loop, GC, CLI, skills)
  - `extension/commands/harness.{init,run,status,resume}.md` — 4 harness skill commands
  - `network/` — Squid proxy config assets for sandbox network policy
  - `scripts/docker-{gc,network,sandbox}.sh`, `sandbox-exec.sh` — sandbox lifecycle helpers
  - All harness tests migrated: unit (33), integration (11), contract (1), shim (5), e2e (6), fixtures
  - `echelon harness init/run` — harness subcommands merged into the `echelon` CLI; `harness` binary removed
- **Single config file** — `harness:` section added to `echelon.yml`; `harness-config.yml` eliminated
  - `echelon harness init` writes into the `harness:` section of `echelon.yml` (merging with existing squad settings)
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
