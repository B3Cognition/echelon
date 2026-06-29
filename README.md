# Echelon

A multi-agent system for AI-assisted software development. Instead of one AI doing everything, specialized agents handle specific cognitive tasks — understanding, critiquing, planning, building, and learning.

**Version 3.0.0** — 53 registered agent roles across the Echelon architecture, with 45 active-routed manifest roles in the executable workflow, MemPalace requirements memory (wing-scoped, per-project, collision-safe), `echelon init` wing provisioning, `codegen requirements mine/search/clean`, endocrine system fully enabled by default (all 6 hormones, phase 3), echelon_result journal contracts, compaction-safe dispatch tracking, Understanding v3.8 Depth gate, BUILD/QA split workflow, brownfield extraction (GOLDDIGGER), internalization loop, terminal CLI entry points, multi-LLM provider support (Claude, Copilot, Opencode)

For the grounded role inventory, see [Agent Role Catalog](docs/agent-role-catalog.md).

## Quick Start

### First-time install

```bash
# 1. Install spec-kit
uv tool install specify-cli --force --from "git+git@github.com:mbachorik/spec-kit.git"

# 2. Clone echelon
git clone https://github.com/B3Cognition/echelon.git ~/echelon

# 3. Install all CLI tools + SOAR into a shared venv
bash ~/echelon/scripts/install.sh
source ~/.zshrc   # or restart terminal

# 4. Register the spec-kit extension
specify extension add --dev ~/echelon/extension
```

`install.sh` installs four CLI tools into `~/.echelon/venv/bin/` and adds that directory to your PATH:

| Tool | Purpose |
| ---- | ------- |
| `echelon` | Main CLI — init, run, bugfix, build, review, change, codegen |
| `echelon harness` | Build harness subcommands — init, run |
| `echelon spec` | Spec metadata subcommands — target |
| `codegen` | SOAR codegen pipeline (also called by `echelon codegen`) |
| `understanding` | Requirements quality metrics |

See [INSTALLATION.md](INSTALLATION.md) for prerequisites, upgrade, and uninstall instructions.

### Update to latest version

```bash
cd ~/echelon && git pull
bash ~/echelon/scripts/install.sh   # re-run to pick up dependency updates
specify extension update --dev ~/echelon/extension
```

Knowledge-base data (calibration, feedback, patterns) is protected by `.extensionignore` — updates never overwrite your runtime learning data.

Terminal `echelon status`, `echelon run`, `echelon continue`, and `echelon resume`
warn when the installed project extension under `.specify/extensions/echelon`
differs from a trusted source extension. In a dev checkout this is detected
automatically; otherwise set `ECHELON_EXTENSION_SOURCE` to your Echelon repo or
extension directory before running the command. When you see `EXTENSION DRIFT`,
rerun:

```bash
specify extension update --dev ~/echelon/extension
```

### Per-project setup (once per repo)

```bash
cd ~/my-project

# Claude Code (default)
specify init --here --offline
specify extension add --dev ~/echelon/extension

# GitHub Copilot
specify init --integration copilot --here --offline
specify extension add --dev ~/echelon/extension

# Opencode
specify init --integration opencode --here --offline
specify extension add --dev ~/echelon/extension

echelon init    # bootstrap echelon-config.yml, set up Docker/Traefik or CLI wrapper, install git hook
echelon harness init    # write harness: section into echelon-config.yml, mirror-clone target repo, detect language + image
```

Both `echelon init` and `echelon harness init` are pure Python — no AI session required.

### Typical workflow

```bash
# Phase A — spec authoring (default: Claude)
echelon run "Build a photo album app with sharing and tagging"
echelon status                             # re-orient: run state, artifacts, cost, next step
echelon artifacts 001                      # generate specs/001-*/ARTIFACTS.md
echelon continue                           # run the next no-input recovery/phase action
echelon resume "your clarification"        # answer a human-input block, then continue
echelon rewind <phase-id>                  # recover a safe Phase 3 checkpoint, then continue

# Phase B — build, verify in Docker, open PR
echelon harness run 001                    # echelon squad build (default)
echelon harness run 001 strategy=codegen   # SOAR pipeline build (alternative)

# Polyrepo: record the implementation repo before build
echelon spec target 001 og-platform            # explicit target in spec frontmatter
echelon harness run 001 mode=semi              # recommends a target and stops if missing
echelon harness run 001 mode=banzai            # writes a high-confidence target and continues

# After build converges, fulfillment passes, and PR is open
echelon land 001                           # lands the target repo branch, then marks the spec landed

# After PR is open — review triage runs automatically via harness Phase 3
# but can also be invoked directly:
echelon review 001 pr_url=https://github.com/org/repo/pull/42
```

Set `ECHELON_LLM` to switch AI provider for any command above — see [AI Provider Support](#ai-provider-support) below.

Echelon has separate Phase A spec-authoring choices and Phase B build-strategy
choices. Before enabling the derived Lexicon controlled-grammar gate or SOAR
codegen, read [Echelon Pipeline Matrix](docs/pipeline-matrix.md) for the current
compatibility contract.

### Other echelon commands

```bash
echelon change  001 "scope change description"   # mid-build spec change
echelon codegen 001                              # SOAR pipeline directly (no harness)
echelon build   001                              # agent-driven build (no harness)
echelon harness init                            # re-run to auto-detect high-confidence verify_command
```

### Harness fulfillment refresh policy

Harness fulfillment refreshes are controlled from the repo config under
`harness.fulfillment.refresh_policy`. Set this in
`.specify/extensions/echelon/echelon-config.yml` for a committed project default,
or in `.specify/extensions/echelon/local-config.yml` for a local override.

```yaml
harness:
  verify_command: env NP_SMOKE_SKIP_IOS=1 bash scripts/smoke.sh
  fulfillment:
    refresh_policy: scoped
```

Available policies:

- `milestone` — default; run full `verify-spec` at normal milestone boundaries
- `scoped` — run scoped incremental fulfillment refreshes after passing slices, but still require a full `verify-spec` before convergence or land
- `every_slice` — old behavior; run full `verify-spec` after each passing build slice
- `convergence_only` — defer full fulfillment refresh until task progress is complete enough to attempt convergence

Use `scoped` when full fulfillment refreshes are dominating cost or latency during
active harness loops. Use `milestone` when you want the most conservative default.

With `scoped` or `convergence_only`, harness output may show `verify: deferred`
or `fulfillment refresh: cached`. That is not a failed build. It means the
current slice did not require a full fulfillment refresh, or no requirements were
deterministically impacted. In short: full fulfillment evidence is still required before convergence or land.

Harness `run` and `resume` also print `HARNESS HISTORY`: tracked runs, checkpoint state, and token/cost totals for the same spec so repeated resumes do not feel like a black box.

### Active run recovery

During spec authoring, `runs/.current` is the active-run pointer. `echelon
continue` reads that pointer, loads the named run directory, and resumes from the
phase recorded in that run's `state.json`.

The active squad workspace is run-local: agents read and write
`runs/<run>/specs/<id>`. The canonical `specs/<id>` folder is the published spec
folder used by humans and by Phase B. The build harness reads canonical `specs/<id>`
and should not consume run-local staging paths. When a squad run is
continued after artifacts were already published, `echelon continue` syncs
missing canonical artifacts back into the active run copy; it never guesses the newest `specs/*` directory.

Use rewind when a resumed squad run reports `missing_echelon_result`,
`missing_phase_outputs`, or a safe Phase 3 phase needs to be replayed with the
proper context:

```bash
echelon rewind phase3-sentinel
echelon continue
```

Safe rewind targets are intentionally narrow. They reset the active run state and
clean downstream generated artifacts, but they do not ask you to manually copy
`state.json` or `reasoning-journal.jsonl` into `specs/<id>`.

### Spec-kit skills (Claude session)

All of the above are also available as spec-kit slash commands inside a Claude Code session:

```bash
speckit.echelon.init
speckit.echelon.run "Build a photo album app"
speckit.echelon.bugfix 001 "upload button does nothing"
speckit.echelon.harness-run 001
speckit.echelon.harness-run 001 strategy=codegen
speckit.echelon.verify
speckit.echelon.feedback 001
./scripts/bash/dry-run.sh    # validate extension setup without running agents
```

## Execution Paths

Echelon commands can be invoked two ways. Both paths are fully supported and run independently of each other.

### Interactive Claude Code session (spec-kit skill system)

When you type a slash command inside a Claude Code session (e.g. `speckit.echelon.run`), spec-kit reads the skill file directly and injects its content into the current conversation context. The `disable-model-invocation: true` frontmatter in each skill file is honoured — Claude executes the instructions in-context rather than spawning a subprocess.

This path has no dependency on the `echelon` CLI tool or the `ECHELON_LLM` env var. It always uses the Claude instance already running your session.

### Terminal CLI (`echelon` / `harness` commands)

When you run `echelon run "..."` from the terminal, the `echelon` CLI:

1. Locates the skill file for the selected provider (Claude, Copilot, or Opencode)
2. Strips the YAML frontmatter (which is meaningful only to spec-kit, not to the LLM)
3. Prepends an execution preamble ("You are COMMANDER running non-interactively…") so the model acts on the instructions rather than narrating them
4. Injects the effective host tool-policy preamble and invokes the LLM CLI subprocess (`claude -p <prompt>`, `codex exec <prompt>`, `copilot -p <prompt>`, or `opencode run <prompt>`)

This path requires the `echelon` CLI to be installed (`scripts/install.sh`) and the target LLM CLI to be on your PATH. The `ECHELON_LLM` env var (or `harness.llm.cli` in `echelon-config.yml`) selects the provider.

By default, terminal CLI runs do **not** add dangerous permission-bypass flags to the underlying AI CLI. Unsafe host execution is fail-closed and must be explicitly configured under `harness.llm.tool_policy` with both `allow_unsafe_host_execution: true` and an `approval_reason`. When approved, Echelon re-enables the selected provider's equivalent bypass flag, such as Claude/Opencode `--dangerously-skip-permissions` or Codex `--dangerously-bypass-approvals-and-sandbox`. File, network, and individual tool-call isolation beyond those CLI flags still depends on the selected AI CLI runtime.

The two paths share the same skill content but are otherwise fully independent — changes to one do not affect the other.

## AI Provider Support

All `echelon` and `harness` CLI commands are provider-agnostic. Set the `ECHELON_LLM` environment variable to select which AI tool runs the skills:

| Value | AI tool | Skill location |
| ----- | ------- | -------------- |
| `claude` | Claude CLI (default) | `.claude/skills/speckit-echelon-<cmd>/skill.md` |
| `copilot` | GitHub Copilot CLI | `.github/agents/speckit.echelon.<cmd>.agent.md` |
| `opencode` | Opencode | `.opencode/command/speckit.echelon.<cmd>.md` |

```bash
# Use Copilot for all echelon commands
export ECHELON_LLM=copilot
echelon run "Build a photo album app"

# Use Opencode for a single command
ECHELON_LLM=opencode echelon bugfix 001 "upload button broken on Safari"
```

Skill files are placed in the right location automatically by `specify extension add` after `specify init --integration <tool>`. Each provider's skill files are rewritten for that tool's conventions — do not copy them between providers manually.

The `harness` build loop (`echelon harness run`) also respects `ECHELON_LLM` — LLM-driven build steps, feedback loops, and the PR review skill all use the same provider. Set it in your CI environment or `echelon-config.yml` (`harness.llm.cli`).

## Harness

The harness is the Phase B execution substrate: it takes echelon's Phase A output (spec.md, tasks.md, feature branch) and runs build → Docker verify → PR in an isolated sandbox. LLM reasoning stays on the host; deterministic work (build, test, verify) runs inside Docker.

### Container Runtime

`echelon harness` uses a Docker-compatible container CLI for sandbox creation.
Docker is the default, and Podman is supported by setting `harness.container_cli`
to `podman`.

Initialize a project with Podman:

```bash
ECHELON_CONTAINER_CLI=podman echelon harness init
```

`echelon harness init` persists the selected CLI in
`.specify/extensions/echelon/echelon-config.yml`:

```yaml
harness:
  provider: docker
  container_cli: podman
```

On macOS, make sure the Podman machine is running first:

```bash
podman machine start
podman info
```

Future `echelon harness run` and `echelon harness resume` commands read the
persisted `harness.container_cli` value. If no value is configured, Echelon uses
Docker.

### Deployment Models

**Single-repo (recommended):** Install harness in the same repo you are building. Specs, code, and harness config all live together.

```
my-project/
  .git
  src/
  specs/
    001-feature/           ← echelon Phase A artifacts
      spec.md
      tasks.md
  .specify/
    extensions/
      echelon/             ← echelon config
      harness/
        config.yml         ← target_repo: "."
        mirror.git/        ← local bare clone of this repo
```

### How to read a spec folder

Start with `specs/<id>-*/ARTIFACTS.md`. Echelon generates this file deterministically, without LLM tokens, as a concise map of known spec artifacts, what each file is for, when it is updated, and which expected files are missing for the current lifecycle stage.

Refresh it manually with:

```bash
echelon artifacts <id>
```

**Two-repo (advanced):** A dedicated control-plane repo manages one or more target repos. Useful when build infrastructure should be separate from product code, or when managing multiple products from one place.

### Build Strategies

`echelon harness run` accepts a `strategy` argument that controls which build engine Phase 1 uses:

| Strategy | Build engine | When to use |
| -------- | ------------ | ----------- |
| `default` (omit) | `echelon.build` — multi-agent squad | General use |
| `codegen` | `echelon.codegen` — SOAR CQ-ISC pipeline | Inviolable quality gates instead of agent review |

```bash
echelon harness run 001                    # default — echelon squad build
echelon harness run 001 strategy=codegen   # SOAR pipeline build
```

Both strategies follow the same outer loop: build → Docker verify → feedback if needed → commit + PR. On retry, both strategies fix failures by editing worktree files directly rather than re-running the full pipeline.

Build strategy is independent from Phase A spec format. The default and codegen
strategies both consume the published Phase A artifacts under `specs/<id>-*/`.
See [Echelon Pipeline Matrix](docs/pipeline-matrix.md) for the supported
spec-format/build-strategy combinations.

### Review Loop (Phase 3)

After Phase 1 converges and a PR is open, the harness optionally enters a review loop. Enable in `echelon-config.yml` under `harness:`:

```yaml
pr_host: github
review_loop:
  enabled: true
  poll_interval_minutes: 1
  merge_timeout_hours: 1
  max_fix_iterations: 3
```

The loop polls for blocking inline comments, invokes `echelon.review` (DEBUGGER → SENTINEL → SPEC GUARD per comment group), writes `review-fix-{n}.md` tasks to the branch, then re-enters Phase 1 with the review content injected into the build prompt.

### Harness Architecture

```
+-------------------------------+       +---------------------------+
|        HOST (LLM side)        |       |    DOCKER SANDBOX         |
|                               |       |                           |
|  StrategyCoordinator          |       |  deterministic execution  |
|    |                          |       |    - build (fallback)     |
|    ├── Phase 1: RalphController|       |    - test                 |
|    │     ├── ClaudeCliProvider |------>|    - verify               |
|    │     └── DockerProvider   |       |      (npm ci/test/build)  |
|    ├── Phase 2: VisualRalph   |       |                           |
|    │     (Playwright, optional)|       |  network: squid proxy     |
|    └── Phase 3: ReviewLoop    |       +---------------------------+
|          (gh api + echelon.review)
|
|  GitOpsManager
|    - mirror.git / state store / GC
+-------------------------------+
```

| Step | Executor |
| ---- | -------- |
| Build (Phase 1) | `claude -p` on host (or `echelon build`/`echelon codegen`) |
| Verify | Docker sandbox — always |
| Visual tests (Phase 2) | Docker sandbox — Playwright; disabled by default |
| Review skill (Phase 3) | `claude -p` on host via `echelon.review` |

## How It Works

### The 4-Phase Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: UNDERSTAND                                                     │
│                                                                         │
│   [GOLDDIGGER] ──► SCOUT ──► SYNTHESIZER ──►                            │
│   (brownfield)    (discover)  (fuse)                                    │
│                                                                         │
│   ──► SAGE ──► CARTOGRAPHER ──► SAGE ──► GATEKEEPER                     │
│      (why1)   (what)         (why2)    (assess)                         │
│                                                                         │
│   + Specialists: INVESTIGATOR, GUARDIAN, ORACLE, BENCHMARK, ADVOCAT     │
│   Output: spec.md, feasibility.md, estimates.md, priorities.md          │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: DECIDE                                                         │
│                                                                         │
│   CHECKPOINT: Internalize spec — every agent proves comprehension       │
│   Decision: PASS (continue) / KILL (stop) / DEFER (reduce scope)        │
│   STRATEGIST: Alignment analysis and advisory                           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: SOLUTION                                                       │
│                                                                         │
│   ARCHITECT ──► Specialists ──► SENTINEL ──► ORCHESTRATOR               │
│   (how)                         (test)        (plan)                    │
│                                                                         │
│   Output: plan.md, data-model.md, contracts/, test-strategy.md, tasks.md│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: BUILD (optional)                                               │
│                                                                         │
│   Per task: IMPLEMENTER → SPEC GUARD → CODE REVIEWER → TEST GUARDIAN    │
│   Per phase: ENGINEERING MANAGER + INTEGRATOR + VISUAL VALIDATOR        │
│   Debug: DEBUGGER (root cause analysis on non-obvious failures)         │
│   Final: VERIFICATION (100% spec coverage check)                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### Autonomy Modes

Set in `echelon-config.yml`:

```yaml
autonomy:
  mode: semi  # guided | semi | banzai
```

| Mode | Behavior |
|------|----------|
| `guided` | Checkpoint after every phase |
| `semi` | Checkpoint after Phase 1 only (default) |
| `banzai` | Full autonomous — human reviews final output |

## Agents

41 cognitive functions organized into 7 layers.

### Naming Convention

Each agent has a **codename** (file name, what you see in logs) and a **functional name** (what it does):

```
SCOUT (DISCOVER) — codename is SCOUT, functional name is DISCOVER
File: agents/exploration/scout.md
```

### Agent Reference

#### Control Layer (5 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **COMMANDER** | MANAGER | Orchestrates all phases, dispatches agents, conflict resolution |
| **CHECKPOINT** | INTERNALIZE | Ensures agents prove comprehension before building |
| **TRACKER** | INTENT-TRACKER | Watches user intent vs spec drift |
| **STRATEGIST** | STRATEGIC-ADVISOR | Alignment analysis and advisory |
| **SCOREKEEPER** | SCOREKEEPER | Tracks agent performance, enables self-healing |

#### Exploration Layer (6 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **SCOUT** | DISCOVER | Maps domain, glossary, boundaries |
| **GOLDDIGGER** | BROWNFIELD-EXTRACT | Drives native brownfield re-* extraction (Mode 1: survey, Mode 2: deep dive) |
| **SYNTHESIZER** | FUSE | Fuses discovery outputs into unified knowledge base |
| **CARTOGRAPHER** | WHAT | Writes testable requirements via spec-kit |
| **SAGE** | WHY | Adversarial critic, quality gates via Understanding CLI |
| **MODELER** | MENTAL-MODEL | Maintains code graph with invariants |

#### Feasibility Layer (2 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **GATEKEEPER** | ASSESS | Kill gate — feasibility, RICE scoring, estimation |
| **VALIDATOR** | INTERNALIZATION-GATE | Ensures agents prove comprehension before working |

#### Solution Layer (3 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **ARCHITECT** | HOW | Tech stack, data model, ADRs |
| **ORCHESTRATOR** | PLAN | Tasks, critical path, dependencies |
| **SENTINEL** | TEST-ARCHITECT | Test strategy, coverage mapping, flakiness management |

#### Specialists (6 agents, summoned adaptively)
| Codename | Functional | Trigger |
|----------|------------|---------|
| **INVESTIGATOR** | SCIENTIST | Unknowns, unproven tech |
| **GUARDIAN** | SECURITY | Auth, payments, PII, compliance (always-on by default) |
| **BENCHMARK** | PERFORMANCE | High-load, scalability |
| **ADVOCATE** | UX-A11Y | Frontend, accessibility |
| **ORACLE** | DOMAIN-EXPERT | Domain-specific knowledge |
| **MAVERICK** | INNOVATE | Stagnation, need alternatives (uses AutoTRIZ) |

#### Learning Layer (8 agents, cross-cutting)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **AUDITOR** | CALIBRATE | Tracks accuracy, adjusts confidence |
| **INTERNALIZER** | INTERNALIZATION-SCORING | Computes 16 deterministic metrics per agent |
| **ADAPTIVE** | EVOLVE | Detects regressions across runs |
| **REALIST** | GROUND | Reality-checks estimates with real-world data |
| **MIRROR** | REFLECT | Extracts patterns and pitfalls |
| **MONITOR** | METACOGNITION-MONITOR | "Are we still doing the right thing?" |
| **VETERAN** | GLOBAL-MEMORY | Cross-project knowledge — promotes validated patterns to ~/.specify/squad-global/ |
| **CONSOLIDATOR** | CONSOLIDATE | Transforms episodic experience into generalized schemas across projects |

#### Build Layer (11 agents, Phase 4)
| Agent | Purpose |
|-------|---------|
| **IMPLEMENTER** | Writes code following TDD |
| **SPEC GUARD** | Verifies code matches requirements |
| **CODE REVIEWER** | Reviews quality, ADR compliance |
| **TEST GUARDIAN** | Validates test quality |
| **ENGINEERING MANAGER** | Phase gates, rework decisions, verification loop |
| **INTEGRATOR** | System integration checks |
| **PROGRESS TRACKER** | Effort tracking, drift detection |
| **CHANGE CONTROLLER** | Handles mid-build spec changes |
| **DEBUGGER** | Systematic root cause analysis |
| **VERIFICATION** | 100% spec coverage backpropagation check |
| **VISUAL VALIDATOR** | Screenshot-based visual verification |

## Brownfield Support

When analyzing an existing codebase, the squad uses a two-phase extraction pipeline:

1. **GOLDDIGGER Mode 1 (Survey)** runs `speckit.echelon.re-analyze` at signature level → writes artifact paths to `state.json.golddigger_artifacts`
2. If `speckit.echelon.re-extract` skill invocation succeeds:
   - **SCOUT** reads artifact paths from `state.json.golddigger_artifacts` as a head-start for domain mapping
   - **GOLDDIGGER Mode 2 (Deep Dive)** runs on-demand when Phase 1 agents need deeper analysis of specific domains
3. If brownfield extraction is not available, SCOUT proceeds with manual structural analysis

Phase 1 agents (SCOUT, SYNTHESIZER, CARTOGRAPHER) can request Mode 2 deep dives by writing to `state.json.golddigger_requests`. COMMANDER processes the queue between agent dispatches.

## Commands

Each command is available two ways: as a terminal CLI tool (no Claude session needed) and as a spec-kit skill inside a Claude Code session.

### Command architecture

All major command files (`echelon.run.md`, `echelon.bugfix.md`, `echelon.build.md`, `echelon.codegen.md`, `echelon.codegenlight.md`) are **thin wrappers** (~35–75 lines). They set the role, load `agents/control/commander.md` (the shared behavioral framework for COMMANDER-driven commands), then delegate to `workflow/definition.yaml` and `workflow/phases/` for the full workflow logic.

The workflow is split into two layers:

- **`workflow/definition.yaml`** — phase graph with routing conditions, transitions, agent assignments, convergence thresholds, and the build task-loop state machine. COMMANDER reads this before every routing decision.
- **`workflow/phases/*.md`** — per-phase spec files with context pack assembly, exact dispatch prompts, and expected outputs. Each phase node in `definition.yaml` points to its spec file via `spec_file:`.

This keeps commands readable and makes individual phases independently editable without touching the command files.

### echelon — spec authoring

| Terminal | Spec-kit skill | Purpose |
| -------- | -------------- | ------- |
| `echelon init` | `speckit.echelon.init` | One-time project setup — `echelon-config.yml`, deploy infra, git hook |
| `echelon run "<description>"` | `speckit.echelon.run` | Phase A: full squad run → spec.md, tasks.md, feature branch |
| `echelon bugfix <id> "<desc>"` | `speckit.echelon.bugfix` | DEBUGGER + SENTINEL + SPEC GUARD → bugfix plan + tasks |
| `echelon build <id>` | `speckit.echelon.build` | Build phase (agent-driven) |
| `echelon codegen <id>` | `speckit.echelon.codegen` | Build phase via SOAR pipeline (alternative to build) |
| `echelon review <id> [pr_url=…]` | `speckit.echelon.review` | PR review triage — groups blocking comments, runs DEBUGGER → SENTINEL → SPEC GUARD per group, writes `review-fix-{n}.md` + tasks, signals `review_fix_queued` to harness |
| `echelon verify-spec <id> [strict=true] [--reconcile] [--dry-run]` | `speckit.echelon.verify-spec` | Audit fulfillment; with `--reconcile`, apply deterministic task-progress bookkeeping fixes through harness helpers. Use `--reconcile --dry-run` to preview changes only |
| `echelon reopen <id> [from=<report>]` | `speckit.echelon.reopen` | Reopen a spec from fulfillment gaps and append harness-ready `FG-T*` tasks |
| `echelon change <id> "<desc>"` | `speckit.echelon.change` | Handle spec change during build |
| `echelon cicd` | — | Retired; re-run `echelon harness init` to auto-detect high-confidence `verify_command` |
| `echelon status` | `speckit.echelon.status` | Re-orient summary — run state, staging artifacts, open issues, cost, next step |
| `echelon artifacts <id>` | — | Generate or refresh `specs/<id>-*/ARTIFACTS.md`, the deterministic human map of spec-folder outputs |
| `echelon continue` | — | Run the next no-input recovery action: resume an active/interrupted run, retry recoverable failed dispatches, or advance incomplete Phase A work |
| `echelon resume "<answer>"` | `speckit.echelon.resume` | Provide an answer only when the squad asked for human input; after recording it, Echelon delegates back to continuation |
| `echelon rewind <phase-id>` | — | Rewind the active squad run to a safe checkpoint such as `phase3-how`, `phase3-sentinel`, or `phase3-plan`, then continue |
| `echelon land <id>` | — | Merge PR, delete remote branch, clean worktrees, mark spec landed; uses `targets:` to land the target repo branch and blocks on unresolved fulfillment gaps |
| `echelon land <id> --allow-fulfillment-gaps` | — | Emergency override for knowingly landing despite fulfillment gaps |
| *(spec-kit only)* | `speckit.echelon.verify` | Check 100% spec coverage |
| *(spec-kit only)* | `speckit.echelon.health` | Periodic health check (drift, KB freshness) |
| *(spec-kit only)* | `speckit.echelon.investigate` | Trigger INVESTIGATOR |
| *(spec-kit only)* | `speckit.echelon.innovate` | Trigger MAVERICK |
| *(spec-kit only)* | `speckit.echelon.ground` | Trigger REALIST |
| *(spec-kit only)* | `speckit.echelon.feedback` | Post-implementation feedback |
| *(spec-kit only)* | `speckit.echelon.deploy` | Trigger deploy, check status, or rollback |

### harness — build, verify, PR

| Terminal | Spec-kit skill | Purpose |
| -------- | -------------- | ------- |
| `echelon harness init [<repo>]` | `speckit.echelon.harness-init` | One-time harness setup — config, mirror clone, image fingerprint |
| `echelon harness run <id>` | `speckit.echelon.harness-run <id>` | Build → Docker verify → PR (echelon squad strategy); in polyrepos, validates or infers the spec target before build; prints `HARNESS HISTORY` |
| `echelon harness run <id> strategy=codegen` | `speckit.echelon.harness-run <id> strategy=codegen` | Build → Docker verify → PR (SOAR pipeline strategy) |
| `echelon harness resume <id>` | `speckit.echelon.harness-resume <id> <answer>` | Resume a loop blocked on escalation or missing `verify_command`; prints `HARNESS HISTORY` |
| *(spec-kit only)* | `speckit.echelon.harness-status [<id>]` | Show active loop status, iterations, token usage, PR URL |

## Codegen Pipeline

`speckit.echelon.codegen` is a first-class alternative to `speckit.echelon.build`. It drives the same Phase A artifacts (`spec.md`, `tasks.md`, `constitution.md`, `research.md`) through a SOAR-powered pipeline with inviolable CQ-ISC quality gates instead of the multi-agent squad.

The `codegen` CLI and SOAR binary are bundled — installed by `scripts/install.sh`, no separate setup needed.

Two entry points are available:

- `/codegen` — standalone skill, drives the full pipeline directly
- `speckit.echelon.codegen` — echelon wrapper, validates Phase A artifacts and delegates to `/codegen`

### Standalone use

```bash
# After Phase A artifacts are in place
speckit.echelon.codegen 001-photo-album
```

This runs `RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER` and writes the active run's `state.json` after every phase transition — same schema as `echelon.build`, so all status commands work unchanged.

### Parallel strategy run (with harness)

On the first `echelon.codegen` run, a strategy file is auto-registered at `.specify/harness/strategies/001-photo-album/codegen.md`. No manual setup required. Once registered, run both build strategies in parallel:

```bash
run spec 001-photo-album strategies=default,codegen kill_losers
```

`kill_losers=true` cancels the slower strategy the moment the first one converges. Omit it to let both run to completion for comparison.

### Convergence signals

| Condition | `state.json` status |
|-----------|---------------------|
| Ψ ≥ 0.70, Tier 1 tests pass | `build_done` |
| Pipeline in progress | `building` |
| SOAR impasse (conflict, escalate) | `escalated` |
| SOAR blocked task | `blocked` |

On impasse, `codegen-impasse.md` is written with the exact conflict. Resume:

```bash
speckit.echelon.codegen 001-photo-album --resume
```

### MemPalace requirements memory

`codegen` uses MemPalace — a ChromaDB-backed semantic memory store — to retrieve project requirements during the RE phase and record pipeline decisions across runs. All projects share one backing database at `~/.mempalace/palace/`, scoped by a per-project **wing** identifier.

#### Wing

The wing is your project's stable identity in MemPalace. It is set once during `echelon init` and written to `echelon-config.yml`:

```yaml
mempalace:
  wing: my-app   # set by echelon init — do not change
```

`echelon init` auto-suggests a wing name from your git remote URL (e.g. `my-app` from `github.com/org/my-app`), falling back to `{dirname}-{hash6}` if no remote exists. It checks for collision with other projects before writing.

**Wing portability:** all clones of the same repo should use the same wing name so they share mined requirements across machines and teammates. The wing is committed in `echelon-config.yml` — clones inherit it automatically.

#### Mine requirements into MemPalace

**When using `echelon harness run strategy=codegen`, mining happens automatically.** The codegen pipeline always runs `codegen requirements mine` on the feature's `spec.md` and `research.md` at the start of every run — no manual step needed.

The manual command is only needed when you want to pre-populate MemPalace before running codegen, or to mine spec files outside the standard feature directory:

```bash
# Mine a single spec file
codegen requirements mine specs/spec.md

# Mine all specs in a directory
codegen requirements mine specs/*.md

# Override wing (useful for testing)
codegen requirements mine spec.md --wing my-app
```

Requirements are parsed by ID (`FR-xxx`, `NFR-xxx`, `AC-xxx`, `ADR-xxx`, `US-xxx`) and written as drawers with their actual source file paths — enabling collision detection and targeted cleanup.

#### Search requirements

```bash
codegen requirements search "OAuth2 authentication" --wing my-app
codegen requirements search "payment processing" --wing my-app --n 10
```

#### Clean up old drawers

When switching projects or after re-specifying requirements, remove stale drawers:

```bash
# Preview what would be deleted
codegen requirements clean --from-wing my-app --project-dir . --dry-run

# Delete drawers belonging to this project
codegen requirements clean --from-wing my-app --project-dir .
```

`clean` filters by `source_file` prefix — only drawers whose spec file path is under `--project-dir` are removed, leaving other projects' drawers in the shared database untouched.

#### Data flow

```text
echelon-config.yml (mempalace.wing)
        │
        ▼
codegen run  ──► codegen-state.json (wing field)
        │                │
        ▼                ▼
  RE phase          phase_gate
  (semantic          (traceability
   retrieval)         citations,
                       bug mining,
                       respecify)
```

`codegen run` reads `wing` from `echelon-config.yml`, writes it to `codegen-state.json`, and all subsequent phase gate operations read it back from the state file — no config file needed at gate time.

## PR Review Loop

When `harness.run` creates a PR and reviewers comment, the harness can automatically triage those comments and re-run Phase 1 to address them. `echelon.review` is the diagnostic half of this cycle — it is never called directly by users.

**Flow:**

```text
Reviewer leaves comments on PR
        │
        ▼
harness Phase 3 (ReviewLoopController)
  fetches blocking comments via GitHub/GitLab API
        │
        ▼
echelon.review skill (claude -p)
  groups comments by file proximity + reviewer
  per group: DEBUGGER → root cause
             SENTINEL → failing test spec
             SPEC GUARD → scope check
  writes specs/{id}-*/review-fix-{n}.md
  writes RF{n}-T* tasks to tasks.md
  commits to feature branch
        │
        ▼
harness re-enters Phase 1
  review-fix-{n}.md content injected into build prompt
  Claude addresses reviewer feedback
        │
        ▼
verify → push → re-request review
```

**What counts as blocking:** comments containing `must`, `needs to`, `fix`, `change`, `remove`, `refactor`, etc. Nits, pure questions, and already-processed comment IDs are skipped.

## Configuration

```bash
cp config-template.yml echelon-config.yml
```

76 configurable values across 20 sections. Key ones:

| Section | Purpose | Example |
|---------|---------|---------|
| `analysis.max_iterations` | Squad iteration limit | `5` (range: 3-10) |
| `analysis.token_budget_k` | Token budget in thousands | `1000` (range: 100-2000) |
| `quality_gates.overall` | Minimum spec quality | `0.70` |
| `quality_gates.depth` | Minimum depth score | `0.30` (Understanding v3.6+) |
| `convergence.quality_delta_threshold` | Stop when improvement below | `0.02` |
| `harness.container_cli` | Docker-compatible sandbox CLI | `docker` (default) or `podman` |
| `specialists.guardian_mode` | GUARDIAN dispatch mode | `always_on` (default) |
| `endocrine.enabled` | Hormone-modulated motivation | `false` (default) |
| `deploy.enabled` | Enable local blue/green CD after merge | `true` (default); set `false` to skip deploy infra |

See `config-template.yml` for full reference with guidance comments.

## Local CD

Echelon includes built-in local continuous delivery. After `harness.run` merges a feature branch to main, it calls `deploy.sh` directly. Set `deploy.enabled: false` in `echelon-config.yml` to skip all deploy infrastructure checks and the post-merge deploy step — useful for projects that manage their own CD pipeline.

**Both UI and CLI apps use blue/green deployment.** Two image slots (blue/green) are maintained. Each deploy builds to the inactive slot, health-checks it, then flips the active pointer — keeping the previous slot available for instant rollback. Everything runs in Docker to keep the dev machine clean.

The only difference between UI and CLI is how traffic is routed to the active slot:

- **UI apps (`type: http`)** — single shared Traefik at `:80` routes by path prefix: `http://localhost/{app-name}/`
- **CLI apps (`type: cli`)** — no long-lived containers; a wrapper script reads the active image tag at invocation time

### UI apps — `type: http` (blue/green via Traefik)

Two Docker containers run concurrently. On each deploy, the inactive slot is started, health-checked via `curl`, then Traefik switches traffic. All apps on a machine share one Traefik instance — adding a new app never restarts Traefik.

**Config (`echelon-config.yml`):**

```yaml
deploy:
  type: http
  blue_port: 3000    # health-check port only (unique per app)
  green_port: 3001   # health-check port only (unique per app)
  # Convention: App1=3000/3001, App2=3100/3101, AppN=3N00/3N01
  # Live URL: http://localhost/{app-name}/  (all apps share Traefik at :80)
```

**Dockerfile (minimal Vite/React example):**

```dockerfile
FROM nginx:alpine
COPY dist/ /usr/share/nginx/html/
EXPOSE 80
```

> **SPA base path:** `echelon.init` automatically sets `base` (Vite), `basePath` (Next.js), or `homepage` (CRA) to `/{app-name}/` in your framework config so assets load correctly under the path prefix. This is auto-corrected even if the value is wrong or computed — no manual step needed.

**What happens on `echelon.init`:**
- Docker network `speckit-deploy` created (shared across all apps on this machine)
- `speckit-traefik` container started at `:80` — one per machine, started once, never recreated
- SPA framework config auto-corrected for path-prefix routing (Vite/Next.js/CRA)

**Deploy flow (automatic after merge to main):**

1. `docker build` → `{app}:candidate` (Dockerfile auto-generated if missing; `.env.local` injected as `--build-arg`)
2. Start inactive slot with Traefik labels `PathPrefix(/{app})`, expose health-check port on host
3. `curl -sf http://localhost:{blue_port|green_port}` — 5 attempts, 2s apart
4. On success: stop old slot, tag image, update state
5. On failure: stop new slot, old slot unchanged (automatic rollback)

**Rollback:** `speckit.echelon.deploy rollback` restarts the stopped inactive container and flips Traefik routing.

---

### CLI apps — `type: cli` (blue/green via tag pointer)

Two image tags (blue/green) are maintained. No Traefik, no long-lived containers. Each deploy builds a new image, optionally verifies it via `docker run --rm`, then updates the active-tag pointer. An optional wrapper script at `install_path` reads the active tag on every invocation — rollback is instant since the wrapper always checks the pointer at runtime.

**Config (`echelon-config.yml`):**

```yaml
deploy:
  type: cli
  health_check: "myapp --version"  # command run inside container; empty = skip
  install_path: "~/.local/bin"     # where to install wrapper; empty = no wrapper
```

**Dockerfile (minimal Python CLI example):**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -e .
ENTRYPOINT ["myapp"]
```

**What happens on `echelon.init`:**

- Wrapper script installed to `install_path/myapp` (if `install_path` set)

**Deploy flow (automatic after merge to main):**

1. `docker build` → `{app}:candidate` (Dockerfile auto-generated if missing; `.env.local` injected as `--build-arg`)
2. If `health_check` set: `docker run --rm {app}:candidate {health_check_cmd}` (exit 0 = healthy)
3. On success: tag image → `{app}:{inactive_slot}`, update state pointer
4. On failure: build discarded, active pointer unchanged

**Running the app:**
```bash
# Via wrapper (transparent — always runs the active version):
myapp --help

# Or directly:
docker run --rm myapp:blue --help
```

**Rollback:** `speckit.echelon.deploy rollback` flips the active pointer — the wrapper picks it up on next invocation, no reinstall needed.

---

### Deploy Commands

| Command | Purpose |
|---------|---------|
| `speckit.echelon.deploy` | Trigger a deploy manually |
| `speckit.echelon.deploy status` | Show active slot, image, ports, last deploy time |
| `speckit.echelon.deploy rollback` | Roll back to the previous slot |

Deploy state lives in two locations (kept in sync on every deploy and rollback):
- Active run `deploy-state.json` — project-local copy (`runs/.current`, `squad/.current`, with legacy fallback for older workspaces)
- `~/.speckit-deploy/{app}.json` — global registry (used for port conflict detection and CLI wrapper scripts)

## Innovation Templates

MAVERICK uses evidence-based innovation with TRIZ (ISO/TR 18686:2017):

| Template | Purpose |
|----------|---------|
| `templates/triz-40-principles.md` | All 40 TRIZ principles adapted for software |
| `templates/triz-contradiction-matrix.md` | 16 software parameters + resolution matrix |

Innovation process: Design Thinking (find right problem) → AutoTRIZ (resolve contradictions) → Lateral Thinking (break patterns)

## Fallback Mode

When spec-kit skill invocations fail at runtime, the system degrades gracefully:

- spec-kit dependencies are validated at install time via `specify extension add echelon` (declared in `extension.yml requires.skills[]`)
- If a skill invocation fails during the run, COMMANDER sets `fallback_mode=true` and continues with manual specification
- All fallback artifacts are marked with `FALLBACK STATUS: UNVALIDATED_DEPENDENCY`
- Quality gates remain active — no phase skipping allowed
- Recovery runs reconciliation checklist when skills become available

See [docs/fallback-mode.md](docs/fallback-mode.md) for details.

## Knowledge Base Management

Scripts for managing the knowledge base with concurrent write protection:

| Script | Purpose |
|--------|---------|
| `kb-write.sh` | Atomic KB writes with locking |
| `kb-lock.sh` | Manage KB file locks |
| `kb-pending-write.sh` | Queue pending KB updates |
| `kb-pending-merge.sh` | Merge pending updates safely |
| `kb-recover.sh` | Recover from failed KB operations |
| `kb-seed.sh` | Initialize KB with baseline data |
| `kb-validate-evolution.sh` | Validate evolution signal integrity |

## Quality Gates

### Phase 1: Understanding (via Understanding CLI)
| Gate | Threshold | Standard |
|------|-----------|----------|
| Overall | >= 0.70 | ISO 29148 |
| Structure | >= 0.70 | IEEE 830 |
| Testability | >= 0.70 | ISO 29148 |
| Semantic | >= 0.60 | Lucassen 2017 |
| Cognitive | >= 0.60 | Sweller 1988 |
| Readability | >= 0.50 | Flesch 1948 |
| Depth | >= 0.30 | B3 Benchmark (Understanding v3.6+) |

### Phase 4: Build (per task)
| Gate | Agent | Pass Criteria |
|------|-------|---------------|
| Spec compliance | SPEC GUARD | All requirements implemented |
| Code quality | CODE REVIEWER | No violations, ADR-compliant |
| Test quality | TEST GUARDIAN | Min tests per component |
| Verification | VERIFICATION | 100% spec coverage |

## Validation

Validate the extension setup without running agents:

```bash
./scripts/bash/dry-run.sh
```

Checks: agent files, commands, config, templates, state machine flow, role separation rules.

## Installation

```bash
git clone https://github.com/B3Cognition/echelon.git ~/echelon
bash ~/echelon/scripts/install.sh
specify extension add --dev ~/echelon/extension
```

See [INSTALLATION.md](INSTALLATION.md) for full prerequisites, upgrade, and uninstall instructions.

## Requirements

- **spec-kit** >= 0.4.2 (required)
- **Claude CLI** (`claude`) — required for `echelon run`, `echelon bugfix`, and other LLM commands
- **uv** (required — install via `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Docker** (required for `echelon harness run` — sandbox verification runs in Docker)
- **SOAR** >= 9.6.4 (bundled — downloaded by `scripts/install.sh` to `~/.echelon/soar/`)
- **understanding** >= 3.7.0 (bundled — installed by `scripts/install.sh`)
- **codegen** >= 0.9.1 (bundled — installed by `scripts/install.sh`)
- **harness** (bundled — installed by `scripts/install.sh`; provides `harness` CLI for sandbox build/verify/PR)
- **brownfield re-* commands** (bundled — native extraction, no separate install needed)

## Directory Structure

```text
extension/
├── extension.yml        # Single merged extension manifest (covers echelon + harness skills)
├── agents/
│   ├── control/         # COMMANDER, CHECKPOINT, TRACKER, STRATEGIST, SCOREKEEPER
│   ├── exploration/     # SCOUT, GOLDDIGGER, SYNTHESIZER, CARTOGRAPHER, SAGE, MODELER
│   ├── feasibility/     # GATEKEEPER, VALIDATOR
│   ├── solution/        # ARCHITECT, ORCHESTRATOR, SENTINEL
│   ├── specialists/     # INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK
│   ├── learning/        # AUDITOR, INTERNALIZER, ADAPTIVE, REALIST, MIRROR, MONITOR, VETERAN, CONSOLIDATOR
│   └── build/           # IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN, EM, INTEGRATOR,
│                        # PROGRESS TRACKER, CHANGE CONTROLLER, DEBUGGER, VERIFICATION, VISUAL VALIDATOR
├── commands/            # Thin wrappers (~35–75 lines each) — delegate to workflow/phases/
│   ├── echelon.run.md          # Squad run: reads commander.md + workflow/definition.yaml, starts at init
│   ├── echelon.bugfix.md       # Bugfix: reads commander.md + phases[], starts at bugfix-1-init
│   ├── echelon.build.md        # Build phase (agent-driven): starts at build-1-init
│   ├── echelon.codegen.md      # Build phase (SOAR pipeline): reads workflow/phases/codegen-*.md
│   ├── echelon.codegenlight.md # Build phase (SOAR, brownfield/greenfield): reads codegenlight-*.md
│   ├── echelon.*.md            # Other echelon commands (10 more)
│   ├── harness.init.md         # Harness initialization
│   ├── harness.run.md          # Build → verify → PR loop
│   ├── harness.status.md       # Loop status
│   ├── harness.resume.md       # Resume blocked loop
│   ├── understanding.scan.md   # 34-metric spec quality scan
│   ├── understanding.validate.md
│   ├── understanding.energy.md
│   ├── understanding.diagram.md
│   └── understanding.batch.md
└── workflow/            # Externalized workflow logic (deployed with the extension)
    ├── definition.yaml          # Phase graph, routing rules, convergence thresholds, build state machine
    ├── journal-entry-types.yaml # Canonical registry of valid reasoning-journal entry types
    └── phases/                  # Per-phase spec files — context pack assembly, dispatch prompts, outputs
        ├── init.md / phase1-*.md / phase2-*.md / phase3-*.md / phase4-document.md
        ├── bugfix-1-init.md … bugfix-5-finalize.md
        ├── build-1-init.md … build-8-finalize.md
        ├── codegen-A-preamble.md … codegen-7-deliver.md / codegen-resume.md
        └── codegenlight-0-preflight.md … codegenlight-7-deliver.md / codegenlight-resume.md
src/
├── echelon/             # echelon CLI (entry point: echelon) — terminal-invokable skills
├── codegen/             # SOAR build pipeline CLI (entry point: codegen)
├── understanding/       # Requirements quality metrics CLI (entry point: understanding)
└── harness/             # Build harness library (invoked via: echelon harness)
    ├── provider.py        SandboxProvider abstract interface
    ├── docker_provider.py DockerWorktreeProvider — Docker sandbox lifecycle
    ├── llm_provider.py    ClaudeCliProvider — claude -p subprocess for LLM build
    ├── build_prompt.py    BuildPromptBuilder — self-contained prompt construction
    ├── gitops.py          GitOpsManager — mirror, worktrees, push, PR creation
    ├── state.py           State store (per-strategy JSON, atomic writes)
    ├── config.py          Configuration (4-level cascade)
    ├── ralph.py           RalphController — Phase 1 outer/inner loop
    ├── visual_ralph.py    VisualRalphController — Phase 2 Playwright loop
    ├── review_loop.py     ReviewLoopController — Phase 3 PR review cycle
    ├── coordinator.py     StrategyCoordinator — fans out strategies, owns Phase 1→3 loop
    └── skills/            CLI skill entry points
network/
├── generate-squid-conf.sh   # Generate Squid proxy config for sandbox network policy
└── squid.conf.template      # Squid config template with egress allowlist
scripts/
├── install.sh               # Downloads SOAR, creates ~/.echelon/venv/, installs all CLIs
├── uninstall.sh             # Removes venv, SOAR, memory, PATH entries
├── docker-gc.sh             # Garbage-collect stale sandbox containers and worktrees
├── docker-network.sh        # Create/teardown the Docker bridge network + Squid proxy
├── docker-sandbox.sh        # Lifecycle helpers for the Docker sandbox container
└── sandbox-exec.sh          # Run a command inside the active sandbox
docs/
└── fallback-mode.md
knowledge-base/
├── calibration-profile.yaml
├── estimates-log.yaml
├── patterns.yaml
└── pitfalls.yaml
templates/
├── triz-40-principles.md
├── triz-contradiction-matrix.md
└── state-schema.json
```

## Why Multiple Agents?

A single prompt can't:
- Challenge its own output (SAGE rejects what CARTOGRAPHER wrote)
- Track its own accuracy (AUDITOR logs: "estimation accuracy: 0.45")
- Verify 100% coverage backward (VERIFICATION: spec → code)
- Watch for process violations (MONITOR: "you skipped quality gates")
- Accumulate cross-project knowledge (VETERAN maintains global patterns)
- Detect brownfield structure before understanding (GOLDDIGGER → SCOUT)
- Modulate urgency based on budget pressure (endocrine system)

These require separation of concerns. That's why there are 41 functions, not 1.

## Agent Colors

Each layer has a distinct color in the Claude Code UI task list:

| Layer | Color | Agents |
|-------|-------|--------|
| Control | `blue` | COMMANDER, CHECKPOINT, SCOREKEEPER, STRATEGIST, TRACKER |
| Exploration | `green` | SCOUT, GOLDDIGGER, SYNTHESIZER, CARTOGRAPHER, SAGE, MODELER |
| Feasibility | `orange` | GATEKEEPER, VALIDATOR |
| Solution | `purple` | ARCHITECT, ORCHESTRATOR, SENTINEL |
| Specialists | `cyan` | INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK |
| Build | `red` | IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN, ENGINEERING MANAGER, INTEGRATOR, PROGRESS TRACKER, CHANGE CONTROLLER, DEBUGGER, VERIFICATION, VISUAL VALIDATOR |
| Learning | `yellow` | AUDITOR, INTERNALIZER, ADAPTIVE, REALIST, MIRROR, MONITOR, VETERAN, CONSOLIDATOR |

The `understanding` extension commands also use `green` — they are invoked by SAGE during the exploration phase (WHY2/WHY3).

## Journal Architecture

All agents return structured output via an `echelon_result` YAML block at the end of their response. Agents put durable reasoning records in `echelon_result.journal_entries` and state changes in `echelon_result.state_updates`. The harness/COMMANDER runtime is the only writer to `reasoning-journal.jsonl` and `state.json`.

Agents must not use Write, Edit, Bash redirection, `cat >>`, or `tee` to mutate `reasoning-journal.jsonl` or `state.json` directly. Direct writes split ownership and make rewind/continue recovery nondeterministic.

```yaml
echelon_result:
  agent: SCOUT
  verdict: COMPLETE
  journal_entries:
    - id: RJ-NNN
      type: insight
      phase: discover
      data: { ... }
  state_updates:
    phase: synthesize
  artifacts_written:
    - staging/glossary.md
```

**Compaction safety:** Before dispatching each agent, COMMANDER writes a `last_dispatch` sentinel to `state.json` with `post_dispatch_complete: false`. After completing the Post-Dispatch Protocol (parse echelon_result → write journal → apply state updates → confirm), it flips the flag to `true`. On every bootstrap, COMMANDER checks this flag to detect and recover from mid-dispatch compaction.

## License

MIT

---

## Brownfield extraction (re-* commands)

Echelon includes native brownfield extraction for reverse-engineering existing codebases into spec-kit format artifacts. This replaces the standalone `revenge` extension.

### Three-phase workflow

**Phase 1 — Extract** (`/speckit.echelon.re-extract`): Full pipeline from codebase → specs + strategic artifacts. Runs analysis, generates domain specs with iterative coverage/validation loops, produces `constitution.md`, `migration-strategy.md`, `risk-matrix.md`, `gap-analysis.md`, and ADRs.

**Phase 2 — Retarget** (`/speckit.echelon.re-retarget`): Guided prompts to fill `[REQUIRES INPUT]` placeholders in strategic artifacts — target stack decisions, migration strategy choices.

**Phase 3 — Plan All** (`/speckit.echelon.re-plan-all`): Generates per-domain `plan.md` and `tasks.md` files ready for echelon's build pipeline.

### Individual commands

| Command | Purpose |
|---------|---------|
| `speckit.echelon.re-analyze` | Extract structured data from codebase → `runs/<run-id>/re/analysis.json` during `echelon run`, or `.specify/echelon/re/analysis.json` standalone, plus optional CodeGraph artifacts |
| `speckit.echelon.re-specify` | Generate domain specs with coverage tracking |
| `speckit.echelon.re-verify` | Verify spec coverage; identify orphan files |
| `speckit.echelon.re-expand` | Fill coverage gaps from orphan file clusters |
| `speckit.echelon.re-validate` | Quality-check specs; auto-resolve ambiguities |
| `speckit.echelon.re-checklist` | Generate per-domain quality checklists |
| `speckit.echelon.re-constitute` | Generate strategic artifacts with `[REQUIRES INPUT]` placeholders |
| `speckit.echelon.re-plan` | Generate per-domain `plan.md` files |
| `speckit.echelon.re-tasks` | Generate per-domain `tasks.md` files |

### Polyrepo support

Auto-detects multi-repo workspaces via `discover-repos.sh`. Runs per-repo extraction and produces `cross-repo.json` for shared-tech and dependency mapping.

### Presets

- `echelon-brownfield-microservices` — DDD decomposition, service boundary ADRs
- `echelon-brownfield-cloud-native` — 12-factor, 7R migration strategy, container ADRs
- `echelon-brownfield-compliance` — GDPR/HIPAA/SOC2 checklists and risk templates

Install via: `specify preset add echelon-brownfield-microservices`

For full documentation, see [`docs/re-overview.md`](docs/re-overview.md).
