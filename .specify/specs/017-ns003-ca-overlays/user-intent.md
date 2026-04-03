# User Intent — Spec 017

**Produced by**: SYNTHESIZER acting as TRACKER (BANZAI mode inline) | **Date**: 2026-04-03

---

## Stated Goals

### Goal 1: NS-003 Prototype
Build the self-correcting artifact store prototype:
- **NS-003-A (Generator-Critic):** Write-time schema compliance enforcement for all agent artifact outputs using a deterministic Python JSON Schema validator. Maximum 2 retries per invocation. ESCALATE after 2 failures.
- **NS-003-B (AGM Belief Graph):** Write-time belief consistency enforcement using a persistent BeliefNode graph with ConflictSignal emission and AGM K*2 revision on conflict. Pre-commit architecture (before artifact file write, not post-hoc).
- **Experiment parameters:** N=30 agent invocations (5 per agent type: DISCOVER, WHY, WHAT, ASSESS, HOW, PLAN). Test codebase: Echelon extension at `/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/`.

### Goal 2: U-CA-004 Experiment
Run the CA overlay gate experiment to determine whether cognitive architecture overlays improve artifact quality:
- **Three conditions:** A (naive baseline), B (expert prompts), C (ACT-R Typed Buffer)
- **N=20 runs per condition** (60 total). Staged: N=10 first, expand to N=20 on INCONCLUSIVE.
- **Verdict:** POSITIVE / NEGATIVE / INCONCLUSIVE based on three criteria simultaneously: (1) Mann-Whitney U p < 0.05 on AQS(C) vs AQS(B), (2) ΔAQS ≥ 0.10, (3) ΔSVR ≥ 15% relative reduction.

### Goal 3: CA Overlay Implementations (conditional on U-CA-004 POSITIVE)
If U-CA-004 resolves POSITIVE for ACT-R Typed Buffer:
- Implement ACT-R Typed Buffer as production CA overlay in COMMANDER dispatch
- Proceed sequentially to test Goal Stack overlay
- Continue through 5 overlays: ACT-R, Goal Stack, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory
- Early termination on any NEGATIVE result

---

## Explicit Constraints

1. **No human in loop** — resolve all decisions autonomously. BANZAI mode confirmed.
2. **Resolve autonomously** — instruction from human override: "resolve U-CA-004, unblock CA overlays, no human in loop."
3. **BANZAI mode** — confirmed in state.json (`banzai_mode: true`). Squad operates without escalation to human except for BLOCKED conditions.
4. **P-006 override confirmed** — `state.json` human_override.p006_ca_overlays = "AUTHORIZED", authorized_by = "human", message_date = "2026-04-03".
5. **API-only constraint (ADR-003)** — CA overlays must be prompt-level modifications only. No model fine-tuning, weight changes, or learned parameters. Local computation (TF-IDF, BM25) permitted for preprocessing.
6. **Pre-registration principle** — NS-003 experiment verdict must use pre-registered criteria from `ns003-experiment-design.md` Section 6 without post-hoc adjustment.
7. **LLM version lock** — all invocations within a single experiment batch must use the same model API string.

---

## Human Authorization

- **P-006 authorization date:** 2026-04-03
- **Authorization scope:** Proceed with NS-003 prototype build AND U-CA-004 experiment infrastructure AND conditional CA overlay implementation artifacts.
- **Authorization does NOT cover:** Deploying CA overlays to production Echelon runs before U-CA-004 POSITIVE verdict. The experimental gate is still in effect.
- **BANZAI mode authorization:** Human explicitly instructed "no human in loop." Squad resolves all decisions within constitutional bounds without escalation.

---

## Success Criteria

### NS-003-A (Generator-Critic) Success
- **PASS:** FPCR ≥ 0.80 (pre-registered threshold — see resolution below)
- **INCONCLUSIVE:** 0.50 ≤ FPCR < 0.80 → trigger staged schema redesign protocol
- **FAIL:** FPCR < 0.50 → schema is fundamentally unusable; redesign from scratch
- **RRR (Retry Resolution Rate):** Reported but not a PASS gate. Minimum informative threshold: RRR ≥ 0.50 (majority of retries succeed on attempt 2).

### NS-003-B (Belief Graph) Success
- **CCR (Correct Catch Rate) ≥ 0.80** — at least 80% of genuine contradictions caught pre-commit (vs heuristic baseline)
- **FPR (False Positive Rate) ≤ 0.20** — no more than 20% of ConflictSignals are false alarms
- **N=20+20** (pre-registered sample sizes for NS-003-B — see unknowns.md U-010 for clarification)

### U-CA-004 Success
- **POSITIVE verdict requires ALL THREE simultaneously:**
  1. Mann-Whitney U: p < 0.05 (two-tailed) on AQS(Condition C) vs AQS(Condition B)
  2. ΔAQS ≥ 0.10 (absolute improvement in composite score)
  3. ΔSVR ≥ 15% relative reduction: SVR(C) ≤ SVR(B) × 0.85
- **NEGATIVE verdict:** Any criterion fails → terminate overlay program
- **INCONCLUSIVE:** Staged expansion to N=20 if first N=10 shows marginal effect (within 1 standard error of p=0.05)

### CA Overlay Implementations (if POSITIVE)
- **5 overlays to implement** if all sequential tests are POSITIVE: ACT-R Typed Buffer, Goal Stack, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory
- **Sequential testing with early termination** — no parallel overlay testing

---

## FPCR Threshold Resolution (BANZAI Mode — Autonomous Decision)

**Conflict:** Spec 017 brief states ≥0.70; pre-registered design (ns003-experiment-design.md Section 6) states ≥0.80.

**Autonomous resolution:** The pre-registered 0.80 threshold is authoritative for the formal experiment PASS verdict. This is required by the pre-registration principle (Section 8) and scientific validity.

**Interpretation of 0.70:** Treated as the minimum viable schema quality threshold. If FPCR < 0.70 during Phase 1 calibration, schema redesign begins before running the full N=30 experiment. FPCR in [0.70, 0.80) during the full experiment = INCONCLUSIVE per pre-registered criteria.

**This interpretation is documented here and will be stated in the experiment report.** If the human intended 0.70 as a downward amendment to the pre-registered threshold, an explicit amendment with scientific justification must be provided. In BANZAI mode with no human in loop, the conservative (more scientifically valid) interpretation is used.

---

## Tracking State

### Resolved Autonomously
- FPCR threshold ambiguity: use 0.80 (pre-registered) as PASS criterion; 0.70 as minimum viable start threshold

### Unresolved — Require Human Input (non-blocking in BANZAI mode, will document as limitations)
- U-007: Prior spec runs 008-014 location — HOW phase will design fallback (runs 015-016 as calibration set or synthetic known-good samples)
- U-009: Write-time interception hook mechanism — HOW phase will audit COMMANDER dispatch and design the hook

### Unresolved — Require SCIENTIST Investigation
- U-004: Markdown → dict parsing strategy (SCIENTIST)
- U-005: BeliefGraph persistence format (SCIENTIST)
- U-008: ACT-R cosine_similarity computation method (SCIENTIST)
- SUSP-001: Structured-to-prose ratio in prior spec artifacts (SCIENTIST)
- SUSP-002: Evaluator blinding feasibility (SCIENTIST)
