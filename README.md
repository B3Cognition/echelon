# Echelon

A multi-agent system for AI-assisted software development. Instead of one AI doing everything, specialized agents handle specific cognitive tasks — understanding, critiquing, planning, building, and learning.

**Version 0.9.2** — 42-agent, 7-layer architecture with echelon_result journal contracts, compaction-safe dispatch tracking, Understanding v3.8 Depth gate, BUILD/QA split workflow, brownfield extraction (GOLDDIGGER), install-time dependency validation, internalization loop, terminal CLI entry points, multi-LLM provider support (Claude, Copilot, Opencode)

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
| `harness` | Build harness CLI — init, run, status, resume |
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

echelon init    # bootstrap echelon.yml, set up Docker/Traefik or CLI wrapper, install git hook
harness init    # write harness-config.yml, mirror-clone target repo, detect language + image
```

Both `echelon init` and `harness init` are pure Python — no AI session required.

### Typical workflow

```bash
# Phase A — spec authoring (default: Claude)
echelon run "Build a photo album app with sharing and tagging"
echelon bugfix 001 "upload button does nothing on mobile Safari"

# Phase B — build, verify in Docker, open PR
harness run 001                    # echelon squad build (default)
harness run 001 strategy=codegen   # SOAR pipeline build (alternative)

# After PR is open — review triage runs automatically via harness Phase 3
# but can also be invoked directly:
echelon review 001 pr_url=https://github.com/org/repo/pull/42
```

Set `ECHELON_LLM` to switch AI provider for any command above — see [AI Provider Support](#ai-provider-support) below.

### Other echelon commands

```bash
echelon change  001 "scope change description"   # mid-build spec change
echelon codegen 001                              # SOAR pipeline directly (no harness)
echelon build   001                              # agent-driven build (no harness)
```

### Spec-kit skills (Claude session)

All of the above are also available as spec-kit slash commands inside a Claude Code session:

```bash
speckit.echelon.init
speckit.echelon.run "Build a photo album app"
speckit.echelon.bugfix 001 "upload button does nothing"
speckit.harness.run 001
speckit.harness.run 001 strategy=codegen
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
4. Invokes the LLM CLI subprocess (`claude -p <prompt> --dangerously-skip-permissions`, or the equivalent for Copilot/Opencode)

This path requires the `echelon` CLI to be installed (`scripts/install.sh`) and the target LLM CLI to be on your PATH. The `ECHELON_LLM` env var (or `llm.cli` in `harness-config.yml`) selects the provider.

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

The `harness` build loop (`harness run`) also respects `ECHELON_LLM` — LLM-driven build steps, feedback loops, and the PR review skill all use the same provider. Set it in your CI environment or `harness-config.yml` (`llm.cli`).

## Harness

The harness is the Phase B execution substrate: it takes echelon's Phase A output (spec.md, tasks.md, feature branch) and runs build → Docker verify → PR in an isolated sandbox. LLM reasoning stays on the host; deterministic work (build, test, verify) runs inside Docker.

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

**Two-repo (advanced):** A dedicated control-plane repo manages one or more target repos. Useful when build infrastructure should be separate from product code, or when managing multiple products from one place.

### Build Strategies

`harness run` accepts a `strategy` argument that controls which build engine Phase 1 uses:

| Strategy | Build engine | When to use |
| -------- | ------------ | ----------- |
| `default` (omit) | `echelon.build` — multi-agent squad | General use |
| `codegen` | `echelon.codegen` — SOAR CQ-ISC pipeline | Inviolable quality gates instead of agent review |

```bash
harness run 001                    # default — echelon squad build
harness run 001 strategy=codegen   # SOAR pipeline build
```

Both strategies follow the same outer loop: build → Docker verify → feedback if needed → commit + PR. On retry, both strategies fix failures by editing worktree files directly rather than re-running the full pipeline.

### Review Loop (Phase 3)

After Phase 1 converges and a PR is open, the harness optionally enters a review loop. Enable in `harness-config.yml`:

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

Set in `squad-config.yml`:

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

42 cognitive functions organized into 7 layers.

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
| **GOLDDIGGER** | BROWNFIELD-EXTRACT | Drives revenge extension for brownfield codebases (Mode 1: survey, Mode 2: deep dive) |
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

#### Learning Layer (9 agents, cross-cutting)
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

1. **GOLDDIGGER Mode 1 (Survey)** runs revenge extension at signature level → writes artifact paths to `state.json.golddigger_artifacts`
2. If `speckit.revenge.extract` skill invocation succeeds:
   - **SCOUT** reads artifact paths from `state.json.golddigger_artifacts` as a head-start for domain mapping
   - **GOLDDIGGER Mode 2 (Deep Dive)** runs on-demand when Phase 1 agents need deeper analysis of specific domains
3. If revenge extension is not available, SCOUT proceeds with manual structural analysis

Phase 1 agents (SCOUT, SYNTHESIZER, CARTOGRAPHER) can request Mode 2 deep dives by writing to `state.json.golddigger_requests`. COMMANDER processes the queue between agent dispatches.

## Commands

Each command is available two ways: as a terminal CLI tool (no Claude session needed) and as a spec-kit skill inside a Claude Code session.

### echelon — spec authoring

| Terminal | Spec-kit skill | Purpose |
| -------- | -------------- | ------- |
| `echelon init` | `speckit.echelon.init` | One-time project setup — `echelon.yml`, deploy infra, git hook |
| `echelon run "<description>"` | `speckit.echelon.run` | Phase A: full squad run → spec.md, tasks.md, feature branch |
| `echelon bugfix <id> "<desc>"` | `speckit.echelon.bugfix` | DEBUGGER + SENTINEL + SPEC GUARD → bugfix plan + tasks |
| `echelon build <id>` | `speckit.echelon.build` | Build phase (agent-driven) |
| `echelon codegen <id>` | `speckit.echelon.codegen` | Build phase via SOAR pipeline (alternative to build) |
| `echelon review <id> [pr_url=…]` | `speckit.echelon.review` | PR review triage — groups blocking comments, runs DEBUGGER → SENTINEL → SPEC GUARD per group, writes `review-fix-{n}.md` + tasks, signals `review_fix_queued` to harness |
| `echelon change <id> "<desc>"` | `speckit.echelon.change` | Handle spec change during build |
| *(spec-kit only)* | `speckit.echelon.verify` | Check 100% spec coverage |
| *(spec-kit only)* | `speckit.echelon.health` | Periodic health check (drift, KB freshness) |
| *(spec-kit only)* | `speckit.echelon.status` | Check progress |
| *(spec-kit only)* | `speckit.echelon.resume` | Answer squad's question |
| *(spec-kit only)* | `speckit.echelon.investigate` | Trigger INVESTIGATOR |
| *(spec-kit only)* | `speckit.echelon.innovate` | Trigger MAVERICK |
| *(spec-kit only)* | `speckit.echelon.ground` | Trigger REALIST |
| *(spec-kit only)* | `speckit.echelon.feedback` | Post-implementation feedback |
| *(spec-kit only)* | `speckit.echelon.deploy` | Trigger deploy, check status, or rollback |

### harness — build, verify, PR

| Terminal | Spec-kit skill | Purpose |
| -------- | -------------- | ------- |
| `harness init [<repo>]` | `speckit.harness.init` | One-time harness setup — config, mirror clone, image fingerprint |
| `harness run <id>` | `speckit.harness.run <id>` | Build → Docker verify → PR (echelon squad strategy) |
| `harness run <id> strategy=codegen` | `speckit.harness.run <id> strategy=codegen` | Build → Docker verify → PR (SOAR pipeline strategy) |
| *(spec-kit only)* | `speckit.harness.status [<id>]` | Show active loop status, iterations, token usage, PR URL |
| *(spec-kit only)* | `speckit.harness.resume <id> <answer>` | Resume a loop blocked on a human escalation question |

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

This runs `RE → DECOMPOSE → IMPLEMENT → GATE → TEST → DELIVER` and writes `.specify/squad/state.json` after every phase transition — same schema as `echelon.build`, so all status commands work unchanged.

### Parallel strategy run (with echelon-harness)

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
cp config-template.yml squad-config.yml
```

76 configurable values across 20 sections. Key ones:

| Section | Purpose | Example |
|---------|---------|---------|
| `analysis.max_iterations` | Squad iteration limit | `5` (range: 3-10) |
| `analysis.token_budget_k` | Token budget in thousands | `1000` (range: 100-2000) |
| `quality_gates.overall` | Minimum spec quality | `0.70` |
| `quality_gates.depth` | Minimum depth score | `0.30` (Understanding v3.6+) |
| `convergence.quality_delta_threshold` | Stop when improvement below | `0.02` |
| `guardian.mode` | GUARDIAN dispatch mode | `always_on` (default) |
| `endocrine.enabled` | Hormone-modulated motivation | `false` (default) |

See `config-template.yml` for full reference with guidance comments.

## Local CD

Echelon includes built-in local continuous delivery. After `harness.run` merges a feature branch to main, a `post-merge` git hook fires `deploy.sh` automatically.

**Both UI and CLI apps use blue/green deployment.** Two image slots (blue/green) are maintained. Each deploy builds to the inactive slot, health-checks it, then flips the active pointer — keeping the previous slot available for instant rollback. Everything runs in Docker to keep the dev machine clean.

The only difference between UI and CLI is how traffic is routed to the active slot:

- **UI apps (`type: http`)** — single shared Traefik at `:80` routes by path prefix: `http://localhost/{app-name}/`
- **CLI apps (`type: cli`)** — no long-lived containers; a wrapper script reads the active image tag at invocation time

### UI apps — `type: http` (blue/green via Traefik)

Two Docker containers run concurrently. On each deploy, the inactive slot is started, health-checked via `curl`, then Traefik switches traffic. All apps on a machine share one Traefik instance — adding a new app never restarts Traefik.

**Config (`echelon.yml`):**

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
- `.git/hooks/post-merge` installed

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

**Config (`echelon.yml`):**

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
- `.git/hooks/post-merge` installed
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
| `speckit.echelon.deploy` | Trigger a deploy manually (same as post-merge hook) |
| `speckit.echelon.deploy status` | Show active slot, image, ports, last deploy time |
| `speckit.echelon.deploy rollback` | Roll back to the previous slot |

Deploy state lives in two locations (kept in sync on every deploy and rollback):
- `.specify/squad/deploy-state.json` — project-local copy
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
- **Docker** (required for `harness run` — sandbox verification runs in Docker)
- **SOAR** >= 9.6.4 (bundled — downloaded by `scripts/install.sh` to `~/.echelon/soar/`)
- **understanding** >= 3.7.0 (bundled — installed by `scripts/install.sh`)
- **codegen** >= 0.9.1 (bundled — installed by `scripts/install.sh`)
- **echelon-harness** (optional — installed by `scripts/install.sh` from sibling directory; provides `harness` CLI)
- **revenge** >= 3.0.0 (optional — brownfield extraction via GOLDDIGGER)

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
└── commands/
    ├── echelon.run.md          # Main squad run orchestration
    ├── echelon.build.md        # Build phase (agent-driven)
    ├── echelon.codegen.md      # Build phase (SOAR pipeline)
    ├── echelon.*.md            # Other echelon commands (10 more)
    ├── harness.init.md         # Harness initialization
    ├── harness.run.md          # Build → verify → PR loop
    ├── harness.status.md       # Loop status
    ├── harness.resume.md       # Resume blocked loop
    ├── understanding.scan.md   # 31-metric spec quality scan
    ├── understanding.validate.md
    ├── understanding.energy.md
    ├── understanding.diagram.md
    └── understanding.batch.md
src/
├── echelon/             # echelon CLI (entry point: echelon) — terminal-invokable skills
├── codegen/             # SOAR build pipeline CLI (entry point: codegen)
├── understanding/       # Requirements quality metrics CLI (entry point: understanding)
└── harness/             # Build harness library (entry point: harness)
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

These require separation of concerns. That's why there are 42 functions, not 1.

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

All agents return structured output via an `echelon_result` YAML block at the end of their response. COMMANDER is the sole writer to the reasoning journal and state.json — no agent writes these files directly.

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
