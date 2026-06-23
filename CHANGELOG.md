# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- Documented the EGR completion gate: every implemented EGR now requires a
  matching `[Unreleased]` changelog entry, register update, and verification
  notes before the work is considered complete.
- **EGR-001 deterministic `echelon_result` validation** — added `src/harness/echelon_result_schema.py` to validate agent result payloads before harness state mutation.
  - Covers required string `verdict`, supported verdict values, `state_updates` object shape, `journal_entries` list shape, and reserved harness-owned state keys including `last_dispatch`.
  - `src/harness/squad_provider.py` now converts invalid parsed agent results into blocked results before executors can consume `state_updates`; when `ECHELON_DEBUG_RAW_DIR` is set, the blocked result includes a raw-output debug path.
  - `src/harness/squad_state.py` now defensively validates again in `SquadStateStore.advance()` so malformed results cannot complete phases or mutate state.
  - Focused tests added in `tests/kernel/test_echelon_result_schema.py`, `tests/kernel/test_squad_provider.py`, and `tests/kernel/test_squad_state.py`.
  - Verification: `pytest tests/kernel -q` (`532 passed in 1.59s`).
- **EGR-002 deterministic Phase A readiness validation** — added shared Phase A build-input validation so blocked runs and specs missing `spec.md`, `plan.md`, `research.md`, `data-model.md`, or `tasks.md` cannot be reported as ready to build.
  - `echelon status` / next-step guidance and `echelon continue` now use the same artifact readiness predicate.
  - `phase4-document` blocks the squad run with `phase_a_readiness_failed` instead of finalizing incomplete Phase A output.
  - Focused tests added in `tests/unit/test_phase_a_readiness.py`, `tests/unit/test_cli_next_step_escalation.py`, `tests/unit/test_cli_continue.py`, and `tests/integration/test_squad_controller.py`.
  - Verification: `pytest tests/unit/test_phase_a_readiness.py tests/unit/test_cli_next_step_escalation.py tests/unit/test_run_readiness.py tests/unit/test_cli_continue.py tests/integration/test_squad_controller.py -q` (`83 passed`); `pytest tests/kernel -q` (`532 passed`). Broader `pytest tests/unit tests/kernel tests/integration/test_squad_controller.py -q` collection is blocked in this environment by missing existing dependencies `freezegun` and `lark`.
- **EGR-003 deterministic host LLM tool policy** — added `harness.llm.tool_policy` defaults and shared host-side LLM command builders that inject the effective policy into prompt-based dispatches and only enable dangerous CLI permission-bypass flags after explicit approval metadata.
  - Defaults use `file_boundary: workspace`, `network_boundary: harness_allowlist`, and `allow_unsafe_host_execution: false`.
  - Unapproved unsafe host execution fails config validation; approved mode requires `approval_reason` and then re-enables the underlying AI CLI bypass flags.
  - `AICodingCliProvider`, review-loop skill invocation, and direct `echelon build/review/change/codegen/...` skill dispatch now share deterministic policy command construction; native opencode `--command speckit...` dispatch is preserved while sharing the same unsafe-bypass gate.
  - Remaining scope: this first pass deterministically gates known CLI bypass flags and prompt preamble disclosure; deeper file, network, and tool-call isolation still depends on each selected AI CLI runtime.
  - Focused tests added in `tests/unit/test_llm_tool_policy.py`, `tests/unit/test_cli_llm_tool_policy.py`, `tests/unit/test_llm_provider.py`, `tests/unit/test_review_loop.py`, and `tests/unit/test_config.py`.
  - Verification: `pytest tests/unit/test_cli_llm_tool_policy.py tests/unit/test_llm_tool_policy.py tests/unit/test_llm_provider.py tests/unit/test_review_loop.py tests/unit/test_config.py -q` (`61 passed`); `pytest tests/kernel -q` (`534 passed`).
- **EGR-004 sandbox suggestion report** — added a deterministic `harness.sandbox_suggestion` report before risky dependency install or app execution decisions.
  - The report records repository evidence, confidence label and score, suggested strategy and commands, risks, an explicit human approval point, and a fallback path for manual config.
  - `echelon harness init` now persists the structured report under `harness.sandbox_suggestion`, writes `sandbox-suggestion.md`, and surfaces its confidence and approval point in the init summary.
  - Focused tests added in `tests/unit/test_sandbox_suggestion.py` and `tests/unit/test_cli_harness_init_summary.py`.
  - Verification: `pytest tests/unit/test_sandbox_suggestion.py tests/unit/test_cli_harness_init_summary.py tests/unit/test_harness_init_verify.py tests/unit/test_harness_init_app_runtime.py tests/unit/test_init.py -q` (`20 passed`); `pytest tests/kernel -q` (`534 passed`).
- **EGR-005 typed blocked decisions** — blocked squad runs now persist machine-readable `blocked_decision` data alongside the existing human-readable escalation question.
  - Captures answer type (`free_text` or `choice`), normalized options, recommended/default answer when present, supported risk levels, blocked phase/reason, and stable blocked-at metadata.
  - `echelon resume` now records `resume_metadata`, marks the blocked decision resolved, preserves existing choice-option routing, and supports free-text blocked decisions without requiring executable options.
  - File-based harness escalations now include JSON `Decision Metadata` and `Resume Metadata` sections while preserving the Markdown answer flow.
  - Focused tests added in `tests/unit/test_blocked_decision.py`, `tests/unit/test_escalation.py`, `tests/unit/test_cli_resume_escalation_options.py`, and `tests/kernel/test_squad_state.py`.
  - Verification: `pytest tests/unit/test_blocked_decision.py tests/unit/test_escalation.py tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_continue.py tests/unit/test_cli_next_step_escalation.py tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py -q` (`145 passed`); `pytest tests/kernel -q` (`534 passed`).
- **EGR-006 reusable repair-loop primitive** — added `src/harness/repair_loop.py` as a deterministic Draft output -> Critique -> Repair -> Re-check -> Accept / Block / Exhaust substrate for harness feedback loops.
  - The primitive is LLM-agnostic: callers provide critique, repair, and re-check functions while the harness bounds iterations, records structured events, tracks token counts, and blocks repeated critique signatures before infinite loops.
  - This intentionally lands as a small substrate first; Ralph/review-loop controller rewiring can now use a tested primitive instead of introducing a risky large-controller refactor.
  - Focused tests added in `tests/unit/test_repair_loop.py`.
  - Verification: `pytest tests/unit/test_repair_loop.py -q` (`4 passed`); `pytest tests/kernel -q` (`534 passed`).

## [2.1.0] - 2026-05-17

### Added

- **Native brownfield extraction (re-* commands)** — absorbed the standalone `revenge` extension into echelon; no separate install required.
  - 12 new commands: `speckit.echelon.re-extract`, `re-retarget`, `re-plan-all`, `re-analyze`, `re-specify`, `re-verify`, `re-expand`, `re-validate`, `re-checklist`, `re-constitute`, `re-plan`, `re-tasks`
  - 8 bash extraction scripts in `extension/scripts/bash/re/` (structure, deps, git, configs, chunks, cross-repo, polyrepo discovery)
  - Node CodeGraph bridge at `extension/scripts/node/re/` for structural code intelligence
  - 3 presets: `echelon-brownfield-microservices`, `echelon-brownfield-cloud-native`, `echelon-brownfield-compliance`
  - Polyrepo support via `discover-repos.sh` auto-detection
  - Config under `re:` top-level key in `echelon-config.yml`
  - Test suite: 48 assertions across 3 brownfield integration test scripts

### Changed

- `extension.yml` version bumped `2.0.0` → `2.1.0`
- `GOLDDIGGER` agent now invokes `speckit.echelon.re-extract` (was `speckit.revenge.extract`)
- Config layer-2 overrides now written to `.specify/extensions/echelon/local-config.yml` under `re:` key
- Preflight probe renamed from `"revenge"` to `"brownfield"` — update any `degraded_mode_stack` strings accordingly
- `integration-smoke-test.sh`: `--revenge PATH` flag deprecated (brownfield is now built-in); accepted as no-op with warning

### Removed

- `revenge` optional tool dependency from `extension.yml` `requires.tools`
- Standalone `revenge/` extension directory (absorbed; the `revenge` spec-kit extension is now obsolete)

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
  - Idempotent: skips if `mempalace.wing` already set in `echelon-config.yml`
  - Wing written to `echelon-config.yml` and committed with the project — all clones inherit it automatically
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
- `echelon.codegenlight.md` — `WING=$(basename $(pwd))` replaced with python snippet reading `mempalace.wing` from `echelon-config.yml`
- `extension/echelon-config.yml`, `extension/config-template.yml` — `mempalace: { wing: "" }` block added
- `README.md` — new `### MemPalace requirements memory` subsection under Codegen Pipeline
- `INSTALLATION.md` — new `Per-project setup: wing provisioning` and `Mine requirements into MemPalace` sections

### Migration

Existing projects with drawers stored under wing `"codegen"` (the broken default):

```bash
# 1. Set wing in echelon-config.yml
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
