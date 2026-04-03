# Contradictions and Gaps — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: SYNTHESIZER (FUSE) | **Date**: 2026-04-03

---

## Summary

| ID | Type | Description | Severity | Status |
|----|------|-------------|----------|--------|
| CRIT-001 | CONTRADICTION | FPCR threshold: spec 017 brief says ≥0.70, pre-registered design says ≥0.80 | CRITICAL | Unresolved — escalate to WHY1 |
| GAP-001 | GAP | No write-time interception hook defined in COMMANDER for NS-003 | CRITICAL | Unresolved — block NS-003 architecture |
| GAP-002 | GAP | No API dependency management (scripts/requirements.txt absent) | HIGH | Actionable — create file |
| GAP-003 | GAP | No Python Anthropic SDK usage pattern in codebase | HIGH | Architectural decision required |
| GAP-004 | GAP | Prior spec run artifacts (runs 008-014) not confirmed accessible | HIGH | Blocks Phase 1 calibration |
| SUSP-001 | SUSPICIOUS | FPCR measurement may conflate schema coverage gaps with agent compliance | MEDIUM | Investigate before Phase 2 |
| SUSP-002 | SUSPICIOUS | Evaluator blinding for U-CA-004 may be structurally infeasible | MEDIUM | Investigate before experiment design |
| PAT-001 | PATTERN | Both sub-systems converge on same COMMANDER integration point with conflicting hook types | HIGH | Design coordination required |
| PAT-002 | PATTERN | Endocrine cortisol contagion risk from NS-003 ESCALATED event cascade | MEDIUM | Monitor in implementation |
| PAT-003 | PATTERN | stop-key list in contradiction-scanner.py is reusable empirical data for NS-003-B | LOW | Capture as design input |

---

## CONTRADICTIONS

### CRIT-001: FPCR Threshold — spec 017 brief vs pre-registered experiment design

| Dimension | Source A | Source B |
|-----------|----------|----------|
| Document | Spec 017 user brief | `ns003-experiment-design.md` Section 6 (pre-registered) |
| FPCR PASS threshold | ≥ 0.70 | ≥ 0.80 |
| FPCR INCONCLUSIVE zone | Not defined | 0.50 ≤ FPCR < 0.80 (explicitly) |
| Verdict for FPCR = 0.72 | SUCCESS (brief) | INCONCLUSIVE (pre-registered) |
| Verdict for FPCR = 0.85 | SUCCESS (brief) | PASS (pre-registered) |

**Conflict type:** DIRECT CONTRADICTION — the two sources produce opposite verdicts for any FPCR result in [0.70, 0.80).

**Why this is critical:**
- The pre-registration principle (ns003-experiment-design.md Section 8) requires using pre-registered criteria without post-hoc adjustment. If 0.80 is the pre-registered threshold, applying 0.70 post-hoc violates the reproducibility requirement.
- The human authorized BANZAI mode and instructed "resolve autonomously" — however, this contradiction involves the formal experiment PASS criterion, which is a scientific validity question, not an implementation preference. Autonomous resolution requires choosing a threshold; any choice has implications for the experiment's validity.
- **SYNTHESIZER recommendation for autonomous resolution (BANZAI mode):** Use the pre-registered 0.80 threshold as the formal PASS criterion. Treat 0.70 in the spec 017 brief as the minimum viable start threshold (below which schema redesign begins before running the full N=30). Document this interpretation in user-intent.md. If FPCR lands in [0.70, 0.80) during the experiment, report as INCONCLUSIVE per pre-registered criteria and trigger the staged expansion protocol.

**Flagged for:** WHY1 adversarial challenge on interpretation validity.

---

## GAPS

### GAP-001: No Write-Time Interception Hook in COMMANDER (CRITICAL)

**Expected (NS-003 design):** COMMANDER intercepts agent output between LLM call completion and artifact file write. The Critic function runs in this gap.

**Actual (codebase):** commander.md Pre-Dispatch Protocol describes only pre-dispatch steps (endocrine read → hormone injection → prompt assembly). There is NO documented post-dispatch, pre-commit hook. No mechanism for write-time interception exists anywhere in the codebase.

**Gap size:** Unknown — the interception mechanism is entirely undesigned. This is not a missing parameter but a missing architectural pattern. Two possible architectures:
1. COMMANDER pipes LLM output through a validation wrapper before writing — requires COMMANDER to orchestrate the write step itself
2. Agents write via a shared write utility that calls the Critic — requires modifying agent write behavior

**Impact:** Without resolving GAP-001, NS-003 cannot be pre-commit (it would degrade to post-hoc like contradiction-scanner.py, eliminating its novelty claim).

**Evidence base:** SCOUT reasoning-journal.json RJ-009; unknowns.md U-009 (elevated to Priority 1).

### GAP-002: No Python Dependency Management for scripts/ Directory (HIGH)

**Expected:** A `scripts/requirements.txt` (or equivalent) listing all Python dependencies for reproducibility.

**Actual:** Only `radar/requirements.txt` exists (flask, flask-cors, watchdog). No top-level or scripts-level requirements file. NS-003 requires jsonschema; U-CA-004 requires scipy; both may require anthropic SDK. pyyaml is already used (system-installed, not tracked).

**Gap size:** Medium effort — create the file, verify all dependencies install cleanly in a fresh environment, pin versions for reproducibility.

**Impact:** Experiment reproducibility requirement (ns003-experiment-design.md Section 8) demands a third party can reproduce the experiment. Untracked dependencies prevent this.

**Evidence base:** SCOUT reasoning-journal.json RJ-007; boundaries.md external boundaries section.

### GAP-003: No Python Anthropic SDK Integration Pattern in Codebase (HIGH)

**Expected:** NS-003 Generator requires programmatic API calls with token count capture.

**Actual:** Zero Python scripts import `anthropic` SDK. All Claude invocations go through the speckit CLI framework externally. The token-logger.py anticipates SDK-style token counts but has no actual SDK to consume from.

**Gap size:** Moderate — establishing the first SDK usage pattern requires: installing anthropic library, writing API call wrapper, setting ANTHROPIC_API_KEY, instrumenting token counts, and handling rate limits / retries.

**Impact:** If SDK cannot be used (architecture forces CLI subprocess), token count measurement degrades to word-count heuristic, undermining REQ-015-003 token baseline fidelity.

**Evidence base:** SCOUT reasoning-journal.json RJ-002; boundaries.md Anthropic Claude API section; unknowns.md U-002.

### GAP-004: Prior Spec Run Artifacts (Runs 008-014) Not Confirmed Accessible (HIGH)

**Expected:** `ns003-experiment-design.md` Phase 1 criterion: "All 6 schemas parse and validate against known-good sample outputs from prior Echelon runs (runs 008-014). Zero false rejections."

**Actual:** `.specify/specs/` directory shows only specs 015 and 016. Runs 008-014 are not confirmed accessible in the current working directory. Their location is unknown.

**Gap size:** Unknown — could be archived elsewhere, or may not exist in accessible form.

**Impact:** Without known-good samples, Phase 1 schema calibration cannot be completed. The false-rejection measurement is impossible. This blocks all downstream NS-003 phases.

**Evidence base:** SCOUT unknowns.md U-007; boundaries.md Echelon Extension Test Codebase section.

---

## SUSPICIOUS FINDINGS

### SUSP-001: FPCR May Conflate Schema Coverage Gaps with Agent Compliance

**Finding:** The NS-003 Critic validates structured fields (section headers, KV pairs, tables) extracted from Markdown. LLM agents produce substantial unstructured prose in reasoning sections.

**Suspicion:** A Critic that only validates structured fields will compute FPCR based on structured-field compliance only. Prose sections — which may contain scope violations or internal contradictions — are invisible to the schema validator. The FPCR number may look high (agents format structured fields correctly) while actual artifact quality remains low (prose sections are out of scope or inconsistent).

**Risk:** NS-003-A would report a misleading FPCR that overstates compliance. The metric would be technically correct but scientifically insufficient.

**Cross-reference:** Unknown unknowns (unknowns.md) Area 1 — SCOUT identified this; SYNTHESIZER confirms as a systemic pattern across all 6 artifact types.

**Recommended action:** SCIENTIST should measure structured-to-prose ratio in 10-15 prior Echelon run artifacts before Phase 1 schema design. If prose fraction > 40%, the Critic's coverage must be documented as a limitation in the experiment report.

### SUSP-002: U-CA-004 Evaluator Blinding May Be Structurally Infeasible

**Finding:** AQS Internal Consistency dimension requires evaluator access to all prior stage artifacts. Conditions are: (A) naive baseline, (B) expert prompts, (C) ACT-R buffer. ACT-R buffer outputs would likely be structurally different (different context organization), making condition C distinguishable even without condition labels.

**Suspicion:** If evaluators can identify which condition they are scoring, evaluation bias (conscious or unconscious) may inflate Condition C scores. The Mann-Whitney U test result could reflect evaluator bias rather than genuine quality improvement.

**Cross-reference:** SCOUT reasoning-journal.json RJ-008 (evaluator workflow constraint); unknowns.md Area 3.

**Recommended action:** SCIENTIST should determine if condition labels can be redacted while preserving artifact content, and design a pre-calibration rubric exercise (5 reference outputs before main batch).

---

## PATTERNS (Cross-Source Only)

### PAT-001: Both Sub-Systems Converge on COMMANDER with Conflicting Hook Types (HIGH)

**Pattern:** NS-003 requires a POST-dispatch, PRE-commit hook (write-time interception after LLM output). U-CA-004 ACT-R buffer requires a PRE-dispatch hook (context preprocessing before LLM call). Both require COMMANDER.md modifications. These are different hook points in the dispatch lifecycle and must coexist.

**Risk:** If COMMANDER integration is designed independently for each sub-system, the two hook points may conflict or interfere. A unified COMMANDER dispatch lifecycle model must be designed that accommodates:
1. Pre-dispatch: context preprocessing (ACT-R buffer, if CA overlay active)
2. Dispatch: LLM call
3. Post-dispatch: NS-003 Critic validation (if NS-003 active)
4. Post-validation: artifact commit OR retry OR ESCALATE
5. Post-commit: endocrine event wiring

**Recommended action:** HOW phase must produce a unified COMMANDER dispatch lifecycle design that accounts for both hooks simultaneously.

### PAT-002: Cortisol Contagion Risk from NS-003 ESCALATED Cascade (MEDIUM)

**Pattern:** SCOUT reasoning-journal.json RJ-006 identifies an emergent risk: each NS-003 ESCALATED event triggers `on_gate_fail` → cortisol +0.10. Build archetype baseline cortisol is 0.5. After 3 consecutive ESCALATED events: cortisol = 0.5 + 0.30 = 0.80 → contagion threshold. This triggers `propagate_cortisol_contagion` to downstream agents: to.cortisol += 0.05 per propagation step.

**Context:** NS-003 experiment runs 5 invocations per agent type across 6 types (30 total). If schema underspecification causes many FAIL results, the endocrine system will enter high-stress state during NS-003-A validation. This is a coupling risk between the NS-003 experiment and normal squad operation.

**Recommended action:** NS-003 experiment should be run in isolated mode (separate from production squad runs) to prevent cortisol cascade from contaminating production endocrine state.

### PAT-003: contradiction-scanner.py Stop-Key List is Reusable Empirical Data for NS-003-B (LOW)

**Pattern:** The `_GENERIC_STOP_KEYS` frozenset in contradiction-scanner.py (25 keys: statement, description, note, source, author, evidence, approach, summary, etc.) was accumulated over multiple spec runs to prevent false positives from generic key names. This is calibration knowledge.

**For NS-003-B:** When designing per-field exclusion lists for BeliefNode consistency rules, the stop-key list provides the starting set of field names that should NOT trigger ConflictSignal — they are too semantically ambiguous to enforce consistency rules on.

**Recommended action:** NS-003-B design should import stop-key list as the initial per-field false-positive prevention set, then extend with domain-specific rules per artifact type.
