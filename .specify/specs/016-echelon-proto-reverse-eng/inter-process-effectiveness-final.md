# Inter-Process Effectiveness — Final Report (REQ-RE-004)

**Date**: 2026-04-02
**Run ID**: squad-1775164062
**Sources**: inter-process-effectiveness.md, architecture-gaps.md (Gaps 3–5), synthesis-report.md §4, knowledge-base/patterns.yaml, squad-config.yml
**Constitution compliance**: P-004 (every claim cites evidence), P-005 (NOVEL-004 speculation labelled)

---

## Section 1: 8-Phase Pipeline Assessment (AC-004-001)

Source: architecture-gaps.md Gap 4.

| Phase | Agent(s) | Entry Condition | Exit Condition | Output Artifacts | Primary Bottleneck |
|-------|----------|-----------------|----------------|------------------|--------------------|
| DISCOVER | SCOUT, SYNTHESIZER, GOLDDIGGER, MODELER, PROSPECTOR | Codebase provided; run_id initialized; phase="discover" in state.json | glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md present and parseable; SYNTHESIZER fuses to contradictions-and-gaps.md | glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md, contradictions-and-gaps.md | SYNTHESIZER entity fusion (O(N) linear on entity count) — MEDIUM |
| WHY | SAGE, CARTOGRAPHER | glossary.md + mental-model.md + boundaries.md + assumptions.md present; no BLOCKED status | SAGE quality gates pass on spec.md: overall ≥ 0.70 OR (structure ≥ 0.70, testability ≥ 0.70, semantic ≥ 0.60, cognitive ≥ 0.60, readability ≥ 0.50, behavioral ≥ 0.50, depth ≥ 0.40) | amended-assumptions.md, issues.md, quality-gates.md | SAGE amendment loops if >3 iterations — HIGH |
| WHAT | CARTOGRAPHER, GOLDDIGGER (conditional) | amended-assumptions.md exists; spec.md passed WHY quality gates; GOLDDIGGER Mode 1 complete | spec.md final; no outstanding NEEDS_CLARIFICATION; TRACKER confirms scope locked | spec.md (final), specifications/ sub-specs (if applicable) | SAGE quality gate iterations (2–3 amendment loops typical) — MEDIUM |
| ASSESS | GATEKEEPER, VALIDATOR | spec.md final + scope locked; no BLOCKED status | GATEKEEPER decision: PASS / DEFER (loop back max 3×) / KILL | feasibility.md, estimates.md, prioritization.md, mvp-scope.md | GATEKEEPER DEFER loops (max 3 per assess.defer_max_iterations) — LOW |
| HOW | ARCHITECT, SENTINEL, INVESTIGATOR (conditional) | GATEKEEPER=PASS + feasibility.md complete; scope locked; no architecture-blocking unknowns | architecture.md + data-model.md + contracts/; SENTINEL validates test-architecture.md | architecture.md, data-model.md, contracts/, test-architecture.md, investigation/ | ARCHITECT task dependency complexity O(N log N) if N > 100 — MEDIUM |
| PLAN | ORCHESTRATOR, STRATEGIST, CHECKPOINT | architecture.md + data-model.md complete; no blocking unknowns; phase="plan" | tasks.md complete dependency graph; CHECKPOINT internalization gate passes; no BLOCKED tasks | tasks.md, task-dependencies.json, plan.md, prioritization.md | Task dependency graph complexity if >200 tasks — LOW |
| BUILD | IMPLEMENTER + 10 supporting agents | tasks.md complete + no BLOCKED tasks; GATEKEEPER implementability check passes (six-point consensus) | All tasks complete in state.json; CODE-REVIEWER, TEST-GUARDIAN, SPEC-GUARD, VERIFICATION approved; no BLOCKED tasks | source/, tests/ (≥80% coverage), docs/, deployment artifacts | CODE-REVIEWER throughput (~1000 LOC/hour realistic) — CRITICAL |
| LEARN | MIRROR, AUDITOR, ADAPTIVE, REALIST, VETERAN, INTERNALIZER, MONITOR, GLOBAL-MEMORY | BUILD complete; all artifacts produced and reviewed; phase="learn" | MIRROR produces run-reflection.md; AUDITOR updates calibration-profile.yaml; VETERAN registers patterns; INTERNALIZER updates metrics.json | run-reflection.md, calibration-profile.yaml, agent-scores.yaml, patterns.yaml, metrics.json | Pattern registration + calibration complexity — LOW |

---

## Section 2: Bottleneck Analysis (AC-004-003 + AC-004-004)

Sources: inter-process-effectiveness.md §§Bottlenecks, architecture-gaps.md Gap 5, Gap 3.

| Phase | Bottleneck | Severity | Mitigation |
|-------|-----------|----------|-----------|
| DISCOVER (SCOUT/SYNTHESIZER) | Large codebase scalability — 100k+ LOC produces 1000+ entities; SYNTHESIZER fusion is O(N) | MEDIUM | GOLDDIGGER Mode 2 defers fine-grained analysis to named domains; SCOUT reads cached analysis.json when golddigger_status="complete_cached" |
| WHY (SAGE) | Amendment loop oscillation — testability fix breaks readability; pathological loops possible | HIGH | Max 3 SAGE iterations configured (convergence.issue_repeat_limit); escalate to human if loop persists; PAT-011: per-requirement failure routing reduces amendment cycles O(failing) vs O(n) |
| WHAT (CARTOGRAPHER/SAGE) | Iterative spec refinement — 2–3 amendment loops typical when DISCOVER output is verbose | MEDIUM | PAT-006: deterministic tooling (Understanding v3.4.0) runs at every iteration, not only heuristic check; row-level SAGE feedback from PAT-011 |
| ASSESS (GATEKEEPER) | DEFER loop scope oscillation — incremental 10% scope reduction each iteration | LOW | assess.defer_max_iterations=3 caps oscillation; TRACKER alignment check before each CARTOGRAPHER re-scope prevents arbitrary reduction |
| HOW (ARCHITECT) | Task dependency complexity O(N log N) — beyond 200 tasks, manual critical path review needed | MEDIUM | ORCHESTRATOR warns if task count >200; recommends task granularity increase; PAT-014 (architecture outpaces data): focus on data generation over feature addition |
| PLAN (ORCHESTRATOR) | Dependency graph with complex parallelism constraints | LOW | ORCHESTRATOR can suggest "dependency simplification" to ARCHITECT if graph too complex |
| BUILD (CODE-REVIEWER) | Code review throughput bottleneck — IMPLEMENTER outpaces reviewer on large codebases | CRITICAL | BANZAI mode max_parallel_agents=5 runs parallel CODE-REVIEWERs; automated linters handle style; complex logic reviewed first (priority queue) |
| LEARN (VETERAN/AUDITOR) | Sparse data — calibration updates unreliable with fewer than N=5 historical runs | MEDIUM | Minimum N=5 historical runs before correction factors become reliable (inter-process-effectiveness.md); VETERAN monitors pattern evidence grades per NEVER rules |

**Concurrent Write Risk (architecture-gaps.md Gap 3)**: In BANZAI parallel mode, COMMANDER and TEST-GUARDIAN may simultaneously write state.json. Severity: HIGH. Current mitigation: state-backup.sh (5 checkpoints). Recommended: state-lock.sh + atomic temp-file rename pattern.

---

## Section 3: Token Efficiency (AC-004-005)

Source: squad-config.yml budget section (lines 72–86).

| Budget Tier | Phases Covered | Allocation |
|-------------|---------------|-----------|
| Tier 1 | DISCOVER + WHAT | 25% |
| Tier 2 | WHY | 20% |
| Tier 3 | HOW + Specialists | 25% |
| Tier 4 | PLAN + ASSESS | 15% |
| Tier 5 | Consensus + Finalize | 10% |
| Reserve | Buffer | 5% |
| BUILD (single agent max) | Per-agent cap | up to 50% |

**BANZAI mode note**: squad-config.yml analysis.token_budget_k: 999999 makes these allocations *guidance*, not hard enforcement. Actual per-phase distribution depends on complexity.

**Baseline measurement status**: AC-003-002 PENDING. 1 of 3 required instrumented runs complete (spec015-verification.md, build-1775162749 CONDITION-002). Evidence grade for per-phase actuals: Grade C (est.).

**Efficiency mechanisms (from inter-process-effectiveness.md)**:
1. Belief annotation system — estimated 10–20% token savings on repeated codebases with mature calibration data (est., Grade C)
2. Contradiction Scanner (SYNTHESIZER phase) — early detection is O(N) rework vs late BUILD detection at O(N²); estimated 20–30% downstream savings if contradictions caught early (est., Grade C)
3. Calibration data injection — estimated 5–10% savings in ASSESS phase via fewer deferral loops (est., Grade C)
4. 40–70% aggregate token reduction for repeated codebases — **SPECULATION per P-005, proof-status-table.md row 5; no empirical grounding; N≥50 runs required to upgrade**

---

## Section 4: Endocrine Feedback Loops (AC-004-006)

Sources: squad-config.yml endocrine section (lines 469–531), scripts/bash/endocrine.sh.

### Hormone Trigger Events

| Event | Trigger | Hormone Delta | Scope |
|-------|---------|--------------|-------|
| `on_gate_pass` | Quality gate passes | dopamine +0.15 | triggering agent |
| `on_gate_fail` | Quality gate fails | dopamine −0.20, cortisol +0.10 | triggering agent |
| `on_rework` | Task sent back for rework | cortisol +0.10 | triggering agent |
| `on_quality_improvement` | Quality metric improves | serotonin +0.10 | system-wide broadcast |
| `propagate_downstream` | Agent completes with high dopamine | dopamine delta = (from.dopamine − 0.5) × 0.30 | downstream agent (30% ratio per hop) |
| `propagate_cortisol_contagion` | Agent cortisol > 0.8 | cortisol +0.05 | downstream agent |

Source: endocrine.sh lines 686–795, confirmed by test-endocrine-phase2.sh P2-06/P2-07/P2-08.

### Decay Rates (per dispatch cycle)

| Hormone | Decay Rate | Interpretation |
|---------|-----------|---------------|
| adrenaline | 0.60× | Fast decay — urgency is brief |
| norepinephrine | 0.70× | Fast decay — intense focus is exhausting |
| cortisol | 0.80× | Moderate — stress should not linger |
| dopamine | 0.85× | Slower — motivation maintained longer |
| oxytocin | 0.92× | Slow — collaboration trust persists |
| serotonin | 0.95× | Slowest — baseline calm persists |

Source: squad-config.yml endocrine.decay (lines 525–531).

### Per-Archetype Baselines [adrenaline, dopamine, cortisol, serotonin, oxytocin, norepinephrine]

| Archetype | Agents | Baseline |
|-----------|--------|----------|
| exploration | SCOUT, SYNTHESIZER, CARTOGRAPHER, MODELER, GOLDDIGGER | [0.3, 0.7, 0.3, 0.6, 0.5, 0.4] |
| validation | SAGE, CHECKPOINT, VALIDATOR | [0.4, 0.3, 0.8, 0.4, 0.4, 0.7] |
| feasibility | GATEKEEPER | [0.4, 0.5, 0.7, 0.6, 0.5, 0.5] |
| solution | ARCHITECT, ORCHESTRATOR, SENTINEL | [0.4, 0.6, 0.4, 0.7, 0.5, 0.5] |
| build | IMPLEMENTER, CODE-REVIEWER, TEST-GUARDIAN, DEBUGGER + 7 others | [0.7, 0.5, 0.5, 0.4, 0.7, 0.9] |
| innovation | MAVERICK, INVESTIGATOR, ADVOCATE | [0.2, 0.8, 0.2, 0.6, 0.5, 0.3] |
| learning | MIRROR, ADAPTIVE, AUDITOR, REALIST, VETERAN, GLOBAL-MEMORY | [0.2, 0.6, 0.4, 0.8, 0.7, 0.3] |
| control | COMMANDER, SCOREKEEPER, TRACKER, STRATEGIST, PROSPECTOR | [0.5, 0.5, 0.5, 0.5, 0.5, 0.5] |

**Efficacy note**: Endocrine system is fully implemented (1047-line endocrine.sh). Whether hormones measurably improve output quality is unknown (U-005, assumption A-005 UNVALIDATED). Effect size could be 0–20%. This is Grade B evidence on implementation; Grade D on efficacy.

---

## Section 5: Quality Gate Effectiveness (AC-004-007)

Source: inter-process-effectiveness.md §§Quality Gate Effectiveness, synthesis-report.md §2.

| Gate | Agent | Pass Rate | Evidence |
|------|-------|-----------|---------|
| WHY1/WHY2 (spec quality) | SAGE | ~70% first pass; ~90% after amendments | (est., Grade B evidence — synthesis-report.md §2 confirms consistency across documents) |
| GATEKEEPER (feasibility) | GATEKEEPER | ~80% PROCEED; ~5–10% KILL; remainder DEFER | (est., Grade B evidence — inter-process-effectiveness.md lines 103–110) |
| CODE-REVIEWER (build) | CODE-REVIEWER | ~15% block rate | (est., Grade B evidence — inter-process-effectiveness.md lines 115–122) |
| TEST-GUARDIAN (coverage ≥80%) | TEST-GUARDIAN | ~20% block rate | (est., Grade B evidence) |
| SPEC-GUARD (spec compliance) | SPEC-GUARD | ~10% block rate | (est., Grade B evidence) |
| VERIFICATION (regression) | VERIFICATION | ~5% block rate | (est., Grade B evidence) |

All estimates marked **(est., Grade B evidence)** per P-004 and IS-003. No empirical calibration against human expert judgment has been run (U-003).

**Overall gate effectiveness**: HIGH for SAGE (prevents 30% of first-pass specs from advancing); HIGH for GATEKEEPER (prevents 5–10% of projects from wasting BUILD resources). BUILD gates create redundant validation — MEDIUM-HIGH combined effectiveness.

---

## Section 6: Pattern Registry Evidence (AC-004-008)

Source: knowledge-base/patterns.yaml. PAT-001 through PAT-006 listed below (spec task requirement); PAT-007 through PAT-016 also registered.

| ID | Name | Confidence | Evidence Grade | Pipeline Behavior Validated |
|----|------|-----------|---------------|----------------------------|
| PAT-001 | Critical-Issue Recovery via Conditional AC Rewrites | 0.84 | C | WHY → CARTOGRAPHER amendment removes blockers in single pass without architecture churn |
| PAT-002 | Early Synthesis Prevents Contradiction Drift | 0.79 | C | Running SYNTHESIZER before assumption challenge exposes cross-document contradictions; reduces WHAT and HOW rework |
| PAT-003 | Constitution-Anchored ADRs Reduce Governance Rework | 0.82 | C | ADRs mapped to constitution principles pass final governance checks with fewer follow-up corrections |
| PAT-004 | Full AC Coverage Mapping De-risks Consensus | 0.80 | C | SENTINEL mapping of all ACs to test IDs improves implementability clarity; PLAN2 resolves most consensus issues without returning to WHAT |
| PAT-005 | Dual-Pass Estimation with Complexity Uplift | 0.86 | C | ASSESS baseline + ASSESS2 complexity uplift captures hidden integration cost; produces execution-ready planning numbers |
| PAT-006 | Deterministic Scoring Correction | 0.88 | B | When heuristic review passes but deterministic tooling (Understanding v3.4.0) fails, heuristic was overconfident by 15–29% on structure/testability; always run deterministic tooling |

All six patterns are Grade C (PAT-001–PAT-005) or Grade B (PAT-006), scope: local_only (single project fingerprint). Promotion to Grade B requires ≥2 runs; Grade A requires ≥3 runs + peer review (AUDITOR NEVER rule per constitution P-010/P-011).

---

## Section 7: Critical Path (AC-004-009)

Source: architecture-gaps.md Gap 5.

**Critical path** (longest sequential chain):
```
T-001:DISCOVER (15–20 min) → T-002:WHY (10–15 min) → T-003:WHAT (8–12 min)
  → T-004:ASSESS (5–8 min) → T-005:HOW (10–15 min) → T-006:PLAN (5–8 min)
  → T-007:BUILD (30–45 min) → [T-008:LEARN parallel, non-blocking]
```

**BUILD phase dominates**: 37–42% of total pipeline time (est.). Source: architecture-gaps.md Gap 5 — critical path: 83–123 min serial; 60–95 min with parallelism (DISCOVER: −5–10 min saved; BUILD: −15–20 min saved via 5 parallel agents).

| Phase | Token % | Wall Clock (est.) | Parallelism |
|-------|---------|-----------------|-------------|
| DISCOVER | 25% | 15–20 min | 4 agents |
| WHY | 20% | 10–15 min | 2 agents |
| WHAT | 15% | 8–12 min | 2 agents |
| ASSESS | 10% | 5–8 min | 1–2 agents |
| HOW | 15% | 10–15 min | 3 agents |
| PLAN | 8% | 5–8 min | 2 agents |
| BUILD | 40–50% (no BANZAI cap) | 30–45 min | 5 agents |
| LEARN | 10% | 5–10 min | 8 agents (post-BUILD, non-blocking) |

All timings are estimates (est., Grade C evidence) — no instrumented measurement run (AC-003-002 PENDING).

---

## Section 8: state.json Corruption Risks (AC-004-010)

Source: architecture-gaps.md Gap 3.

| # | Risk | Severity | Current Mitigation | Status |
|---|------|----------|-------------------|--------|
| 1 | Concurrent write conflicts — two agents write state.json simultaneously in BANZAI parallel mode | MEDIUM | state-backup.sh (5 checkpoints); no write lock exists | OPEN — kb-lock.sh protects KB only; state-lock.sh not yet implemented |
| 2 | Partial writes — process crashes mid-write, leaving truncated JSON | HIGH | state-backup.sh backup-before-write; append-only reasoning-journal.json as source of truth | PARTIAL — atomic temp-file pattern (temp → rename) recommended but not fully confirmed in code |
| 3 | Schema drift — new agents add state.json fields without updating readers | LOW | Documented in architecture-gaps.md Gap 1 (30-field enumeration); no JSON Schema validation in code | OPEN — explicit state-schema.json + COMMANDER validation proposed but not implemented |
| 4 | Stale reads — agent reads state.json before COMMANDER updates it (parallel mode) | MEDIUM | COMMANDER reads state before each dispatch (inter-process-effectiveness.md §state.json) | PARTIAL — no version stamping or serialized read API; token budget via context pack injection proposed |
| 5 | Lost updates — write reordering loses one of two sequential updates | LOW | COMMANDER bundles all updates into single jq call; append-only reasoning-journal.json provides audit trail | ADDRESSED — single atomic write + fsync pattern documented |

**Implementation priority**: Concurrent writes (HIGH) and partial write crash safety (MEDIUM) are highest priority. Schema drift and stale reads are lower priority for single-machine deployments.

---

*All un-measured values are marked (est.) and carry Grade B or Grade C evidence per P-004. NOVEL-004 token reduction speculation is not repeated here per P-005 — see Section 3.*
