# Cognitive Squad

A Spec-Kit extension that orchestrates 19 specialized cognitive functions to handle the complete pre-code phase of software development. From an initial idea or existing codebase, Cognitive Squad autonomously discovers the domain, defines requirements, validates quality against IEEE/ISO standards, evaluates feasibility, designs architecture, builds a test strategy, and produces an estimated implementation plan -- all with evidence-graded confidence and a learning feedback loop that improves accuracy over time.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  TIER 1: CORE SQUAD (7 agents, always active)            │
│                                                          │
│  MANAGER → DISCOVER → WHAT → WHY → ASSESS → HOW → PLAN │
└──────────────────────────┬───────────────────────────────┘
                           │ summons on demand
┌──────────────────────────▼───────────────────────────────┐
│  TIER 2: SPECIALIST POOL (7 specialists)                 │
│                                                          │
│  SCIENTIST · SECURITY · TEST ARCHITECT · PERFORMANCE     │
│  DOMAIN EXPERT · UX/A11Y · INNOVATE                      │
└──────────────────────────┬───────────────────────────────┘
                           │ runs after/between
┌──────────────────────────▼───────────────────────────────┐
│  TIER 3: LEARNING LAYER (4 functions + feedback)         │
│                                                          │
│  REFLECT · EVOLVE · CALIBRATE · GROUND                   │
│  + FEEDBACK intake (post-implementation)                  │
└──────────────────────────────────────────────────────────┘
```

**Totals:** 7 core + 7 specialists + 4 learning + 1 feedback intake = **19 cognitive functions**.

## The Flow

The MANAGER routes through a state machine, dynamically adapting based on quality gates and domain signals:

```
INIT → DISCOVER → WHY1 (challenge assumptions)
  → WHAT (define requirements) → WHY2 (validate specs)
  → ASSESS (feasibility / kill gate)
  → [SPECIALISTS: SCIENTIST, SECURITY, DOMAIN, UX, PERFORMANCE]
  → HOW (architecture) → TEST ARCHITECT (mandatory)
  → PLAN (tasks, critical path, risk)
  → CONSENSUS (WHY3 + ASSESS2 + PLAN2 + specialists review)
  → FINALIZE (GROUND + REFLECT + CALIBRATE)
  → DONE
```

Any step can route back to an earlier stage if quality gates fail. ASSESS can kill a project entirely if unfeasible. The MANAGER enforces convergence after 5 iterations maximum.

## Installation

Install as a Spec-Kit extension:

```bash
# From registry
specify extension add cognitive-squad

# From local path (development)
specify extension add --dev /path/to/cognitive-squad
```

## Quick Start

```bash
# Full autonomous run with a project description
/speckit.squad.run "Build a photo album app with sharing and tagging"

# Check progress mid-run
/speckit.squad.status

# After implementation is complete, feed back results
/speckit.squad.feedback 001
```

## Commands

| Command | Description | When to use |
|---------|-------------|-------------|
| `/speckit.squad.run` | Full autonomous cognitive squad run | Starting a new analysis or re-running on existing specs |
| `/speckit.squad.status` | Check current squad state and progress | Mid-run monitoring, reviewing prior runs |
| `/speckit.squad.innovate` | Manually trigger INNOVATE specialist | Stagnation, want alternative approaches |
| `/speckit.squad.investigate` | Manually trigger SCIENTIST for a question | Need evidence-graded research on a topic |
| `/speckit.squad.ground` | Manually trigger reality check on artifacts | Validate plans against real-world constraints |
| `/speckit.squad.feedback` | Post-implementation feedback intake | After building the project, to close the learning loop |
| `/speckit.squad.resume` | Provide answer to human escalation | Squad asked a question and is waiting for your input |

## Agent Roster

### Tier 1: Core Squad

| Agent | Role | Key Output |
|-------|------|------------|
| **MANAGER** | Orchestrator -- routes agents, enforces convergence, resolves conflicts | `state.json`, routing log |
| **DISCOVER** | Reconnaissance -- maps domain, glossary, boundaries, assumptions | `glossary.md`, `mental-model.md`, `boundaries.md` |
| **WHAT** | Requirements definer -- testable specs from discovered territory | `spec.md`, domain decomposition |
| **WHY** | Adversarial critic -- finds holes, runs Understanding quality gates | `issues.md`, `quality-gates.md` |
| **ASSESS** | Strategic PM -- feasibility, estimation, prioritization, kill gate | `feasibility.md`, `estimates.md`, `mvp-scope.md` |
| **HOW** | Architect -- tech stack, data model, API contracts, ADRs | `plan.md`, `data-model.md`, `contracts/` |
| **PLAN** | Operational PM -- tasks, critical path, dependencies, risk | `tasks.md`, `critical-path.md`, `risk-matrix.md` |

### Tier 2: Specialist Pool

| Specialist | Trigger | Key Output |
|------------|---------|------------|
| **SCIENTIST** | Unknowns, unproven tech, conflicting evidence | Investigation reports, experiment results |
| **SECURITY** | Auth, payments, PII, compliance domains | `threat-model.md`, `compliance-requirements.md` |
| **TEST ARCHITECT** | Mandatory after HOW | `test-strategy.md`, `coverage-map.md` |
| **DOMAIN EXPERT** | Domain-specific knowledge needed | Domain amendments to spec and plan |
| **UX / A11Y** | Frontend, user-facing features | `accessibility-requirements.md`, `user-flow.md` |
| **PERFORMANCE** | High-load, real-time, scalability needs | `performance-requirements.md`, `capacity-model.md` |
| **INNOVATE** | Stagnation, re-runs, circular reasoning | `alternatives.md`, `challenge-assumptions.md` |

### Tier 3: Learning Layer

| Function | When | Purpose |
|----------|------|---------|
| **REFLECT** | End of every run | Extracts patterns and pitfalls to knowledge base |
| **EVOLVE** | Start/end of re-runs | Diffs artifacts, detects regressions, flags stagnation |
| **CALIBRATE** | End of run + after feedback | Tracks AI accuracy per domain, adjusts confidence |
| **GROUND** | During FINALIZE | Reality-checks artifacts against real-world data |
| **FEEDBACK** | Post-implementation (manual) | Closes prediction-to-outcome loop for calibration |

## Configuration

Copy the template and customize:

```bash
cp config-template.yml squad-config.yml
```

Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `analysis.mode` | `auto` | `auto` / `greenfield` / `brownfield` |
| `analysis.max_iterations` | `5` | Maximum squad iterations before forced convergence |
| `analysis.token_budget_k` | `1000` | Approximate token budget (thousands) |
| `analysis.convergence_delta` | `0.02` | Understanding score delta for convergence |
| `specialists.max_active` | `3` | Max simultaneous specialists |
| `specialists.always_test_architect` | `true` | Always summon TEST ARCHITECT |
| `quality_gates.overall` | `0.70` | Minimum Understanding overall score |

See `config-template.yml` for the complete reference.

## Knowledge Base

Cognitive Squad learns over time through YAML knowledge files:

```
knowledge-base/
├── patterns.yaml             # Reusable patterns (validated by REFLECT)
├── pitfalls.yaml             # Common mistakes to avoid
├── calibration-profile.yaml  # AI accuracy per domain
├── estimates-log.yaml        # Predicted vs actual effort
└── feedback/                 # Post-implementation outcome data
    └── 001-{project}.yaml
```

The learning loop:
1. **REFLECT** logs patterns and pitfalls after each run
2. **CALIBRATE** tracks prediction accuracy per domain
3. **FEEDBACK** (manual, post-implementation) provides ground truth
4. **EVOLVE** detects stagnation and confirmation bias
5. After 5-10 projects with feedback, estimates auto-adjust based on real data

## Evidence Grades

All research from SCIENTIST is graded for source quality:

| Grade | Description | Examples | Weight |
|-------|-------------|----------|--------|
| **A** | Peer-reviewed research, ISO/IEEE standard | IEEE 830, published papers | 1.0 |
| **B** | Official documentation, proven benchmark | Framework docs, reproducible benchmarks | 0.8 |
| **C** | Well-regarded blog, conference talk | ThoughtWorks Radar, conference presentations | 0.6 |
| **D** | Stack Overflow, forum post, anecdotal | Accepted SO answers, Reddit threads | 0.3 |
| **E** | AI training data (unverified) | LLM-generated without citation | 0.1 |

Higher grade wins in conflicts. Same grade: more recent wins. Experiment validation can upgrade a source from C-E to B.

## Prerequisites

- **spec-kit** >= 0.3.0 (required)
- **understanding** >= 3.4.0 (optional, enables WHY quality gates with 31 deterministic metrics)
- **spec-kit-reverse-eng** >= 1.0.0 (optional, enables brownfield codebase analysis)

## Related Projects

- [spec-kit](https://github.com/Testimonial/spec-kit) -- The specification framework this extension runs on
- [understanding](https://github.com/Testimonial/understanding) -- IEEE/ISO-backed specification quality metrics
- [spec-kit-reverse-eng](https://github.com/Testimonial/spec-kit-reverse-eng) -- Reverse engineering extension for brownfield analysis

## License

MIT -- see [LICENSE](./LICENSE) for details.
