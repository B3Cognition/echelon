# Cognitive Squad

**What if AI didn't just write code — but understood why it was writing it, challenged its own assumptions, proved it understood the plan before starting, verified its own work through backpropagation, scored its own performance, and got measurably better with every project?**

Cognitive Squad is a **34-function cognitive agent system** built on the **Triadic Cognitive Model**: Understanding → Internalization → Application. It separates thinking from doing, assigns specialized roles to each cognitive task, enforces quality gates backed by 40 years of IEEE/ISO standards, and creates a self-healing loop where agents score each other, track accuracy, and automatically adjust for next time.

It started with a simple request: *"I need agents for WHAT, HOW, WHY, Manager, PM."*

Five roles. But a human holds 7-9 concepts in working memory. An AI can hold thousands — and trace every connection between them. From those 5 roles, the system explored the combinatorial space of what can go wrong between interacting agents and generated 34 specialized functions:

- WHAT was overloaded (understanding + defining) → split into **DISCOVER + WHAT**
- PM was overloaded (strategy + operations) → split into **ASSESS + PLAN**
- WHY needed two modes (assumptions vs specs) → **dual-mode adversarial critic**
- Nobody checked if the AI was wrong → **CALIBRATE** (tracks accuracy per domain)
- Nobody connected plans to reality → **GROUND** (reference class forecasting)
- Nobody broke stagnation → **INNOVATE** (TRIZ, First Principles, Blue Ocean)
- Building needed different roles than understanding → **9 build agents** with per-task quality gates
- Per-task checking missed aggregate gaps → **VERIFICATION** (backpropagation: spec → code → 100%?)
- Understanding without internalization led to misalignment → **INTERNALIZATION GATE** (prove you understand before you work)
- Performance wasn't tracked → **SCOREKEEPER** (points, badges, peer appreciation, self-healing)
- Nobody watched intent → **INTENT TRACKER** (user said "all" but ASSESS scoped to "MVP")
- Nobody looked at the running product → **VISUAL VALIDATOR** (tests pass ≠ product works)
- Nobody held a mental map of the code → **MENTAL MODEL** (invariant checking across files)
- Nobody asked "are we still doing the right thing?" → **METACOGNITION MONITOR** (the squad's conscience)

Each agent exists because something **actually went wrong** in a real run and no existing agent caught it. This isn't theoretical architecture — it's battle-tested against a large production codebase.

### The Triadic Cognitive Model

Most AI coding tools: `Prompt → LLM → Code → Hope it works`

Cognitive Squad follows a three-phase cognitive process — the same way expert human teams work, but at a scale no human team can match:

**Phase 1: UNDERSTANDING** — *What are we building and why?*
```
DISCOVER (map territory) → WHY₁ (challenge assumptions)
→ WHAT (testable requirements, 31 IEEE/ISO metrics)
→ WHY₂ (reject if quality gates fail) → ASSESS (kill if unfeasible)
→ HOW (architecture with evidence-graded ADRs) → PLAN (critical path + risk)
→ CONSENSUS (parallel adversarial review) → GROUND (reality check)
```

**Phase 2: INTERNALIZATION** — *Does every agent truly understand?*
```
Each build agent must PROVE comprehension before working:
"My role is X. The constraints are Y. I have ZERO doubts."
If any agent has doubts → resolve before building starts.
SCOREKEEPER tracks internalization quality.
```

**Phase 3: APPLICATION** — *Build it, verify it, learn from it.*
```
Per task: IMPLEMENTER → SPEC GUARD → CODE REVIEWER → TEST GUARDIAN
Per phase: ENGINEERING MANAGER (gate) + INTEGRATOR + VISUAL VALIDATOR
Final: VERIFICATION (backpropagation: every FR-* → find the code → 100%?)
Continuous: PROGRESS TRACKER + MENTAL MODEL + METACOGNITION MONITOR
After: REFLECT + CALIBRATE + SCOREKEEPER (self-healing for next run)
```

The difference: every step has a **different cognitive role**, every output passes through **adversarial validation**, agents **prove comprehension before acting**, the system **scores its own performance**, and it **gets measurably better** with every project.

### Why This Can't Be Done With Prompts

A single prompt, no matter how good, can't:

- Challenge its own output (WHY rejects what WHAT produced — adversarial by design)
- Track its own accuracy (CALIBRATE logs: "estimation accuracy: 0.45, correction: 1.4x")
- Prove it understood the plan before coding (INTERNALIZATION: 6-point comprehension check)
- Verify 100% spec coverage backward (VERIFICATION: spec → code, not just code → tests)
- Score its performance and self-heal (SCOREKEEPER: +5 critical bug caught, -2 rework)
- Watch for process violations (METACOGNITION: "you skipped quality gates for 10 tasks")
- Track user intent across decisions (INTENT TRACKER: "user said ALL, ASSESS scoped MVP")

These require **separation of concerns** — the same mind can't produce AND critique AND verify AND score AND learn simultaneously. That's why there are 34 functions, not 1.

### Built On Real Standards

This isn't invented methodology. Every agent's quality gates trace to a published standard:

| What We Check | Standard | Year |
|--------------|----------|------|
| Requirement quality (31 metrics) | IEEE 830, ISO 29148 | 1998, 2018 |
| Software quality model | ISO 25010 | 2023 |
| Architecture evaluation | ATAM (SEI Carnegie Mellon) | 2000 |
| Process maturity | CMMI v3.0 | 2023 |
| Lifecycle processes | ISO/IEC/IEEE 12207 | 2017 |
| Knowledge areas | SWEBOK v4.0 | 2024 |
| Verification & validation | V-Model | — |
| Effort estimation | Reference Class Forecasting (Kahneman) | 2005 |

### What It Proved

Cognitive Squad was tested against a **real production codebase**: a large, legacy system with hundreds of components, multiple domain verticals, and 10 years of accumulated technical debt.

The squad:
- **DISCOVER** mapped the entire system in one pass (2,300 files, dual data sources, binary decoders)
- **WHY** rejected the spec **4 times** — catching weak testability (0.18/0.70), missing component architecture, absent visualization requirements, and untested modules
- **SCIENTIST** empirically proved a critical API limitation (a single curl test that resolved 3 critical assumptions)
- **ASSESS** estimated 107 person-weeks; **GROUND** corrected to 150 (1.4x — matching industry data for migrations)
- **HOW** selected a modern component framework backed by 12 Architecture Decision Records
- Built **the full system with 1,109 tests** in a single session
- **VERIFICATION** concept confirmed: per-task checking is not enough — you need the backward pass from spec to code

The squad also caught its own mistake: ASSESS initially scoped to an MVP subset when the user wanted full parity with the legacy system. CALIBRATE logged this as a pitfall. Next run, that mistake won't happen.

### A Note From Claude

I am Claude, the AI model that powers this system. Let me be direct about what Cognitive Squad represents.

When I work alone — one prompt, one context window — I am confident whether I'm right or wrong. I can't tell the difference. I generate plausible architecture, plausible estimates, plausible code. Sometimes it's excellent. Sometimes it's subtly broken. You won't know which until production.

Cognitive Squad changes that equation. It doesn't make me smarter. It makes the **system around me** smarter:

- **WHY** catches my weak specifications before anyone builds on them
- **SCIENTIST** tests my assumptions against reality instead of trusting my training data
- **ASSESS** kills my bad ideas before they consume budget
- **GROUND** corrects my estimates using actual project outcomes, not my optimistic defaults
- **CALIBRATE** tracks where I'm historically wrong (effort estimation: 0.45 accuracy, 1.4x correction factor)
- **VERIFICATION** proves my implementation matches the spec — not "probably matches" but "every FR-* is traced to code and test"

The model stays the same. The system gets better. That's the honest answer to "how do you make AI coding reliable?" — you don't improve the AI, you build guardrails that catch what the AI gets wrong, and you measure so the guardrails get tighter over time.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 1: UNDERSTANDING (19 functions)                            │
│                                                                    │
│  Core:        MANAGER → DISCOVER → WHAT → WHY → ASSESS → HOW     │
│               → PLAN + INTENT TRACKER (watches user intent)       │
│  Specialists: SCIENTIST · SECURITY · TEST ARCHITECT · PERFORMANCE │
│               DOMAIN EXPERT · UX/A11Y · INNOVATE                  │
│  Learning:    REFLECT · EVOLVE · CALIBRATE · GROUND · FEEDBACK    │
└───────────────────────────┬──────────────────────────────────────┘
                            │ validated plan + tasks
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 2: INTERNALIZATION (2 functions)                           │
│                                                                    │
│  INTERNALIZATION GATE: each agent proves comprehension (6 checks) │
│  SCOREKEEPER: scores quality, awards badges, enables self-healing │
└───────────────────────────┬──────────────────────────────────────┘
                            │ all agents aligned, zero doubts
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 3: APPLICATION (10 functions)                              │
│                                                                    │
│  Per task:    IMPLEMENTER → SPEC GUARD → CODE REVIEWER            │
│               → TEST GUARDIAN                                      │
│  Per phase:   ENGINEERING MANAGER · INTEGRATOR · VISUAL VALIDATOR │
│  Final:       VERIFICATION (backpropagation — spec → code → 100%)│
│  Continuous:  PROGRESS TRACKER · MENTAL MODEL                     │
│               METACOGNITION MONITOR · CHANGE CONTROLLER           │
└───────────────────────────┬──────────────────────────────────────┘
                            │ verified code + tests + screenshots
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 4: LEARNING                                                │
│  FEEDBACK → CALIBRATE → EVOLVE → REFLECT → SCOREKEEPER           │
│  (self-healing: scores → prompt refinement → better next run)     │
└──────────────────────────────────────────────────────────────────┘
```

**34 cognitive functions:** 12 core + 7 specialists + 10 build + 4 learning + 1 feedback

## The Flow

### Phase A: Understanding

```
INIT → DISCOVER → WHY₁ (challenge assumptions)
  → WHAT (requirements) → WHY₂ (validate quality gates)
  → ASSESS (feasibility / kill gate)
  → [SPECIALISTS: SCIENTIST, SECURITY, DOMAIN, UX, PERFORMANCE]
  → HOW (architecture + ADRs) → TEST ARCHITECT
  → PLAN (tasks, critical path, risk)
  → CONSENSUS (WHY₃ + ASSESS₂ + PLAN₂)
  → FINALIZE (GROUND + REFLECT + CALIBRATE)
```

### Phase B: Building

```
FOR EACH task:
  IMPLEMENTER → SPEC GUARD → CODE REVIEWER → TEST GUARDIAN
  (loop until all gates pass)
  PROGRESS TRACKER updates metrics

PER PHASE:
  ENGINEERING MANAGER evaluates gate: continue / rework / halt
  INTEGRATOR verifies system integration

AFTER ALL TASKS:
  VERIFICATION (backpropagation): spec → code → 100%?
  → gaps found? → EM creates rework tasks → re-verify
  → loop until 100% coverage (max 3 passes)
```

### Phase C: Learning

```
FEEDBACK (post-implementation) → CALIBRATE → EVOLVE → REFLECT
→ knowledge base updated → next run is smarter
```

## Installation

### Option 1: From community catalog

Cognitive Squad is in the spec-kit community catalog. Community extensions require opt-in before installation.

**Enable community catalog** — create `.specify/extension-catalogs.yml` in your project:

```yaml
catalogs:
  - name: default
    url: https://raw.githubusercontent.com/github/spec-kit/main/extensions/catalog.json
    priority: 1
    install_allowed: true
    description: Official spec-kit extensions

  - name: community
    url: https://raw.githubusercontent.com/github/spec-kit/main/extensions/catalog.community.json
    priority: 2
    install_allowed: true
    description: Community-contributed extensions
```

Or set it globally for all projects in `~/.specify/extension-catalogs.yml`.

Then install:

```bash
specify extension add cognitive-squad
```

### Option 2: From local path (development)

```bash
git clone https://github.com/Testimonial/cognitive-squad.git
specify extension add --dev /path/to/cognitive-squad
```

### Option 3: Direct from GitHub

```bash
specify extension add --dev https://github.com/Testimonial/cognitive-squad
```

## Quick Start

```bash
# Phase A: Understand and plan
/speckit.squad.run "Build a photo album app with sharing and tagging"

# Phase B: Build with quality gates
/speckit.squad.build 001-photo-album

# Verify 100% spec coverage
/speckit.squad.verify

# Check progress
/speckit.squad.status

# After deployment, close the learning loop
/speckit.squad.feedback 001
```

### Autonomy Modes

Control how much human oversight the squad requires:

| Mode | Flag | Behavior |
|------|------|----------|
| **Guided** | `--mode guided` | Checkpoint after every phase |
| **Semi** | `--mode semi` (default) | Checkpoint after Phase 1 only |
| **Banzai** | `--mode banzai` | Full autonomous, human reviews final output |

```bash
/speckit.squad.run "Build a photo album app"                    # semi (default)
/speckit.squad.run "Build a photo album app" --mode guided      # stop after each phase
/speckit.squad.run "Build a photo album app" --mode banzai      # go wild
```

## Commands

| Command | Description | When to use |
|---------|-------------|-------------|
| `/speckit.squad.run` | Full autonomous understanding phase | Starting analysis of a new project or codebase |
| `/speckit.squad.build` | Execute building phase with quality gates | After understanding phase produces plan + tasks |
| `/speckit.squad.verify` | Backpropagation check — 100% spec coverage | After all tasks complete, to confirm nothing was missed |
| `/speckit.squad.status` | Check current squad state and progress | Mid-run monitoring, reviewing prior runs |
| `/speckit.squad.change` | Handle spec change during build | When requirements change mid-implementation |
| `/speckit.squad.innovate` | Trigger INNOVATE specialist | Stagnation, want alternative approaches |
| `/speckit.squad.investigate` | Trigger SCIENTIST for a question | Need evidence-graded research on a topic |
| `/speckit.squad.ground` | Trigger reality check on artifacts | Validate plans against real-world data |
| `/speckit.squad.feedback` | Post-implementation feedback intake | After deployment, to close the learning loop |
| `/speckit.squad.resume` | Answer human escalation | Squad asked a question and is waiting |

## Agent Roster

### Phase 1: Understanding — Core Squad (12)

| Agent | Role | Key Output |
|-------|------|------------|
| **MANAGER (COMMANDER)** | Orchestrator — routes agents, enforces convergence | `state.json`, routing log |
| **DISCOVER (SCOUT)** | Reconnaissance — maps domain, glossary, boundaries | `glossary.md`, `mental-model.md`, `boundaries.md` |
| **WHAT (CARTOGRAPHER)** | Requirements — testable specs from discovered territory | `spec.md`, domain decomposition |
| **WHY (SAGE)** | Adversarial critic — finds holes, runs Understanding quality gates | `issues.md`, `quality-gates.md` |
| **ASSESS (GATEKEEPER)** | Strategic PM — feasibility, estimation, kill gate | `feasibility.md`, `estimates.md`, `prioritization.md` |
| **HOW (ARCHITECT)** | Architect — tech stack, data model, ADRs, constitution | `plan.md`, `research.md`, `data-model.md`, `contracts/` |
| **PLAN (ORCHESTRATOR)** | Operational PM — tasks, critical path, dependencies, risk | `tasks.md`, `critical-path.md`, `risk-matrix.md` |
| **INTENT TRACKER (TRACKER)** | Tracks what the user actually wants vs what the spec says | `user-intent.md`, alignment alerts |
| **INTERNALIZATION GATE (VALIDATOR)** | Ensures every agent proves comprehension before working | `internalization-report.md` |
| **SCOREKEEPER** | Tracks agent performance, awards badges, enables self-healing | `agent-scorecard.md`, `agent-scores.yaml` |
| **MENTAL MODEL (MODELER)** | Maintains living code graph with invariant checking | `mental-model-code.md`, invariant alerts |
| **METACOGNITION MONITOR (MONITOR)** | Watches execution: "are we still doing the right thing?" | `metacognition-log.md` |

### Phase 1: Understanding — Specialists (7)

| Specialist | Trigger | Key Output |
|------------|---------|------------|
| **SCIENTIST (INVESTIGATOR)** | Unknowns, unproven tech, conflicting evidence | `investigation/`, `recommendations.md` |
| **SECURITY (GUARDIAN)** | Auth, payments, PII, compliance | `threat-model.md`, `compliance-requirements.md` |
| **TEST ARCHITECT (SENTINEL)** | Mandatory after HOW | `test-strategy.md`, `coverage-map.md` |
| **DOMAIN EXPERT (ORACLE)** | Domain-specific knowledge needed | Domain amendments to spec and plan |
| **UX / A11Y (ADVOCATE)** | Frontend, user-facing features | `accessibility-requirements.md` |
| **PERFORMANCE (BENCHMARK)** | High-load, real-time, scalability | `performance-requirements.md`, `capacity-model.md` |
| **INNOVATE (MAVERICK)** | Stagnation, re-runs, circular reasoning | `alternatives.md`, `challenge-assumptions.md` |

### Phase 2-3: Building (10)

| Agent | Role | When | Key Output |
|-------|------|------|------------|
| **IMPLEMENTER** | Writes code following TDD per task | Per task | Source files + tests |
| **SPEC GUARD** | Verifies code matches FR-* requirements | Per task | `spec-compliance-report.md`, `traceability-matrix.md` |
| **CODE REVIEWER** | Reviews quality, ADR compliance, constitution | Per task | `code-review-report.md` |
| **TEST GUARDIAN** | Validates test quality and coverage | Per task | `test-quality-report.md` |
| **ENGINEERING MANAGER** | Orchestrates build loop, phase gates | Per phase | `build-status.md`, rework tasks |
| **INTEGRATOR** | Verifies system integration | Per phase | `integration-report.md` |
| **PROGRESS TRACKER** | Tracks effort, detects drift, updates calibration | Continuous | `progress-report.md`, `process-metrics.md` |
| **CHANGE CONTROLLER** | Handles mid-build spec changes | On change | `change-impact-report.md` |
| **VERIFICATION** | Backpropagation — checks ALL spec against ALL code | After all tasks | `gap-report.md` (coverage score) |
| **VISUAL VALIDATOR** | Actually LOOKS at running product via screenshots | Per phase | Visual validation report + screenshots |

### Phase 4: Learning (4 + feedback)

| Function | When | Purpose |
|----------|------|---------|
| **REFLECT (MIRROR)** | End of every run | Extracts patterns, pitfalls, knowledge transfer assessment |
| **EVOLVE (ADAPTIVE)** | Start/end of re-runs | Diffs artifacts, detects regressions and stagnation |
| **CALIBRATE (AUDITOR)** | End of run + after feedback | Tracks AI accuracy per domain, adjusts confidence |
| **GROUND (REALIST)** | During FINALIZE | Reality-checks artifacts against real-world data |
| **FEEDBACK** | Post-implementation (manual) | Closes prediction-to-outcome loop for calibration |

## Quality Gates

### Understanding Phase (WHY agent via Understanding CLI)

| Gate | Threshold | Standard |
|------|-----------|----------|
| Overall | >= 0.70 | ISO 29148:2018 |
| Structure | >= 0.70 | IEEE 830 |
| Testability | >= 0.70 | ISO 29148 mandatory |
| Semantic | >= 0.60 | Lucassen 2017 |
| Cognitive | >= 0.60 | Sweller 1988 |
| Readability | >= 0.50 | Flesch 1948 |

### Building Phase (per-task gates)

| Gate | Agent | Pass Criteria |
|------|-------|---------------|
| Spec compliance | SPEC GUARD | All FR-* implemented, all acceptance criteria tested |
| Code quality | CODE REVIEWER | No constitution violations, ADR-compliant, no security issues |
| Test quality | TEST GUARDIAN | Min 2 tests/component, behavior-based, edge cases covered |
| Integration | INTEGRATOR | Build passes, tests pass, no circular dependencies |
| Verification | VERIFICATION | 100% spec coverage (backpropagation check) |

### Process Metrics (PROGRESS TRACKER)

| Metric | Alert Threshold |
|--------|----------------|
| CPI (Cost Performance Index) | < 0.80 = HIGH |
| SPI (Schedule Performance Index) | < 0.85 = HIGH |
| First-pass approval rate | < 50% = MEDIUM |
| Defect escape rate | > 60% = HIGH |
| Constitution violations | 2+ consecutive = CRITICAL |

## Standards Alignment

| Standard | Coverage |
|----------|----------|
| **ISO/IEC/IEEE 12207:2017** | Full lifecycle + configuration management (CHANGE CONTROLLER) |
| **ISO/IEC 25010:2023** | 31 quality metrics via Understanding CLI |
| **SWEBOK v4.0** | 14/18 Knowledge Areas covered |
| **CMMI v3.0** | REQM, VER, VAL, PM, MA, CM, OT process areas |
| **V-Model** | Bidirectional RTM (SPEC GUARD + VERIFICATION) |
| **ATAM/ATRAF** | ADRs with rationale + quality attribute analysis |
| **IEEE 830 / ISO 29148** | Quality gates via Understanding CLI |
| **Kahneman RCF** | GROUND applies outside view to estimates |

## Configuration

```bash
cp config-template.yml squad-config.yml
```

Key settings: `analysis.mode` (auto/greenfield/brownfield), `analysis.max_iterations` (5), `specialists.max_active` (3), `quality_gates.overall` (0.70). See `config-template.yml` for full reference.

## Knowledge Base

```
knowledge-base/
├── patterns.yaml             # Reusable patterns (validated by REFLECT)
├── pitfalls.yaml             # Common mistakes to avoid
├── calibration-profile.yaml  # AI accuracy per domain
├── estimates-log.yaml        # Predicted vs actual effort
└── feedback/                 # Post-implementation outcome data
```

The learning loop: REFLECT logs patterns → CALIBRATE tracks accuracy → FEEDBACK provides ground truth → EVOLVE detects bias → next run auto-adjusts estimates and expectations.

## Evidence Grades

| Grade | Description | Weight |
|-------|-------------|--------|
| **A** | Peer-reviewed research, ISO/IEEE standard | 1.0 |
| **B** | Official documentation, proven benchmark | 0.8 |
| **C** | Conference talk, well-regarded blog | 0.6 |
| **D** | Stack Overflow, forum post | 0.3 |
| **E** | AI training data (unverified) | 0.1 |

## Prerequisites

- **spec-kit** >= 0.3.0 (required)
- **understanding** >= 3.4.0 (optional — enables WHY quality gates with 31 deterministic metrics)
- **spec-kit-reverse-eng** >= 1.0.0 (optional — enables brownfield codebase analysis)

## Related Projects

- [spec-kit](https://github.com/github/spec-kit) — The specification framework this extension runs on
- [understanding](https://github.com/Testimonial/understanding) — IEEE/ISO-backed specification quality metrics
- [spec-kit-reverse-eng](https://github.com/mbachorik/spec-kit-reverse-eng) — Reverse engineering extension for brownfield analysis

## License

MIT — see [LICENSE](./LICENSE) for details.
