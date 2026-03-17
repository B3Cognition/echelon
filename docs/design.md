# Cognitive Agent Squad — Design Specification

**Date:** 2026-03-16
**Status:** Approved (design phase)
**Runtime:** Spec-Kit Extension
**Entry Point:** `/speckit.squad.run`

---

## 1. Problem Statement

The initial phase of software development — understanding requirements, mapping domains, validating feasibility, designing architecture, and planning implementation — consumes 80% of project effort and is where the most expensive mistakes happen. Current AI coding tools dump entire repositories into prompts and hope the LLM understands. This produces:

- Generic architectures disconnected from domain reality
- Specs that pass no quality standard
- Plans with no estimation, no risk analysis, no critical path
- No feedback loop — the AI never learns whether its output was correct
- Equal confidence whether right or wrong

This design specifies a **Cognitive Agent Squad** — a system of 26 specialized cognitive functions packaged as a Spec-Kit extension that handles the complete development lifecycle: from initial idea through to validated, tested implementation.

---

## 2. Design Principles

1. **Context compilation over prompt stuffing** — Each agent receives a compiled context pack (domain map, quality scores, dependency graph), not the raw repository.
2. **Specifications as source of truth** — All understanding is externalized into documents, not locked in conversation context.
3. **Deterministic guardrails** — Quality gates backed by IEEE/ISO standards via Understanding's 31 metrics, not LLM opinion.
4. **Evidence over reasoning** — Measured experiment results > deterministic metrics > research > code evidence > agent reasoning.
5. **The system improves, not the model** — The model stays the same; the knowledge base, calibration profile, and evidence library grow with every project.
6. **Kill bad ideas early** — ASSESS gate prevents expensive planning of unfeasible or low-priority work.
7. **Closed feedback loop** — Post-implementation feedback flows back into calibration, grounding, and pattern recognition.

---

## 3. Architecture Overview

### Two-Phase System with Four Tiers

```
┌──────────────────────────────────────────────────────────────┐
│  PHASE A: UNDERSTANDING                                       │
│                                                                │
│  TIER 1: CORE SQUAD (7 agents)                                │
│  MANAGER → DISCOVER → WHAT → WHY → ASSESS → HOW → PLAN      │
│                                                                │
│  TIER 2: SPECIALIST POOL (7 specialists)                      │
│  SCIENTIST · SECURITY · TEST ARCHITECT · PERFORMANCE          │
│  DOMAIN EXPERT · UX/A11Y · INNOVATE                           │
│                                                                │
│  TIER 3: LEARNING LAYER (4 + feedback)                        │
│  REFLECT · EVOLVE · CALIBRATE · GROUND · FEEDBACK             │
└────────────────────────┬─────────────────────────────────────┘
                         │ validated plan + tasks
                         ↓
┌──────────────────────────────────────────────────────────────┐
│  PHASE B: BUILDING                                             │
│                                                                │
│  Per task:  IMPLEMENTER → SPEC GUARD → CODE REVIEWER          │
│                         → TEST GUARDIAN                        │
│  Per phase: INTEGRATOR                                         │
│  Continuous: PROGRESS TRACKER                                  │
│  On change: CHANGE CONTROLLER                                  │
└────────────────────────┬─────────────────────────────────────┘
                         │ working code + tests
                         ↓
┌──────────────────────────────────────────────────────────────┐
│  PHASE C: LEARNING (existing learning layer)                   │
│  FEEDBACK → CALIBRATE → EVOLVE → REFLECT                      │
└──────────────────────────────────────────────────────────────┘
```

**Totals:** 7 core + 7 specialists + 7 build + 4 learning + 1 feedback = **26 cognitive functions** in 1 Spec-Kit extension.

---

## 4. Tier 1: Core Squad

### 4.1 MANAGER

**Cognitive role:** Orchestrator — evaluates state after each agent's output, routes to next agent, enforces convergence, resolves conflicts, manages token budget.

**Key science:** Decision Theory (Herbert Simon — satisficing vs optimizing), Expected Value of Information (EVOI), Toulmin model of argumentation, delta convergence detection.

**Capabilities:**
- Detects greenfield vs brownfield (codebase exists?)
- Compiles context packs per agent (only relevant artifacts, not everything)
- Tracks quality trajectory across iterations (Understanding scores over time)
- Detects circular reasoning (same issue raised 3x)
- Enforces evidence hierarchy for conflict resolution
- Manages token budget allocation across agents
- Summons specialists based on domain signals from DISCOVER

**Convergence rules:**
- Understanding delta < 0.02 for 2 consecutive passes → stop WHY iterations
- Same issue appears 3x without resolution → defer or escalate to human
- Max 5 total squad iterations → force convergence with warnings
- Token budget exhausted → force finalize with quality report
- CALIBRATE confidence < 0.5 for a domain → summon SCIENTIST or flag for human

**Evidence hierarchy (for conflict resolution):**
1. SCIENTIST experiment results (measured reality)
2. Understanding metrics (deterministic, reproducible)
3. SCIENTIST research (graded A/B/C/D/E sources)
4. Code evidence (from Reverse-Eng / codebase)
5. Agent reasoning (lowest weight)

**Outputs:** `state.json`, routing log, convergence report, final sign-off.

---

### 4.2 DISCOVER

**Cognitive role:** Reconnaissance — maps the territory before anyone tries to define requirements. Surfaces implicit knowledge, builds domain vocabulary, identifies system boundaries, and catalogs what nobody thought to mention.

**Key science:** Domain-Driven Design (Eric Evans), Tacit Knowledge theory (Nonaka & Takeuchi), Bounded Context mapping.

**Primary tool:** spec-kit-reverse-eng (brownfield) / domain research pipeline (greenfield).

**What it does:**

- **Brownfield:** Runs Reverse-Eng extraction → analysis.json → domain decomposition. Then goes deeper: identifies implicit business rules in code, maps behavioral patterns (event flows, state transitions), extracts historical context from git history (why was it built this way?).

- **Greenfield:** Instead of merely structuring the user's description, DISCOVER runs a **domain research pipeline** — a programmatic equivalent of Reverse-Eng for when no code exists:
  1. **Reference architecture search** — SCIENTIST is summoned to find similar open-source projects, established reference architectures, and domain-specific patterns (e.g., "e-commerce" → search for proven e-commerce architectures, data models, common pitfalls).
  2. **Competitive/prior art scan** — Web search for existing solutions in the same problem space. Not to copy, but to map: what entities do they all have? What boundaries do they draw? What APIs do they expose? This gives DISCOVER the same structural understanding that Reverse-Eng provides from code.
  3. **Domain knowledge loading** — Search for domain-specific standards, regulations, and terminology (e.g., "healthcare app" → HL7/FHIR, HIPAA; "payment system" → PCI-DSS, ISO 8583). Loaded into glossary.
  4. **Assumption generation from analogy** — Based on reference architectures, generate explicit assumptions: "similar systems typically have X, Y, Z — do we?" This replaces the code-derived assumptions that Reverse-Eng provides.
  5. **User description structuring** — Only after domain research, structure the user's input against the discovered domain map.

- **Both:** Builds domain glossary (disambiguates terms), identifies system boundaries, catalogs assumptions that need validation, surfaces unknown unknowns.

**Greenfield vs brownfield parity:** Brownfield DISCOVER reads code to build understanding. Greenfield DISCOVER reads the ecosystem (reference architectures, similar projects, domain standards) to build equivalent understanding. Neither relies solely on what the user says.

**Outputs:**
- `glossary.md` — domain language with disambiguation (e.g., "order" means X in billing, Y in logistics)
- `mental-model.md` — entity/concept relationship map
- `boundaries.md` — system boundaries, external integrations, dependencies
- `assumptions.md` — explicit list of assumptions requiring validation
- `unknowns.md` — questions nobody has asked yet
- `reference-architectures.md` — similar projects/architectures analyzed (greenfield only)

---

### 4.3 WHAT

**Cognitive role:** Requirements definer — takes DISCOVER's mapped territory and writes precise, testable specifications.

**Key science:** IEEE 830-1998 (software requirements), ISO/IEC/IEEE 29148:2018 (requirements engineering), User Story Mapping (Jeff Patton).

**Primary tool:** spec-kit `/speckit.specify` workflow.

**What it does:**
- Transforms DISCOVER's domain map into structured requirements (functional + non-functional)
- Writes user stories with acceptance criteria (Given/When/Then)
- Defines success criteria (measurable, technology-agnostic)
- Identifies key entities and relationships (without implementation details)
- Scopes MVP vs full feature set

**Constraint:** No implementation details. No mention of languages, frameworks, databases. Written for non-technical stakeholders.

**Outputs:**
- `spec.md` — feature specification (spec-kit format)
- `00-overview.md` — domain summary with dependency graph
- Domain decomposition (numbered directories)

---

### 4.4 WHY

**Cognitive role:** Adversarial critic — finds holes, inconsistencies, quality failures, and unknown unknowns. The only agent that can block progress.

**Key science:** Cognitive Load Theory (Sweller 1988), Pre-mortem analysis (Gary Klein), Devil's Advocate methodology, Understanding's 31-metric framework (IEEE 830, ISO 29148, Lucassen 2017, Harel 2003/2005).

**Primary tool:** Understanding CLI (31 deterministic metrics + quality gates).

**Operating modes:**

WHY operates in two distinct modes depending on when it is invoked:

- **Assumption-challenge mode (WHY₁ — pre-WHAT):** Validates DISCOVER's outputs (glossary, mental model, boundaries, assumptions). Does NOT run Understanding metrics (no specs exist yet). Instead: challenges assumptions for logical consistency, identifies contradictions in the domain map, performs pre-mortem on the discovered understanding ("if our understanding of this system is wrong, where is it most likely wrong?"), and flags unknowns that need SCIENTIST investigation. Pass/fail criteria: all CRITICAL assumptions validated or flagged, no logical contradictions in domain model, unknowns cataloged.

- **Spec-validation mode (WHY₂, WHY₃ — post-WHAT):** Runs Understanding `validate` against specs → deterministic quality scores. Challenges requirements for ambiguity, incompleteness, untestability. Hunts for what's NOT written (unknown unknowns) — missing edge cases, unstated assumptions, implicit requirements. Checks internal consistency across all artifacts.

**Quality gates (spec-validation mode only, from Understanding, ISO-backed):**
- Overall ≥ 0.70 (ISO 29148:2018)
- Structure ≥ 0.70 (IEEE 830 §4.3.6)
- Testability ≥ 0.70 (ISO 29148 mandatory)
- Semantic ≥ 0.60 (Lucassen 2017)
- Cognitive ≥ 0.60 (Sweller 1988)
- Readability ≥ 0.50 (Flesch 1948)

**Blocking power:** In assumption-challenge mode: can block progress if CRITICAL assumptions are unvalidated. In spec-validation mode: blocks if quality gates fail or critical inconsistencies are found. MANAGER must route back to DISCOVER, WHAT, or HOW as appropriate.

**Outputs:**
- `issues.md` — scored findings (CRITICAL / HIGH / MEDIUM / LOW)
- `quality-gates.md` — Understanding metric results (spec-validation mode only)
- `assumption-review.md` — assumption validation results (assumption-challenge mode only)
- Amendment demands (routed back to responsible agent)

---

### 4.5 ASSESS

**Cognitive role:** Strategic PM and early kill gate — evaluates feasibility, estimates effort, prioritizes features, scopes MVP. Runs after WHY₂ (post-WHAT) to prevent HOW from wasting effort planning an architecture for unfeasible or low-priority requirements.

**Key science:** COCOMO II (Barry Boehm), Kano Model, RICE scoring (Reach/Impact/Confidence/Effort), Cone of Uncertainty, Cost of Delay / WSJF (SAFe), Function Point Analysis.

**What it does:**
- **Feasibility:** Can this be built within implied constraints (team size, budget, timeline)?
- **Estimation:** Function Point Analysis from spec entities → effort range with confidence interval. Adjusted by CALIBRATE's historical accuracy data.
- **Prioritization:** Classifies features using Kano (must-be / performance / delighter) and scores with RICE.
- **MVP scoping:** Identifies minimum viable scope. What must ship? What can defer to v2?
- **Kill gate:** If unfeasible or all features are low-priority → produce kill report, stop squad.

**Outputs:**
- `feasibility.md` — can-we/should-we verdict with rationale
- `prioritization.md` — RICE scores + Kano classification per feature
- `estimates.md` — effort estimates with confidence intervals (calibrated)
- `mvp-scope.md` — must-have vs nice-to-have vs v2-deferred

---

### 4.6 HOW

**Cognitive role:** Architect — makes technology decisions, designs system structure, owns cross-cutting concerns (security, observability, performance as architectural properties, not afterthoughts).

**Key science:** Architecture Tradeoff Analysis Method (ATAM), ISO 25010:2023 (quality models), Architecture Decision Records (ADRs).

**Primary tool:** spec-kit `/speckit.plan` workflow.

**What it does:**
- Selects technology stack with explicit rationale and alternatives considered
- Designs system structure (data model, API contracts, component architecture)
- Defines cross-cutting concerns as architectural decisions, not feature add-ons
- Creates constitution (non-negotiable project principles)
- Documents every decision with ADR format: decision + rationale + alternatives rejected + consequences

**Outputs:**
- `plan.md` — implementation plan with phases
- `research.md` — technical decisions with rationale
- `data-model.md` — entity definitions, relationships, validation rules
- `contracts/` — API/interface specifications
- `constitution.md` — project governance principles

---

### 4.7 PLAN

**Cognitive role:** Operational PM — breaks the architecture into executable tasks, identifies the critical path, maps dependencies, and assesses risk.

**Key science:** Critical Path Method (CPM), Theory of Constraints (Goldratt), PMBOK risk framework, Work Breakdown Structure (WBS).

**Primary tool:** spec-kit `/speckit.tasks` workflow.

**What it does:**
- Breaks plan into phased tasks (foundation → features → polish)
- Identifies critical path (longest dependency chain = minimum timeline)
- Maps task dependencies and parallelization opportunities
- Assesses risk per task (probability × impact)
- Identifies bottleneck tasks (block the most other tasks)

**Outputs:**
- `tasks.md` — ordered tasks with effort estimates, [P] parallel markers, dependencies
- `critical-path.md` — dependency chain analysis, minimum timeline
- `risk-matrix.md` — risk per task (probability × impact × mitigation)
- `dependencies.md` — task dependency graph, parallel execution map

---

## 5. Tier 2: Specialist Pool

Specialists are summoned by MANAGER on demand based on signals from DISCOVER and other core agents. They're like subject matter experts brought in for consultation — not permanent team members.

### 5.1 SCIENTIST

**Cognitive role:** Owns the complete scientific method for investigating unknowns. Not a librarian who finds papers — a scientist who formulates hypotheses, evaluates evidence quality, runs experiments, and produces confidence-scored recommendations.

**Trigger:** Unknown territory, unproven technology, conflicting evidence, CALIBRATE showing low confidence, INNOVATE proposing something unvalidated.

**The scientific method, applied:**
1. **QUESTION** — What don't we know? (from requesting agent)
2. **RESEARCH** — Web search, papers, official docs, prior art, benchmarks
3. **EVALUATE** — Grade evidence quality:
   - A: Peer-reviewed research, ISO/IEEE standard
   - B: Official documentation, proven benchmark
   - C: Well-regarded blog, conference talk, case study
   - D: Stack Overflow, forum post, anecdotal
   - E: AI training data (unverified, possibly stale)
4. **HYPOTHESIZE** — "If X, then Y because Z"
5. **EXPERIMENT** — Prototype spike in git worktree (throwaway code)
6. **MEASURE** — Run spike, collect performance/correctness data
7. **SYNTHESIZE** — Combine all evidence sources
8. **RECOMMEND** — Confidence-scored conclusion with evidence grades

**Any agent can request SCIENTIST.** MANAGER evaluates whether the investigation is worth the token cost.

**Outputs:**
- `investigation/{topic}.md` — full research report
- `evidence-grades.md` — scored sources
- `experiment-results.md` — spike measurement data
- `recommendations.md` — confidence-scored conclusions
- `knowledge-gaps.md` — what remains unknown

---

### 5.2 SECURITY

**Trigger:** Domain involves authentication, payments, PII, regulatory compliance.

**Science:** OWASP Top 10, STRIDE threat modeling, compliance frameworks (PCI-DSS, HIPAA, GDPR, SOC 2).

**Outputs:** `threat-model.md`, `compliance-requirements.md`, security-specific amendments to spec and plan.

---

### 5.3 TEST ARCHITECT

**Trigger:** Mandatory specialist — MANAGER summons after HOW completes, before or in parallel with PLAN. Every project needs a test strategy; this is a required step in the state machine, not a conditional summon.

**Position in flow:** Runs after HOW produces `plan.md` and `data-model.md`. Produces `test-strategy.md` before PLAN generates tasks (so test tasks are included in `tasks.md`). Can block: if acceptance criteria have no corresponding test approach, routes back to WHAT.

**Science:** Test pyramid, coverage analysis, acceptance criteria → test case mapping, boundary value analysis.

**Outputs:** `test-strategy.md`, `test-architecture.md`, `coverage-map.md` (requirements → test cases).

---

### 5.4 DOMAIN EXPERT

**Trigger:** Domain-specific knowledge required (fintech, healthcare, IoT, e-commerce, ML/AI, real-time systems, etc.).

**Loaded dynamically** based on DISCOVER's domain classification. Provides domain patterns, regulatory requirements, common pitfalls, and terminology.

**Outputs:** Domain-specific amendments to spec, plan, and glossary.

---

### 5.5 UX / A11Y

**Trigger:** Frontend, user-facing features, accessibility requirements.

**Science:** WCAG 2.1/2.2, Nielsen's 10 usability heuristics, user flow analysis.

**Outputs:** `accessibility-requirements.md`, `user-flow.md`, UX-specific amendments to spec.

---

### 5.6 PERFORMANCE

**Trigger:** High-load requirements, real-time constraints, scalability needs detected in spec or plan. Also summoned when SCIENTIST experiment results show performance concerns.

**Science:** Load modeling, capacity planning, Little's Law, Amdahl's Law, benchmarking methodology.

**Outputs:** `performance-requirements.md`, `capacity-model.md`, performance-specific amendments to plan and architecture.

---

### 5.7 INNOVATE

**Trigger:** Re-runs (iteration ≥ 2), stagnation detected by EVOLVE, score plateau. Also summoned on first run if MANAGER detects circular reasoning (same issue raised 3x without resolution) — serves as an escape valve before escalating to human.

**Science:** TRIZ (40 inventive principles), Design Thinking (IDEO — diverge before converge), Blue Ocean Strategy, Antifragility (Taleb), First Principles decomposition.

**What it does:** Proposes 2-3 fundamentally different approaches, challenges established assumptions, introduces controlled risk with upside analysis.

**Key rule:** INNOVATE proposes, WHY + ASSESS evaluate. Innovation without validation is chaos. Validation without innovation is stagnation.

**Outputs:**
- `alternatives.md` — fundamentally different approaches
- `risk-opportunities.md` — risky ideas with upside analysis
- `challenge-assumptions.md` — "what if X isn't true?"

---

## 6. Tier 3: Learning Layer

### 6.1 REFLECT

**When:** End of every squad run.

**What it does:** Post-run analysis — extracts what assumptions were wrong, which patterns worked, what the squad should do differently next time. Logs reusable patterns to the knowledge base.

**Outputs:** Updates to `knowledge-base/patterns.yaml`, `knowledge-base/pitfalls.yaml`.

---

### 6.2 EVOLVE

**When:** Start and end of every re-run (loads prior state, diffs against previous).

**Science:** Kaizen (continuous improvement), Statistical Process Control (is variance normal or signal?), confirmation bias detection.

**What it does:**
- Diffs artifacts between runs (what changed, why)
- Measures quality trajectory over time (are scores improving, flat, or oscillating?)
- Detects regressions (things that got worse)
- Flags stagnation (no improvement → triggers INNOVATE)
- Checks knowledge base for confirmation bias (are past patterns becoming prison bars?)

**Outputs:**
- `evolution-report.md` — diff between runs
- `improvement-metrics.md` — quality trajectory
- `regression-alerts.md` — things that got worse
- `stagnation-flags.md` — areas with no improvement
- `bias-check.md` — knowledge base entries that may be stale

---

### 6.3 CALIBRATE

**When:** End of every squad run + after FEEDBACK intake.

**Science:** Brier Score (probability calibration), Bayesian updating from outcomes, metacognition research (Dunning-Kruger correction).

**What it does:**
- Tracks AI accuracy per domain (e.g., "REST API design: 92%, distributed systems: 58%")
- Builds confidence profile used by MANAGER (where to push harder, when to summon specialists)
- Adjusts ASSESS estimates based on historical accuracy (e.g., "multiply backend estimates by 1.4x")
- Flags low-confidence domains for human input or SCIENTIST investigation

**Outputs:**
- `knowledge-base/calibration-profile.yaml` — accuracy per domain
- `confidence-flags.md` — per-artifact confidence scores

---

### 6.4 GROUND

**When:** During FINALIZE phase (reality-checks all artifacts before delivery).

**Science:** Reference Class Forecasting (Kahneman/Flyvbjerg), Evidence-Based Software Engineering (Kitchenham), Outside View vs Inside View.

**What it does:**
- Connects plans to real-world data: actual infrastructure costs, production benchmarks, team capacity
- Compares estimates to actual outcomes from past projects (via FEEDBACK data)
- Checks architectural decisions against operational constraints
- Flags disconnects: "plan says microservices but budget supports only 2 containers"

**Outputs:**
- `reality-check.md` — grounded assessment of all artifacts
- `cost-analysis.md` — real infrastructure/operational costs
- `benchmark-data.md` — relevant performance benchmarks

---

### 6.5 FEEDBACK (Post-Implementation Intake)

**When:** After implementation is complete (weeks/months later). Triggered manually via `/speckit.squad.feedback <spec-id>`.

**The `spec-id` parameter:** The sequential feature number from the spec-kit naming convention (e.g., `001`, `002`). This matches the `.specify/specs/{NNN}-{feature-name}/` directory. The squad prints the `spec-id` on completion of each run. Use `/speckit.squad.status` to list prior spec IDs and their run dates.

**Purpose:** Closes the loop between the squad's predictions and real-world outcomes. Without this, CALIBRATE has no ground truth.

**What it collects:**

| Dimension | Question | Updates |
|-----------|----------|---------|
| Effort accuracy | Actual time vs estimated? | CALIBRATE + ASSESS accuracy log |
| Architecture decisions | Which held vs broke under load? | CALIBRATE + HOW patterns |
| Requirements quality | Which were missing or wrong? | CALIBRATE + WHAT accuracy |
| Risk accuracy | Which risks materialized? Which were missed? | PLAN risk model |
| Test strategy | What gaps were found in production? | TEST ARCHITECT patterns |
| SCIENTIST accuracy | Which recommendations proved correct? | Evidence grade validation |

**Storage:**
```
knowledge-base/
├── feedback/
│   ├── 001-{project-name}.yaml
│   ├── 002-{project-name}.yaml
│   └── ...
├── calibration-profile.yaml    # updated with real accuracy
├── estimates-log.yaml          # predicted vs actual
└── patterns.yaml               # validated (proven in production)
```

**The closed loop:**
```
SQUAD → artifacts → implementation → REALITY
  ↑                                      │
  └──────── FEEDBACK ← outcomes ─────────┘
```

After 5-10 projects with feedback, the system has real calibration data. ASSESS adjusts estimates automatically. WHY knows where the AI is historically weak. GROUND has real reference classes. The system genuinely learns.

---

## 7. Manager State Machine

### Flow (dynamic, Manager-routed)

```
INIT
  │
  ├─ detect greenfield → DISCOVER (from user input)
  └─ detect brownfield → DISCOVER (via Reverse-Eng)
  │
  ▼
DISCOVERED
  │→ WHY₁ (challenge understanding — are assumptions valid?)
  │    │
  │    ├─ FAIL → route back to DISCOVER (re-investigate)
  │    └─ PASS ↓
  │
  ▼
WHAT (define requirements from discovered territory)
  │→ WHY₂ (challenge specs — Understanding quality gates)
  │    │
  │    ├─ FAIL → route back to WHAT (fix specs)
  │    └─ PASS ↓
  │
  ▼
ASSESS (early kill gate)
  │
  ├─ KILL (unfeasible / low-value) → produce kill report → DONE
  ├─ DEFER (v2) → reduce scope → re-route to WHAT
  └─ PASS → summon SPECIALISTS based on domain
  │
  ▼
[SCIENTIST if unknowns exist — investigate before committing]
[SECURITY / DOMAIN / UX / PERFORMANCE — if relevant]
  │
  ▼
HOW (architecture, informed by specialist input)
  │
  ▼
TEST ARCHITECT (mandatory — produces test-strategy.md from plan.md + data-model.md)
  │
  ▼
PLAN (tasks + test tasks, critical path, dependencies, risk)
  │
  ▼
CONSENSUS (parallel)
  │  WHY₃ + ASSESS₂ + PLAN₂ + active SPECIALISTS
  │
  │  ASSESS₂ receives: plan.md + data-model.md + contracts/ + tasks.md + original estimates
  │    → re-evaluates feasibility against concrete architecture
  │    → updates effort estimates with architectural complexity
  │    → IMPLEMENTABILITY CHECK (developer-perspective feasibility):
  │      • Can a developer pick up each task and execute it without unstated knowledge?
  │      • Do tasks reference APIs, libraries, or services that actually exist?
  │      • Are "parallel" tasks truly independent (no hidden shared state or ordering)?
  │      • Does the tech stack match available team skills (from constitution/constraints)?
  │      • Are task descriptions self-contained or do they require reading 5 other docs?
  │      • Can each task be tested independently as described?
  │    → produces: implementability-report.md (scored per task: READY / NEEDS_CLARIFICATION / BLOCKED)
  │    → can flag but NOT kill at this stage (only CRITICAL feasibility issues route back to HOW)
  │
  │  PLAN₂ receives: updated plan.md + test-strategy.md + specialist outputs + implementability-report.md
  │    → re-evaluates task dependencies with specialist-added tasks
  │    → updates critical path if specialist work changed sequencing
  │    → validates all specialist outputs have corresponding tasks
  │    → incorporates implementability feedback (splits unclear tasks, adds missing context)
  │
  ├─ ALL PASS → FINALIZE
  ├─ MINOR issues → MANAGER resolves, re-run consensus
  └─ CRITICAL issues → route back to failing stage
  │
  ▼
FINALIZE
  │→ GROUND (reality check all artifacts)
  │→ REFLECT (extract learnings)
  │→ EVOLVE (diff against prior runs if re-run)
  │→ CALIBRATE (update confidence profile)
  │
  ▼
DONE → deliver artifacts
  │
  │  ... weeks/months later ...
  │
  ▼
FEEDBACK (post-implementation intake) → updates knowledge base

ERROR (entered when external tool fails)
  │→ MANAGER logs failure + affected agent
  │→ If Understanding CLI unavailable → WHY falls back to heuristic review (no quality gates, flag as degraded)
  │→ If Reverse-Eng fails → DISCOVER falls back to manual greenfield mode (ask user for input)
  │→ If spec-kit CLI unavailable → HOW/PLAN produce artifacts manually (markdown, no spec-kit validation)
  │→ If subagent times out → MANAGER retries once, then skips agent with warning in final report
  │→ All degraded-mode artifacts are flagged in final delivery as UNVALIDATED
```

### CONSENSUS Phase Agent Definitions

| Agent | Inputs | Validates | Can Block? |
|-------|--------|-----------|------------|
| **WHY₃** | All artifacts (spec, plan, tasks, specialist outputs) | Full Understanding quality gates + cross-artifact consistency | Yes — CRITICAL issues route back |
| **ASSESS₂** | plan.md + data-model.md + contracts/ + tasks.md + original estimates.md | Feasibility against concrete architecture, effort re-estimation, **implementability check** (can devs execute these tasks?) | Only for CRITICAL feasibility issues |
| **PLAN₂** | Updated plan.md + test-strategy.md + specialist outputs | Task completeness, dependency accuracy, critical path validity | Only if specialist outputs have no tasks |

### Manager Decision Points

| Decision | Signal | Action |
|----------|--------|--------|
| Greenfield vs brownfield | Codebase exists in target directory | Route DISCOVER accordingly |
| Which specialists to summon | DISCOVER domain classification + CALIBRATE confidence | Summon matching specialists |
| When to kill an idea | ASSESS feasibility < threshold or RICE below cutoff | Produce kill report, stop |
| When to loop back | WHY critical issues or Understanding gate fails | Route to responsible agent |
| When to summon SCIENTIST | Unknown territory, conflicting evidence, CALIBRATE < 0.5 | Dispatch SCIENTIST with question |
| When to stop iterating | Delta < 0.02 for 2 passes OR max 5 iterations OR budget exhausted | Force finalize |
| How to resolve conflicts | Evidence hierarchy | Experiments > metrics > research > code > reasoning |
| When to trigger INNOVATE | EVOLVE detects stagnation on re-runs OR circular reasoning 3x on first run | Summon INNOVATE specialist |
| ASSESS DEFER loop | DEFER re-route ≥ 2 with no scope stabilization | Produce kill report or escalate to human. DEFER re-routes count toward the 5-iteration max. |
| External tool failure | Non-zero exit or timeout from Understanding/Reverse-Eng/spec-kit | Enter ERROR state, attempt fallback |
| Max specialists exceeded | Projected specialist token cost > 40% of total budget | Prioritize by domain signal strength, defer lower-priority specialists |

### Human Escalation Protocol

When the squad must escalate to a human (same issue 3x, CALIBRATE < 0.5 after SCIENTIST, unresolvable conflict):

1. **MANAGER produces** `escalation-request.md` containing: the specific question, context (what was tried), options considered, and a recommended answer.
2. **State machine enters BLOCKED state** — recorded in `state.json` with `"status": "blocked"`, `"reason": "..."`.
3. **User is notified** via terminal output with the escalation summary.
4. **User responds** via `/speckit.squad.resume <answer>` — MANAGER incorporates the answer and re-routes to the appropriate agent.
5. **If no response** within the session — squad produces artifacts with `UNRESOLVED` flags on blocked sections.

---

## 8. Phase B: Building

Phase A (Understanding) produces a validated plan with tasks, specs, ADRs, constitution, and test strategy. Phase B (Building) executes that plan with role-based agents and quality gates. The MANAGER orchestrates both phases but uses different agent pools for each.

### 8.1 Build Agents (6 agents)

#### IMPLEMENTER

**Cognitive role:** Developer — writes production code and tests for a single task from `tasks.md`.

**Key science:** Test-Driven Development (Kent Beck), Clean Code (Robert Martin).

**Process:** Reads the task, referenced FR-* requirements, ADRs, and constitution. Writes failing tests first, then minimal passing code, then refactors. Verifies all acceptance criteria, `tsc --noEmit`, and `vitest run`.

**Outputs:** Source files, test files, status report (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED).

**Agent file:** `agents/build/implementer.md`

#### SPEC GUARD

**Cognitive role:** Traceability enforcer — verifies that implemented code matches specification requirements.

**Key science:** Requirements Traceability (IEEE 830), Specification by Example (Gojko Adzic).

**Process:** For each FR-* requirement referenced by the task, verifies the code implements the correct actor/action/object/outcome/constraints. Checks acceptance criteria have corresponding tests. Detects scope creep (code not traced to any requirement).

**Verdict:** PASS / FAIL (with specific gaps) / WARN (edge cases uncovered).

**Outputs:** Appends to `spec-compliance-report.md` with traceability matrix (FR-* to file:line).

**Agent file:** `agents/build/spec-guard.md`

#### CODE REVIEWER

**Cognitive role:** Quality gate — reviews code for bugs, security, patterns, and architectural compliance.

**Key science:** Google Engineering Practices, OWASP Secure Coding Guidelines.

**Review checklist:** Constitution compliance, ADR compliance, code quality (function length < 30 lines, nesting < 3 levels, no magic numbers), security (no XSS, no injection, no hardcoded secrets), TypeScript strictness, performance (no memory leaks, no N+1), accessibility (ARIA, keyboard handlers).

**Verdict:** APPROVED / CHANGES_REQUESTED (with specific issues) / BLOCKED (architectural redesign needed).

**Outputs:** Appends to `code-review-report.md`.

**Agent file:** `agents/build/code-reviewer.md`

#### TEST GUARDIAN

**Cognitive role:** Test quality gate — validates that tests are sufficient, meaningful, and cover edge cases.

**Key science:** Test Pyramid (Mike Cohn), Mutation Testing principles.

**Process:** Counts tests against minimums (2 per function, 3 per component, 4 per API endpoint). Checks tests test behavior not implementation. Verifies meaningful assertions (not just "doesn't throw"). Checks edge case coverage (null, empty, boundary values, error paths). Updates `coverage-map.md`.

**Verdict:** PASS / FAIL (with missing tests) / WARN (improvement suggestions).

**Outputs:** Appends to `test-quality-report.md`, updates `coverage-map.md`.

**Agent file:** `agents/build/test-guardian.md`

#### INTEGRATOR

**Cognitive role:** System-level verifier — confirms that individually-tested components work together.

**Key science:** Integration Testing (Martin Fowler), Dependency Analysis.

**When:** Runs after each build phase checkpoint (not after every task).

**Process:** Full build (`npm run build`), type check (`tsc --noEmit`), full test suite (`vitest run`), integration checks (module registration, contract compliance, data flow, lifecycle), bundle size analysis, circular dependency detection.

**Verdict:** PASS / FAIL (with specific component pairs and responsible tasks).

**Outputs:** `integration-report.md` (one per phase checkpoint).

**Agent file:** `agents/build/integrator.md`

#### PROGRESS TRACKER

**Cognitive role:** Effort monitor — tracks actual vs estimated effort, detects schedule drift, updates calibration data.

**Key science:** Earned Value Management (EVM), Reference Class Forecasting (Kahneman).

**When:** Runs after each task completion (lightweight).

**Process:** Records task ID, estimated vs actual effort, and ratio. Updates running totals. Detects drift (3 consecutive tasks > 1.5x, or phase total > 1.3x). Updates `calibration-profile.yaml`. Predicts completion based on current burn rate.

**Alerts:** DRIFT_WARNING, PHASE_OVERRUN, ACCELERATION_WARNING, SYSTEMATIC_BIAS.

**Outputs:** Appends to `progress-report.md`, updates `knowledge-base/estimates-log.yaml` and `knowledge-base/calibration-profile.yaml`.

**Agent file:** `agents/build/progress-tracker.md`

### 8.2 Build State Machine

```
BUILD PHASE (per task from tasks.md):
  FOR EACH task in tasks.md (ordered by phase, respecting dependencies):
    │
    IMPLEMENTER dispatched with task + spec context
      │
      ├─ DONE → proceed to review
      ├─ NEEDS_CONTEXT → MANAGER provides context, re-dispatch
      └─ BLOCKED → MANAGER escalates or skips
      │
    SPEC GUARD validates code vs FR-* requirements
      │
      ├─ PASS → proceed to code review
      └─ FAIL → IMPLEMENTER fixes gaps, re-validate
      │
    CODE REVIEWER checks quality + ADR + constitution
      │
      ├─ APPROVED → proceed to test review
      └─ CHANGES_REQUESTED → IMPLEMENTER fixes, re-review
      │
    TEST GUARDIAN validates test quality + coverage
      │
      ├─ PASS → task complete
      └─ FAIL → IMPLEMENTER adds tests, re-validate
      │
    PROGRESS TRACKER records effort, checks for drift
    │
  END FOR
  │
  INTEGRATOR runs after each phase checkpoint
    │
    ├─ PASS → next phase
    └─ FAIL → IMPLEMENTER fixes integration issues
```

### 8.3 Build Convergence Rules

| Rule | Threshold | Action |
|------|-----------|--------|
| Max fix cycles per quality gate | 2 | Flag as DEGRADED, proceed |
| Max IMPLEMENTER dispatches per task | 7 (1 initial + 2 per gate) | Force complete with DEGRADED flag |
| Max BLOCKED tasks before pause | 3 | MANAGER assesses, may re-order or escalate |
| Max DEGRADED tasks | 30% of total | Print warning, continue |
| Token budget for build phase | 2M tokens (configurable) | Force complete with report |
| Wall-clock time limit | 60 minutes | Force complete with report |

### 8.4 Build Artifacts

Phase B produces these report files in `.specify/specs/{feature}/`:

| Artifact | Producer | Content |
|----------|----------|---------|
| `spec-compliance-report.md` | SPEC GUARD | Per-task FR-* traceability matrix, acceptance criteria coverage |
| `code-review-report.md` | CODE REVIEWER | Per-task constitution/ADR compliance, issues found |
| `test-quality-report.md` | TEST GUARDIAN | Per-task test inventory, quality assessment, missing tests |
| `integration-report.md` | INTEGRATOR | Per-phase build/type/test results, bundle analysis, dependency graph |
| `progress-report.md` | PROGRESS TRACKER | Per-task effort tracking, drift alerts, completion predictions |

### 8.5 Build Entry Point

The build phase is invoked via `/speckit.squad.build`, which is separate from `/speckit.squad.run` (Phase A). The MANAGER decides at the end of Phase A whether to offer the user the option to proceed to building, but the user must explicitly invoke the build command.

---

## 9. Tool Integration

| Tool | Version | Used By | Purpose |
|------|---------|---------|---------|
| **spec-kit** | ≥0.3.0 | WHAT (specify), HOW (plan), PLAN (tasks), constitution | Forward spec-driven workflow |
| **understanding** | ≥3.4.0 | WHY (31 metrics + quality gates), CALIBRATE (accuracy) | Deterministic requirements quality analysis |
| **spec-kit-reverse-eng** | ≥1.0.0 | DISCOVER (brownfield extraction), EVOLVE (cross-run diffing) | Code → specification extraction |

---

## 10. Context Pack Design

Each agent receives a **compiled context pack** — not the raw repository. MANAGER assembles packs per agent:

| Agent | Receives |
|-------|----------|
| DISCOVER | User input or codebase path + knowledge-base/calibration-profile.yaml |
| WHAT | glossary.md + mental-model.md + boundaries.md + assumptions.md + unknowns.md |
| WHY | All current artifacts + Understanding CLI access + calibration-profile.yaml |
| ASSESS | spec.md + glossary.md + assumptions.md + issues.md (from WHY₂) + calibration-profile.yaml + estimates-log.yaml |
| HOW | spec.md + feasibility.md + prioritization.md + constitution.md + specialist outputs |
| TEST ARCHITECT | plan.md + data-model.md + spec.md (acceptance criteria) + contracts/ |
| PLAN | plan.md + research.md + data-model.md + contracts/ + test-strategy.md + risk data |
| SCIENTIST | Specific question + relevant artifacts + web search + worktree access |
| SPECIALISTS | Domain-relevant artifacts only |
| ASSESS₂ (consensus) | plan.md + data-model.md + contracts/ + tasks.md + original estimates.md + constitution (team constraints) |
| PLAN₂ (consensus) | Updated plan.md + test-strategy.md + specialist outputs |
| LEARNING LAYER | All artifacts + prior run data (if re-run) + feedback history |

This is the "precompiled header" pattern: each agent gets the minimum context needed, not everything.

**Every agent also receives `reasoning-journal.json`** — a shared structured log that preserves the *why* behind decisions, not just the *what*. This solves the lossy inter-agent communication problem.

### Reasoning Journal

The problem: when DISCOVER writes `boundaries.md`, the nuance of *why* a boundary was drawn there (a subtle insight from code analysis, a domain expert's warning, a historical lesson) gets compressed into prose. Downstream agents read the boundary but miss the reasoning.

The solution: every agent appends structured entries to `reasoning-journal.json` alongside its artifacts:

```json
{
  "entries": [
    {
      "id": "RJ-001",
      "agent": "DISCOVER",
      "timestamp": "2026-03-16T10:23:00Z",
      "type": "insight",
      "artifact": "boundaries.md",
      "section": "payment-service boundary",
      "reasoning": "Separated payment from order because the legacy code had 3 production incidents caused by payment transaction locks blocking order reads. Git blame shows this was patched 4 times without fixing the root coupling.",
      "confidence": 0.92,
      "evidence_grade": "B",
      "implications": ["HOW must ensure async communication between payment and order domains", "PLAN should schedule payment service as independent deployable"]
    },
    {
      "id": "RJ-002",
      "agent": "WHY",
      "timestamp": "2026-03-16T10:31:00Z",
      "type": "challenge",
      "references": "RJ-001",
      "reasoning": "DISCOVER's payment boundary is well-evidenced (grade B from git history). However, the assumption that async communication is required needs SCIENTIST validation — eventual consistency may not be acceptable for payment confirmations.",
      "action_required": "SCIENTIST: investigate sync vs async payment confirmation patterns"
    }
  ]
}
```

**Entry types:**
- `insight` — discovery or analysis that should inform downstream agents
- `challenge` — WHY raising a concern with reasoning
- `decision` — HOW/ASSESS making a choice with rationale and alternatives rejected
- `assumption` — something taken as true without proof (flagged for validation)
- `evidence` — SCIENTIST reporting findings with quality grade

**How agents use it:**
- Each agent receives the full journal as part of its context pack
- Agents can search by `artifact`, `agent`, `type`, or `references` to find relevant reasoning
- WHY uses it to trace whether decisions were properly justified
- ASSESS uses it to understand confidence levels behind estimates
- PLAN uses `implications` fields to discover hidden task dependencies

This is the shared memory that prevents lossy handoffs between subagents.

---

## 11. Extension File Structure

```
.specify/extensions/squad/
├── extension.yml                    # manifest: commands, config, hooks
├── CLAUDE.md                        # agent context for Claude Code
├── README.md                        # user documentation
│
├── commands/
│   ├── squad.run.md                 # main entry: autonomous run
│   ├── squad.status.md              # check current state
│   ├── squad.innovate.md            # manually trigger INNOVATE
│   ├── squad.investigate.md         # manually trigger SCIENTIST
│   ├── squad.ground.md              # manually trigger reality check
│   ├── squad.feedback.md            # post-implementation feedback intake
│   ├── squad.resume.md              # provide answer to human escalation
│   └── squad.build.md               # execute building phase
│
├── agents/
│   ├── core/
│   │   ├── manager.md               # state machine + routing logic
│   │   ├── discover.md              # reconnaissance prompt + tools
│   │   ├── what.md                  # requirements definition prompt
│   │   ├── why.md                   # adversarial critic prompt + Understanding
│   │   ├── assess.md               # strategic PM + kill gate prompt
│   │   ├── how.md                   # architect prompt
│   │   └── plan.md                  # operational PM prompt
│   │
│   ├── specialists/
│   │   ├── scientist.md             # scientific method prompt + experiment
│   │   ├── security.md              # OWASP/STRIDE/compliance prompt
│   │   ├── test-architect.md        # test strategy prompt
│   │   ├── domain-expert.md         # dynamic domain loading prompt
│   │   ├── ux-a11y.md              # WCAG/Nielsen prompt
│   │   ├── performance.md          # capacity/load modeling prompt
│   │   └── innovate.md             # TRIZ/Design Thinking prompt
│   │
│   ├── build/
│   │   ├── implementer.md           # TDD developer prompt
│   │   ├── spec-guard.md            # spec traceability verifier prompt
│   │   ├── code-reviewer.md         # code quality reviewer prompt
│   │   ├── test-guardian.md          # test quality validator prompt
│   │   ├── integrator.md            # system integration verifier prompt
│   │   └── progress-tracker.md      # effort tracking + drift detection prompt
│   │
│   └── learning/
│       ├── reflect.md               # post-run analysis prompt
│       ├── evolve.md                # cross-run diffing prompt
│       ├── calibrate.md             # accuracy tracking prompt
│       └── ground.md                # reality check prompt
│
├── templates/
│   ├── context-pack.md              # context pack assembly template
│   ├── state-schema.json            # manager state machine schema
│   ├── evidence-grades.md           # A/B/C/D/E grading reference
│   ├── kill-report.md               # template for ASSESS kill decisions
│   ├── feedback-questionnaire.md    # template for FEEDBACK intake
│   └── escalation-request.md        # template for human escalation
│
├── scripts/
│   └── bash/
│       ├── detect-project.sh        # greenfield vs brownfield detection
│       ├── run-understanding.sh     # invoke Understanding CLI
│       ├── setup-worktree.sh        # create throwaway worktree for SCIENTIST
│       └── migrate-kb-v{N}.sh      # knowledge base schema migrations
│
└── knowledge-base/                  # persists across runs, grows over time (JSON)
    ├── patterns.yaml                # validated patterns (queryable by domain/tags)
    ├── estimates-log.yaml           # predicted vs actual effort
    ├── pitfalls.yaml                # known failure modes
    ├── calibration-profile.yaml     # AI accuracy per domain
    ├── archive/                     # pruned stale/low-confidence entries
    ├── domain-glossaries/           # accumulated domain vocabularies
    │   └── {domain}.yaml
    └── feedback/                    # post-implementation reports
        └── {NNN}-{project-name}.yaml
```

---

## 12. Slash Commands

| Command | Purpose | Trigger |
|---------|---------|---------|
| `/speckit.squad.run <description\|repo-path>` | Full autonomous squad run (Phase A: Understanding) | User initiates |
| `/speckit.squad.build [feature-path] [task-ids]` | Execute building phase (Phase B: Building) | User initiates after Phase A |
| `/speckit.squad.status` | Check current squad state and progress | User checks progress |
| `/speckit.squad.innovate` | Manually trigger INNOVATE specialist | User wants fresh perspective |
| `/speckit.squad.investigate <question>` | Manually trigger SCIENTIST | User has specific unknown |
| `/speckit.squad.ground` | Manually trigger reality check | User wants grounding |
| `/speckit.squad.feedback <spec-id>` | Post-implementation feedback intake | After implementation complete |
| `/speckit.squad.resume <answer>` | Provide answer to human escalation | Squad is in BLOCKED state |

---

## 13. Artifact Delivery

On completion, the squad delivers to `.specify/specs/{feature}/`:

```
├── glossary.md                ← DISCOVER
├── mental-model.md            ← DISCOVER
├── boundaries.md              ← DISCOVER
├── assumptions.md             ← DISCOVER (validated by SCIENTIST)
├── unknowns.md                ← DISCOVER + WHY
├── reference-architectures.md ← DISCOVER (greenfield only)
├── spec.md                    ← WHAT
├── feasibility.md             ← ASSESS
├── prioritization.md          ← ASSESS (RICE + Kano)
├── estimates.md               ← ASSESS (calibrated)
├── mvp-scope.md               ← ASSESS
├── plan.md                    ← HOW
├── research.md                ← HOW + SCIENTIST
├── data-model.md              ← HOW
├── contracts/                 ← HOW
├── constitution.md            ← HOW
├── tasks.md                   ← PLAN (with effort estimates)
├── critical-path.md           ← PLAN
├── risk-matrix.md             ← PLAN
├── dependencies.md            ← PLAN
├── test-strategy.md           ← TEST ARCHITECT
├── issues.md                  ← WHY (resolved)
├── quality-gates.md           ← WHY + Understanding
├── assumption-review.md       ← WHY (assumption-challenge mode, if applicable)
├── reality-check.md           ← GROUND
├── cost-analysis.md           ← GROUND
├── benchmark-data.md          ← GROUND
├── investigation/             ← SCIENTIST
│   └── {topic}.md
├── evidence-grades.md         ← SCIENTIST
├── experiment-results.md      ← SCIENTIST
├── recommendations.md         ← SCIENTIST
├── knowledge-gaps.md          ← SCIENTIST
├── threat-model.md            ← SECURITY (if summoned)
├── performance-requirements.md ← PERFORMANCE (if summoned)
├── alternatives.md            ← INNOVATE (on re-runs)
├── implementability-report.md  ← ASSESS₂ (per-task: READY / NEEDS_CLARIFICATION / BLOCKED)
├── reasoning-journal.json     ← ALL AGENTS (shared structured reasoning log)
├── calibration-profile.yaml    ← CALIBRATE
└── evolution-report.md        ← EVOLVE (on re-runs)
```

---

## 14. Iterative Improvement Cycle

```
RUN 1 → REFLECT → EVOLVE → knowledge base created
                                │
RUN 2 → uses prior learnings → EVOLVE diffs → improvement measured
                                │
RUN 3 → EVOLVE detects stagnation → INNOVATE proposes alternative
        → SCIENTIST validates → breakthrough architecture
                                │
RUN 4 → optimizes new approach → quality trajectory: ↑↑↑
                                │
IMPLEMENTATION → ... weeks later ...
                                │
FEEDBACK → actual outcomes → CALIBRATE updated
         → real estimates → GROUND has reference data
         → patterns validated → knowledge base strengthened
                                │
RUN 5 → calibrated squad → better estimates, grounded decisions,
        known weaknesses compensated → genuinely better output
```

---

## 15. Key Science References

| Domain | Reference | Used By |
|--------|-----------|---------|
| Requirements Engineering | IEEE 830-1998, ISO 29148:2018 | WHAT, WHY |
| Readability | Flesch 1948, Gunning 1952, Kincaid 1975 | WHY (Understanding) |
| Cognitive Load | Sweller 1988 | WHY (Understanding) |
| Semantic Completeness | Lucassen et al. 2017 | WHY (Understanding) |
| Behavioral Modeling | Harel 2003/2005 (Statecharts) | WHY (Understanding) |
| Quality Models | ISO 25010:2023 | HOW |
| Architecture Analysis | ATAM (Kazman et al.) | HOW |
| Estimation | COCOMO II (Boehm 2000), Function Point Analysis | ASSESS |
| Prioritization | Kano 1984, RICE framework | ASSESS |
| Uncertainty | Cone of Uncertainty (Boehm) | ASSESS |
| Critical Path | CPM, Theory of Constraints (Goldratt 1984) | PLAN |
| Risk Management | PMBOK Guide (PMI) | PLAN |
| Decision Theory | Satisficing (Simon 1956), EVOI | MANAGER |
| Argumentation | Toulmin Model (1958) | MANAGER |
| Domain-Driven Design | Eric Evans 2003 | DISCOVER |
| Tacit Knowledge | Nonaka & Takeuchi 1995 | DISCOVER |
| Innovation | TRIZ (Altshuller), Design Thinking (IDEO) | INNOVATE |
| Antifragility | Taleb 2012 | INNOVATE |
| Calibration | Brier Score, Bayesian updating | CALIBRATE |
| Forecasting | Reference Class Forecasting (Kahneman/Flyvbjerg) | GROUND |
| Evidence-Based SE | Kitchenham et al. | GROUND |
| Continuous Improvement | Kaizen, SPC | EVOLVE |
| Scientific Method | Popper (falsifiability), hypothesis testing | SCIENTIST |
| Threat Modeling | STRIDE (Microsoft), OWASP Top 10 | SECURITY |
| Accessibility | WCAG 2.1/2.2, Nielsen's 10 heuristics | UX/A11Y |
| Test Strategy | Test pyramid, boundary value analysis | TEST ARCHITECT |
| Performance Engineering | Little's Law, Amdahl's Law, capacity planning | PERFORMANCE |

---

## 16. Non-Functional Requirements (System Performance)

### Runtime Budget

| Phase | Expected Duration | Token Budget |
|-------|------------------|-------------|
| INIT + DISCOVER | 1-3 min | ~50K tokens |
| WHY₁ + WHAT + WHY₂ | 2-5 min | ~100K tokens |
| ASSESS (kill gate) | 1-2 min | ~30K tokens |
| SPECIALISTS (parallel where possible, max 3 active) | 2-5 min | ~80K tokens per specialist (capped at 40% of total budget — MANAGER prioritizes by domain signal strength if more would exceed cap) |
| HOW + TEST ARCHITECT | 3-5 min | ~120K tokens |
| PLAN | 2-3 min | ~80K tokens |
| CONSENSUS (parallel) | 3-5 min | ~150K tokens |
| FINALIZE (GROUND + learning layer) | 2-3 min | ~60K tokens |
| **Total (typical run)** | **15-30 min** | **~700K-1M tokens** |

### Constraints

- **Max wall-clock time per run:** 45 minutes. MANAGER forces convergence at 40 min.
- **Max token budget per run:** 1.5M tokens (configurable). MANAGER tracks cumulative usage.
- **Subagent timeout:** 5 minutes per individual agent invocation. MANAGER retries once, then skips with warning.
- **Parallelism:** CONSENSUS phase runs WHY₃ + ASSESS₂ + PLAN₂ + specialists concurrently. All other phases are sequential (each depends on prior output). SCIENTIST experiments run in isolated git worktrees.
- **Degraded mode:** If any external tool (Understanding, Reverse-Eng, spec-kit) is unavailable, squad continues in degraded mode with heuristic fallbacks. All degraded artifacts flagged as UNVALIDATED.

### Token Budget Allocation (MANAGER enforces)

| Priority | Allocation | Rationale |
|----------|-----------|-----------|
| DISCOVER + WHAT | 25% | Understanding the problem is the 80% |
| WHY (all passes) | 20% | Quality validation is non-negotiable |
| HOW + SPECIALISTS | 25% | Architecture decisions need depth |
| PLAN + ASSESS | 15% | Estimation and task breakdown |
| CONSENSUS + FINALIZE | 10% | Validation and grounding |
| Reserve | 5% | For re-routes and error recovery |

---

## 17. Knowledge Base Management

### Format: YAML

The knowledge base uses **YAML** for all data files. Consistent with the spec-kit ecosystem (extension.yml, preset.yml), human-readable, supports comments (critical for explaining *why* an entry exists), and clean git diffs. LLM agents parse YAML as easily as any other format.

**Why YAML over alternatives:**
- **vs Markdown:** Not queryable, lossy, no structure
- **vs JSON:** No comments, verbose, noisy git diffs on arrays
- **vs JSONL:** Not human-readable, no comments, bad for config-style data
- **vs SQLite:** Binary, not git-diffable, not human-inspectable

**Schemas:**

```yaml
# knowledge-base/estimates-log.yaml
schema_version: 1
last_updated: "2026-03-16"
updated_by: squad-run-003

entries:
  # Photo album project — first squad run, uncalibrated
  - id: EST-001
    project: 001-photo-album
    date: "2026-03-16"
    domain: backend
    tech_stack: [typescript, nestjs, postgresql]
    estimated_effort_days: 15
    actual_effort_days: 23
    accuracy_ratio: 0.65
    notes: Underestimated database migration complexity
    tags: [backend, postgresql, migration]
```

```yaml
# knowledge-base/patterns.yaml
schema_version: 1

entries:
  # Validated by SCIENTIST in project 002-payment-system
  # Confirmed by FEEDBACK: reduced audit incidents by 60%
  - id: PAT-001
    name: Event sourcing for audit trails
    domain: fintech
    evidence_grade: B
    source: SCIENTIST investigation RJ-042
    validated_by_feedback: true
    feedback_project: 002-payment-system
    confidence: 0.88
    description: Event sourcing pattern validated for audit trail requirements in regulated domains
    tags: [event-sourcing, audit, compliance, fintech]
    status: active
```

```yaml
# knowledge-base/calibration-profile.yaml
schema_version: 1

domains:
  rest-api-design:
    accuracy: 0.92
    sample_size: 12
    trend: stable

  distributed-systems:
    accuracy: 0.58
    sample_size: 5
    trend: improving

  frontend-state-mgmt:
    accuracy: 0.63
    sample_size: 8
    trend: stable

  effort-estimation:
    accuracy: 0.41
    sample_size: 15
    trend: improving
    correction_factor: 1.4  # multiply AI estimates by this
```

**Querying:** Agents can filter by `tags`, `domain`, `tech_stack`, `evidence_grade`, `confidence`, `status`. MANAGER compiles relevant subsets into context packs. For example, ASSESS receives only entries matching the current project's domain and tech stack, not the entire log.

### Versioning

Each YAML file has a `schema_version` field. When the format changes:
1. `schema_version` increments
2. MANAGER runs a migration function on first read (old → new format)
3. Migration functions are stored in `scripts/bash/migrate-kb-v{N}.sh`

### Multi-Project Isolation

The knowledge base lives at the extension level (`.specify/extensions/squad/knowledge-base/`), which means it is **per-repository** by default. For cross-project learning:

- **Same repo, different features:** Knowledge accumulates naturally (shared knowledge-base directory).
- **Different repos:** Each repo has its own knowledge base. Cross-repo learning requires manual copying or a shared preset that includes a knowledge base seed.
- **Domain glossaries** are namespaced: `domain-glossaries/{domain}.yaml` to prevent fintech terms contaminating a game engine project.

### Pruning Strategy

- **EVOLVE** flags entries older than 6 months with no matching feedback as `status: stale`.
- **CALIBRATE** flags entries with accuracy < 0.4 as `status: low_confidence`.
- Entries flagged `stale` + `low_confidence` for 2 consecutive runs are moved to `knowledge-base/archive/`.
- The `archive/` directory is never auto-deleted — humans can review and restore.
- Maximum active entries per file: 200. Oldest entries archived when limit exceeded.

---

## Standards Alignment

The Cognitive Squad aligns with established software engineering standards:

| Standard | Version | Coverage in Squad |
|----------|---------|------------------|
| ISO/IEC/IEEE 12207 | 2017 (DIS 2027 in progress) | Full lifecycle: requirements, design, implementation, testing, configuration management |
| ISO/IEC 25010 | 2023 | 31 quality metrics via Understanding covering structure, testability, readability, cognitive, semantic, behavioral |
| SWEBOK | v4.0 (Oct 2024) | 14 of 18 Knowledge Areas: Requirements (WHAT), Design (HOW), Architecture (HOW), Testing (TEST ARCHITECT + TEST GUARDIAN), Quality (WHY), Management (ASSESS + PLAN + PROGRESS TRACKER) |
| CMMI | v3.0 (2023) | REQM (WHAT), VER (SPEC GUARD), VAL (WHY), PM (PLAN), MA (PROGRESS TRACKER), CM (CHANGE CONTROLLER), OT (REFLECT knowledge transfer) |
| V-Model | — | Bidirectional traceability matrix, verification at each level, validation against requirements |
| ATAM / ATRAF | 2025 | Architecture decisions documented as ADRs with rationale, alternatives, quality attribute analysis |
| IEEE 830 / ISO 29148 | 2018 | Understanding CLI enforces quality gates derived from these standards |
| Reference Class Forecasting | Kahneman/Flyvbjerg | GROUND applies outside view correction to all effort estimates |
| ICSA Conference Series | 2025-2026 | Architecture sustainability, AI-driven development, architecture erosion detection |
