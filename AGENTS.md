# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this repo is

Echelon is a Prosaic-first multi-agent system for AI-assisted software development. Neutral command and subagent prose lives under `prosaic/`; Echelon-owned workflows, templates, scripts, stacks, and configuration live under `runtime/`. Provider adapters execute the rendered prose through Claude Code, Codex CLI, Copilot CLI, OpenCode, or an OpenAI-compatible endpoint. Python under `src/` is the deterministic substrate around them: CLI dispatch, spec orchestration, delivery harness, provider routing, SOAR codegen, and the `understanding` requirements-quality CLI.

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

# Reinstall the core CLIs into ~/.echelon/venv after editing src/ — needed
# because the CLIs run from an installed venv on PATH, not from this checkout.
bash scripts/install.sh
# Include the optional SOAR/codegen launcher when that pipeline is needed.
bash scripts/install.sh --with-codegen
```

There is no lint config — don't add one unless asked.

## Prose source and execution paths

`prosaic/commands/echelon.<verb>.md` and `prosaic/subagents/echelon.<role>.md` are the source of truth. Their frontmatter is neutral metadata (`model_tier`, `effort`, `tools`, `color`); Prosaic parses it and provider adapters map it to provider-specific models and controls.

1. **Provider-native deployment.** Prosaic renders commands and subagents into the selected provider's native command/agent locations. Provider scaffolding is Prosaic's responsibility.
2. **Echelon CLI execution.** Workspaces load `.echelon/prosaic` plus `.echelon/runtime`; `src/echelon/cli.py` and the abstract/concrete provider implementations dispatch the rendered body and interpreted metadata.

When debugging, first determine whether the failure is bundle installation, Prosaic rendering/inspection, Echelon orchestration, or provider execution.

## Phase A / Phase B split

- **Phase A — spec authoring.** `echelon spec run` / `echelon spec bugfix` / `echelon spec change`. The squad publishes under `specs/{NNN-slug}/`; durable controller state stays under `runs/spec-*`. The Echelon constitution is `.echelon/constitution.md`.
- **Phase B — build + verify + PR.** `echelon delivery run <id>`. Lives under `src/harness/`. LLM build steps run on the host; verification runs in the configured sandbox. Strategies include the default squad delivery loop and optional SOAR/codegen flow. The review loop is controlled by `harness.review_loop.*` in `.echelon/config.yml`.

`echelon land <id>` and `echelon spec target …` are pure-Python (no LLM); `_cmd_init`, `_cmd_land`, `_cmd_harness_init`, `_cmd_harness_run` in `src/echelon/cli.py` are the dispatch points.

## Thin command wrappers + externalized workflow

The big squad commands (`echelon.run.md`, `echelon.bugfix.md`, `echelon.build.md`, `echelon.codegen.md`, `echelon.codegenlight.md`) are **thin wrappers — typically 35–75 lines**. They set the COMMANDER role, load `agents/control/commander.md`, then delegate to:

- `runtime/workflow/definition.yaml` — phase graph: routing conditions, transitions, agent assignments, convergence thresholds, and controller contracts.
- `runtime/workflow/phases/*.md` — per-phase dispatch contracts with context-pack assembly, prompts, and expected outputs.

When modifying phase logic, edit the workflow files — do not bloat the command wrappers. If a command file grows past ~100 lines you've likely put logic in the wrong place.

## Journal architecture (compaction-safe dispatch)

Agents return structured output as a trailing `echelon_result:` YAML block. **COMMANDER is the sole writer to `state.json` and the reasoning journal.** Other agents never write either.

Before each dispatch COMMANDER writes a `last_dispatch` sentinel to `state.json` with `post_dispatch_complete: false`. After the Post-Dispatch Protocol (parse echelon_result → write journal entries → apply state updates) it flips the flag to `true`. On every bootstrap COMMANDER reads this flag to detect and recover from mid-dispatch context compaction. Don't bypass this — any new agent must emit an `echelon_result` block, and COMMANDER must be the one to persist it.

The canonical set of valid journal entry types lives in `runtime/workflow/journal-entry-types.yaml`.

## Source layout (the parts you'll touch most)

```
src/
  echelon/           CLI entrypoint (cli.py main → SKILL_MAP, harness, spec, land subcommands)
  harness/           Delivery harness library — invoked via `echelon delivery`
    coordinator.py     StrategyCoordinator — fans out strategies, owns Phase 1→3 loop
    ralph.py           RalphController — Phase 1 build outer/inner loop
    visual_ralph.py    VisualRalphController — Phase 2 (Playwright, off by default)
    review_loop.py     ReviewLoopController — Phase 3 PR review cycle
    docker_provider.py DockerWorktreeProvider — sandbox lifecycle
    llm_provider.py    Abstract provider contract and concrete CLI/API adapters
    skill_loader.py    Skill resolution + preamble injection (terminal CLI path)
    gitops.py          Mirror, worktrees, push, PR creation
    state.py           Per-strategy state JSON (atomic writes)
    config.py          4-level config cascade (defaults → repo → env → CLI args)
    spec_frontmatter.py  Polyrepo `targets:` read/write
  codegen/           SOAR-powered build pipeline (RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER)
                     Uses MemPalace (ChromaDB) for wing-scoped requirements memory.
  understanding/     34-metric requirements quality CLI (Phase 1 quality gates)
prosaic/
  commands/          Neutral command prose
  subagents/         Neutral, flat `echelon.<role>.md` subagent prose
  agents/            Companion appendices and templates loaded by prose
runtime/
  workflow/          definition.yaml + phases/*.md + controller/journal schemas
  templates/         Echelon-owned artifact templates
  scripts/           Runtime shell, Python, and Node helpers
  stacks/            Stack definitions
  config-template.yml
scripts/             Host installation, release, and sandbox tooling
```

Host tooling under `scripts/` and deployed helpers under `runtime/scripts/` are different surfaces. Check the caller before moving files between them.

## Polyrepo dispatch (subtle)

`echelon delivery run <id>` resolves the spec's targets before local delivery configuration. If a spec has targets, the run dispatches to each source repository. A polyrepo orchestration root with `.echelon/config.yml` must not silently short-circuit target dispatch.

## MemPalace wings

`codegen` retrieves requirements semantically from a ChromaDB store at `~/.mempalace/palace/` shared across projects. Projects are isolated by a **wing** key in `.echelon/config.yml` under `mempalace.wing`. `MemPalaceContext` is the single source of truth for `(wing, run_id, palace_path)`; do not introduce parallel wing derivation.

## When making changes

- Editing Prosaic/runtime content but testing an existing workspace? Reinstall Echelon if Python changed, then run `echelon workspace migrate-to-prosaic` to refresh `.echelon/prosaic` and `.echelon/runtime`.
- Editing CLI Python? Re-run `bash scripts/bash/install.sh` (or `scripts/install.sh`) — `echelon` on PATH points at `~/.echelon/venv/bin/echelon`, not `python -m echelon.cli` from this tree.
- Adding a new Echelon CLI verb? Update CLI routing/usage and add matching neutral prose under `prosaic/commands/echelon.<verb>.md` when the command invokes an LLM workflow.
- Adding a new agent? Add `prosaic/subagents/echelon.<role>.md`, reference its neutral ID from `runtime/workflow/definition.yaml`, and keep provider-specific interpretation out of the prose.

## Agent Authoring Patterns

Established patterns for writing echelon agent and phase spec files. Apply to
all new agents; adopt in existing agents when next revised.

### Dispatcher / Protocol Split

> The spec file is the dispatcher + phase contract. The agent file is the invariant protocol.

A phase spec file (e.g. `workflow/phases/phase1-constitution.md`) owns:
- **What to read** — context pack (which files)
- **What mode** — Creation, Amendment, WHY1, ASSESS2, etc.
- **What to produce** — expected output filenames
- **What state to write** — `state_updates` keys the harness reads
- **What echelon_result to emit** — routing contract

A phase spec file must NOT describe how the agent does its work internally —
that belongs in the agent file. Violations cause protocol drift: the same logic
appears in two places and diverges over time (e.g. filename changes that only
land in one location).

The agent file owns the invariant protocol: identity, ALWAYS/NEVER rules, reasoning
steps, tool invocation sequences, verification logic, output block schema.

### ALWAYS / NEVER Pairs

> Every behavioural rule in an agent file has both a positive and a negative form.

The ALWAYS form states what good behaviour looks like (positive motivation,
aligned with Anthropic prompting best-practices). The NEVER form closes the
escape route and prevents rationalisation. Together they form a complete
behavioural contract.

Format:
```
ALWAYS [positive behaviour — what the agent should reach for]
NEVER  [its violation — what must not happen]
```

Example (from CHIEF):
```
ALWAYS invoke `speckit.constitution` to write or update the constitution.
NEVER write `constitution.md` via Write or Edit without first invoking `speckit.constitution`.
```

Existing agents only have NEVER rules. New agents must have paired rules.
Existing agents adopt paired rules when next revised.
