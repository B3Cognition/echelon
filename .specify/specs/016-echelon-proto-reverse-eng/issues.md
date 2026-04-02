# WHY1 Issues Report

**Run ID**: squad-1775164062  
**Phase**: WHY1 (SAGE — Assumption Challenge & Validation)  
**Date**: 2026-04-02  
**Validator**: SAGE Agent (Assumption Adversary)

---

## Executive Summary

Staging artifacts have been validated for internal consistency, coverage, and evidence quality. **One CRITICAL issue, three HIGH issues, and four MEDIUM issues identified.** Overall, discovery phase has strong structure but significant gaps in validation and proof. No factual contradictions between documents, but multiple assumptions are unvalidated and blocking unknowns threaten production readiness.

---

## Issue Classification

| ID | Severity | Source Artifact | Type | Description |
|----|----|----|----|---|
| **IS-001** | CRITICAL | novelty-catalogue.md, synthesis-report.md | Implementation Gap | constitution.md artifact missing; governance gate (NOVEL-006) cannot be tested |
| **IS-002** | HIGH | assumptions.md (A-001, A-004, A-005) | Unvalidated Foundation | Three critical assumptions (Opus capability, unlimited tokens, endocrine efficacy) lack empirical validation and are blocking unknowns |
| **IS-003** | HIGH | inter-process-effectiveness.md, synthesis-report.md | Evidence Quality Gap | Quality gate effectiveness claims (SAGE 70%+ pass rate, 90% amendment success) are labeled "est." (estimate) not "measured"; confidence uncertain |
| **IS-004** | HIGH | unknowns.md (U-007, U-008) | Blocking Unknowns | Two experiments (U-CA-004, NS-003 prototype) must complete before production; these are not optional or deferred |
| **IS-005** | HIGH | novelty-catalogue.md, synthesis-report.md | Novelty Scope Inflation | NOVEL-004 (predictive coding) and NOVEL-008 (calibration injection) are presented as novel but are incremental applications of existing techniques; limited novelty defensibility |
| **IS-006** | MEDIUM | assumptions.md (A-002, A-003) | Design Choice Not Validated | 42-agent count and 8-phase sequence are presented as "optimal" but lack comparative validation; ablation studies missing |
| **IS-007** | MEDIUM | boundaries.md, glossary.md | Tiering Model Ambiguity | "No cross-tier leakage" rule stated, but consequences of violations are unclear (escalate? block? warn?); enforcement mechanism undefined |
| **IS-008** | MEDIUM | unknowns.md (Area 5) | Specification Explosion Risk | Requirements proliferation (1000+ for 100k LOC) may cause quality gate bottleneck; SAGE gate throughput vs requirement count unknown |
| **IS-009** | LOW | synthesis-report.md | Patent Claim Overreach | "40-70% token reduction" (NOVEL-004 row 5) claimed as novelty but explicitly marked SPECULATION with "zero empirical grounding"; should not be filed as patent claim |

---

## CRITICAL Issues (CRITICAL)

### IS-001: constitution.md Artifact Missing — Governance Implementation Incomplete

**Severity**: CRITICAL  
**Source**: novelty-catalogue.md (NOVEL-006); synthesis-report.md (Section 2, reasoning journal entry line 12); agents/control/commander.md (lines 152–159)  
**Finding**: 
- NOVEL-006 claims "Pre-dispatch constitutional governance is novel for LLM orchestration"
- glossary.md (line 116) states: "Enforced at dispatch time; blocks take precedence over agent autonomy"
- agents/control/commander.md (line 159) instructs: "Enter BLOCKED state in state.json. Wait for `/speckit.echelon.resume <answer>`."
- **BUT**: constitution.md does not exist in the codebase. Verified via `ls /Users/ladislavbihari/myWork/competition/echelon_proto/constitution*` — no matches.
- boundaries.md (lines 87–91) references constitution as "hard dependency" for governance enforcement
- synthesis-report.md (lines 50–52) identifies this as "Minor gap (not contradiction): Constitution enforcement is designed but constitution.md artifact missing from codebase."

**Impact**: 
- NOVEL-006 (Constitutional Governance) cannot be tested or validated without the constitution document
- Pre-dispatch gate logic is documented in prompts but cannot be enforced against missing rules
- Assumption A-012 ("constitution.md exists and is machine-readable") is violated

**Required Action**: 
1. Create constitution.md with explicit governance principles (immutable rules, escalation tiers, authority hierarchy)
2. Validate COMMANDER pre-dispatch gate reads and enforces constitution correctly
3. Test with N=20+ intentional governance violations; target ≥80% pre-flight catch rate
4. Re-validate NOVEL-006 claim after artifact is in place

**Evidence Grade**: This is not an assumption but a missing implementation artifact.

---

## HIGH Issues (HIGH)

### IS-002: Three Blocking Assumptions Lack Empirical Validation

**Severity**: HIGH  
**Source**: assumptions.md (A-001, A-004, A-005); unknowns.md (U-005)  
**Finding**:

1. **A-001 (Claude Opus Model Capability)**  
   - Statement: "Opus provides sufficient reasoning capability for each agent's task"
   - Status: UNVALIDATED (per assumptions.md line 10)
   - Risk: Sonnet-class models may degrade quality; "Quality degradation unpredictable"
   - Validation method documented (line 9) but not executed
   - Blocker: BANZAI config hardcodes Opus; all tier agents depend on this assumption

2. **A-004 (Unlimited Token Budget)**  
   - Statement: "Unlimited tokens improve quality without degrading latency"
   - Status: UNVALIDATED (per assumptions.md line 31)
   - Risk: "Unlimited budget may cause information overload: downstream agents process 10k tokens context, become unfocused. Token cost unsustainable."
   - Validation: "Measurement not done" (line 31)
   - Current state: BANZAI mode enabled with unlimited token budget (squad-config.yml token_budget_k: 999999)
   - Unknown: True cost per run, quality plateau point

3. **A-005 (Endocrine Hormones Improve Quality)**  
   - Statement: "Hormone modulation improves agent outputs on average"
   - Status: UNVALIDATED (per assumptions.md line 38, unknowns.md U-005)
   - Risk: "Hormones may add noise without signal"
   - Validation method: Run 10 tasks, BANZAI with hormones vs frozen baseline; measure ≥5% improvement on ≥2 metrics (line 37)
   - Current state: Hormones are active in BANZAI mode but effectiveness unknown
   - Blocking unknown: U-005 "Does the Endocrine System measurably improve quality?" (unknowns.md line 33)

**Impact**:  
All three assumptions underpin core BANZAI mode design. If any is false:
- A-001 failure: Entire system degrades (Sonnet lacks nuance for ARCHITECT, GATEKEEPER reasoning)
- A-004 failure: Cost model breaks ($500/run instead of $50); production economics fail
- A-005 failure: System complexity increases without quality gain (wasted implementation effort)

**Status of Validation Efforts**: All three explicitly marked "Unvalidated" with documented test plans but no execution record.

**Required Action**: 
- U-005 (endocrine): Run N=10 controlled experiments before finalizing BANZAI mode as baseline
- A-004: Measure token cost on representative codebases (N=5 diverse domains) before claiming unlimited budget is viable
- A-001: Run Understanding metric comparison (Opus vs Sonnet on same tasks) to establish quality delta

---

### IS-003: Quality Gate Effectiveness Claims Lack Empirical Grounding

**Severity**: HIGH  
**Source**: inter-process-effectiveness.md (lines 89–101, 103–111); synthesis-report.md (Section 4, lines 261–267)  
**Finding**:

The report claims:
- SAGE quality gates "Pass rate on first run: ~70% (estimated, per inter-process-effectiveness.md line 91)"
- "Amendment loop success: ~90% pass after 1–2 re-runs (line 101)"
- GATEKEEPER "Technical feasibility: 80%+ FEASIBLE or FEASIBLE_WITH_RISKS (line 105)"

**Key phrase**: All labeled "(est.)" (estimate) not "(measured)" or "(observed)"

Verification:
- inter-process-effectiveness.md line 91: "~70% (first pass)" — tilde indicates estimation
- Line 101: "amendment loop (can loop up to 2–3 times before escalation per squad-config.yml assess.defer_max_iterations=3, but this is for ASSESS deferral; spec failures loop in CARTOGRAPHER until pass)" — no measurement provided
- Assumption A-009 (line 69): "SAGE's Understanding Metrics Accurately Measure Spec Quality" — explicitly marked UNVALIDATED; "human calibration unknown"

**Evidence Quality**: 
- Claims are based on design analysis (O(N) time complexity estimates) not empirical runs
- No run data from squad-run-001 or prior runs shown
- Pattern confidence (PAT-001 through PAT-006, lines 249–256) are 0.79–0.88 but these measure "pipeline stage effectiveness," not gate pass rates

**Impact**: 
- Quality gate effectiveness is claimed as HIGH overall (synthesis-report.md line 279) but supported by estimates, not measurements
- SAGE gate failures could be higher or lower than 30%; amendment loop iterations could exceed design expectations
- Unknown: Actual gate pass rates, actual amendment loop count distribution, actual time per gate evaluation

**Required Action**:
1. Instrument squad run with gate pass/fail tracking: for each spec, record (structure_score, testability_score, ..., gate_result)
2. Benchmark SAGE Understanding metrics against human expert judgment (N=20 specs, Cohen's kappa ≥0.60 success criterion)
3. Track amendment loop iterations: N=50+ specs, plot iteration count distribution
4. Re-validate gate effectiveness claims with measured data

---

### IS-004: Two Blocking Unknowns Unresolved — Production Readiness Threatened

**Severity**: HIGH  
**Source**: unknowns.md (U-007, U-008); synthesis-report.md (lines 149–152, 338–342); proof-status-table.md (rows 6–10)  
**Finding**:

**U-007 (CA Overlay Gate U-CA-004)**: 
- Five CA mechanisms (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Workspace, Episodic Memory) are blocked pending U-CA-004 experiment
- proof-status-table.md rows 6–10 all carry: "GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001)"
- unknowns.md line 51 (U-007): "Must-resolve-before-ARCHITECT (blocks architecture decisions)"
- Status: U-CA-004 "not yet run" (unknowns.md line 52)
- Implication: Five rows of proof-status-table cannot be validated until gate resolves

**U-008 (NS-003 Component Transfer)**:
- NS-003 is the primary architecture (Generator-Critic + AGM belief revision for artifact validation)
- NL2GenSym achieves 86%+ schema compliance on Soar rule generation (different task)
- Kumiho achieves 93.3% contradiction detection on LoCoMo-Plus (different task)
- Transfer assumption A-015 (assumptions.md, line 115–120): "NL2GenSym's 86%+ schema compliance ... will transfer to Echelon"
- Status: Transfer "not yet measured" (A-015, line 120); prototype experiment REQ-015-006 required
- unknowns.md line 56: "Priority: Must-resolve-before-HOW (NS-003 is primary architecture; transfer failure invalidates design)"
- Risk: If transfer fails (60%+ compliance instead of 86%+), primary architecture degrades

**Evidence**:
- synthesis-report.md lines 338–342 explicitly labels both U-CA-004 and U-008 as "CRITICAL BLOCKING UNKNOWNS (Must Resolve Before Production)"
- unknowns.md line 129: "Blocking Unknowns: U-007 and U-008 must be resolved before Echelon can be considered production-ready"
- proof-status-table.md rows 1–2: NS-003 components marked "PARTIAL (Echelon-specific proof pending REQ-015-006)"

**Impact**:  
Echelon is currently **NOT production-ready**. Five high-value CA mechanisms cannot be deployed. Primary architecture (NS-003) has unvalidated task transfer.

**Status**: Both experiments documented in spec 015 but not executed. No timeline provided.

**Required Action**: These are not assumptions but BLOCKING UNKNOWNS. Cannot proceed to BUILD phase without resolution.

---

### IS-005: Novelty Claims IS-005: Questionable Defensibility on Two Mechanisms

**Severity**: HIGH  
**Source**: novelty-catalogue.md (NOVEL-004, NOVEL-008); synthesis-report.md (Section 3, Priority 3)  
**Finding**:

**NOVEL-004 (Predictive Coding Inter-Agent Protocol)**:
- Claim: "Upstream predictions gate downstream LLM calls to reduce token cost"
- Novelty assessment (synthesis-report.md, Section 3, lines 222–229): 
  - "Structural analog to Speculative Decoding"
  - "Patent claim is obvious in retrospect once Speculative Decoding is understood"
  - Evidence grade: C (no direct measurement for agent-level prediction)
  - Defensibility: **MEDIUM. Generalization of published Speculative Decoding. Patent claim is obvious in retrospect.**
- Status: NOT PROVEN (proof-status-table.md row 4); "no direct measurement for agent-level prediction"
- Additional problem (proof-status-table.md row 5): "40-70% token reduction" claim marked SPECULATION with "zero empirical grounding"
- Recommendation (synthesis-report.md, Priority 3, line 226): "Patent claim is obvious in retrospect once Speculative Decoding is understood. **Weak defensibility.**"

**NOVEL-008 (Calibration Data Injection)**:
- Claim: "Per-agent historical failure mode priming improves estimate accuracy"
- Novelty assessment (synthesis-report.md, Priority 2, lines 211–216):
  - "Calibration is known technique; context injection application to LLM agents is novel"
  - Evidence grade: B
  - Defensibility: **MEDIUM. Calibration concept is known; fine-tuning could achieve similar results.**
- Status: IMPLEMENTED (gatekeeper.md), but effect size unvalidated
- Unknown U-004: "What is the calibration data convergence rate for new domains?" (unknowns.md, line 26)

**Patent Concern**:
- NOVEL-004 is essentially "Speculative Decoding applied to agents" — generalization of prior art
- NOVEL-008 is essentially "calibration tuning via context injection" — application of known technique
- Neither claim has strong defensibility compared to NS-003 (Generator-Critic + AGM), which has HIGH defensibility and novelty confirmed via systematic search (synthesis-report.md, lines 88–90)

**Impact**: 
- Patent filing strategy is over-broad if NOVEL-004 and NOVEL-008 are included
- Resources may be wasted on patenting low-defensibility claims
- Only NS-003 should be filed immediately (HIGH defensibility, "novelty confirmed, component proofs exist")

**Required Action**: 
1. Separate novelty claims by defensibility level
2. File only HIGH-defensibility claims (NS-003, Endocrine, Constitutional Gate)
3. Defer NOVEL-004 and NOVEL-008 until effectiveness is proven (then reconsider defensibility)

---

## MEDIUM Issues (MEDIUM)

### IS-006: Agent Count and Phase Sequence Are Design Choices, Not Optimized

**Severity**: MEDIUM  
**Source**: assumptions.md (A-002, A-003); unknowns.md (U-001)  
**Finding**:

**A-002 (42 Agents Is Optimal)**:
- Statement: "Seven tiers with 3–11 agents per tier provides right balance between specialization and coordination overhead"
- Basis: "Design experience; no formal optimization" (assumptions.md line 14)
- Risk: "Over-specialization (too many tiers) causes coordination bottlenecks. Under-specialization (fewer agents) causes role confusion. Unknown where optimum is." (line 15)
- Status: UNVALIDATED (line 17)
- Validation method: Ablation study documented (line 16) but not executed

**A-003 (Phase Sequencing Is Optimal)**:
- Statement: "The 8-phase sequence (DISCOVER → LEARN) cannot be reordered"
- Basis: "Logical dependencies + empirical heuristic from software engineering" (line 21)
- Risk: "Alternative orderings (e.g., ASSESS before HOW, exploratory prototyping before requirements) might improve time-to-delivery or quality" (lines 22–23)
- Status: UNVALIDATED (line 24); "logical foundation strong, empirical test pending"
- Validation method: Run same spec with alternate phase sequences; measure quality and time (line 23)

**Verification**: Glossary.md (line 3) claims "42 Agents across 7 Tiers" and agent count verified as exactly 42. But optimality is not validated.

**Impact**: 
- If 42 agents is overspecialization, system is unnecessarily complex; 5–6 tiers might suffice
- If 8-phase sequence is not optimal, alternative orderings might deliver faster or better quality
- Unknown: Coordination overhead O(N²) impact, quality vs agent count curve, phase sequence alternatives

**Gap**: These are design choices presented as "optimal" without comparative data.

**Required Action**:
1. Run ablation study: remove agents from one tier (e.g., 3 specialists instead of 6); measure quality delta
2. If quality stays same, reduce agent count
3. Test alternate phase sequences (at minimum: parallel DISCOVER+ASSESS, WHY→WHAT→HOW without separate ASSESS phase); measure quality and time
4. Document comparative findings; update assumptions if alternatives are comparable or better

---

### IS-007: Tiering Model Violation Consequences Undefined

**Severity**: MEDIUM  
**Source**: boundaries.md (lines 169–170); glossary.md (lines 119–120); mental-model.md (lines 74–81)  
**Finding**:

**Stated Rule** (boundaries.md, lines 158–169):
- "No cross-tier leakage" — "Each tier has a single, clear responsibility"
- "Violation: ARCHITECT writing requirements (WHAT's job) → escalation, possible run failure"

**Problem**: 
- Stated consequence is vague: "escalation, possible run failure"
- Not defined: Under what conditions is escalation automatic vs. warning only?
- glossary.md (line 120): "7-Tier Cognitive Specialization" enforces "NEVER rules in each agent prompt" and "COMMANDER validates tier boundaries"
- But: No enforcement mechanism specified (exception type? log entry? auto-reject?)
- agents/control/commander.md documents conflict resolution but does not mention tier boundary enforcement

**Gap**: If ARCHITECT violates rule, what happens?
- Option A: COMMANDER logs warning, continues
- Option B: COMMANDER rejects dispatch, re-routes to SAGE for amendment
- Option C: COMMANDER escalates to human (CONSULT tier)
- Unknown which is correct

**Impact**: 
- Tier enforcement is aspirational but enforcement mechanism is unclear
- Agents may violate tier boundaries with unclear consequences
- Unknown: False positive rate (legitimate cross-tier collaboration flagged as violation), false negative rate (violations not caught)

**Required Action**:
1. Define explicit tier boundary violation protocol: what triggers escalation vs. warning vs. re-route?
2. Implement COMMANDER tier boundary check with documented decision logic
3. Validate on intentional violations (N=20+); measure false positive and false negative rates
4. Document in COMMANDER prompt and design

---

### IS-008: Specification Explosion Risk at Large Scale

**Severity**: MEDIUM  
**Source**: unknowns.md (Area 5, lines 95–97); inter-process-effectiveness.md (lines 128–131)  
**Finding**:

**Stated Risk** (unknowns.md lines 95–97):
- "For 100k+ LOC, requirements can multiply to 1000+. SAGE quality gate time unknown; could scale super-linearly."
- "Impact: Large projects may hit SAGE gate bottleneck"
- Validation: "Measurement needed on representative codebases (N=5, varied sizes)"

**Evidence**:
- inter-process-effectiveness.md line 130: "SCOUT output scales linearly with codebase size (LOC). For 100k+ LOC, discovery produces 1000+ entities, 100+ boundaries, 50+ unknowns."
- Line 131: "Current limit: Estimated to scale fine up to 500k LOC (no measured limit). Beyond that, token consumption explodes."
- Line 136: "SAGE feedback is specific per requirement (row-level failures in issue.md); CARTOGRAPHER focuses amendments, reducing re-work"

**Gap**:
- Claim: "scales fine up to 500k LOC" — based on estimation, not measurement
- Unknown: Actual SAGE gate latency, actual amendment loop count, actual token cost
- Risk: "Super-linear scaling" possible; specification explosion could make large projects infeasible

**Current Status**: Not measured; marked as "Can-defer (not blocking, but important for production)" (unknowns.md line 71)

**Impact**: 
- Production readiness for large codebases unknown
- Unknown scaling limits; could hit bottleneck at 100k–500k LOC

**Required Action**:
1. Measure SAGE gate throughput on representative codebases: small (5k LOC), medium (50k LOC), large (100k+ LOC)
2. Track: requirement count, gate evaluation time, amendment loop iterations
3. Plot: execution time vs requirement count; verify linear (not super-linear) relationship
4. Establish documented limit: max LOC or requirements per run

---

### IS-009: Patent Claim (40-70% Token Reduction) Is Speculation

**Severity**: LOW  
**Source**: novelty-catalogue.md (NOVEL-004); proof-status-table.md (row 5); synthesis-report.md (Priority 4, lines 234–239)  
**Finding**:

**Claim** (novelty-catalogue.md, inter-process-effectiveness.md line 175): 
- "40-70% token reduction on repeated codebases" (from activated belief system and calibration data)

**Evidence Status**:
- proof-status-table.md row 5: "SPECULATION: no empirical grounding"
- Synthesis-report.md line 236: "Evidence Grade: NONE (proof-status-table row 5: 'SPECULATION: no empirical grounding')"
- Line 238: "Quantitative range (40-70%) is pure speculation"
- Recommendation (line 239): "DO NOT CLAIM in patent. This requires N=50+ prototype runs with instrumented token counters to validate. Only file after measurement."

**Issue**: 
- This claim is being tracked as a novelty mechanism (NOVEL-004) but has zero empirical grounding
- Mechanism-level estimate (lines 168–175 of inter-process-effectiveness.md): "40–70% token reduction on repeated codebases (per NOVEL-004's claimed benefit; currently SPECULATION per proof-status-table.md row 5)"
- This is inflated marketing language, not a validated claim

**Impact**: 
- Patent filing on this claim would be rejected or invalidated if challenged
- Misleads stakeholders about system capabilities
- Resources wasted on patenting unproven claims

**Required Action**:
1. Do not include "40-70% token reduction" in patent filings until N=50+ runs with instrumented token counters validate it
2. Reframe claim as "hypothesized 40-70% reduction pending validation"
3. Deprioritize NOVEL-004 patent filing until effectiveness is proven

---

## Summary by Severity

| Severity | Count | Issues |
|----------|-------|--------|
| CRITICAL | 1 | IS-001 (constitution.md missing) |
| HIGH | 4 | IS-002 (A-001, A-004, A-005 unvalidated), IS-003 (quality gate claims unproven), IS-004 (U-CA-004, U-008 blocking), IS-005 (NOVEL-004, NOVEL-008 weak defensibility) |
| MEDIUM | 4 | IS-006 (42 agents not optimized), IS-007 (tier boundary enforcement undefined), IS-008 (spec explosion risk), IS-009 (40-70% reduction unproven) |

---

## Recommendations

### BLOCKING (Resolve Before CARTOGRAPHER Dispatch)

1. **IS-001**: Create constitution.md artifact; validate pre-dispatch gate
2. **IS-004**: Execute U-CA-004 and NS-003 prototype experiments (spec 015 requirements); these are prerequisites for production readiness

### HIGH PRIORITY (Validate Before ASSESS Phase)

3. **IS-002**: Run A-005 experiment (endocrine efficacy); measure A-004 token cost; benchmark A-001 Opus vs Sonnet
4. **IS-003**: Instrument runs to measure actual gate pass rates, amendment loop distributions; benchmark SAGE against human experts

### MEDIUM PRIORITY (Improve Before BUILD Phase)

5. **IS-006**: Run ablation study on agent count; test alternate phase sequences
6. **IS-007**: Document tier boundary enforcement protocol; validate on intentional violations
7. **IS-008**: Measure SAGE gate throughput on large codebases; establish documented scaling limits

### LOW PRIORITY (Do Not File Patents Yet)

8. **IS-009**: Remove "40-70% token reduction" from patent claims until N=50+ runs validate

---

## Validation Completeness Assessment

**Discovery Artifacts Quality**: GOOD
- All major concepts defined (glossary.md is comprehensive)
- Mental model shows strong understanding of system architecture
- Boundaries clearly articulated

**Assumption Validation**: POOR  
- 15 assumptions documented; 10+ marked UNVALIDATED
- No empirical measurements for core claims (Opus capability, token budget, hormone efficacy, gate effectiveness)
- Design choices (42 agents, 8 phases) presented as optimal without comparative data

**Evidence Grading**: INCONSISTENT
- Novelty claims well-documented with systematic search (NS-003)
- Effectiveness claims largely speculative or estimated
- No distinction between "design estimates" and "measured performance"

**Blocking Unknowns**: ACKNOWLEDGED BUT UNRESOLVED
- U-CA-004, U-008, U-003 clearly documented as blocking
- No timeline provided for resolution
- Production readiness explicitly conditioned on these experiments

---

## Final Assessment

**Overall WHY1 Quality**: 7.2/10
- Strengths: Clear architecture, well-documented assumptions, good cross-reference consistency
- Weaknesses: Too many unvalidated assumptions, blocking unknowns unresolved, effectiveness claims lack empirical support
- Recommendation: PROCEED TO CARTOGRAPHER with IS-001 and IS-004 as BLOCKING prerequisites; address IS-002 and IS-003 before ASSESS phase

