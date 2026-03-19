# Cognitive Squad

A multi-agent system for AI-assisted software development. Instead of one AI doing everything, specialized agents handle specific cognitive tasks — understanding, critiquing, planning, building, and learning.

**Version 0.2.0** — Layer-based architecture with dual naming (codename + functional)

## Quick Start

```bash
# Install
specify extension add cognitive-squad

# Run analysis on your project idea
/speckit.squad.run "Build a photo album app with sharing and tagging"

# Build with quality gates
/speckit.squad.build 001-photo-album

# Verify 100% spec coverage
/speckit.squad.verify

# Validate the extension setup
./scripts/bash/dry-run.sh
```

## How It Works

### The 4-Phase Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: UNDERSTAND                                                      │
│                                                                          │
│   SCOUT ──► SYNTHESIZER ──► SAGE ──► CARTOGRAPHER ──► SAGE ──► GATEKEEPER│
│   (discover)  (fuse)       (why1)   (what)         (why2)    (assess)   │
│                                                                          │
│   + Specialists: INVESTIGATOR, GUARDIAN, ORACLE, BENCHMARK, ADVOCATE    │
│   Output: spec.md, feasibility.md, estimates.md, priorities.md          │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ CHECKPOINT: Review spec, fill [REQUIRES INPUT] sections                  │
│ Decision: PASS (continue) / KILL (stop) / DEFER (reduce scope)          │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: DECIDE (human guided)                                           │
│                                                                          │
│   Confirm scope, priorities, constraints, team capacity                  │
│   Output: Completed strategic artifacts                                  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: SOLUTION                                                        │
│                                                                          │
│   ARCHITECT ──► Specialists ──► SENTINEL ──► ORCHESTRATOR               │
│   (how)                         (test)        (plan)                    │
│                                                                          │
│   Output: plan.md, data-model.md, contracts/, test-strategy.md, tasks.md│
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: BUILD (optional)                                                │
│                                                                          │
│   Per task: IMPLEMENTER → SPEC GUARD → CODE REVIEWER → TEST GUARDIAN    │
│   Per phase: ENGINEERING MANAGER + INTEGRATOR + VISUAL VALIDATOR        │
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

36 cognitive functions organized into 7 layers.

### Naming Convention

Each agent has a **codename** (file name, what you see in logs) and a **functional name** (what it does):

```
SCOUT (DISCOVER) — codename is SCOUT, functional name is DISCOVER
File: agents/exploration/scout.md
```

### Agent Reference

#### Control Layer
| Codename | Functional | Purpose |
|----------|------------|---------|
| **COMMANDER** | MANAGER | Orchestrates all phases, dispatches agents |
| **TRACKER** | INTENT-TRACKER | Watches user intent vs spec drift |
| **SCOREKEEPER** | SCOREKEEPER | Tracks agent performance, enables self-healing |

#### Exploration Layer (Phase 1)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **SCOUT** | DISCOVER | Maps domain, glossary, boundaries |
| **SYNTHESIZER** | FUSE | Fuses discovery outputs into unified knowledge base |
| **CARTOGRAPHER** | WHAT | Writes testable requirements |
| **SAGE** | WHY | Adversarial critic, challenges assumptions |
| **MODELER** | MENTAL-MODEL | Maintains code graph with invariants |

#### Feasibility Layer
| Codename | Functional | Purpose |
|----------|------------|---------|
| **GATEKEEPER** | ASSESS | Kill gate — feasibility, RICE scoring, estimation |
| **VALIDATOR** | INTERNALIZATION-GATE | Ensures agents prove comprehension before working |

#### Solution Layer (Phase 3)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **ARCHITECT** | HOW | Tech stack, data model, ADRs |
| **ORCHESTRATOR** | PLAN | Tasks, critical path, dependencies |
| **SENTINEL** | TEST-ARCHITECT | Test strategy, coverage mapping |

#### Specialists (summoned adaptively)
| Codename | Functional | Trigger |
|----------|------------|---------|
| **INVESTIGATOR** | SCIENTIST | Unknowns, unproven tech |
| **GUARDIAN** | SECURITY | Auth, payments, PII, compliance |
| **BENCHMARK** | PERFORMANCE | High-load, scalability |
| **ADVOCATE** | UX-A11Y | Frontend, accessibility |
| **ORACLE** | DOMAIN-EXPERT | Domain-specific knowledge |
| **MAVERICK** | INNOVATE | Stagnation, need alternatives (uses AutoTRIZ) |

#### Learning Layer (cross-cutting)
| Codename | Functional | Purpose |
|----------|------------|---------|
| **AUDITOR** | CALIBRATE | Tracks accuracy, adjusts confidence |
| **ADAPTIVE** | EVOLVE | Detects regressions across runs |
| **REALIST** | GROUND | Reality-checks estimates |
| **MIRROR** | REFLECT | Extracts patterns and pitfalls |
| **MONITOR** | METACOGNITION-MONITOR | "Are we still doing the right thing?" |
| **VETERAN** | GLOBAL-MEMORY | Cross-project knowledge (~/.specify/squad-global/) |

#### Build Layer (Phase 4)
| Agent | Purpose |
|-------|---------|
| **IMPLEMENTER** | Writes code following TDD |
| **SPEC GUARD** | Verifies code matches requirements |
| **CODE REVIEWER** | Reviews quality, ADR compliance |
| **TEST GUARDIAN** | Validates test quality |
| **ENGINEERING MANAGER** | Phase gates, rework decisions |
| **INTEGRATOR** | System integration |
| **PROGRESS TRACKER** | Effort tracking, drift detection |
| **CHANGE CONTROLLER** | Handles mid-build spec changes |
| **VERIFICATION** | 100% spec coverage check |
| **VISUAL VALIDATOR** | Actually looks at running product |

## Commands

| Command | Purpose |
|---------|---------|
| `/speckit.squad.run` | Start analysis (Phase 1-3) |
| `/speckit.squad.build` | Execute build phase |
| `/speckit.squad.verify` | Check 100% spec coverage |
| `/speckit.squad.health` | Periodic health check (drift, KB freshness) |
| `/speckit.squad.status` | Check progress |
| `/speckit.squad.resume` | Answer squad's question |
| `/speckit.squad.change` | Handle spec change during build |
| `/speckit.squad.investigate` | Trigger INVESTIGATOR |
| `/speckit.squad.innovate` | Trigger MAVERICK |
| `/speckit.squad.ground` | Trigger REALIST |
| `/speckit.squad.feedback` | Post-implementation feedback |

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
| `convergence.quality_delta_threshold` | Stop when improvement below | `0.02` |
| `code_quality.max_function_lines` | Code review threshold | `30` |
| `tests.min_api_endpoint` | Minimum tests per endpoint | `4` |
| `calibration.correction_factor_max` | Max estimate adjustment | `3.0` |

See `config-template.yml` for full reference with guidance comments.

## Innovation Templates

MAVERICK uses evidence-based innovation with TRIZ (ISO/TR 18686:2017):

| Template | Purpose |
|----------|---------|
| `templates/triz-40-principles.md` | All 40 TRIZ principles adapted for software |
| `templates/triz-contradiction-matrix.md` | 16 software parameters + resolution matrix |

Innovation process: Design Thinking (find right problem) → AutoTRIZ (resolve contradictions) → Lateral Thinking (break patterns)

## Quality Gates

### Phase 1: Understanding (via Understanding CLI)
| Gate | Threshold | Standard |
|------|-----------|----------|
| Overall | >= 0.70 | ISO 29148 |
| Structure | >= 0.70 | IEEE 830 |
| Testability | >= 0.70 | ISO 29148 |

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
specify extension add cognitive-squad
```

### From source
```bash
git clone https://github.com/Testimonial/cognitive-squad.git
specify extension add --dev /path/to/cognitive-squad
```

## Requirements

- **spec-kit** >= 0.3.0 (required)
- **understanding** >= 3.4.0 (optional — enables quality gates)
- **spec-kit-reverse-eng** >= 1.0.0 (optional — brownfield analysis)

## Directory Structure

```
agents/
├── control/           # COMMANDER, TRACKER, SCOREKEEPER
├── exploration/       # SCOUT, SYNTHESIZER, CARTOGRAPHER, SAGE, MODELER
├── feasibility/       # GATEKEEPER, VALIDATOR
├── solution/          # ARCHITECT, ORCHESTRATOR, SENTINEL
├── specialists/       # INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK
├── learning/          # AUDITOR, ADAPTIVE, REALIST, MIRROR, MONITOR, VETERAN
└── build/             # Build phase agents
templates/
├── triz-40-principles.md
├── triz-contradiction-matrix.md
└── state-schema.json
scripts/
└── bash/dry-run.sh    # Validation script
```

## Why Multiple Agents?

A single prompt can't:
- Challenge its own output (SAGE rejects what CARTOGRAPHER wrote)
- Track its own accuracy (AUDITOR logs: "estimation accuracy: 0.45")
- Verify 100% coverage backward (VERIFICATION: spec → code)
- Watch for process violations (MONITOR: "you skipped quality gates")
- Accumulate cross-project knowledge (VETERAN maintains global patterns)

These require separation of concerns. That's why there are 36 functions, not 1.

## License

MIT
