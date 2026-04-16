# Echelon

A multi-agent system for AI-assisted software development. Instead of one AI doing everything, specialized agents handle specific cognitive tasks — understanding, critiquing, planning, building, and learning.

**Version 0.9.0** — 42-agent, 7-layer architecture with echelon_result journal contracts, compaction-safe dispatch tracking, Understanding v3.8 Depth gate, BUILD/QA split workflow, brownfield extraction (GOLDDIGGER), install-time dependency validation, internalization loop

## Quick Start

### First-time install

```bash
# 1. Install spec-kit
uv tool install specify-cli --force --from "git+https://github.com/Testimonial/qag-spec-kit.git@35bc7c7"

# 2. Clone echelon
git clone https://github.com/B3Cognition/echelon.git ~/echelon

# 3. Install Python CLIs + SOAR (codegen pipeline + understanding metrics)
bash ~/echelon/scripts/install.sh

# 4. Register the spec-kit extension
specify extension add --dev ~/echelon/extension
```

See [INSTALLATION.md](INSTALLATION.md) for prerequisites, upgrade, and uninstall instructions.

### Update to latest version

```bash
cd ~/echelon && git pull
bash ~/echelon/scripts/install.sh   # re-run to pick up dependency updates
specify extension update --dev ~/echelon/extension
```

Knowledge-base data (calibration, feedback, patterns) is protected by `.extensionignore` — updates never overwrite your runtime learning data.

### Usage

```bash
# Initialize deploy infrastructure (once per project)
speckit.echelon.init

# Run analysis on your project idea
speckit.echelon.run "Build a photo album app with sharing and tagging"

# Build with quality gates (agent-driven)
speckit.echelon.build 001-photo-album

# Build via SOAR codegen pipeline (alternative — see Codegen Integration below)
speckit.echelon.codegen 001-photo-album

# Verify 100% spec coverage
speckit.echelon.verify

# Close the learning loop after implementation
speckit.echelon.feedback 001

# Validate the extension setup
./scripts/bash/dry-run.sh
```

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

| Command | Purpose |
|---------|---------|
| `speckit.echelon.init` | One-time project setup — deploy infra, git hook (run first) |
| `speckit.echelon.run` | Start analysis (Phase 1-3) |
| `speckit.echelon.build` | Execute build phase (agent-driven) |
| `speckit.echelon.codegen` | Execute build phase via SOAR codegen pipeline (alternative to build) |
| `speckit.echelon.verify` | Check 100% spec coverage |
| `speckit.echelon.health` | Periodic health check (drift, KB freshness) |
| `speckit.echelon.status` | Check progress |
| `speckit.echelon.resume` | Answer squad's question |
| `speckit.echelon.change` | Handle spec change during build |
| `speckit.echelon.investigate` | Trigger INVESTIGATOR |
| `speckit.echelon.innovate` | Trigger MAVERICK |
| `speckit.echelon.ground` | Trigger REALIST |
| `speckit.echelon.feedback` | Post-implementation feedback |
| `speckit.echelon.deploy` | Trigger deploy, check status, or rollback |

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
- **uv** (required — install via `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **SOAR** >= 9.6.4 (bundled — downloaded by `scripts/install.sh` to `~/.echelon/soar/`)
- **understanding** >= 3.7.0 (bundled — installed by `scripts/install.sh`)
- **codegen** >= 0.9.1 (bundled — installed by `scripts/install.sh`)
- **revenge** >= 3.0.0 (optional — brownfield extraction via GOLDDIGGER)

## Directory Structure

```text
extension/
├── extension.yml        # Single merged extension manifest
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
    ├── understanding.scan.md   # 31-metric spec quality scan
    ├── understanding.validate.md
    ├── understanding.energy.md
    ├── understanding.diagram.md
    └── understanding.batch.md
src/
├── codegen/             # SOAR build pipeline CLI (entry point: codegen)
└── understanding/       # Requirements quality metrics CLI (entry point: understanding)
scripts/
└── install.sh           # Downloads SOAR, creates ~/.echelon/venv/, installs both CLIs
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
