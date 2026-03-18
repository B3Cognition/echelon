# Cognitive Squad

**What if AI didn't just write code — but understood why it was writing it, challenged its own assumptions, verified its own work, and got better with every project?**

Cognitive Squad is a **28-function cognitive agent system** that does what no single AI prompt can: it separates thinking from doing, assigns specialized roles to each cognitive task, enforces quality gates backed by 40 years of IEEE/ISO standards, and runs a backpropagation loop that catches every requirement the implementation missed.

It is not a code generator. It is a **development team** — with a DISCOVER agent that maps unknown territory, a WHY agent that rejects weak specifications, a SCIENTIST that runs real experiments before committing to architecture, an ASSESS agent that kills unfeasible ideas before they waste effort, and a VERIFICATION agent that traces every line of code back to the requirement that demanded it.

### Why This Matters

Most AI coding tools work like this:

```
Prompt → LLM → Code → Hope it works
```

Cognitive Squad works like this:

```
Idea → DISCOVER (map the territory)
     → WHY (challenge every assumption)
     → WHAT (write testable requirements, validated by 31 IEEE/ISO metrics)
     → ASSESS (kill it if unfeasible — before anyone writes code)
     → HOW (architecture with evidence-graded decisions)
     → PLAN (tasks with critical path and risk analysis)
     → BUILD (per-task: implement → spec guard → code review → test check)
     → VERIFY (backpropagation: every requirement → find the code → 100%?)
     → LEARN (what was wrong? calibrate for next time)
```

The difference: every step has a **different cognitive role**, every output passes through **adversarial validation**, and the system **measures its own accuracy** so the next project starts smarter than the last.

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

Cognitive Squad was tested against a **real production codebase**: Opta Sports Data Widgets V3 — 435,000 lines of code, 202 widgets, 19 sports, jQuery-based, 10 years of accumulated technical debt.

The squad:
- **DISCOVER** mapped the entire system in one pass (2,300 files, dual data sources, 43 binary decoders)
- **WHY** rejected the spec **4 times** — catching weak testability (0.18/0.70), missing video widget architecture, absent SVG requirements, and 106 untested widgets
- **SCIENTIST** empirically proved CORS is not supported on any Opta API (a single curl test that resolved 3 critical assumptions)
- **ASSESS** estimated 107 person-weeks; **GROUND** corrected to 150 (1.4x — matching industry data for migrations)
- **HOW** selected Lit 4 Web Components + Vite 6 + Signals backed by 12 Architecture Decision Records
- Built **206 widgets across 19 sports with 1,109 tests** in a single session
- **VERIFICATION** concept confirmed: per-task checking is not enough — you need the backward pass from spec to code

The squad also caught its own mistake: ASSESS initially scoped to 5 MVP sports (51 widgets) when the user wanted full V3 parity (202 widgets). CALIBRATE logged this as a pitfall. Next run, that mistake won't happen.

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
┌──────────────────────────────────────────────────────────────┐
│  PHASE A: UNDERSTANDING (19 functions)                        │
│                                                               │
│  Core:        MANAGER → DISCOVER → WHAT → WHY → ASSESS       │
│               → HOW → PLAN                                    │
│  Specialists: SCIENTIST · SECURITY · TEST ARCHITECT           │
│               PERFORMANCE · DOMAIN EXPERT · UX/A11Y · INNOVATE│
│  Learning:    REFLECT · EVOLVE · CALIBRATE · GROUND · FEEDBACK│
└───────────────────────────┬──────────────────────────────────┘
                            │ validated plan + tasks
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  PHASE B: BUILDING (9 functions)                              │
│                                                               │
│  Per task:    IMPLEMENTER → SPEC GUARD → CODE REVIEWER        │
│               → TEST GUARDIAN                                  │
│  Per phase:   INTEGRATOR · ENGINEERING MANAGER                │
│  Continuous:  PROGRESS TRACKER                                │
│  On change:   CHANGE CONTROLLER                               │
│  Final:       VERIFICATION (backpropagation — spec → code)    │
└───────────────────────────┬──────────────────────────────────┘
                            │ verified code + tests
                            ↓
┌──────────────────────────────────────────────────────────────┐
│  PHASE C: LEARNING                                            │
│  FEEDBACK → CALIBRATE → EVOLVE → REFLECT                     │
└──────────────────────────────────────────────────────────────┘
```

**28 cognitive functions:** 7 core + 7 specialists + 9 build + 4 learning + 1 feedback

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

```bash
# From registry
specify extension add cognitive-squad

# From local path (development)
specify extension add --dev /path/to/cognitive-squad
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

### Phase A: Understanding — Core Squad (7)

| Agent | Role | Key Output |
|-------|------|------------|
| **MANAGER** | Orchestrator — routes agents, enforces convergence | `state.json`, routing log |
| **DISCOVER** | Reconnaissance — maps domain, glossary, boundaries | `glossary.md`, `mental-model.md`, `boundaries.md` |
| **WHAT** | Requirements — testable specs from discovered territory | `spec.md`, domain decomposition |
| **WHY** | Adversarial critic — finds holes, runs Understanding quality gates | `issues.md`, `quality-gates.md` |
| **ASSESS** | Strategic PM — feasibility, estimation, kill gate | `feasibility.md`, `estimates.md`, `prioritization.md` |
| **HOW** | Architect — tech stack, data model, ADRs, constitution | `plan.md`, `research.md`, `data-model.md`, `contracts/` |
| **PLAN** | Operational PM — tasks, critical path, dependencies, risk | `tasks.md`, `critical-path.md`, `risk-matrix.md` |

### Phase A: Understanding — Specialists (7)

| Specialist | Trigger | Key Output |
|------------|---------|------------|
| **SCIENTIST** | Unknowns, unproven tech, conflicting evidence | `investigation/`, `recommendations.md` |
| **SECURITY** | Auth, payments, PII, compliance | `threat-model.md`, `compliance-requirements.md` |
| **TEST ARCHITECT** | Mandatory after HOW | `test-strategy.md`, `coverage-map.md` |
| **DOMAIN EXPERT** | Domain-specific knowledge needed | Domain amendments to spec and plan |
| **UX / A11Y** | Frontend, user-facing features | `accessibility-requirements.md` |
| **PERFORMANCE** | High-load, real-time, scalability | `performance-requirements.md`, `capacity-model.md` |
| **INNOVATE** | Stagnation, re-runs, circular reasoning | `alternatives.md`, `challenge-assumptions.md` |

### Phase B: Building (9)

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

### Phase C: Learning (4 + feedback)

| Function | When | Purpose |
|----------|------|---------|
| **REFLECT** | End of every run | Extracts patterns, pitfalls, knowledge transfer assessment |
| **EVOLVE** | Start/end of re-runs | Diffs artifacts, detects regressions and stagnation |
| **CALIBRATE** | End of run + after feedback | Tracks AI accuracy per domain, adjusts confidence |
| **GROUND** | During FINALIZE | Reality-checks artifacts against real-world data |
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
