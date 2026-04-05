# Echelon Proto — Agent Architecture Report

**Spec**: 016-echelon-proto-reverse-eng
**Date**: 2026-04-02
**ACs Satisfied**: AC-001-001, AC-001-002, AC-001-003, AC-001-004, AC-001-005, AC-001-006
**Source Authority**: glossary.md, boundaries.md, architecture-gaps.md, mental-model.md

---

## All 42 Agents (AC-001-001)

**Evidence**: `find agents/ -name "*.md" | wc -l` returns **42** (verified 2026-04-02).
Build tier (11 agents) lives in `agents/build/`; remaining 31 agents in control/exploration/feasibility/learning/solution/specialists directories.

Source: `glossary.md` Agent Directory.

| Tier | Codename | Functional Name | Primary Artifact |
|------|----------|-----------------|-----------------|
| CONTROL | COMMANDER | MANAGER | state.json, routing decisions |
| CONTROL | SCOREKEEPER | SCORING ENGINE | agent-scores.yaml, calibration entries |
| CONTROL | TRACKER | INTENT-TRACKER | user-intent verification, scope-drift flags |
| CONTROL | STRATEGIST | OVERVIEW | goal-stack context summary |
| CONTROL | CHECKPOINT | INTERNALIZE-GATE | internalization verification report |
| CONTROL | PROSPECTOR | SURVEY | lightweight discovery cache |
| EXPLORATION | SCOUT | DISCOVER | glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md |
| EXPLORATION | SAGE | WHY | amended-assumptions.md, issues.md, quality-gates.md |
| EXPLORATION | SYNTHESIZER | FUSE | contradictions-and-gaps.md |
| EXPLORATION | CARTOGRAPHER | WHAT | spec.md |
| EXPLORATION | GOLDDIGGER | REVERSE-ENG | golddigger_artifacts (analysis.json, structure.json, dependencies.json) |
| EXPLORATION | MODELER | MENTAL-MODEL | refined mental-model.md (entity-relationship enrichment) |
| FEASIBILITY | GATEKEEPER | ASSESS | feasibility.md, estimates.md, PASS/DEFER/KILL decision |
| FEASIBILITY | VALIDATOR | INTERNALIZATION-GATE | spec internalization validation report |
| SOLUTION | ARCHITECT | HOW | architecture.md, data-model.md, contracts/ |
| SOLUTION | ORCHESTRATOR | PLAN | tasks.md, task-dependencies.json, plan.md |
| SOLUTION | SENTINEL | TEST-ARCHITECT | test-architecture.md |
| BUILD | IMPLEMENTER | BUILDER | source/ (implementation code) |
| BUILD | CODE-REVIEWER | CODE-REVIEW | code review report (block or pass decision) |
| BUILD | DEBUGGER | DEBUG | bug fix patches, root-cause analysis |
| BUILD | TEST-GUARDIAN | TEST-EXECUTOR | tests/ (test suite), coverage reports |
| BUILD | SPEC-GUARD | SPEC-CHECK | spec-compliance report, waiver artifacts |
| BUILD | INTEGRATOR | INTEGRATION | merged modules, integration test results |
| BUILD | CHANGE-CONTROLLER | CHANGE-CONTROL | change log, semantic version decisions |
| BUILD | VERIFICATION | BACKPROPAGATION-CHECK | regression report, requirements-to-code trace |
| BUILD | VISUAL-VALIDATOR | VISUAL-VALIDATION | accessibility/UI validation report |
| BUILD | PROGRESS-TRACKER | BUILD-TRACKER | schedule variance report |
| BUILD | ENGINEERING-MANAGER | BUILD-MANAGER | build phase escalation log |
| SPECIALISTS | GUARDIAN | SECURITY | security-review.md |
| SPECIALISTS | BENCHMARK | PERFORMANCE | performance-report.md |
| SPECIALISTS | INVESTIGATOR | SCIENTIST | investigation/ reports, experiment results |
| SPECIALISTS | MAVERICK | INNOVATE | innovation proposals, alternative-design docs |
| SPECIALISTS | ADVOCATE | UX-A11Y | accessibility review, UX validation report |
| SPECIALISTS | ORACLE | DOMAIN-EXPERT | domain-knowledge advisory reports |
| LEARNING | MIRROR | REFLECT | run-reflection.md |
| LEARNING | AUDITOR | CALIBRATE | calibration-profile.yaml (updated), agent-scores.yaml |
| LEARNING | ADAPTIVE | EVOLVE | evolution-report.md |
| LEARNING | REALIST | GROUND | grounding report, revised timeline projections |
| LEARNING | VETERAN | PROJECT-SCOPING | patterns.yaml (new/updated entries) |
| LEARNING | INTERNALIZER | INTERNALIZE-METRICS | metrics.json |
| LEARNING | MONITOR | METACOGNITION-MONITOR | health-check log, anomaly flags |
| LEARNING | GLOBAL-MEMORY | KNOWLEDGE-VAULT | knowledge-base vault entries |

**Total: 42 agents across 7 tiers.** (CONTROL: 6, EXPLORATION: 6, FEASIBILITY: 2, SOLUTION: 3, BUILD: 11, SPECIALISTS: 6, LEARNING: 8)

---

## Tier Structure (AC-001-002)

Source: `boundaries.md` Internal Boundaries.

| Tier | Agents (count) | Responsibility | Data Ownership | Active Phases |
|------|---------------|---------------|----------------|---------------|
| CONTROL | COMMANDER, SCOREKEEPER, TRACKER, STRATEGIST, CHECKPOINT, PROSPECTOR (6) | Route all agents; maintain state.json; track metrics; enforce quality gates; verify user intent alignment | state.json, reasoning-journal.json, dispatch_history | All phases |
| EXPLORATION | SCOUT, SAGE, SYNTHESIZER, CARTOGRAPHER, GOLDDIGGER, MODELER (6) | Map domain (SCOUT), challenge assumptions (SAGE), fuse fragments (SYNTHESIZER), write specs (CARTOGRAPHER), deep code analysis (GOLDDIGGER), refine models (MODELER) | All discovery and requirement markdown artifacts in spec directory | DISCOVER, WHY, WHAT |
| FEASIBILITY | GATEKEEPER, VALIDATOR (2) | Evaluate feasibility (GATEKEEPER); gate internalization (VALIDATOR); make PASS/DEFER/KILL decisions | feasibility.md, estimates.md, mvp-scope.md | ASSESS |
| SOLUTION | ARCHITECT, ORCHESTRATOR, SENTINEL (3) | Design architecture (ARCHITECT); decompose tasks (ORCHESTRATOR); architect tests (SENTINEL) | architecture.md, plan.md, tasks.md, data-model.md, contracts/, test-architecture.md | HOW, PLAN |
| BUILD | IMPLEMENTER, CODE-REVIEWER, TEST-GUARDIAN, SPEC-GUARD, INTEGRATOR, CHANGE-CONTROLLER, VERIFICATION, VISUAL-VALIDATOR, DEBUGGER, PROGRESS-TRACKER, ENGINEERING-MANAGER (11) | Code implementation, code review, testing, debugging, integration, verification, progress tracking | Codebase (source/), test suites, build artifacts | BUILD |
| SPECIALISTS | GUARDIAN, BENCHMARK, INVESTIGATOR, MAVERICK, ADVOCATE, ORACLE (6) | Security (GUARDIAN), performance (BENCHMARK), research (INVESTIGATOR), innovation (MAVERICK), UX/a11y (ADVOCATE), domain expertise (ORACLE); all advisory | Specialty reports (security-review.md, performance-report.md, investigation/, etc.) | On demand (any phase) |
| LEARNING | MIRROR, AUDITOR, ADAPTIVE, REALIST, VETERAN, INTERNALIZER, MONITOR, GLOBAL-MEMORY (8) | Post-run analysis, calibration, evolution, grounding, historical learning, understanding measurement, self-monitoring, knowledge vault | knowledge-base/, calibration-profile.yaml, marketplace-index.yaml, run history | LEARN (post-BUILD) |

**Tiering rule** (boundaries.md:159-171): CONTROL routes; EXPLORATION discovers; FEASIBILITY gates; SOLUTION designs; BUILD executes; SPECIALISTS advise (no tier depends on specialist output); LEARNING evolves for next run. No cross-tier artifact ownership is permitted.

---

## state.json Spine — 30 Fields (AC-001-003)

Source: `architecture-gaps.md` Gap 1 (observed state.json 2026-04-02T23:15:00Z).

Constitution P-012: "state.json is the single source of truth for run state. No agent may maintain private run state outside state.json."

| # | Field | Type | Purpose | Writer | Readers |
|---|-------|------|---------|--------|---------|
| 1 | run_id | string | Unique run identifier across all squad operations | COMMANDER (on init) | All agents (read-only) |
| 2 | status | string | Operational state: "running" / "paused" / "complete" / "failed" | COMMANDER | All agents; external tooling |
| 3 | phase | string | Current pipeline phase (discover/why/what/assess/how/plan/build/learn) | COMMANDER (on phase transition) | All agents; GATEKEEPER for validation |
| 4 | mode | string | Execution mode: "brownfield" / "greenfield" / "hybrid" | COMMANDER (on init) | ARCHITECT, ORCHESTRATOR |
| 5 | iteration | number | Current iteration count within a phase (0-indexed) | COMMANDER (post-dispatch) | COMMANDER (convergence), AUDITOR |
| 6 | spec_id | string OR null | Spec identifier if reverse-engineering a spec artifact | TRACKER (conditional) | CARTOGRAPHER, GATEKEEPER |
| 7 | spec_dir | string OR null | Directory path to spec artifact if reverse-engineering | PROSPECTOR (on codebase scan) | GOLDDIGGER, SCOUT |
| 8 | constitution_status | string | Constitution artifact status: "missing" / "exists" / "validated" | COMMANDER (pre-dispatch gate) | SENTINEL |
| 9 | created_at | ISO-8601 UTC | Run initialization timestamp | COMMANDER (on init) | AUDITOR, MIRROR |
| 10 | updated_at | ISO-8601 UTC | Last state.json modification timestamp | COMMANDER (post-dispatch) | MONITOR, AUDITOR |
| 11 | token_usage | number | Total tokens consumed by all agents so far | COMMANDER (post-dispatch, cumulative) | SCOREKEEPER; COMMANDER (budget enforcement) |
| 12 | quality_scores | array[object] | Per-agent quality evaluation scores (dimension → score) | SAGE (per-dispatch) | CHECKPOINT, COMMANDER |
| 13 | active_specialists | array[string] | Codenames of currently active specialist agents | COMMANDER (based on domain signals) | SENTINEL, external logging |
| 14 | issues_log | array[object] | Non-fatal errors: {agent, phase, issue, timestamp, severity} | SYNTHESIZER + individual agents on error | COMMANDER (severity escalation); AUDITOR |
| 15 | blocked_reason | string OR null | Human-readable reason if phase is blocked | COMMANDER (on gate DENY) | External dashboard, human escalation |
| 16 | escalation_question | string OR null | Question awaiting human answer if intervention required | COMMANDER (on escalation trigger) | Human interface, TRACKER |
| 17 | dispatch_counters | object[string→number] | Per-agent dispatch count (how many times each agent was invoked) | COMMANDER (post-dispatch) | AUDITOR; SCOREKEEPER |
| 18 | agent_scores | array[object] | Historical scores: {agent, dispatch_count, avg_quality, confidence, tokens_per_dispatch} | SCOREKEEPER (post-LEARN) | COMMANDER (dispatch weighting); VETERAN |
| 19 | split_metrics | object | Phase quality metrics: {fallback_count, qa_coverage, rework_count} | SENTINEL, CODE-REVIEWER, TEST-GUARDIAN | ENGINEERING-MANAGER |
| 20 | prospector_status | string | PROSPECTOR cache status: "not_run" / "complete_cached" / "complete_fresh" | PROSPECTOR | COMMANDER (skip/redo decision) |
| 21 | golddigger_status | string | GOLDDIGGER cache status: "not_run" / "complete_cached" / "complete_fresh" | GOLDDIGGER | COMMANDER |
| 22 | golddigger_mode | string | GOLDDIGGER mode: "mode1_survey" / "mode2_deepdive" | COMMANDER (based on scope signals) | GOLDDIGGER |
| 23 | golddigger_notes | string | Annotation about GOLDDIGGER run (caching source, prior run reference) | GOLDDIGGER | COMMANDER; AUDITOR |
| 24 | golddigger_artifacts | object[string→string] | Map of artifact type → file path (analysis, structure, dependencies, git_history, configs) | GOLDDIGGER (on completion) | SCOUT, SYNTHESIZER, CARTOGRAPHER |
| 25 | golddigger_requests | array[string] | Queue of GOLDDIGGER Mode 2 deep-dive domain requests | SCOUT, SYNTHESIZER, CARTOGRAPHER (append) | COMMANDER (dispatch sequencing); GOLDDIGGER |
| 26 | golddigger_completed_domains | array[string] | Completed Mode 2 domains (prevent re-analysis) | GOLDDIGGER (post-deep-dive) | COMMANDER (completeness check) |
| 27 | fallback_mode | boolean | If true, system is in fallback/safe mode (conservative gates) | COMMANDER (on repeated failures) | All agents |
| 28 | banzai_mode | boolean | If true, unlimited token budget mode active | COMMANDER (on init, per config) | SCOREKEEPER (budget override) |
| 29 | endocrine_enabled | boolean | If true, neuromodulation system (6 hormones) is active | COMMANDER (on init, per config) | endocrine.sh; agents (context injection) |
| 30 | endocrine_phase | number | Current endocrine cycle phase (0-indexed) for hormone decay calculation | endocrine.sh (post-cycle) | endocrine.sh; SCOREKEEPER |

**Stability**: Fields 1-11 are core run state (immutable after creation except field 10). Fields 12-30 evolve during run. State backed up at each phase transition via `scripts/bash/state-backup.sh` (MAX_BACKUPS=5).

---

## Pipeline Phase Sequence (AC-001-004)

Source: `architecture-gaps.md` Gap 4 (phase entry/exit conditions table).
Sequence: **DISCOVER → WHY → WHAT → ASSESS → HOW → PLAN → BUILD → LEARN**

| Phase | Active Agent(s) | Entry Condition | Exit Condition | Output Artifacts |
|-------|-----------------|-----------------|----------------|-----------------|
| DISCOVER | SCOUT, SYNTHESIZER, GOLDDIGGER, MODELER, PROSPECTOR | Codebase provided; run_id initialized; phase = "discover" set in state.json | glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md present and parseable; SYNTHESIZER contradictions-and-gaps.md produced | glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, contradictions-and-gaps.md (conditional) |
| WHY | SAGE, CARTOGRAPHER | glossary.md + mental-model.md + boundaries.md + assumptions.md present and SAGE-reviewed; no BLOCKED status | SAGE quality gates pass: overall ≥ 0.70 OR (structure ≥ 0.70 AND testability ≥ 0.70 AND semantic ≥ 0.60 AND cognitive ≥ 0.60 AND readability ≥ 0.50 AND behavioral ≥ 0.50 AND depth ≥ 0.40); amended-assumptions.md produced | amended-assumptions.md, issues.md, quality-gates.md |
| WHAT | CARTOGRAPHER, GOLDDIGGER (conditional) | amended-assumptions.md exists; spec.md passed WHY quality gates; GOLDDIGGER Mode 1 complete | spec.md final version produced; no outstanding NEEDS_CLARIFICATION items; TRACKER confirms scope locked | spec.md (final), specifications/ (sub-specs per domain, if produced) |
| ASSESS | GATEKEEPER, VALIDATOR | spec.md final + scope locked; no BLOCKED status from prior phase | GATEKEEPER decision: PASS → proceed to HOW; DEFER → loop back to WHAT (max 3 iterations per P-007); KILL → escalate to human | feasibility.md, estimates.md, prioritization.md (MVP scope) |
| HOW | ARCHITECT, SENTINEL, INVESTIGATOR (conditional) | GATEKEEPER decision = PASS + feasibility.md complete; scope locked; architecture unknowns cleared | architecture.md + data-model.md + contracts/ produced; SENTINEL validates test-architecture.md; all design decisions documented | architecture.md, data-model.md, contracts/, test-architecture.md, investigation/ (conditional) |
| PLAN | ORCHESTRATOR, STRATEGIST, CHECKPOINT | architecture.md + data-model.md complete; no blocking unknowns; phase = "plan" | tasks.md with complete dependency graph produced; CHECKPOINT internalization gate passes; no BLOCKED tasks | tasks.md, task-dependencies.json, plan.md, prioritization.md |
| BUILD | IMPLEMENTER, CODE-REVIEWER, TEST-GUARDIAN, SPEC-GUARD, DEBUGGER, INTEGRATOR, CHANGE-CONTROLLER, VERIFICATION, VISUAL-VALIDATOR, PROGRESS-TRACKER, ENGINEERING-MANAGER | tasks.md complete + no BLOCKED tasks; GATEKEEPER implementability check passes (six-point consensus); phase = "build" | All tasks complete in dispatch_counters; code submitted; all quality gates (CODE-REVIEWER, TEST-GUARDIAN, SPEC-GUARD, VERIFICATION) approved; no BLOCKED tasks remain | source/ (code), tests/ (≥80% coverage), docs/, deployment-ready artifacts |
| LEARN | MIRROR, AUDITOR, ADAPTIVE, REALIST, VETERAN, INTERNALIZER, MONITOR, GLOBAL-MEMORY | BUILD phase complete; all artifacts produced and reviewed; phase = "learn" | MIRROR produces run-reflection.md; AUDITOR updates calibration-profile.yaml + agent-scores.yaml; VETERAN registers new patterns (grade C minimum); INTERNALIZER updates metrics.json | run-reflection.md, calibration-profile.yaml, agent-scores.yaml, patterns.yaml, metrics.json |

---

## Inter-Phase Data Flow (AC-001-005)

Source: `mental-model.md` Concept Map (lines 190-222).

```
DISCOVER (SCOUT, SYNTHESIZER, GOLDDIGGER, MODELER, PROSPECTOR)
  Produces:  glossary.md, mental-model.md, boundaries.md, assumptions.md,
             unknowns.md, contradictions-and-gaps.md (conditional)
  Consumed by: WHY (SAGE reads all), WHAT (CARTOGRAPHER reads all)
  ↓

WHY (SAGE, CARTOGRAPHER)
  Produces:  amended-assumptions.md, issues.md, quality-gates.md
  Consumed by: WHAT (CARTOGRAPHER uses amended-assumptions.md as spec input)
              ASSESS (GATEKEEPER reads quality-gates.md to confirm WHY passed)
  ↓

WHAT (CARTOGRAPHER, GOLDDIGGER conditional)
  Produces:  spec.md (final, scope-locked)
  Consumed by: ASSESS (GATEKEEPER evaluates spec.md),
               HOW (ARCHITECT designs from spec.md)
  ↓

ASSESS (GATEKEEPER, VALIDATOR)
  Produces:  feasibility.md, estimates.md, prioritization.md
             Decision: PASS / DEFER (loop to WHAT) / KILL (human escalation)
  Consumed by: HOW (entry condition: GATEKEEPER decision = PASS)
  ↓

HOW (ARCHITECT, SENTINEL, INVESTIGATOR conditional)
  Produces:  architecture.md, data-model.md, contracts/, test-architecture.md
  Consumed by: PLAN (ORCHESTRATOR decomposes architecture into tasks)
               BUILD (IMPLEMENTER follows architecture.md)
  ↓

PLAN (ORCHESTRATOR, STRATEGIST, CHECKPOINT)
  Produces:  tasks.md, task-dependencies.json, plan.md
  Consumed by: BUILD (IMPLEMENTER uses tasks.md as work queue)
               PROGRESS-TRACKER reads task-dependencies.json for schedule variance
  ↓

BUILD (11 agents — IMPLEMENTER, CODE-REVIEWER, TEST-GUARDIAN, SPEC-GUARD,
       DEBUGGER, INTEGRATOR, CHANGE-CONTROLLER, VERIFICATION,
       VISUAL-VALIDATOR, PROGRESS-TRACKER, ENGINEERING-MANAGER)
  Produces:  source/ (code), tests/ (≥80% coverage), docs/,
             deployment-ready artifacts, quality gate verdicts
  Consumed by: LEARN (all run artifacts read by MIRROR, AUDITOR, VETERAN, etc.)
  ↓

LEARN (MIRROR, AUDITOR, ADAPTIVE, REALIST, VETERAN, INTERNALIZER, MONITOR, GLOBAL-MEMORY)
  Produces:  run-reflection.md, calibration-profile.yaml (updated),
             agent-scores.yaml, patterns.yaml, metrics.json, evolution-report.md
  Consumed by: Next run's GATEKEEPER (reads calibration-profile.yaml),
               Next run's CARTOGRAPHER (reads marketplace-index.yaml patterns),
               Next run's VETERAN (reads prior evolution-report.md)
```

Cross-cutting: `state.json` is read by all agents on every dispatch (via COMMANDER context pack injection). `reasoning-journal.json` is append-only throughout all phases.

---

## Tier Boundary Enforcement (AC-001-006)

Source: `architecture-gaps.md` Gap 2 (COMMANDER pre-dispatch gate + NEVER rules per tier).

### COMMANDER Pre-Dispatch Gate

Before every agent dispatch, COMMANDER runs `scripts/bash/pre-dispatch-gate.sh`.

```bash
pre-dispatch-gate.sh \
  --run-id "$run_id" \
  --agent "$agent_codename" \
  --phase "$current_phase" \
  --constitution-path ".specify/memory/constitution.md" \
  --state-path ".specify/squad/state.json"
# Exit codes:
# 0 = PASS   (dispatch authorized)
# 1 = DENY   (gate violation; do not dispatch; log in constitution_violations)
# 2 = CONSULT (human review required; halt dispatch; set escalation_question)
# 3 = ERROR  (script failure; fail-open per P-007)
```

**Gate logic**: For each NEVER rule in the agent's prompt file (`agents/${TIER}/${AGENT}.md`), the script checks the pre-dispatch context (agent prompt, dispatch history, state.json) for rule-violation signals. Constitutional principle violations (P-001 through P-019) trigger DENY; non-constitutional guideline violations trigger CONSULT.

### NEVER Rules Per Tier

**CONTROL tier**
- COMMANDER: NEVER do another agent's job directly; NEVER dispatch SAGE with fix/rewrite prompts; NEVER skip phases
- SCOREKEEPER: NEVER modify knowledge base during run (append-only enforced by P-010)
- TRACKER: NEVER override human intent
- STRATEGIST: NEVER propose architectural changes (re-routed to ARCHITECT if attempted)
- CHECKPOINT: NEVER apply spec quality gates (that is SAGE/VALIDATOR's role only)

**EXPLORATION tier**
- SCOUT: NEVER claim false novelty (evidence grade B minimum required)
- SAGE: NEVER produce domain artifacts (feedback-only; SAGE cannot rewrite spec.md)
- SYNTHESIZER: NEVER suppress contradictions (contradiction count in output must match documentation)
- CARTOGRAPHER: NEVER change scope without TRACKER approval
- GOLDDIGGER: NEVER hallucinate artifacts (spot-check of 5 random file references enforced)
- MODELER: NEVER ignore tier boundaries in mental model

**FEASIBILITY tier**
- GATEKEEPER: NEVER gate on subjective criteria (decision must be measurable threshold, not opinion)
- VALIDATOR: NEVER internalize invalid artifacts (artifact must have passed prior quality gates)

**SOLUTION tier**
- ARCHITECT: NEVER implement CA overlays — Goal Stack, ACT-R Buffer, LIDA Broadcast, GWT Workspace, Episodic Memory are GATE_BLOCKED pending U-CA-004 positive result (constitution P-006)
- ORCHESTRATOR: NEVER violate task dependencies (no serial execution of independent tasks, no parallel execution of dependent tasks)
- SENTINEL: NEVER skip architecture validation (must cover all primary design decisions)

**BUILD tier**
- IMPLEMENTER: NEVER implement unreviewed architecture (SENTINEL result must be reviewed pre-BUILD)
- CODE-REVIEWER: NEVER commit code that fails gate
- DEBUGGER: NEVER mask root cause (patch-only fixes flagged for escalation if critical)
- TEST-GUARDIAN: NEVER lower coverage requirements below 80%
- SPEC-GUARD: NEVER allow spec deviation without documented waiver artifact
- INTEGRATOR: NEVER skip merge conflict resolution
- CHANGE-CONTROLLER: NEVER allow breaking changes to public APIs without major version bump
- VERIFICATION: NEVER accept regressions (compare against prior build baseline)
- VISUAL-VALIDATOR: NEVER deploy untested UI (WCAG 2.1 AA minimum required)
- PROGRESS-TRACKER: NEVER hide schedule variance > 20%
- ENGINEERING-MANAGER: NEVER override quality gates (can request human review but cannot override PASS/BLOCK)

**SPECIALISTS tier**
- GUARDIAN: NEVER approve security-sensitive decisions alone (human sign-off required if risk > ACCEPT_WITH_MITIGATIONS, per constitution P-001)
- BENCHMARK: NEVER ignore performance anomalies (root-cause analysis required for all flagged anomalies)
- INVESTIGATOR: NEVER present speculation as proof (SPECULATION claims must be labeled per P-005)
- MAVERICK: NEVER propose changes that violate constitution (P-001 through P-019 checked)
- ADVOCATE: NEVER neglect accessibility (WCAG 2.1 AA required for all user-facing outputs)
- ORACLE: NEVER provide ungrounded domain advice (must cite domain standard or expert source)

**LEARNING tier**
- MIRROR: NEVER misrepresent metrics (measured vs estimated must be distinguished)
- AUDITOR: NEVER modify patterns without approval (promotion path: C→B requires ≥2 runs; C→A requires ≥3 runs + peer review)
- ADAPTIVE: NEVER skip root-cause analysis before recommending adaptation
- REALIST: NEVER project unrealistic timelines (confidence intervals + documented assumptions required)
- VETERAN: NEVER allow pattern decay below threshold (patterns falling to grade D must be flagged for removal or re-validation)
- INTERNALIZER: NEVER lose historical context (traceability from metrics back to original experiments)
- MONITOR: NEVER miss anomalies in state.json that exceed configured thresholds
- GLOBAL-MEMORY: NEVER commit credentials to vault (API keys, tokens, passwords blocked before storing)

### CA Overlay Gate Block (P-006)

Five CA overlay mechanisms are GATE_BLOCKED and must never appear in ARCHITECT output until U-CA-004 experiment returns a positive result:

| Overlay | Status |
|---------|--------|
| Goal Stack | GATE_BLOCKED on U-CA-004 |
| ACT-R Typed Buffer | GATE_BLOCKED on U-CA-004 |
| LIDA Broadcast | GATE_BLOCKED on U-CA-004 |
| GWT Workspace | GATE_BLOCKED on U-CA-004 |
| Episodic Memory | GATE_BLOCKED on U-CA-004 |

Source: `glossary.md` Novel Mechanisms (Token-Gated CA Overlays entry); `architecture-gaps.md` Gap 2 SOLUTION tier ARCHITECT NEVER rule.

---

## Summary

| Dimension | Value | Evidence Source |
|-----------|-------|----------------|
| Total agents | 42 | `find agents/ -name "*.md" \| wc -l` (verified 2026-04-02) |
| Tiers | 7 | glossary.md, boundaries.md |
| Pipeline phases | 8 | DISCOVER → WHY → WHAT → ASSESS → HOW → PLAN → BUILD → LEARN |
| state.json fields | 30 | architecture-gaps.md Gap 1 |
| NEVER rules documented | 36 (across all tiers) | architecture-gaps.md Gap 2 |
| CA overlays GATE_BLOCKED | 5 | glossary.md; architecture-gaps.md Gap 2 (P-006) |
| Pre-dispatch gate | pre-dispatch-gate.sh (exit 0/1/2/3) | architecture-gaps.md Gap 2 |
