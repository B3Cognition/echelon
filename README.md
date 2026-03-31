# Echelon

A multi-agent system for AI-assisted software development. Instead of one AI doing everything, specialized agents handle specific cognitive tasks — understanding, critiquing, planning, building, and learning.

**Version 0.5.0** — Brownfield extraction (PROSPECTOR + GOLDDIGGER), endocrine system, internalization loop, enhanced verification

## Quick Start

### First-time install

```bash
# 1. Install spec-kit with --dev update support
uv tool install specify-cli --force --from "git+https://github.com/Testimonial/qag-spec-kit.git@35bc7c7"

# 2. Clone echelon
git clone https://github.com/Testimonial/echelon.git /tmp/echelon

# 3. Install as dev extension
specify extension add --dev /tmp/echelon
```

### Update to latest version

```bash
cd /tmp/echelon && git pull
specify extension update --dev /tmp/echelon
```

Knowledge-base data (calibration, feedback, patterns) is protected by `.extensionignore` — updates never overwrite your runtime learning data.

### Usage

```bash
# Run analysis on your project idea
/speckit.echelon.run "Build a photo album app with sharing and tagging"

# Build with quality gates
/speckit.echelon.build 001-photo-album

# Verify 100% spec coverage
/speckit.echelon.verify

# Close the learning loop after implementation
/speckit.echelon.feedback 001

# Validate the extension setup
./scripts/bash/dry-run.sh
```

## How It Works

### The 4-Phase Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: UNDERSTAND                                                      │
│                                                                          │
│   PROSPECTOR ──► [GOLDDIGGER] ──► SCOUT ──► SYNTHESIZER ──►            │
│   (survey)     (brownfield)     (discover)  (fuse)                     │
│                                                                          │
│   ──► SAGE ──► CARTOGRAPHER ──► SAGE ──► GATEKEEPER                    │
│      (why1)   (what)         (why2)    (assess)                        │
│                                                                          │
│   + Specialists: INVESTIGATOR, GUARDIAN, ORACLE, BENCHMARK, ADVOCATE    │
│   Output: spec.md, feasibility.md, estimates.md, priorities.md          │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: DECIDE                                                          │
│                                                                          │
│   CHECKPOINT: Internalize spec — every agent proves comprehension        │
│   Decision: PASS (continue) / KILL (stop) / DEFER (reduce scope)        │
│   STRATEGIST: Alignment analysis and advisory                           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: SOLUTION                                                        │
│                                                                          │
│   ARCHITECT ──► Specialists ──► SENTINEL ──► ORCHESTRATOR               │
│   (how)                         (test)        (plan)                    │
│                                                                          │
│   Output: plan.md, data-model.md, contracts/, test-strategy.md, tasks.md│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: BUILD (optional)                                                │
│                                                                          │
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

#### Control Layer (6 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **COMMANDER** | MANAGER | Orchestrates all phases, dispatches agents, conflict resolution |
| **PROSPECTOR** | SURVEY | Discovers available spec-kit skills from context, writes capability manifest |
| **CHECKPOINT** | INTERNALIZE | Ensures agents prove comprehension before building |
| **TRACKER** | INTENT-TRACKER | Watches user intent vs spec drift |
| **STRATEGIST** | STRATEGIC-ADVISOR | Alignment analysis and advisory |
| **SCOREKEEPER** | SCOREKEEPER | Tracks agent performance, enables self-healing |

#### Exploration Layer (6 agents)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **SCOUT** | DISCOVER | Maps domain, glossary, boundaries |
| **GOLDDIGGER** | BROWNFIELD-EXTRACT | Drives reverse-eng for brownfield codebases (Mode 1: survey, Mode 2: deep dive) |
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
| **VETERAN** | GLOBAL-MEMORY | Cross-project knowledge (~/.specify/squad-global/) |
| **GLOBAL-MEMORY** | GLOBAL-MEMORY | Manages cross-project pattern persistence |

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

1. **PROSPECTOR** enumerates available `speckit.*` skills from the agent's conversation context (assistant-agnostic — no filesystem scanning)
2. If `speckit.reverse-eng.*` skills are available:
   - **GOLDDIGGER Mode 1 (Survey)** runs reverse-eng at signature level → produces `brownfield-index.md`
   - **SCOUT** uses the brownfield index as a head-start for domain mapping
   - **GOLDDIGGER Mode 2 (Deep Dive)** runs on-demand when Phase 1 agents need deeper analysis of specific domains
3. If reverse-eng is not available, SCOUT proceeds with manual structural analysis

Phase 1 agents (SCOUT, SYNTHESIZER, CARTOGRAPHER) can request Mode 2 deep dives by writing to `state.json.golddigger_requests`. COMMANDER processes the queue between agent dispatches.

## Commands

| Command | Purpose |
|---------|---------|
| `/speckit.echelon.run` | Start analysis (Phase 1-3) |
| `/speckit.echelon.build` | Execute build phase |
| `/speckit.echelon.verify` | Check 100% spec coverage |
| `/speckit.echelon.health` | Periodic health check (drift, KB freshness) |
| `/speckit.echelon.status` | Check progress |
| `/speckit.echelon.resume` | Answer squad's question |
| `/speckit.echelon.change` | Handle spec change during build |
| `/speckit.echelon.investigate` | Trigger INVESTIGATOR |
| `/speckit.echelon.innovate` | Trigger MAVERICK |
| `/speckit.echelon.ground` | Trigger REALIST |
| `/speckit.echelon.feedback` | Post-implementation feedback |

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

## Innovation Templates

MAVERICK uses evidence-based innovation with TRIZ (ISO/TR 18686:2017):

| Template | Purpose |
|----------|---------|
| `templates/triz-40-principles.md` | All 40 TRIZ principles adapted for software |
| `templates/triz-contradiction-matrix.md` | 16 software parameters + resolution matrix |

Innovation process: Design Thinking (find right problem) → AutoTRIZ (resolve contradictions) → Lateral Thinking (break patterns)

## Fallback Mode

When spec-kit skills are unavailable (PROSPECTOR finds no `speckit.*` skills in context), the system degrades gracefully:

- PROSPECTOR detects availability from the agent's conversation context — no filesystem scanning, works across any AI coding assistant
- System sets `fallback_mode=true` and continues with manual specification
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

### From catalog
```bash
specify extension add echelon
```

### From source
```bash
git clone https://github.com/Testimonial/echelon.git
specify extension add --dev /path/to/echelon
```

## Requirements

- **spec-kit** >= 0.4.2 (required)
- **understanding** >= 3.6.0 (hard stop for WHY2/WHY3 — heuristic fallback proven 15-29% overconfident; WHY1 does not require it)
- **spec-kit-reverse-eng** >= 1.1.0 (optional — brownfield extraction via GOLDDIGGER)

## Directory Structure

```text
agents/
├── control/           # COMMANDER, PROSPECTOR, CHECKPOINT, TRACKER, STRATEGIST, SCOREKEEPER
├── exploration/       # SCOUT, GOLDDIGGER, SYNTHESIZER, CARTOGRAPHER, SAGE, MODELER
├── feasibility/       # GATEKEEPER, VALIDATOR
├── solution/          # ARCHITECT, ORCHESTRATOR, SENTINEL
├── specialists/       # INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK
├── learning/          # AUDITOR, INTERNALIZER, ADAPTIVE, REALIST, MIRROR, MONITOR, VETERAN, GLOBAL-MEMORY
└── build/             # IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN, EM, INTEGRATOR,
                       # PROGRESS TRACKER, CHANGE CONTROLLER, DEBUGGER, VERIFICATION, VISUAL VALIDATOR
commands/
├── echelon.run.md       # Main squad run orchestration
├── echelon.build.md     # Build phase orchestration
└── squad.*.md         # Other squad commands (11 total)
docs/
└── fallback-mode.md   # Fallback mode documentation
knowledge-base/
├── agent-scores.yaml  # Agent performance tracking
├── calibration-profile.yaml
├── estimates-log.yaml
├── kb-schema.md       # Knowledge base schema
├── patterns.yaml      # Learned patterns
└── pitfalls.yaml      # Known pitfalls
scripts/bash/
├── dry-run.sh         # Validation script
├── kb-*.sh            # Knowledge base management (7 scripts)
├── endocrine.sh       # Hormone-modulated motivation system
├── state-backup.sh    # State checkpoint before phase transitions
├── run-understanding.sh # Understanding CLI wrapper
└── ...                # 22 scripts total
templates/
├── triz-40-principles.md
├── triz-contradiction-matrix.md
├── state-schema.json
├── fallback-artifact-banner.md
└── recovery-checklist.md
tests/
├── unit/              # Unit tests
├── integration/       # Integration tests
├── e2e/               # End-to-end tests
├── benchmarks/        # Performance benchmarks
└── manual/            # Manual test procedures
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

## License

MIT
