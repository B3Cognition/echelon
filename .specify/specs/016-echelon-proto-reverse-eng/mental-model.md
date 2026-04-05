# Mental Model — Echelon Proto Cognitive Architecture

## System Overview

Echelon is a **multi-agent cognitive pipeline** that orchestrates 42 specialized agents across 7 tiers to analyze codebases, validate requirements, and guide implementation. The system operates in discrete phases (DISCOVER → WHY → WHAT → ASSESS → HOW → PLAN → BUILD → LEARN) with inter-agent state synchronization via a shared `state.json` spine and a neuromodulation system (6 hormones) that adjusts agent personality per task.

The architecture is designed to mimic cognitive specialization found in human decision-making: scouts map territory, devils advocate challenges assumptions, architects design solutions, specialists validate domains, and a learning loop extracts patterns for future runs.

---

## Core Entities

### 1. Agent

**Description:** A specialized LLM-backed reasoner that performs a discrete responsibility within a phase. All agents are Claude Opus (in BANZAI mode) or stratified by tier (Opus for critical, Sonnet for learning).

**Key attributes:**
- Codename (e.g., SCOUT, SAGE, CARTOGRAPHER)
- Tier assignment (CONTROL, EXPLORATION, FEASIBILITY, SOLUTION, BUILD, SPECIALISTS, LEARNING)
- Phase(s) in which active (e.g., SCOUT is only in DISCOVER phase)
- Archetype (e.g., exploration, validation, build) — determines hormone baselines
- NEVER rules — hard constraints that agent enforces
- Confidence floor — agent must report confidence with every output
- Output artifact schema (what this agent produces)

**Relationships:**
- Depends on (input from prior agent): Agent A's output becomes Agent B's input
- Blocks (consequence of failure): If Agent A fails, Agent B cannot run
- Specializes in (domain): GUARDIAN specializes in security, BENCHMARK in performance
- Consults (advisory only): ORACLE provides information but doesn't block decisions

**Lifecycle:**
1. COMMANDER dispatches with context pack (glossary, assumptions, prior outputs)
2. Agent processes; applies hormone modulation to reasoning
3. Agent produces output artifacts (Markdown files, JSON reasoning journal entries)
4. COMMANDER evaluates output against quality gates
5. On PASS: Agent retires, next agent in tier dispatches
6. On FAIL: Agent re-routes to SAGE for amendment, or escalates to human

### 2. Phase

**Description:** A macro execution block containing 1-6 agent dispatches. Phases are strictly sequenced; cannot skip or run out of order. Each phase has defined entry conditions, exit conditions, and quality gates.

**Key attributes:**
- Name: DISCOVER, WHY, WHAT, ASSESS, HOW, PLAN, BUILD, LEARN
- Entry condition: What must be true to start this phase (e.g., ASSESS requires spec.md pass WHY)
- Exit condition: What must be true to complete this phase (e.g., WHAT requires spec.md pass quality gates)
- Tiers active: Which tiers of agents run in this phase
- Typical dispatch order (for BANZAI parallelism): max 5 agents in parallel, respecting dependencies

**Relationships:**
- Precedes: DISCOVER precedes WHY; WHY precedes WHAT; etc.
- Blocked by: ASSESS cannot start until WHY completes all agents
- Outputs: Artifacts produced collectively by all agents in phase
- Convergence point: End of each phase is a synchronization barrier

**Lifecycle:**
1. COMMANDER verifies entry conditions met
2. COMMANDER dispatches agents in tier order (or parallel in BANZAI)
3. Each agent produces output (writes to spec directory)
4. COMMANDER aggregates output; runs quality gates
5. If all pass: Phase complete, move to next phase
6. If any fail: Agent re-dispatch, escalation, or human intervention
7. Learning phase extracts patterns and updates calibration data

### 3. Tier

**Description:** A horizontal grouping of agents by responsibility domain. Each tier has one logical "owner" per phase who makes the decision that tier is responsible for.

**Tiers:**
1. **CONTROL** — COMMANDER routes, SCOREKEEPER tracks, TRACKER verifies intent, STRATEGIST provides overview, CHECKPOINT gates internalization, PROSPECTOR surveys
2. **EXPLORATION** — SCOUT discovers, SAGE challenges, SYNTHESIZER fuses, CARTOGRAPHER specifies, GOLDDIGGER deep-dives, MODELER maps concepts
3. **FEASIBILITY** — GATEKEEPER assesses/gates, VALIDATOR internalizes/gates
4. **SOLUTION** — ARCHITECT designs, ORCHESTRATOR plans, SENTINEL tests
5. **BUILD** — IMPLEMENTER codes, CODE-REVIEWER gates, DEBUGGER fixes, TEST-GUARDIAN gates, SPEC-GUARD gates, INTEGRATOR combines, CHANGE-CONTROLLER manages, VERIFICATION backpropagates, VISUAL-VALIDATOR checks UI, PROGRESS-TRACKER monitors, ENGINEERING-MANAGER leads
6. **SPECIALISTS** — GUARDIAN (security), BENCHMARK (perf), INVESTIGATOR (research), MAVERICK (innovation), ADVOCATE (UX/a11y), ORACLE (domain)
7. **LEARNING** — MIRROR reflects, AUDITOR calibrates, ADAPTIVE evolves, REALIST grounds, VETERAN historicizes, INTERNALIZER measures, MONITOR checks, GLOBAL-MEMORY vaults

**Relationship:**
- Tiers are independent horizontally: GUARDIAN doesn't constrain BENCHMARK's output
- Tiers are dependent vertically: CONTROL must route for EXPLORATION to run

### 4. State

**Description:** The shared mutable state dictionary (`state.json`) that persists across all agent dispatches. COMMANDER reads/writes state before and after every dispatch.

**Key attributes:**
- `run_id`: Unique identifier for this end-to-end squad run
- `phase`: Current phase (DISCOVER, WHY, WHAT, ...)
- `dispatch_history`: List of all (agent_codename, timestamp, result, token_count, confidence) tuples
- `golddigger_artifacts`: Reverse-engineering results cached from GOLDDIGGER surveys
- `golddigger_requests`: Queue of GOLDDIGGER Mode 2 deep-dive requests from SCOUT/SYNTHESIZER/CARTOGRAPHER
- `errors`: Accumulated non-fatal errors (handled but logged for human awareness)
- `escalations`: Critical issues requiring human sign-off before proceeding
- `calibration_data`: Per-agent historical accuracy, correction factors, baselines
- `constitution_violations`: Flagged attempts to violate immutable governance rules
- `token_spent`: Running total of tokens used in this run

**Relationships:**
- Read by: All agents (via context pack)
- Written by: COMMANDER (post-dispatch state updates)
- Persisted in: `.specify/squad/state.json`

### 5. Quality Gate

**Description:** A threshold check on agent output that passes or fails before the next agent runs. Seven independent dimensions, each with a minimum acceptable score.

**Attributes:**
- Dimension: structure, testability, semantic, cognitive, readability, behavioral, depth
- Threshold: Minimum score required (e.g., 0.75 for structure)
- Measurement method: SAGE runs Understanding metrics on spec.md
- Evidence: Word count, sentence depth, term consistency, actor-action-object pattern presence, etc.

**Relationships:**
- Enforced by: SAGE agent (post-CARTOGRAPHER); VALIDATOR agent (post-architecture decisions)
- Consequence of fail: Route back to CARTOGRAPHER for amendment
- Aggregated by: CHECKPOINT (internalization gate at phase end)

**Lifecycle:**
1. Agent produces output
2. COMMANDER dispatches SAGE with output
3. SAGE runs Understanding metrics (external tool or python script)
4. SAGE returns scores for each dimension
5. COMMANDER compares against config thresholds
6. PASS: Proceed to next agent
7. FAIL: Invoke amendment mode (agent re-runs with failure feedback)

### 6. Hormone (Neuromodulation)

**Description:** A motivation/urgency signal that modulates how agents reason. Six hormones control attention, risk tolerance, thoroughness, and interpersonal deference.

**Key attributes:**
- Name: adrenaline, dopamine, cortisol, serotonin, oxytocin, norepinephrine
- Baseline per archetype: e.g., exploration archetype has baseline [0.3, 0.7, 0.3, 0.6, 0.5, 0.4]
- Range: [0.0, 1.0]
- Decay rate: How quickly hormone "wears off" across dispatch cycles
- Phase-gated: Only activate when phase-specific triggers fire (e.g., adrenaline spikes on deadline pressure)
- Propagation: 30% boost passed to downstream agents via context injection

**Relationships:**
- Controls: Agent communication style (verbose vs terse), risk tolerance (creative vs conservative), thoroughness (detail-oriented vs big-picture)
- Set by: endocrine.sh script at dispatch time based on archetype + current values + phase signals
- Decayed by: Each subsequent dispatch (decay rate in squad-config.yml)
- Broadcast to: All agents in next dispatch via context pack injection

**Lifecycle:**
1. Agent A runs with hormone levels [a1, d1, c1, s1, o1, n1]
2. Agent A's output influences next dispatch's trigger signals
3. endocrine.sh recalculates based on triggers + decay + baseline
4. Resulting levels [a2, d2, ...] injected into Agent B's context
5. Agent B's reasoning is influenced by hormone levels

### 7. Constitution

**Description:** A human-authored governance document that defines immutable principles, team roles, authority boundaries, and escalation rules. Agents cannot violate constitution without explicit human override.

**Key attributes:**
- Principles: "Security decisions require human sign-off," "No architectural changes without analysis," etc.
- Authority levels: Who can make what decisions (e.g., GATEKEEPER can KILL, but ARCHITECT cannot)
- Escalation rules: When to flag for human, when to escalate to legal/security
- Three-tier enforcement: FLAG (inform human), CONSULT (ask human), BLOCK (refuse to act)

**Relationships:**
- Enforced by: COMMANDER pre-dispatch constitutional gate (checks if dispatch violates rules)
- Override authority: Only human can approve constitution violation
- Scope: Applies to all agents; no agent can bypass it

---

## Relationships & Cardinalities

| Entity A | Relationship | Entity B | Cardinality | Notes |
|----------|------------|----------|-----------|-------|
| Agent | belongs_to | Tier | N:1 | Each agent assigned to exactly one tier |
| Agent | active_in | Phase | N:M | SCOUT active in DISCOVER only; IMPLEMENTER active in BUILD only; SCOREKEEPER active in all |
| Agent | consumes_output_from | Agent | N:M | CARTOGRAPHER consumes glossary/mental-model/boundaries from SCOUT; spec.md is input to GATEKEEPER |
| Phase | precedes | Phase | 1:1 | DISCOVER precedes WHY; WHY precedes WHAT; etc. (linear sequence, no branching) |
| Phase | produces | Artifact | 1:M | DISCOVER produces glossary, mental-model, boundaries, assumptions, unknowns (5-7 artifacts) |
| Tier | owns_agents_in | Phase | M:M | CONTROL owns agents that run in all phases; SPECIALISTS owns agents that run in some phases |
| State | tracks | Dispatch | 1:N | state.json.dispatch_history has one entry per agent invocation |
| Agent | produces | Artifact | 1:M | Each agent produces one primary artifact (spec.md, plan.md, etc.) + reasoning journal entries |
| QualityGate | evaluates | Artifact | N:1 | Multiple gates (7 dimensions) evaluate each spec artifact |
| Constitution | constrains | Agent | N:M | Constitution principles apply to all agents; some principles apply to specific tiers (e.g., security only for GUARDIAN) |
| Hormone | modulates | Agent | M:M | Each agent influenced by all 6 hormones (per baseline + current state) |

---

## Concept Map: Data Flows

```
Codebase Input
    ↓
DISCOVER Phase (SCOUT, SYNTHESIZER, GOLDDIGGER, MODELER)
    ↓ produces ↓
    [glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, contradictions.md]
    ↓
WHY Phase (SAGE challenges, SAGE produces amended-assumptions.md)
    ↓
WHAT Phase (CARTOGRAPHER writes spec.md)
    ↓
Quality Gate (Understanding metrics: 7 dimensions)
    ├─ PASS → proceed
    └─ FAIL → amend loop (SAGE provides feedback, CARTOGRAPHER re-writes)
    ↓
ASSESS Phase (GATEKEEPER evaluates feasibility, produces decision)
    ├─ KILL → end
    ├─ DEFER → loop back to CARTOGRAPHER for scope adjustment
    └─ PASS → proceed
    ↓
HOW Phase (ARCHITECT designs, SENTINEL tests, produces plan.md, data-model.md, contracts/)
    ↓
PLAN Phase (ORCHESTRATOR produces tasks.md with dependencies)
    ↓
BUILD Phase (IMPLEMENTER codes, CODE-REVIEWER/TEST-GUARDIAN/SPEC-GUARD gate quality)
    ├─ Issues detected
    ├─ → DEBUGGER fixes
    └─ → VERIFICATION backpropagates to spec/architecture
    ↓
LEARN Phase (MIRROR, AUDITOR, ADAPTIVE extract patterns, update calibration, produce evolution-report.md)
    ↓
Next Run Benefit (calibration-profile.yaml updated; patterns saved in marketplace; Veteran primes next GATEKEEPER with learned scope heuristics)
```

---

## Behavioral Patterns

### 1. Dispatch Sequencing (Within a Phase)

**Pattern:** Dependency-respecting agent ordering

```
DISCOVER Phase Sequence:
1. SCOUT alone (discovers domain, produces raw artifacts)
2. SYNTHESIZER (waits for SCOUT output; merges fragments into unified artifacts)
3. GOLDDIGGER (optional, if SCOUT/SYNTHESIZER request deep dive)
4. MODELER (optional, enriches mental-model if needed)
Result: Unified knowledge base ready for WHY
```

### 2. Amendment Loop (Failing Quality Gates)

**Pattern:** Iterative refinement until gate passes

```
CARTOGRAPHER writes spec.md
    → COMMANDER dispatches SAGE (runs Understanding metrics)
    → SAGE returns scores: [structure: 0.65, testability: 0.55, ...]
    → COMMANDER checks config thresholds (e.g., structure ≥ 0.75)
    → FAIL: SAGE produces issue.md with per-requirement failures
    → COMMANDER re-dispatches CARTOGRAPHER with issue.md
    → CARTOGRAPHER amends only failing requirements (NEVER rule: don't modify passing ones)
    → Re-test
    → PASS: Move to ASSESS
```

### 3. Gate-Conditioned Claims (CA Overlays)

**Pattern:** Blocking mechanism for unproven features

```
Five CA overlays (Goal Stack, ACT-R Buffer, LIDA Broadcast, GWT Workspace, Episodic Memory)
    cannot be implemented until U-CA-004 gate experiment runs
    → proof-status-table.md explicitly lists all as "GATE-CONDITIONED on U-CA-004"
    → COMMANDER checks proof status before permitting ARCHITECT to use overlay
    → If not POSITIVE (or not run): ARCHITECT must use baseline design instead
    → Result: Echelon remains conservative until gate validates
```

### 4. EVOI Routing (COMMANDER Decision)

**Pattern:** Probabilistic dispatch based on information value

```
Unknown discovered: "What's the auth architecture?"
    → COMMANDER calculates EVOI: impact × (resolution_cost)^-1
    → High EVOI: Dispatch INVESTIGATOR to research
    → Low EVOI: Flag as acceptable assumption, proceed
    → Result: Critical unknowns resolved; minor ones deferred
```

### 5. Hormone Feedback Loop

**Pattern:** Hormones modulate based on phase progress

```
BUILD phase early: adrenaline [0.7], dopamine [0.5] (execution mode)
    ↓ 10 tasks completed, on schedule
    → adrenaline decays 0.7 × 0.6 = 0.42 (urgency drops)
    → dopamine stays high (success boosts reward)
    ↓ IMPLEMENTER receives context with updated hormones
    ↓ Result: Slightly less frantic, maintains motivation
```

### 6. Belief Annotation Freshness Check

**Pattern:** Stale beliefs trigger caution or re-validation

```
@belief(claim: "Python 3.8 is minimum version", expires: "2025-06-30", confidence: 0.8) in config.yml
    → belief-parser.py processes → config-belief-graph.json generated
    → Status classification: approaching_expiry (today: 2026-04-02, expires: 2026-04-15)
    → Agent reading belief sees: "BELIEF-XXX approaching_expiry"
    → Agent raises alertness: "This assumption is stale; needs re-validation before proceeding"
    → INVESTIGATOR may be dispatched to verify Python 3.8 still minimum
```

### 7. Contradiction Detection (SYNTHESIZER → NS-003)

**Pattern:** Cross-artifact validation finds design splits

```
SCOUT reports: "Service A uses REST API"
    GOLDDIGGER reports: "Service A uses gRPC internally"
    SYNTHESIZER detects contradiction
    → contradiction-scanner.py flags as "status_mismatch"
    → SYNTHESIZER produces contradictions-and-gaps.md
    → SAGE adversarially challenges: "Which is authoritative?"
    → Result: Resolved before spec written, preventing cascading errors
```

---

## Execution Models

### BANZAI Mode (Full Autonomous)

```
Config: autonomy.mode = banzai
    → max_parallel_agents: 5
    → token_budget_k: 999999 (unlimited)
    → all 6 hormones enabled
    → auto_kill_threshold: 0.2 (only kill if < 20% viable)

Execution:
    ↓ DISCOVER phase
    ├─ (parallel) SCOUT, SYNTHESIZER, GOLDDIGGER, MODELER run simultaneously
    ├─ (wait for all) Merge outputs
    ↓ WHY phase
    ├─ SAGE challenges in parallel (one per assumption sub-batch)
    ↓ (continuing with parallelism where possible)
    ↓ BUILD phase
    ├─ (parallel) IMPLEMENTER writes code in parallel components
    ├─ (parallel) CODE-REVIEWER, TEST-GUARDIAN review in parallel
    ├─ (parallel) SPEC-GUARD, DEBUGGER monitor in parallel
    ↓ Full run completes faster, using up to 5x more tokens
```

### Standard Mode (Sequential, Token-Constrained)

```
Config: autonomy.mode = standard (not enabled in squad-config.yml)
    → max_parallel_agents: 1
    → token_budget_k: 100000 (example constraint)
    → Tier-level allocation percentages enforce budget sharing

Execution:
    ↓ DISCOVER: SCOUT runs
    ↓ SCOUT → SYNTHESIZER
    ↓ SYNTHESIZER → GOLDDIGGER (if EVOI high enough)
    ↓ Sequential queue, respecting token budget allocations
```

---

## Authority & Escalation

### Three-Tier Escalation

```
FLAG (Informational):
    GUARDIAN detects: "TLS certificate not pinned"
    → Logs FLAG in reasoning journal
    → Allows implementation to proceed with caution flag

CONSULT (Advisory):
    ARCHITECT proposes: "Store passwords in plaintext"
    → COMMANDER checks constitution for security principle
    → Routes to GUARDIAN for advisory review
    → GUARDIAN says "violates principle X"; recommends hash + salt
    → ARCHITECT can override but must document rationale

BLOCK (Enforcement):
    ARCHITECT proposes: "No tests written"
    → Constitution rule: "All code requires tests ≥ 80% coverage"
    → COMMANDER blocks dispatch
    → Escalation to human: "Cannot proceed without tests"
```

---

## Critical Dependency Chains

1. **Discovery Chain**: SCOUT → SYNTHESIZER → SAGE → CARTOGRAPHER
   - Break: SCOUT fails → no discovery, cascade failure
   - Strength: SYNTHESIZER catches cross-source contradictions before spec written

2. **Quality Chain**: CARTOGRAPHER → SAGE (metrics) → GATEKEEPER (feasibility)
   - Break: SAGE quality gate fails → CARTOGRAPHER loops, may hit iteration limit
   - Strength: Low-quality specs rejected before expensive architecture begins

3. **Implementation Chain**: ARCHITECT → ORCHESTRATOR → IMPLEMENTER → CODE-REVIEWER → TEST-GUARDIAN → VERIFICATION
   - Break: ARCHITECT produces infeasible design → cascades to planning/build failure
   - Strength: Multiple gates (CODE-REVIEWER, TEST-GUARDIAN) catch defects before integration

4. **Learning Chain**: MIRROR → AUDITOR → ADAPTIVE → next run's GATEKEEPER
   - Break: AUDITOR incorrectly calibrates → GATEKEEPER under/overestimates in next run
   - Strength: Each run improves future estimate accuracy

---

## Unknown Unknowns / Suspected Complexity

1. **Horn-Clause Constraint Solving** — AC-3 constraint propagation (theoretical) not proven for LLM semantic constraints (practical). May not transfer.

2. **Episodic Memory Retrieval** — Undefined content-addressing scheme. No indexing strategy chosen. Prototype needed to validate retrieval precision.

3. **Hormone Propagation Edge Cases** — 30% downstream boost mathematically simple, but psychological plausibility untested. May need refinement.

4. **EVOI Calibration** — COMMANDER's EVOI calculation uses heuristic weights. Optimal weights unknown. May produce suboptimal dispatch decisions early in run.

5. **State Explosion in Large Codebases** — No measured limit on codebase size where discovery phase scales linearly. At 100k LOC, discovery may become intractable.
