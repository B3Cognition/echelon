# Echelon Evolution Design

> **Status**: Approved
> **Date**: 2026-03-18
> **Approach**: Phased Evolution (v0.2 → v0.3 → v0.4)

## Summary

Evolve echelon by incorporating the best ideas from BMAD-METHOD while preserving its autonomous-first philosophy. Key changes: dual naming system, 4-phase architecture with autonomy modes, new agents (CATALYST, SCRIBE), and layer-based organization.

## Context

### Source Analysis

**BMAD-METHOD** is a mature framework (v6) for AI-assisted software delivery with:
- Persona-based agents (Mary the Analyst, Winston the Architect, etc.)
- Interactive menu-driven workflows
- 4-phase lifecycle: Analysis → Planning → Solutioning → Implementation

**Echelon** is a spec-kit extension for autonomous pre-code analysis with:
- Role-based agents (DISCOVER, WHAT, WHY, ASSESS, HOW, PLAN)
- Autonomous execution via MANAGER dispatch
- Learning layer (CALIBRATE, EVOLVE) for continuous improvement
- Evidence grading (A-E) for knowledge quality

### Key Insight

BMAD and echelon solve adjacent but different problems:
- BMAD: Human guides AI through structured workflows (interactive)
- Echelon: AI runs analysis autonomously, human reviews output (autonomous)

The goal is to strengthen echelon by importing valuable BMAD patterns without losing its autonomous-first identity.

## Design

### 1. Four-Phase Architecture

Inspired by reverse-eng extension's three-phase model, extended to four phases:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: UNDERSTAND (Autonomous with quality loops)                         │
│                                                                             │
│   BRAINSTORM* → DISCOVER → WHY1 → WHAT → WHY2 → ASSESS                     │
│   (CATALYST)    (SCOUT)   (SAGE) (CART) (SAGE) (GATEKEEPER)                │
│                                                                             │
│   Specialists summoned adaptively: SCIENTIST, DOMAIN-EXPERT, INNOVATE      │
│   Loops until: quality gates pass OR max iterations                         │
│   Output: glossary, mental-model, boundaries, assumptions, spec.md,         │
│           feasibility.md, prioritization.md, estimates.md, mvp-scope.md     │
│                                                                             │
│   * BRAINSTORM added in v0.3                                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⏸️  HUMAN CHECKPOINT: Review ASSESS output                                   │
│                                                                             │
│   Decision: KILL (stop) / DEFER (reduce scope) / PASS (continue)           │
│   Review: assumptions, unknowns, priorities, MVP scope                      │
│   Fill: [REQUIRES INPUT] sections                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: DECIDE (Human-guided)                                              │
│                                                                             │
│   /squad.resume with decisions OR manual edits to artifacts                 │
│   Confirm: scope, priorities, constraints, team capacity                    │
│   Output: Completed strategic artifacts (no [REQUIRES INPUT] remaining)     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: SOLUTION (Autonomous)                                              │
│                                                                             │
│   HOW → Specialists → TEST-ARCHITECT → PLAN → CONSENSUS*                   │
│   (ARCHITECT)         (SENTINEL)       (ORCHESTRATOR)                      │
│                                                                             │
│   Specialists summoned adaptively: SECURITY, PERFORMANCE, UX-A11Y          │
│   Output: plan.md, research.md, data-model.md, contracts/,                  │
│           test-strategy.md, tasks.md, constitution.md                       │
│                                                                             │
│   * CONSENSUS = ASSESS2 + PLAN2 verify cross-artifact alignment            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⏸️  HUMAN CHECKPOINT: Review plan + tasks                                    │
│                                                                             │
│   Review: architecture decisions, task breakdown, estimates                 │
│   Optional: proceed to Phase 4 OR go straight to implementation             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: DOCUMENT (Optional, Autonomous)                                    │
│                                                                             │
│   SCRIBE generates:                                                         │
│   - README.md (project overview)                                            │
│   - architecture.md with Mermaid diagrams                                   │
│   - API documentation (from contracts/)                                     │
│   - onboarding.md (for new team members)                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Autonomy Modes

Three modes controlled by `--mode` flag:

| Mode | Flag | Behavior |
|------|------|----------|
| **Guided** | `--mode guided` | Checkpoint after every phase |
| **Semi** | `--mode semi` (default) | Checkpoint after Phase 1 only |
| **Banzai** | `--mode banzai` | Full autonomous, human reviews final output |

```bash
/squad.run "Build a photo album app"                    # semi (default)
/squad.run "Build a photo album app" --mode guided      # stop after each phase
/squad.run "Build a photo album app" --mode banzai      # go wild
```

#### Banzai Mode Defaults

| Phase 2 Decision | Default Behavior |
|------------------|------------------|
| KILL/DEFER/PASS | Auto-PASS if feasibility ≥ FEASIBLE_WITH_RISKS |
| Scope | Accept MVP scope as-is |
| Priorities | Use RICE ranking without modification |
| Constraints | Infer from constitution.md or preset defaults |
| `[REQUIRES INPUT]` | Fill from preset templates OR mark `[AUTO-DEFAULTED]` |

#### Banzai Configuration

```yaml
# In squad-config.yml
banzai:
  # Pull defaults from installed presets
  constitution_preset: "sp-web-fullstack"

  # Or specify inline defaults
  defaults:
    team_size: 1
    tech_stack: "infer"
    timeline: "flexible"

  # Safety rails (scores are 0.0-1.0)
  auto_kill_threshold: 0.3    # Below this feasibility score = KILL
  require_human_if:
    - "compliance requirements detected"
    - "security-critical domain"
    - "ASSESS confidence < 0.5"
```

#### Safety Rails

Banzai mode still stops if:
- Feasibility score below threshold (default 0.3)
- Compliance/security domain detected
- CALIBRATE shows low historical accuracy
- Any agent flags `[CRITICAL: NEEDS HUMAN]`

### 3. Layer Organization & Dual Naming

#### Agent Layers

```
CONTROL PLANE
  MANAGER (COMMANDER)         Orchestrates all phases, dispatches agents

EXPLORATION LAYER (Phase 1)
  BRAINSTORM (CATALYST)*      Guided ideation before analysis
  DISCOVER (SCOUT)            Domain reconnaissance, territory mapping
  WHAT (CARTOGRAPHER)         Requirements definition, spec writing
  WHY (SAGE)                  Adversarial critic, assumption challenger

FEASIBILITY LAYER (Phase 1 → Phase 2 gate)
  ASSESS (GATEKEEPER)         Kill gate, estimation, RICE/Kano, MVP scoping

SOLUTION LAYER (Phase 3)
  HOW (ARCHITECT)             Architecture decisions, tech stack, ADRs
  PLAN (ORCHESTRATOR)         Task breakdown, critical path, dependencies
  TEST-ARCHITECT (SENTINEL)   Test strategy, coverage mapping

SPECIALIST LAYER (Summoned adaptively)
  SCIENTIST (INVESTIGATOR)    Scientific method, evidence grading, experiments
  SECURITY (GUARDIAN)         OWASP, STRIDE, compliance frameworks
  PERFORMANCE (BENCHMARK)     Load modeling, capacity planning
  UX-A11Y (ADVOCATE)          WCAG, Nielsen heuristics, user flows
  DOMAIN-EXPERT (ORACLE)      Dynamic domain knowledge loading
  INNOVATE (MAVERICK)         TRIZ, Design Thinking, alternatives

LEARNING LAYER (Cross-cutting)
  CALIBRATE (AUDITOR)         Accuracy tracking, confidence adjustment
  EVOLVE (ADAPTIVE)           Cross-run improvement, stagnation detection
  GROUND (REALIST)            Reality check against benchmarks, costs

DOCUMENT LAYER (Phase 4)
  SCRIBE (SCRIBE)             README, architecture diagrams, API docs

* CATALYST added in v0.3
```

#### Naming Convention

```markdown
# In agent prompts
You are the DISCOVER agent (codename: SCOUT) — a domain reconnaissance specialist...

# In logs/state.json
{"agent": "DISCOVER", "codename": "SCOUT", "phase": "exploration", ...}

# In user-facing output
✓ SCOUT (DISCOVER) completed — 5 artifacts written
```

#### Directory Structure

```
agents/
├── control/
│   └── commander.md
├── exploration/
│   ├── catalyst.md         # v0.3
│   ├── scout.md
│   ├── cartographer.md
│   └── sage.md
├── feasibility/
│   └── gatekeeper.md
├── solution/
│   ├── architect.md
│   ├── orchestrator.md
│   └── sentinel.md
├── specialists/
│   ├── investigator.md
│   ├── guardian.md
│   ├── benchmark.md
│   ├── advocate.md
│   ├── oracle.md
│   └── maverick.md
├── learning/
│   ├── auditor.md
│   ├── adaptive.md
│   └── realist.md
└── document/
    └── scribe.md           # v0.3
```

### 4. Specialist Summoning (Adaptive)

COMMANDER decides when to summon specialists based on context:

**Phase 1 triggers** (during understanding):
- INVESTIGATOR: when SCOUT finds unknowns that block CARTOGRAPHER
- ORACLE: when domain terminology is ambiguous
- MAVERICK: when user input suggests exploring alternatives

**Phase 3 triggers** (during solution):
- GUARDIAN: when spec touches auth, PII, payments, compliance
- BENCHMARK: when NFRs mention scale, latency, throughput
- ADVOCATE: when spec has user-facing components
- SENTINEL: always (test strategy is mandatory)

**Any phase triggers**:
- INVESTIGATOR: when any agent flags `[NEEDS INVESTIGATION]`
- REALIST: when estimates seem unrealistic or AUDITOR confidence is low

## Release Plan

### v0.2: Structure & Naming (~1 week)

| Deliverable | Description |
|-------------|-------------|
| Dual naming | Add codenames to all 18 agent prompts |
| 4-phase model | Refactor `echelon.run.md` with phase structure |
| Autonomy modes | Add `--mode guided\|semi\|banzai` flag |
| Layer organization | Restructure `agents/` directory by layer |
| Config updates | Add `banzai` section to `config-template.yml` |
| README rewrite | Document new architecture, phases, naming |
| State schema | Update `state.json` with phase tracking |

### v0.3: New Agents (~1-2 weeks after v0.2)

| Deliverable | Description |
|-------------|-------------|
| CATALYST (BRAINSTORM) | New agent for guided ideation before SCOUT |
| SCRIBE | Phase 4 documentation agent |
| Structured research | INVESTIGATOR gets modes: `--research market\|domain\|technical` |
| New command | `/squad.document` for standalone Phase 4 |
| Preset integration | Banzai mode pulls defaults from installed presets |

### v0.4: Polish & Confidence (~1 week after v0.3)

| Deliverable | Description |
|-------------|-------------|
| Confidence scoring | Combined metric: evidence grade + calibration + domain familiarity |
| Communication styles | Add persona flavor to agent prompts (optional, toggle-able) |
| Project Confidence Score | 0-100 executive summary metric |
| Integration hooks | Prepare interfaces for Jira/Confluence (stubs, not full impl) |

## Decisions

### BMAD Extension for Spec-kit: Not Recommended

| Reason | Explanation |
|--------|-------------|
| Different philosophy | BMAD is interactive menu-driven; spec-kit is autonomous-first |
| Overlap | echelon v0.3+ will have the best BMAD features |
| Maintenance burden | Two systems to maintain for similar outcomes |
| BMAD is self-contained | Has its own installer, ecosystem, Discord |

### Spec-kit Core Changes: None

BMAD ideas should flow through extensions (echelon), not spec-kit core. Spec-kit core should stay minimal.

## References

- [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) - Source of inspiration
- [reverse-eng extension](https://github.com/spec-kit/spec-kit-reverse-eng) - Phase model reference
- [echelon implementation plan](../plans/2026-03-16-echelon-implementation.md) - Original implementation
