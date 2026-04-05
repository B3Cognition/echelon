# System Boundaries — Echelon Proto

## Internal Boundaries (Subsystems)

### CONTROL Tier (Orchestration & State Management)
- **Responsibility:** Route all agents; maintain state.json; track metrics; enforce quality gates; verify user intent alignment
- **Interfaces:** Reads all agent outputs; writes state.json; injects context packs to agents
- **Data ownership:** state.json (run state), reasoning-journal.json (decision log), dispatch_history (all invocations)
- **Agents:** COMMANDER, SCOREKEEPER, TRACKER, STRATEGIST, CHECKPOINT, PROSPECTOR

### EXPLORATION Tier (Discovery & Requirements)
- **Responsibility:** Map domain (SCOUT), challenge assumptions (SAGE), fuse fragments (SYNTHESIZER), write specs (CARTOGRAPHER), deep analysis (GOLDDIGGER), refine models (MODELER)
- **Interfaces:** Consumes codebase, documentation, user descriptions; produces glossary, mental-model, spec, assumptions, unknowns
- **Data ownership:** All discovery and requirement artifacts (markdown files in spec directory)
- **Agents:** SCOUT, SAGE, SYNTHESIZER, CARTOGRAPHER, GOLDDIGGER, MODELER

### FEASIBILITY Tier (Assessment & Gating)
- **Responsibility:** Evaluate feasibility (GATEKEEPER); gate internalization (VALIDATOR); make PASS/DEFER/KILL decisions
- **Interfaces:** Consumes spec.md, assumptions.md; produces feasibility.md, estimates.md, decision (PASS/DEFER/KILL)
- **Data ownership:** feasibility.md, estimates.md, mvp-scope.md
- **Agents:** GATEKEEPER, VALIDATOR

### SOLUTION Tier (Architecture & Planning)
- **Responsibility:** Design architecture (ARCHITECT); plan tasks (ORCHESTRATOR); architect tests (SENTINEL)
- **Interfaces:** Consumes spec.md; produces plan.md, data-model.md, contracts/, tasks.md
- **Data ownership:** Architecture and planning artifacts
- **Agents:** ARCHITECT, ORCHESTRATOR, SENTINEL

### BUILD Tier (Implementation & Quality)
- **Responsibility:** Code implementation, review, testing, debugging, integration, verification, progress tracking
- **Interfaces:** Consumes plan.md, tasks.md; produces source code, test code, verification reports
- **Data ownership:** Codebase, test suites, build artifacts
- **Agents:** IMPLEMENTER, CODE-REVIEWER, TEST-GUARDIAN, SPEC-GUARD, INTEGRATOR, CHANGE-CONTROLLER, VERIFICATION, VISUAL-VALIDATOR, DEBUGGER, PROGRESS-TRACKER, ENGINEERING-MANAGER

### SPECIALISTS Tier (Domain Expertise)
- **Responsibility:** Security review (GUARDIAN), performance validation (BENCHMARK), research (INVESTIGATOR), innovation (MAVERICK), UX/accessibility (ADVOCATE), domain expertise (ORACLE)
- **Interfaces:** Consulted on demand by COMMANDER; consume spec/plan/code; produce advisory reports and recommendations
- **Data ownership:** Specialty reports (security-review.md, performance-report.md, etc.)
- **Agents:** GUARDIAN, BENCHMARK, INVESTIGATOR, MAVERICK, ADVOCATE, ORACLE

### LEARNING Tier (Improvement & Evolution)
- **Responsibility:** Post-run analysis (MIRROR), calibration (AUDITOR), evolution (ADAPTIVE), grounding (REALIST), historical learning (VETERAN), understanding measurement (INTERNALIZER), self-monitoring (MONITOR), knowledge vault (GLOBAL-MEMORY)
- **Interfaces:** Reads all run artifacts and reasoning logs; writes calibration-profile.yaml, marketplace-index.yaml, evolution-report.md
- **Data ownership:** Knowledge base, calibration data, run history
- **Agents:** MIRROR, AUDITOR, ADAPTIVE, REALIST, VETERAN, INTERNALIZER, MONITOR, GLOBAL-MEMORY

---

## External Boundaries (Integrations & Dependencies)

### Codebase (External System — INPUT)
- **Type:** File system or Git repository
- **Dependency strength:** Hard (cannot discover without codebase)
- **Data flow:** SCOUT reads source files, documentation, git history. GOLDDIGGER performs reverse-engineering. Direction: INBOUND (read-only).
- **Failure impact:** If codebase is unavailable, DISCOVER phase fails. No discovery → no requirements → no implementation.

### User / Stakeholder (External Actor — INPUT & APPROVAL)
- **Type:** Human decision-maker
- **Dependency strength:** Hard (user intent is foundation; escalations require human approval)
- **Data flow:** User provides intent (text description). TRACKER verifies scope alignment. COMMANDER escalates governance violations for human sign-off. Direction: BIDIRECTIONAL (read intent, escalate decisions).
- **Failure impact:** If user unavailable during escalations (CONSULT, BLOCK decisions), pipeline stalls.

### LLM Service (Claude Opus) (External Service — EXECUTION)
- **Type:** API (Claude API via Anthropic SDK)
- **Dependency strength:** Hard (agents are LLM-backed; no LLM = no agent)
- **Data flow:** COMMANDER sends context pack + prompt to Claude; receives reasoning and output. Direction: BIDIRECTIONAL (send prompts, receive outputs).
- **Failure impact:** API outage → all agents fail. Rate limiting → pipeline slow.

### Knowledge Base (External System — READ/WRITE)
- **Type:** File system (YAML files: calibration-profile.yaml, marketplace-index.yaml, knowledge-base/patterns.yaml, knowledge-base/feedback/)
- **Dependency strength:** Soft (exists but not required for first run; improves quality on subsequent runs)
- **Data flow:** GATEKEEPER reads calibration-profile.yaml. CARTOGRAPHER reads marketplace-index.yaml. AUDITOR writes updated calibration data. Direction: BIDIRECTIONAL (read for tuning, write for learning).
- **Failure impact:** If missing, agents operate without historical calibration/patterns (quality degrades but pipeline proceeds). If write fails, next run loses learning.

### Spec Directory (External System — READ/WRITE)
- **Type:** File system (.specify/specs/NNN-{feature}/)
- **Dependency strength:** Hard (all artifacts written to spec directory; no writes = no output)
- **Data flow:** COMMAND reads prior specs; all agents write outputs. Direction: BIDIRECTIONAL.
- **Failure impact:** If spec directory inaccessible or full disk, pipeline fails mid-phase.

### Configuration Files (External System — INPUT)
- **Type:** File system (YAML: squad-config.yml, config-template.yml, config-belief-graph.json)
- **Dependency strength:** Hard (configuration controls agent behavior, token budgets, quality gates, endocrine baselines)
- **Data flow:** COMMANDER reads config at startup. Agents read config for their specific parameters. Direction: INBOUND (read-only).
- **Failure impact:** Malformed config → startup failure or runtime errors.

### Constitution (External System — INPUT)
- **Type:** File system (constitution.md or constitution.json)
- **Dependency strength:** Hard (governance is non-negotiable; missing constitution = no enforcement)
- **Data flow:** COMMANDER reads constitution at startup, checks before each dispatch. Direction: INBOUND (read-only).
- **Failure impact:** Missing constitution → COMMANDER cannot enforce governance; pipeline operates uncontrolled.

### RADAR Server (External System — OPTIONAL OUTPUT)
- **Type:** Flask HTTP server + SSE streaming
- **Dependency strength:** Soft (monitoring, not execution-critical)
- **Data flow:** COMMANDER writes to agent-states.json. RADAR reads and streams to connected browsers. Direction: OUTBOUND (state updates).
- **Failure impact:** If RADAR crashes, monitoring is unavailable but pipeline continues.

### Git Repository (External System — OPTIONAL INPUT)
- **Type:** Git repository (.git/)
- **Dependency strength:** Soft (optional; enhances discovery if present)
- **Data flow:** SCOUT reads git history (commits, authors, file change frequency). Direction: INBOUND (read-only).
- **Failure impact:** If git unavailable, timeline analysis in SCOUT skipped; other discovery continues.

---

## Trust Boundaries (Security, Authentication, Validation)

### Pre-Dispatch Validation
- **Location:** COMMANDER pre-dispatch constitutional gate
- **Validation:** Agent action validated against constitution principles
- **Authentication:** Not applicable (agents are trusted LLM instances)
- **Authorization:** Constitution defines authority hierarchy (FLAG/CONSULT/BLOCK tiers)

### User Intent Alignment
- **Location:** TRACKER verifies scope against user-intent.md
- **Validation:** Scope drift detected; changes flagged for user approval
- **Authentication:** Not applicable
- **Authorization:** User intent is source of truth for scope decisions

### Spec Quality Validation
- **Location:** SAGE Understanding metrics gate
- **Validation:** Spec.md evaluated on 7 dimensions (structure, testability, semantic, etc.)
- **Authentication:** Not applicable
- **Authorization:** SAGE has authority to reject low-quality specs; CARTOGRAPHER must amend

### Code Quality Validation
- **Location:** CODE-REVIEWER, TEST-GUARDIAN, SPEC-GUARD gates
- **Validation:** Code reviewed for style, test coverage, spec compliance
- **Authentication:** Not applicable
- **Authorization:** Gates can reject code; IMPLEMENTER must fix

### Artifact Integrity
- **Location:** state.json persistence, reasoning-journal.json append-only
- **Validation:** JSON schema validation on load
- **Authentication:** File system permissions (OS-level)
- **Authorization:** Only COMMANDER writes state; only LEARN tier writes knowledge base updates

---

## Data Ownership & Lifecycle

| Artifact | Owner | Created By | Read By | Lifecycle |
|----------|-------|-----------|---------|-----------|
| glossary.md | EXPLORATION | SCOUT/SYNTHESIZER | all agents | DISCOVER → archived after run |
| mental-model.md | EXPLORATION | MODELER | all agents | DISCOVER → archived |
| spec.md | EXPLORATION | CARTOGRAPHER | GATEKEEPER, ARCHITECT, all downstream | WHAT phase → final output |
| assumptions.md | EXPLORATION | SCOUT | SAGE, GATEKEEPER | DISCOVER → updated by SAGE |
| plan.md | SOLUTION | ORCHESTRATOR | BUILD agents | HOW phase → implementation guide |
| tasks.md | SOLUTION | ORCHESTRATOR | IMPLEMENTER, PROGRESS-TRACKER | PLAN phase → task decomposition |
| source code | BUILD | IMPLEMENTER | CODE-REVIEWER, TEST-GUARDIAN, INTEGRATOR | BUILD phase → final deliverable |
| calibration-profile.yaml | LEARNING | AUDITOR | GATEKEEPER | Persists across runs; updated after each run |
| evolution-report.md | LEARNING | ADAPTIVE | VETERAN (next run) | Persists across runs; guides future agent personality |
| config-belief-graph.json | CONTROL | belief-parser.py | all agents | Generated from @belief() annotations; used for freshness checks |

---

## Tiering Model (No Cross-Tier Leakage)

**Rule:** Each tier has a single, clear responsibility. No agent encroaches on another tier's responsibility.

- **CONTROL routes** → all other tiers execute
- **EXPLORATION discovers** → FEASIBILITY/SOLUTION/BUILD consumes discovery
- **FEASIBILITY gates** → SOLUTION/BUILD cannot proceed without PASS
- **SOLUTION designs** → BUILD executes (no re-architecture in BUILD)
- **BUILD implements** → LEARNING reflects
- **SPECIALISTS advise** → no tier depends on specialist output (advisory only)
- **LEARNING evolves** → next run benefits (no immediate feedback loop in current run)

Violation: ARCHITECT writing requirements (WHAT's job) → escalation, possible run failure.

