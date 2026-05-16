# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Echelon is a spec-kit extension that ships a multi-agent system for AI-assisted software development plus the supporting CLIs (`echelon`, `codegen`, `understanding`, and `harness` invoked via `echelon harness`). The agents live as markdown skill/agent files under `extension/` and are executed by an LLM (Claude / Copilot / Opencode); the Python code under `src/` is the deterministic substrate around them — CLI dispatch, the build harness (Docker sandbox + Git mirror + PR flow), the SOAR codegen pipeline, and the `understanding` requirements-quality CLI.

The README is unusually load-bearing for orientation — when you need the big picture (4-phase model, 41-agent layout, harness phases, deploy infra, build strategies), read it rather than re-deriving from the code.

## Build, test, and dev commands

```bash
# Run all Python tests (configured in pyproject.toml; src on pythonpath)
pytest

# Run one Python test file or test
pytest tests/unit/test_config.py
pytest tests/unit/test_config.py::test_load_defaults

# Filter by marker (see pyproject.toml [tool.pytest.ini_options] markers)
pytest -m unit
pytest -m "integration and not docker"
pytest -m e2e

# Bash tests (legacy; not collected by pytest)
bash tests/unit/test-some-thing.sh
for t in tests/unit/*.sh; do bash "$t"; done

# Validate the extension wiring without running any agents
bash scripts/bash/dry-run.sh

# Reinstall the four CLIs (echelon / codegen / understanding / harness)
# into ~/.echelon/venv after editing src/ — needed because the CLIs run from
# an installed venv on PATH, not from this checkout.
bash scripts/install.sh
```

There is no lint config — don't add one unless asked.

## Two execution paths (do not conflate)

A single command file like `extension/commands/echelon.run.md` is invoked two completely independent ways. Whichever path is broken, the other can still work — so when debugging, identify the path first.

1. **Interactive Claude Code session (spec-kit skill system).** When the user types `/speckit.echelon.run` in a Claude session, spec-kit injects the skill file's content into the current conversation. `disable-model-invocation: true` in frontmatter is honoured. No subprocess, no `ECHELON_LLM`, no `echelon` CLI involvement.
2. **Terminal CLI (`echelon run …`).** `src/echelon/cli.py` locates the skill file for the provider selected by `ECHELON_LLM` (default `claude`), strips YAML frontmatter, prepends an execution preamble, and shells out to the LLM CLI (`claude -p` with stream-json, `copilot -p`, or `opencode run --command`). See `SKILL_MAP` in `src/echelon/cli.py:35` for the mapping from CLI verb to skill base name.

The two paths share *skill content* but nothing else. Behaviour differences usually live in the preamble injection in `harness/skill_loader.py` or in spec-kit's own loader.

## Phase A / Phase B split

- **Phase A — spec authoring.** `echelon run` / `echelon bugfix` / `echelon change`. The squad produces `specs/{NNN-slug}/spec.md`, `plan.md`, `tasks.md`, `constitution.md` on a feature branch. Squad reasoning is on the host LLM; no Docker.
- **Phase B — build + verify + PR.** `echelon harness run <id>`. Lives entirely under `src/harness/`. LLM build steps run on the host; verify always runs in a Docker sandbox; a Squid proxy enforces the egress allowlist. Strategies: `default` (echelon squad build via `echelon.build`) or `strategy=codegen` (SOAR CQ-ISC pipeline via `echelon.codegen`). Phase 3 of the harness is the **review loop** — polls the PR for blocking comments and re-runs `echelon.review` to write `review-fix-{n}.md` + `RF{n}-T*` tasks; controlled by `harness.review_loop.*` in `echelon-config.yml`.

`echelon land <id>` and `echelon spec target …` are pure-Python (no LLM); `_cmd_init`, `_cmd_land`, `_cmd_harness_init`, `_cmd_harness_run` in `src/echelon/cli.py` are the dispatch points.

## Thin command wrappers + externalized workflow

The big squad commands (`echelon.run.md`, `echelon.bugfix.md`, `echelon.build.md`, `echelon.codegen.md`, `echelon.codegenlight.md`) are **thin wrappers — typically 35–75 lines**. They set the COMMANDER role, load `agents/control/commander.md`, then delegate to:

- `extension/workflow/definition.yaml` — phase graph: routing conditions, transitions, agent assignments, convergence thresholds, the build-task-loop state machine. COMMANDER reads this before every routing decision.
- `extension/workflow/phases/*.md` — per-phase spec files with context-pack assembly, exact dispatch prompts, expected outputs. Each phase node in `definition.yaml` points to its spec file via `spec_file:`.

When modifying phase logic, edit the workflow files — do not bloat the command wrappers. If a command file grows past ~100 lines you've likely put logic in the wrong place.

## Journal architecture (compaction-safe dispatch)

Agents return structured output as a trailing `echelon_result:` YAML block. **COMMANDER is the sole writer to `state.json` and the reasoning journal.** Other agents never write either.

Before each dispatch COMMANDER writes a `last_dispatch` sentinel to `state.json` with `post_dispatch_complete: false`. After the Post-Dispatch Protocol (parse echelon_result → write journal entries → apply state updates) it flips the flag to `true`. On every bootstrap COMMANDER reads this flag to detect and recover from mid-dispatch context compaction. Don't bypass this — any new agent must emit an `echelon_result` block, and COMMANDER must be the one to persist it.

The canonical set of valid journal entry types lives in `extension/workflow/journal-entry-types.yaml`.

## Source layout (the parts you'll touch most)

```
src/
  echelon/           CLI entrypoint (cli.py main → SKILL_MAP, harness, spec, land subcommands)
  harness/           Build harness library — invoked via `echelon harness`
    coordinator.py     StrategyCoordinator — fans out strategies, owns Phase 1→3 loop
    ralph.py           RalphController — Phase 1 build outer/inner loop
    visual_ralph.py    VisualRalphController — Phase 2 (Playwright, off by default)
    review_loop.py     ReviewLoopController — Phase 3 PR review cycle
    docker_provider.py DockerWorktreeProvider — sandbox lifecycle
    llm_provider.py    ClaudeCliProvider — claude -p subprocess wrapper
    skill_loader.py    Skill resolution + preamble injection (terminal CLI path)
    gitops.py          Mirror, worktrees, push, PR creation
    state.py           Per-strategy state JSON (atomic writes)
    config.py          4-level config cascade (defaults → repo → env → CLI args)
    spec_frontmatter.py  Polyrepo `targets:` read/write
  codegen/           SOAR-powered build pipeline (RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER)
                     Uses MemPalace (ChromaDB) for wing-scoped requirements memory.
  understanding/     34-metric requirements quality CLI (Phase 1 quality gates)
extension/
  agents/            7 layers × 41 agents — markdown skill files
  commands/          Thin command wrappers
  workflow/          definition.yaml + phases/*.md (workflow logic)
  scripts/bash/      Runtime shell helpers (kb-*, dry-run, deploy, endocrine, …)
scripts/             Install/upgrade/uninstall + Docker sandbox helpers (these are not deployed by the extension; extension/scripts/bash/ is)
```

Note the duplication: `scripts/bash/` (host install + sandbox tooling) and `extension/scripts/bash/` (deployed with the extension, used at runtime by agents). They are **different sets** — don't move files between them without checking which one the caller actually invokes.

## Polyrepo dispatch (subtle)

`echelon harness run <id>` checks the spec's `targets:` frontmatter *before* it checks the local `echelon-config.yml`. If a spec has targets, the run dispatches to each sub-repo in parallel via `echelon.orchestrator.run_multi_target`. A polyrepo root with its own `echelon-config.yml` (e.g. for deploy) will **not** silently short-circuit this — `src/echelon/cli.py:_cmd_harness_run` is structured to prevent that. Keep it that way.

## MemPalace wings

`codegen` retrieves requirements semantically from a ChromaDB store at `~/.mempalace/palace/` shared across all projects on the machine. Projects are isolated by a **wing** key written to `echelon-config.yml` under `mempalace.wing`, set once at `echelon init`. `check_wing_collision` (in `src/codegen/memory/collision.py`) refuses to write into a wing that already belongs to a different project unless the user re-confirms the name. `MemPalaceContext` is the single source of truth for `(wing, run_id, palace_path)` — do not introduce parallel wing-derivation logic elsewhere; the 1.5.0 work was specifically to consolidate it. See CHANGELOG.md 1.5.0 for the history if you're tempted to change drawer-id hashing or wing resolution.

## When making changes

- Editing skill content but expecting `echelon <cmd>` to pick it up? Skill files are read from the *installed extension location* (`.specify/extensions/echelon/...` or the global `~/.claude/skills/...`), not from this checkout — re-run `specify extension update --dev ~/echelon/extension` after edits.
- Editing CLI Python? Re-run `bash scripts/bash/install.sh` (or `scripts/install.sh`) — `echelon` on PATH points at `~/.echelon/venv/bin/echelon`, not `python -m echelon.cli` from this tree.
- Adding a new echelon CLI verb? Update `SKILL_MAP` in `src/echelon/cli.py`, add the matching `extension/commands/echelon.<verb>.md` skill, and add the entry to the `USAGE` string. The CLI just forwards arguments — all behaviour lives in the skill.
- Adding a new agent? Drop the markdown under the right `extension/agents/<layer>/` directory and reference it from `extension/workflow/definition.yaml`. Make sure it emits an `echelon_result` block (see existing agents for the schema; canonical types in `extension/workflow/journal-entry-types.yaml`).
