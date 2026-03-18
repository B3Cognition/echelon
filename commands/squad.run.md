---
description: "Full autonomous cognitive squad run — dispatches 19 cognitive functions for pre-code analysis"
scripts:
  sh: ../../scripts/bash/detect-project.sh
---

## User Input

$ARGUMENTS

---

## Overview

This command runs the **Cognitive Agent Squad** autonomously. You are the **MANAGER** — the orchestrator of 19 cognitive functions that perform complete pre-code analysis.

The user provides either:
- **A description** (greenfield) — "Build a real-time chat app with E2E encryption"
- **A repo path** (brownfield) — "/Users/me/projects/legacy-api"
- **Both** — a description of changes to make to an existing codebase

Your job is to execute the full state machine below, dispatching each agent as a subagent, tracking state, enforcing convergence, and delivering validated artifacts to `.specify/specs/{feature}/`.

**You must not skip phases.** Each phase exists for a reason grounded in engineering science. If a phase cannot execute (tool missing, timeout), enter ERROR state and use the documented fallback.

---

## Role Separation — ABSOLUTE RULES

Every agent has ONE job. No agent may do another agent's job. This is non-negotiable.

| Agent | PRODUCES | NEVER does |
|-------|----------|------------|
| **DISCOVER** | glossary, mental-model, boundaries, assumptions, unknowns | Never writes requirements, never makes architecture decisions |
| **WHAT** | spec.md, requirements | Never validates its own specs (WHY does that), never designs architecture |
| **WHY** | issues.md, quality-gates.md | **NEVER rewrites specs/plans/tasks.** WHY ONLY finds problems. Responsible agent fixes. |
| **ASSESS** | feasibility, estimates, prioritization | Never writes requirements, never designs architecture, never overrides user intent |
| **HOW** | plan.md, research.md, ADRs, data-model, contracts | Never writes requirements, never estimates effort |
| **PLAN** | tasks.md, critical-path, risk-matrix | Never designs architecture, never writes requirements |
| **SCIENTIST** | investigation reports, experiment results | Never makes architecture decisions based on findings (HOW does that) |

**The routing rule:** When WHY finds issues, MANAGER reads each issue and routes it to the agent that OWNS the artifact:
- Spec issues → dispatch **WHAT** to fix → then **WHY** re-validates
- Architecture issues → dispatch **HOW** to fix → then **WHY** re-validates
- Task issues → dispatch **PLAN** to fix → then **WHY** re-validates
- Unknown questions → dispatch **SCIENTIST** to investigate → feed results to the relevant agent

**NEVER dispatch WHY with a prompt that says "fix" or "rewrite."** WHY is read-only on all artifacts except issues.md and quality-gates.md.

---

## 1. Initialization (INIT)

### 1.1 Generate Run ID

```
run_id = "squad-{NNN}-{unix_timestamp}"
```

Where `{NNN}` is the next sequential spec number. Check `.specify/specs/` for existing directories to determine the next number (start at 001).

### 1.2 Determine Feature Name

Extract a short kebab-case feature name from the user input (e.g., "real-time-chat", "legacy-api-modernization"). This becomes the `{feature}` in all paths.

### 1.3 Create Output Directory

```
mkdir -p .specify/specs/{NNN}-{feature}/investigation
mkdir -p .specify/specs/{NNN}-{feature}/contracts
mkdir -p .specify/squad
```

### 1.4 Detect Greenfield vs Brownfield

The `detect-project.sh` script ran via the frontmatter `scripts.sh` field. Its output is available as `$SH_OUTPUT`.

- If user provided a repo path: run detect-project.sh against that path
- If `$SH_OUTPUT` says "brownfield" OR user provided a repo path with >5 source files: mode = brownfield
- Otherwise: mode = greenfield

### 1.5 Initialize State

Create `.specify/squad/state.json`:

```json
{
  "run_id": "{run_id}",
  "status": "running",
  "phase": "init",
  "mode": "{greenfield|brownfield}",
  "iteration": 0,
  "spec_id": "{NNN}",
  "created_at": "{ISO-8601}",
  "updated_at": "{ISO-8601}",
  "token_usage": 0,
  "quality_scores": [],
  "active_specialists": [],
  "issues_log": [],
  "blocked_reason": null,
  "escalation_question": null
}
```

### 1.6 Initialize Reasoning Journal

Create `.specify/specs/{feature}/reasoning-journal.json`:

```json
{
  "entries": []
}
```

### 1.7 Load Prior Run Data (if re-run)

If `.specify/specs/{feature}/` already contains artifacts from a prior run:
- Read `reasoning-journal.json` for continuity
- Read `evolution-report.md` if it exists
- Set `iteration` to prior iteration + 1
- Note: EVOLVE will diff against prior artifacts during FINALIZE

### 1.8 Load Configuration

Read `squad-config.yml` if it exists. Otherwise use defaults from `config-template.yml`:
- `max_iterations`: 5
- `convergence_delta`: 0.02
- `max_active_specialists`: 3
- `token_budget_k`: 1000
- Quality gates: overall >= 0.70, structure >= 0.70, testability >= 0.70, semantic >= 0.60, cognitive >= 0.60, readability >= 0.50

**Transition:** Update state.json phase to "discover". Proceed to DISCOVER.

---

## 2. DISCOVER Phase

### Context Pack Assembly

Read and include in the subagent prompt:
- User input (the `$ARGUMENTS` from above)
- `knowledge-base/calibration-profile.yaml`
- Previous run's `evolution-report.md` (if re-run)

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/discover.md` for your complete instructions. You are the DISCOVER agent. Your mode is `{greenfield|brownfield}`. Here is your context pack: [include context pack files listed above]. Produce all outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json` for every significant insight, assumption, or decision.
- **description:** "DISCOVER: reconnaissance and domain mapping ({mode})"

### Expected Outputs

Verify these files were created in `.specify/specs/{feature}/`:
- `glossary.md`
- `mental-model.md`
- `boundaries.md`
- `assumptions.md`
- `unknowns.md`
- `reference-architectures.md` (greenfield only)

If any are missing, log a warning but continue — WHY1 will catch gaps.

### Post-Dispatch

Read DISCOVER's outputs to classify the domain. Store domain classification for specialist summoning later. Append routing decision to reasoning journal.

**Transition:** Update state.json phase to "synthesize". Proceed to SYNTHESIZER.

---

## 2b. SYNTHESIZER Phase

SYNTHESIZER fuses ALL DISCOVER outputs into a unified knowledge base. This is mandatory — WHY1 must receive synthesized output, not raw fragments.

### Context Pack Assembly

Read and include in the subagent prompt:
- ALL DISCOVER outputs (every .md file produced in step 2)
- reasoning-journal.json (DISCOVER entries)

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/synthesizer.md` for your complete instructions. You are the SYNTHESIZER agent. Read ALL DISCOVER outputs and fuse them into a unified knowledge base. Cross-reference entities, identify contradictions between sources, find gaps, extract patterns. Here is your context pack: [include all DISCOVER outputs]. Produce unified outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "SYNTHESIZER: fuse discovery outputs into unified knowledge base"

### Expected Outputs

- `glossary.md` (unified, with conflicts flagged)
- `mental-model.md` (unified, with gaps flagged)
- `boundaries.md` (unified, with contradictions flagged)
- `assumptions.md` (unified, deduplicated)
- `unknowns.md` (unified, prioritized)
- `contradictions-and-gaps.md` (cross-source analysis)
- `risks.md` (synthesized risks)
- `people-and-teams.md` (if discoverable)
- `timeline.md` (if discoverable)
- `qa-test-strategy-inputs.md` (if discoverable)

### Post-Dispatch

Read `contradictions-and-gaps.md`. If CRITICAL contradictions found, log them — WHY1 will challenge these specifically.

**Transition:** Update state.json phase to "why1". Proceed to WHY1.

---

## 3. WHY1 Phase (Assumption Challenge)

### Context Pack Assembly

Read and include in the subagent prompt:
- `glossary.md` + `mental-model.md` + `boundaries.md`
- `assumptions.md` + `unknowns.md`
- `calibration-profile.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/why.md` for your complete instructions. You are the WHY agent operating in **assumption-challenge mode** (WHY1 — pre-WHAT). Do NOT run Understanding metrics (no specs exist yet). Challenge assumptions for logical consistency, identify contradictions in the domain map, perform pre-mortem analysis, flag unknowns needing SCIENTIST investigation. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "WHY1: assumption challenge and pre-mortem analysis"

### Expected Outputs
- `assumption-review.md`
- Updated `unknowns.md` (if new unknowns discovered)
- `issues.md` (if critical issues found)

### Gate Check

Read WHY1 outputs:
- If **CRITICAL** issues found in `assumption-review.md` → route back to DISCOVER (re-investigate). Increment iteration counter. Check iteration limit.
- If **PASS** (no critical issues, all major assumptions validated or flagged) → proceed to WHAT.

**Transition:** Update state.json phase to "what". Proceed to WHAT.

---

## 4. WHAT Phase (Requirements Definition)

### Context Pack Assembly

Read and include in the subagent prompt:
- `glossary.md` + `mental-model.md` + `boundaries.md`
- `assumptions.md` + `unknowns.md`
- `reference-architectures.md` (if greenfield)
- `reasoning-journal.json` (filtered to DISCOVER + WHY1 entries)

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/what.md` for your complete instructions. You are the WHAT agent — requirements definer. Transform DISCOVER's domain map into precise, testable specifications. Write user stories with acceptance criteria (Given/When/Then). No implementation details — no languages, frameworks, or databases. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "WHAT: requirements definition and specification"

### Expected Outputs
- `spec.md`
- `00-overview.md`

**Transition:** Update state.json phase to "why2". Proceed to WHY2.

---

## 5. WHY2 Phase (Spec Validation)

### Context Pack Assembly

Read and include in the subagent prompt:
- All current artifacts in `.specify/specs/{feature}/`
- Understanding CLI access (via `scripts/bash/run-understanding.sh`)
- `calibration-profile.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/why.md` for your complete instructions. You are the WHY agent operating in **spec-validation mode** (WHY2 — post-WHAT). Run Understanding `validate` against `spec.md` to get deterministic quality scores. Challenge requirements for ambiguity, incompleteness, untestability. Hunt for missing edge cases, unstated assumptions, implicit requirements. Quality gates: overall >= 0.70, structure >= 0.70, testability >= 0.70, semantic >= 0.60, cognitive >= 0.60, readability >= 0.50. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "WHY2: spec validation with Understanding quality gates"

### Expected Outputs
- `issues.md` (scored findings: CRITICAL / HIGH / MEDIUM / LOW)
- `quality-gates.md` (Understanding metric results)

### Gate Check + Convergence

Read WHY2 outputs:
1. **Quality gates pass AND no CRITICAL issues** → proceed to ASSESS
2. **Quality gates fail OR CRITICAL issues found** → route back to WHAT with specific amendment demands. Increment iteration. Check limits.
3. **Track quality scores** — append to `state.json.quality_scores[]`
4. **Convergence check:** If this is iteration >= 2, compare quality scores:
   - Delta < `convergence_delta` (0.02) for 2 consecutive passes → stop WHY iterations, proceed even if gates not fully met (flag as best-effort)
   - Same issue appears 3x → defer or escalate (see Section 15)

**Transition:** Update state.json phase to "assess". Proceed to ASSESS.

---

## 6. ASSESS Phase (Kill Gate)

### Context Pack Assembly

Read and include in the subagent prompt:
- `spec.md` + `glossary.md` + `assumptions.md`
- `issues.md` (from WHY2)
- `calibration-profile.yaml` + `estimates-log.yaml`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/assess.md` for your complete instructions. You are the ASSESS agent — strategic PM and kill gate. Evaluate feasibility (can this be built within constraints?). Estimate effort using Function Point Analysis adjusted by calibration data. Prioritize features with Kano + RICE. Scope MVP. **Kill gate:** if unfeasible or all low-priority, produce a kill report using `templates/kill-report.md`. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "ASSESS: feasibility, estimation, prioritization, kill gate"

### Expected Outputs
- `feasibility.md`
- `prioritization.md`
- `estimates.md`
- `mvp-scope.md`

### Gate Check

Read ASSESS outputs:
- **KILL** verdict → write kill report to `.specify/specs/{feature}/kill-report.md`, set state.json status to "killed", print summary, STOP.
- **DEFER** verdict → reduce scope, re-route to WHAT. Track DEFER count. **DEFER loop >= 2 with no scope stabilization → kill or escalate to human.**
- **PASS** → proceed to specialist summoning.

**Transition:** Update state.json phase to "specialists". Proceed to specialist summoning.

---

## 7. Specialist Summoning

### Determine Which Specialists to Summon

After ASSESS passes, determine which specialists are needed:

1. **Read DISCOVER outputs** to classify the domain (e.g., fintech, healthcare, IoT, e-commerce, real-time, ML/AI)
2. **Read `calibration-profile.yaml`** for low-confidence domains
3. **Read `unknowns.md`** for unresolved items

### Summoning Rules

| Specialist | Summon When | Max Priority |
|-----------|-------------|--------------|
| **TEST ARCHITECT** | ALWAYS (mandatory) | Required |
| **SCIENTIST** | `unknowns.md` has unresolved items OR `calibration-profile.yaml` shows confidence < 0.5 for relevant domain | High |
| **SECURITY** | Domain involves auth, payments, PII, regulatory compliance | High |
| **DOMAIN EXPERT** | Domain-specific knowledge needed (detected from DISCOVER) | Medium |
| **PERFORMANCE** | High-load, real-time, scalability requirements in spec | Medium |
| **UX / A11Y** | Frontend, user-facing features, accessibility | Medium |
| **INNOVATE** | Re-run (iteration >= 2) AND EVOLVE detects stagnation, OR circular reasoning 3x | Low |

### Max Active Specialists

Maximum `max_active_specialists` (default 3) can be active simultaneously. If more are needed, prioritize by domain signal strength. Defer lower-priority specialists (their insights can be incorporated in future runs).

**Exception:** TEST ARCHITECT does not count toward the cap — it is mandatory and always runs.

### Dispatch Specialists

For each specialist to summon, dispatch sequentially (unless they are independent — SCIENTIST investigations can run in parallel with domain specialists).

#### SCIENTIST Dispatch (if summoned)

Context pack:
- Specific question(s) from `unknowns.md`
- Relevant artifacts (select based on the question — do not send everything)
- `reasoning-journal.json`

Use the Agent tool:
- **prompt:** Read the file `agents/specialists/scientist.md` for your complete instructions. You are the SCIENTIST. Investigate the following unknowns: [list from unknowns.md]. Follow the full scientific method: QUESTION, RESEARCH, EVALUATE (grade A-E), HYPOTHESIZE, EXPERIMENT (if feasible — use git worktree via `scripts/bash/setup-worktree.sh`), MEASURE, SYNTHESIZE, RECOMMEND. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "SCIENTIST: investigating unknowns — {topic summary}"

#### SECURITY Dispatch (if summoned)

Context pack:
- `spec.md` + `boundaries.md` + domain-relevant artifacts
- `reasoning-journal.json`

Use the Agent tool:
- **prompt:** Read the file `agents/specialists/security.md`. You are the SECURITY specialist. Perform STRIDE threat modeling, check OWASP Top 10 applicability, identify compliance requirements (PCI-DSS, HIPAA, GDPR, SOC 2 as relevant). Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "SECURITY: threat modeling and compliance analysis"

#### DOMAIN EXPERT Dispatch (if summoned)

Context pack:
- Domain-relevant artifacts from `.specify/specs/{feature}/`
- `reasoning-journal.json`

Use the Agent tool:
- **prompt:** Read the file `agents/specialists/domain-expert.md`. You are the DOMAIN EXPERT for {domain}. Provide domain patterns, regulatory requirements, common pitfalls, and terminology corrections. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "DOMAIN EXPERT: {domain} domain analysis"

#### PERFORMANCE Dispatch (if summoned)

Context pack:
- `spec.md` + `boundaries.md` + performance-relevant requirements
- `reasoning-journal.json`

Use the Agent tool:
- **prompt:** Read the file `agents/specialists/performance.md`. You are the PERFORMANCE specialist. Perform load modeling, capacity planning, identify bottleneck risks. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "PERFORMANCE: load modeling and capacity analysis"

#### UX / A11Y Dispatch (if summoned)

Context pack:
- `spec.md` + user-facing requirements
- `reasoning-journal.json`

Use the Agent tool:
- **prompt:** Read the file `agents/specialists/ux-a11y.md`. You are the UX/A11Y specialist. Analyze WCAG 2.1/2.2 compliance needs, apply Nielsen's heuristics, map user flows. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "UX/A11Y: accessibility and usability analysis"

#### INNOVATE Dispatch (if summoned)

Context pack:
- All current artifacts
- Prior run's `evolution-report.md`
- `reasoning-journal.json`

Use the Agent tool:
- **prompt:** Read the file `agents/specialists/innovate.md`. You are the INNOVATE specialist. Propose 2-3 fundamentally different approaches using TRIZ, Design Thinking, or First Principles. Challenge established assumptions. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "INNOVATE: alternative approaches and assumption challenges"

### Post-Specialist

After all specialists complete, collect their outputs. Update `state.json.active_specialists` with the list of specialists that ran.

**Transition:** Update state.json phase to "how". Proceed to HOW.

---

## 8. HOW Phase (Architecture)

### Context Pack Assembly

Read and include in the subagent prompt:
- `spec.md` + `feasibility.md` + `prioritization.md`
- `constitution.md` (if exists from prior run or user provided)
- All specialist outputs (threat-model.md, performance-requirements.md, etc.)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/how.md` for your complete instructions. You are the HOW agent — architect. Select technology stack with explicit rationale. Design system structure (data model, API contracts, component architecture). Define cross-cutting concerns as architectural decisions. Create constitution. Document every decision in ADR format. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "HOW: architecture design and technology decisions"

### Expected Outputs
- `plan.md`
- `research.md`
- `data-model.md`
- `contracts/` (API/interface specs)
- `constitution.md`

**Transition:** Update state.json phase to "test-architect". Proceed to TEST ARCHITECT.

---

## 9. TEST ARCHITECT Phase (Mandatory)

### Context Pack Assembly

Read and include in the subagent prompt:
- `plan.md` + `data-model.md`
- `spec.md` (acceptance criteria)
- `contracts/`
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/specialists/test-architect.md` for your complete instructions. You are the TEST ARCHITECT. Produce a comprehensive test strategy from plan.md + data-model.md + spec.md acceptance criteria. Map every acceptance criterion to a test approach. Define the test pyramid. Identify boundary value cases. If acceptance criteria have no testable form, flag them for routing back to WHAT. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "TEST ARCHITECT: test strategy and coverage mapping"

### Expected Outputs
- `test-strategy.md`
- `test-architecture.md`
- `coverage-map.md`

### Gate Check

If TEST ARCHITECT flags untestable acceptance criteria → route back to WHAT for amendment. Increment iteration. Check limits.

**Transition:** Update state.json phase to "plan". Proceed to PLAN.

---

## 10. PLAN Phase (Task Breakdown)

### Context Pack Assembly

Read and include in the subagent prompt:
- `plan.md` + `research.md` + `data-model.md`
- `contracts/` + `test-strategy.md`
- Risk data from specialists (threat-model.md, performance-requirements.md, etc.)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/plan.md` for your complete instructions. You are the PLAN agent — operational PM. Break the architecture into executable tasks (foundation, features, polish). Identify the critical path. Map task dependencies and parallelization. Assess risk per task. Include test tasks from test-strategy.md. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "PLAN: task breakdown, critical path, dependencies, risk"

### Expected Outputs
- `tasks.md`
- `critical-path.md`
- `risk-matrix.md`
- `dependencies.md`

**Transition:** Update state.json phase to "consensus". Proceed to CONSENSUS.

---

## 11. CONSENSUS Phase (Parallel Validation)

This phase runs **WHY3 + ASSESS2 + PLAN2 in parallel** using multiple Agent tool calls in a single message. If specialists are still active, include them in the parallel dispatch.

### 11.1 WHY3 Context Pack
- All artifacts in `.specify/specs/{feature}/` (spec, plan, tasks, specialist outputs)
- Understanding CLI access
- `calibration-profile.yaml`
- `reasoning-journal.json`

### 11.2 ASSESS2 Context Pack
- `plan.md` + `data-model.md` + `contracts/`
- `tasks.md` + `estimates.md`
- `constitution.md` (team constraints)
- `reasoning-journal.json`

### 11.3 PLAN2 Context Pack
- Updated `plan.md` + `test-strategy.md`
- All specialist outputs
- `implementability-report.md` (from ASSESS2 — dispatch ASSESS2 first, then PLAN2 reads its output)
- `reasoning-journal.json`

### Dispatch (Parallel)

Dispatch WHY3 and ASSESS2 in parallel (single message, two Agent tool calls):

**WHY3:**
- **prompt:** Read the file `agents/core/why.md`. You are WHY operating in **spec-validation mode** (WHY3 — consensus). Run full Understanding quality gates. Check cross-artifact consistency across ALL artifacts. This is the final quality check. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "WHY3: final quality validation and cross-artifact consistency"

**ASSESS2:**
- **prompt:** Read the file `agents/core/assess.md`. You are ASSESS2 — consensus-phase re-evaluation. Re-evaluate feasibility against the concrete architecture. Update effort estimates with architectural complexity. Perform the **6-point IMPLEMENTABILITY CHECK**: (1) Can a developer pick up each task without unstated knowledge? (2) Do tasks reference APIs/libraries/services that actually exist? (3) Are "parallel" tasks truly independent? (4) Does the tech stack match available team skills? (5) Are task descriptions self-contained? (6) Can each task be tested independently? Produce `implementability-report.md` (scored per task: READY / NEEDS_CLARIFICATION / BLOCKED). You can flag but NOT kill at this stage — only CRITICAL feasibility issues route back to HOW. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "ASSESS2: implementability check and effort re-estimation"

After WHY3 and ASSESS2 complete, dispatch PLAN2:

**PLAN2:**
- **prompt:** Read the file `agents/core/plan.md`. You are PLAN2 — consensus-phase plan revision. Re-evaluate task dependencies with specialist-added tasks. Update critical path if specialist work changed sequencing. Validate all specialist outputs have corresponding tasks. Incorporate implementability feedback — split unclear tasks, add missing context. Here is your context pack: [include files — include ASSESS2's implementability-report.md]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "PLAN2: plan revision incorporating implementability feedback"

### Consensus Gate Check

Read outputs from all three consensus agents:

- **ALL PASS** (no CRITICAL issues, quality gates met, all tasks READY or NEEDS_CLARIFICATION with fixes applied) → proceed to FINALIZE
- **MINOR issues only** → MANAGER resolves directly (update artifacts, log reasoning). Re-run consensus if changes are significant.
- **CRITICAL issues** → route back to the responsible phase:
  - WHY3 CRITICAL spec issues → back to WHAT
  - ASSESS2 CRITICAL feasibility issues → back to HOW
  - PLAN2 missing tasks for specialist outputs → back to PLAN
  - Increment iteration. Check limits.

**Transition:** Update state.json phase to "finalize". Proceed to FINALIZE.

---

## 12. FINALIZE Phase

### 12.1 GROUND Agent

Context pack:
- All artifacts in `.specify/specs/{feature}/`
- `calibration-profile.yaml` + `estimates-log.yaml`
- `reasoning-journal.json`

Use the Agent tool:
- **prompt:** Read the file `agents/learning/ground.md`. You are the GROUND agent. Reality-check all artifacts. Connect plans to real-world data: infrastructure costs, production benchmarks, team capacity. Compare estimates to past outcomes via FEEDBACK data. Check architectural decisions against operational constraints. Flag disconnects. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "GROUND: reality check and reference class forecasting"

Expected outputs: `reality-check.md`, `cost-analysis.md`, `benchmark-data.md`

### 12.2 REFLECT Agent

Context pack:
- All artifacts in `.specify/specs/{feature}/`
- `reasoning-journal.json`
- `knowledge-base/patterns.yaml` + `knowledge-base/pitfalls.yaml`

Use the Agent tool:
- **prompt:** Read the file `agents/learning/reflect.md`. You are the REFLECT agent. Perform post-run analysis. Extract what assumptions were wrong, which patterns worked, what the squad should do differently. Log reusable patterns and pitfalls to the knowledge base. Here is your context pack: [include files]. Update `knowledge-base/patterns.yaml` and `knowledge-base/pitfalls.yaml`. Append entries to `reasoning-journal.json`.
- **description:** "REFLECT: post-run learning extraction"

### 12.3 EVOLVE Agent (if re-run)

Only dispatch if `state.json.iteration > 0` or prior run artifacts exist.

Context pack:
- All current artifacts
- Prior run artifacts (for diffing)
- `reasoning-journal.json`
- `knowledge-base/` files

Use the Agent tool:
- **prompt:** Read the file `agents/learning/evolve.md`. You are the EVOLVE agent. Diff artifacts between this run and prior runs. Measure quality trajectory. Detect regressions. Flag stagnation (if no improvement, recommend triggering INNOVATE on next run). Check for confirmation bias in knowledge base entries. Here is your context pack: [include files]. Produce outputs in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "EVOLVE: cross-run diffing and improvement measurement"

Expected outputs: `evolution-report.md`, `improvement-metrics.md`, `regression-alerts.md`

### 12.4 CALIBRATE Agent

Context pack:
- All artifacts in `.specify/specs/{feature}/`
- `knowledge-base/calibration-profile.yaml`
- `knowledge-base/estimates-log.yaml`
- `reasoning-journal.json`
- Quality scores from all WHY passes (from state.json)

Use the Agent tool:
- **prompt:** Read the file `agents/learning/calibrate.md`. You are the CALIBRATE agent. Track AI accuracy per domain. Build/update the confidence profile. Adjust ASSESS estimate multipliers based on historical data. Flag low-confidence domains for human input or SCIENTIST investigation. Here is your context pack: [include files]. Update `knowledge-base/calibration-profile.yaml`. Produce `confidence-flags.md` in `.specify/specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
- **description:** "CALIBRATE: accuracy tracking and confidence profiling"

### 12.5 CALIBRATE Confidence Check

After CALIBRATE completes, read `confidence-flags.md`:
- If any domain has **confidence < 0.5** → summon SCIENTIST for that domain (if not already investigated). This is a late-stage safety net.
- If SCIENTIST was already summoned and confidence is still < 0.5 → flag for human in the final report (do not block delivery).

### 12.6 Collect Final Artifacts

Verify all expected artifacts exist in `.specify/specs/{feature}/`. Create a manifest:

```
Artifact                          | Producer        | Status
----------------------------------|-----------------|--------
glossary.md                       | DISCOVER        | OK/MISSING/UNVALIDATED
mental-model.md                   | DISCOVER        | ...
boundaries.md                     | DISCOVER        | ...
assumptions.md                    | DISCOVER+WHY    | ...
unknowns.md                       | DISCOVER+WHY    | ...
spec.md                           | WHAT            | ...
feasibility.md                    | ASSESS          | ...
prioritization.md                 | ASSESS          | ...
estimates.md                      | ASSESS          | ...
mvp-scope.md                      | ASSESS          | ...
plan.md                           | HOW             | ...
research.md                       | HOW+SCIENTIST   | ...
data-model.md                     | HOW             | ...
contracts/                        | HOW             | ...
constitution.md                   | HOW             | ...
tasks.md                          | PLAN            | ...
critical-path.md                  | PLAN            | ...
risk-matrix.md                    | PLAN            | ...
dependencies.md                   | PLAN            | ...
test-strategy.md                  | TEST ARCHITECT  | ...
test-architecture.md              | TEST ARCHITECT  | ...
coverage-map.md                   | TEST ARCHITECT  | ...
issues.md                         | WHY             | ...
quality-gates.md                  | WHY             | ...
reality-check.md                  | GROUND          | ...
cost-analysis.md                  | GROUND          | ...
benchmark-data.md                 | GROUND          | ...
implementability-report.md        | ASSESS2         | ...
reasoning-journal.json            | ALL             | ...
confidence-flags.md               | CALIBRATE       | ...
```

Additional artifacts (conditional):
- `reference-architectures.md` (greenfield only)
- `assumption-review.md` (if WHY1 produced it)
- `investigation/*.md` (if SCIENTIST ran)
- `evidence-grades.md` (if SCIENTIST ran)
- `experiment-results.md` (if SCIENTIST ran)
- `recommendations.md` (if SCIENTIST ran)
- `threat-model.md` (if SECURITY ran)
- `compliance-requirements.md` (if SECURITY ran)
- `performance-requirements.md` (if PERFORMANCE ran)
- `capacity-model.md` (if PERFORMANCE ran)
- `accessibility-requirements.md` (if UX/A11Y ran)
- `user-flow.md` (if UX/A11Y ran)
- `alternatives.md` (if INNOVATE ran)
- `evolution-report.md` (if EVOLVE ran)

### 12.7 Run SCOREKEEPER

Dispatch SCOREKEEPER to produce the final scorecard (see Section 13 for full protocol).
Read the scorecard output and apply any automatic self-healing actions.

### 12.8 Set Final State

Update `state.json`:
```json
{
  "status": "done",
  "phase": "done",
  "updated_at": "{ISO-8601}"
}
```

### 12.8 Print Final Summary

Print to terminal:

```
============================================
  COGNITIVE SQUAD RUN COMPLETE
============================================

Run ID:     {run_id}
Feature:    {NNN}-{feature}
Mode:       {greenfield|brownfield}
Iterations: {count}
Duration:   {elapsed time}

QUALITY SCORES (final WHY pass):
  Overall:     {score} {pass/fail}
  Structure:   {score} {pass/fail}
  Testability: {score} {pass/fail}
  Semantic:    {score} {pass/fail}
  Cognitive:   {score} {pass/fail}
  Readability: {score} {pass/fail}

SPECIALISTS SUMMONED: {list}

ARTIFACTS: {count} files in .specify/specs/{NNN}-{feature}/

AGENT SCORECARD:
  Top performer: {agent} (+{score}) — {highlight}
  Badges earned: {count} ({badge names})
  Peer appreciation: {count} exchanges
  Self-healing: {count} recommendations

WARNINGS:
  {any UNVALIDATED artifacts}
  {any low-confidence domains}
  {any unresolved unknowns}

Spec ID for feedback: {NNN}
Run: /speckit.squad.feedback {NNN} after implementation
============================================
```

**DONE.** The squad run is complete.

---

## 13. Scorekeeper Protocol

SCOREKEEPER runs throughout the entire squad execution — not as a separate phase, but woven into every agent dispatch.

### After Every Agent Dispatch

After reading an agent's output, MANAGER scores the agent:

```
1. Read the agent's output quality:
   - Did WHY pass or fail? → +5 for CRITICAL catch, -1 for false positive
   - Did WHAT need rework? → -1 per WHY rejection
   - Did IMPLEMENTER pass first review? → +3 first-pass, -1 rework
   - Did SCIENTIST validate an assumption? → +2 validated, +4 invalidated (more valuable)

2. Append to state.json.agent_scores:
   {
     "agent": "{AGENT_NAME}",
     "action": "{what they did}",
     "points": {N},
     "reason": "{why these points}"
   }
```

### Peer Appreciation Collection

When an agent's output is consumed by the NEXT agent, check: did the next agent benefit from high-quality input?

```
IF WHAT produces spec.md AND WHY2 passes on first attempt:
  → Peer appreciation: WHY awards WHAT +2 "clear_and_actionable"

IF SCIENTIST produces investigation/ AND HOW makes a decision based on it:
  → Peer appreciation: HOW awards SCIENTIST +3 "unblocked_my_work"

IF WHY catches an issue that SPEC GUARD would have missed:
  → Peer appreciation: SPEC GUARD awards WHY +2 "caught_my_mistake"
```

Record in reasoning-journal.json:
```json
{
  "type": "peer_appreciation",
  "from": "{agent giving appreciation}",
  "to": "{agent receiving}",
  "points": {N},
  "reason": "{why}"
}
```

### During FINALIZE — Full Scorecard

After GROUND + REFLECT + EVOLVE + CALIBRATE, dispatch SCOREKEEPER:

Use the Agent tool to dispatch a subagent with:
- **prompt:** Read the file `agents/core/scorekeeper.md` for your complete instructions. You are the SCOREKEEPER. Read `state.json.agent_scores` for all points accumulated during this run. Read `reasoning-journal.json` for peer appreciation entries. Read `knowledge-base/agent-scores.yaml` for lifetime scores. Calculate final run scores per agent. Check badge criteria. Produce `agent-scorecard.md`. Check self-healing triggers. Update `knowledge-base/agent-scores.yaml` with run history.
- **description:** "SCOREKEEPER: final scoring, badges, self-healing recommendations"

Context pack:
- state.json (with agent_scores array)
- reasoning-journal.json (with peer_appreciation entries)
- knowledge-base/agent-scores.yaml (lifetime data)
- config-template.yml → scoring section (point values, thresholds)

### Expected SCOREKEEPER Outputs

- `.specify/specs/{feature}/agent-scorecard.md` — leaderboard, peer appreciation, self-healing recommendations
- Updated `knowledge-base/agent-scores.yaml` — run history appended, lifetime scores updated, badges awarded

### Self-Healing Actions (MANAGER executes immediately)

Read SCOREKEEPER's self-healing recommendations and apply:

| Recommendation | MANAGER Action |
|---------------|---------------|
| "ASSESS correction factor should increase to 1.5x" | Update calibration-profile.yaml |
| "WHY false positive rate > 30%" | Log for human review (prompt refinement) |
| "IMPLEMENTER score < -5 over 3 runs" | Log for human review (prompt refinement) |
| "TEST GUARDIAN score low — add test pattern examples" | Log for human review |

Self-healing that affects calibration-profile.yaml is automatic. Self-healing that affects agent prompts is flagged for human review.

---

## 14. State Tracking Protocol

After **every** phase transition, update `.specify/squad/state.json`:

```json
{
  "phase": "{new_phase}",
  "updated_at": "{ISO-8601}",
  "iteration": "{current_iteration}"
}
```

After every agent dispatch, check if the agent appended to `reasoning-journal.json`. If not, append a MANAGER entry noting the agent completed without journal entries.

Track cumulative token usage in `state.json.token_usage` (estimate based on prompt + response sizes).

Track issues in `state.json.issues_log[]`:
```json
{
  "id": "ISS-{NNN}",
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "source": "{agent_name}",
  "description": "{issue}",
  "resolved": false,
  "occurrences": 1
}
```

When the same issue appears again, increment `occurrences` rather than creating a duplicate.

---

## 14. Convergence Rules

These rules prevent infinite loops and ensure the squad terminates:

### Rule 1: Understanding Delta Convergence
- After each WHY pass (WHY2, WHY3), record quality scores in `state.json.quality_scores[]`
- If the delta between the last two passes is < `convergence_delta` (default 0.02) for 2 consecutive passes → **stop WHY iterations**
- Proceed to next phase even if gates are not fully met — flag as "best-effort convergence"

### Rule 2: Circular Issue Detection
- If the same issue (matched by description similarity) appears 3 times in `state.json.issues_log[].occurrences` → **defer or escalate**
- First: attempt INNOVATE (propose alternative approach that avoids the issue)
- If INNOVATE already tried: escalate to human (see Section 15)

### Rule 3: Max Iterations
- Maximum `max_iterations` (default 5) total squad iterations → **force convergence**
- When forced: run FINALIZE with whatever artifacts exist, flag all as "forced convergence"
- DEFER re-routes count toward the iteration max

### Rule 4: Token Budget Exhaustion
- If cumulative `token_usage` exceeds `token_budget_k * 1000` → **force finalize**
- Skip remaining specialists if budget is tight
- Always run GROUND + CALIBRATE (minimum finalize)

### Rule 5: CALIBRATE Confidence Gate
- If CALIBRATE reports confidence < 0.5 for a critical domain → **summon SCIENTIST**
- If SCIENTIST already ran for that domain and confidence is still < 0.5 → flag for human, do not block

### Rule 6: ASSESS DEFER Loop
- If ASSESS returns DEFER >= 2 times with no scope stabilization → **kill or escalate**
- Produce kill report OR escalation request (MANAGER decides based on severity)

---

## 15. Error Handling

### External Tool Failures

| Tool | Failure | Fallback |
|------|---------|----------|
| Understanding CLI | Not installed, crashes, or times out | WHY falls back to heuristic review: manually check ambiguity, completeness, testability. Flag all quality scores as UNVALIDATED. |
| spec-kit-reverse-eng | Not installed or fails on codebase | DISCOVER falls back to greenfield mode: ask user to describe the codebase instead. Flag as degraded. |
| spec-kit CLI | Not installed | HOW and PLAN produce artifacts manually as markdown. No spec-kit validation. Flag as UNVALIDATED. |

### Subagent Failures

- **Timeout** (agent takes > 5 minutes): Retry once. If second attempt also times out, skip the agent with a warning in the final report. Continue to next phase.
- **Error output** (agent produces malformed or empty output): Log the error, skip the agent, continue. Flag missing artifacts as MISSING.
- **Crash**: Same as timeout — retry once, then skip.

### Degraded Mode Artifacts

Every artifact produced in degraded mode (fallback was used) must have this banner at the top:

```markdown
> **UNVALIDATED** — This artifact was produced without {tool_name}. Quality has not been deterministically verified. Treat with additional scrutiny.
```

---

## 16. Human Escalation Protocol

### When Triggered

Escalation to human is triggered when:
1. Same issue appears 3x without resolution (after INNOVATE attempt)
2. CALIBRATE confidence < 0.5 after SCIENTIST investigation
3. Unresolvable conflict between agents (evidence hierarchy cannot resolve)
4. ASSESS DEFER loop >= 2 with no scope stabilization

### Escalation Procedure

1. **Produce escalation request:** Read `templates/escalation-request.md` and fill in all placeholders:
   - `{TOPIC}` — the specific blocked issue
   - `{RUN_ID}` — current run ID
   - `{CURRENT_PHASE}` — phase where escalation was triggered
   - The specific question, context, options considered, recommended answer

2. **Write to file:** Save as `.specify/specs/{feature}/escalation-request.md`

3. **Update state:** Set `state.json`:
   ```json
   {
     "status": "blocked",
     "blocked_reason": "{description of what is blocked}",
     "escalation_question": "{the specific question}"
   }
   ```

4. **Print to terminal:**
   ```
   ============================================
     SQUAD BLOCKED — HUMAN INPUT REQUIRED
   ============================================

   Question: {the specific question}

   Context: {1-2 sentence summary}

   Options:
     A: {option A}
     B: {option B}
     C: {option C}

   Recommended: {option}

   Respond with: /speckit.squad.resume {your answer}
   ============================================
   ```

5. **STOP execution.** Do not proceed. The user must run `/speckit.squad.resume` to continue.

---

## 17. Evidence Hierarchy (Conflict Resolution)

When two agents disagree (e.g., HOW says microservices, ASSESS says monolith), resolve using this hierarchy — higher rank wins:

| Rank | Evidence Type | Source | Example |
|------|-------------|--------|---------|
| 1 | Experiment results | SCIENTIST spike measurements | "Latency measured at 340ms under load" |
| 2 | Understanding metrics | WHY deterministic scores | "Testability score: 0.42 (below 0.70 gate)" |
| 3 | Research (graded A-E) | SCIENTIST evidence evaluation | "Grade B: official Kafka docs confirm this limit" |
| 4 | Code evidence | DISCOVER / Reverse-Eng | "Existing codebase uses event sourcing for audit" |
| 5 | Agent reasoning | Any agent's logical argument | "Microservices better because of team structure" |

When resolving a conflict:
1. Check if higher-ranked evidence exists for either position
2. The position with the highest-ranked supporting evidence wins
3. If same rank: the more recent evidence wins
4. If still tied: MANAGER logs the conflict and chooses the lower-risk option
5. All conflict resolutions are recorded in `reasoning-journal.json` with type "decision"

---

## 18. Token Budget Management

### Allocation (MANAGER enforces)

| Priority | Budget % | Phases |
|----------|---------|--------|
| 1 | 25% | DISCOVER + WHAT |
| 2 | 20% | WHY (all passes) |
| 3 | 25% | HOW + SPECIALISTS |
| 4 | 15% | PLAN + ASSESS |
| 5 | 10% | CONSENSUS + FINALIZE |
| 6 | 5% | Reserve (re-routes, error recovery) |

### Budget Enforcement

- Before each agent dispatch, check remaining budget
- If remaining budget < estimated cost for the agent → check if phase can be skipped
  - DISCOVER, WHAT, WHY, ASSESS, HOW, PLAN: **cannot be skipped** — force finalize instead
  - Specialists (except TEST ARCHITECT): can be deferred
  - CONSENSUS: can be reduced (run WHY3 only, skip ASSESS2 + PLAN2)
  - FINALIZE: always run GROUND + CALIBRATE at minimum

---

## 19. Re-Run Behavior

When this command runs against a feature that already has artifacts:

1. **INIT** detects prior artifacts, sets `iteration` appropriately
2. **EVOLVE** is dispatched at the start of FINALIZE to diff against prior run
3. **All agents** receive prior artifacts in their context packs
4. **INNOVATE** may be summoned if EVOLVE detects stagnation
5. **CALIBRATE** compares quality trajectory across runs
6. Knowledge base entries from prior runs are available to all agents

The goal of re-runs is monotonic improvement: each run should produce artifacts at least as good as the prior run, and ideally better. EVOLVE measures this. If improvement stalls for 2 consecutive runs, INNOVATE is summoned to break out of local optima.

---

## 20. Quick Reference: Phase Transitions

```
INIT ──────► DISCOVER ──► SYNTHESIZER ──► WHY1 ──► WHAT
                  ▲                 │                 │
                  │ (re-investigate) │ (CRITICAL)      │
                  └─────────────────┘                 ▼
                                                    WHY2
                                                      │
                               ┌──────────────────────┤
                               │ (gates fail)         │ (gates pass)
                               ▼                      ▼
                             WHAT ◄────────────── ASSESS
                                                      │
                                    ┌─────────────────┤
                                    │ KILL            │ DEFER (≥2 → kill/escalate)
                                    ▼                 │ PASS
                                   DONE               ▼
                                              SPECIALISTS
                                                      │
                                                      ▼
                                                    HOW
                                                      │
                                                      ▼
                                              TEST ARCHITECT
                                                      │
                                                      ▼
                                                    PLAN
                                                      │
                                                      ▼
                                                 CONSENSUS
                                              (WHY3 ∥ ASSESS2)
                                                 then PLAN2
                                                      │
                               ┌──────────────────────┤
                               │ CRITICAL             │ ALL PASS
                               ▼                      ▼
                          (route back)           FINALIZE
                                              GROUND → REFLECT
                                              → EVOLVE → CALIBRATE
                                                      │
                                                      ▼
                                                    DONE
```

---

## 21. Checklist (MANAGER Self-Verification)

Before declaring DONE, verify:

- [ ] All phases executed (or explicitly skipped with documented reason)
- [ ] `state.json` reflects final state accurately
- [ ] `reasoning-journal.json` has entries from every dispatched agent
- [ ] All quality gate results are recorded in `quality-gates.md`
- [ ] All UNVALIDATED artifacts are clearly flagged
- [ ] All CRITICAL issues are either resolved or documented as unresolved
- [ ] Specialist outputs are incorporated into plan and tasks
- [ ] TEST ARCHITECT ran (mandatory)
- [ ] `implementability-report.md` exists with per-task scores
- [ ] Knowledge base files updated (patterns.yaml, pitfalls.yaml, calibration-profile.yaml)
- [ ] SCOREKEEPER ran — agent-scorecard.md produced
- [ ] agent-scores.yaml updated with run history
- [ ] Self-healing recommendations applied (calibration) or logged (prompt refinement)
- [ ] Final summary printed to terminal with spec ID and scorecard summary
