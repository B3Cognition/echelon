# Assumptions — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: SYNTHESIZER (FUSE) | **Date**: 2026-04-03 | **Supersedes**: SCOUT assumptions.md

---

## Synthesis Note

SCOUT identified 10 assumptions across both sub-systems. SYNTHESIZER confirms all 10, adds cross-referencing, and surfaces A-004 as a CRITICAL CONFLICT requiring WHY1 challenge and human confirmation before implementation proceeds.

**Status legend:**
- [validated] — directly confirmed by code evidence or multiple consistent sources
- [conflicted — CRITICAL] — two sources disagree; must resolve before WHY1
- [unvalidated] — not yet confirmed; risk identified
- [low-risk] — standard assumption, low probability of failure

---

## CRITICAL CONFLICT

### A-004: FPCR target is ≥ 0.70 (brief) vs ≥ 0.80 (pre-registered)
- **Statement:** The spec 017 brief states the NS-003 prototype targets "≥0.70 first-pass compliance." The spec 015 pre-registered criteria (ns003-experiment-design.md Section 6) state FPCR ≥ 0.80 = PASS; 0.50 ≤ FPCR < 0.80 = INCONCLUSIVE. These thresholds are directly contradictory for any FPCR result in [0.70, 0.80).
- **Conflict evidence:**
  - Source A (spec 017 brief): "target ≥0.70 first-pass compliance"
  - Source B (ns003-experiment-design.md Section 6): "NS-003-A: FPCR ≥ 0.80" is the PASS threshold
  - Source B (ns003-experiment-design.md Section 4): INCONCLUSIVE zone explicitly defined as "0.50 ≤ FPCR < 0.80"
  - Implication: FPCR = 0.70 is in the INCONCLUSIVE zone per pre-registered criteria — meaning a result the spec 017 brief calls "success" would formally be INCONCLUSIVE under the experiment design.
- **Risk:** If implementation targets 0.70 and the experiment design requires 0.80, the experiment is unresolvable for any result in [0.70, 0.80). Using 0.70 as the PASS criterion post-hoc violates the reproducibility requirement (ns003-experiment-design.md Section 8: "Apply verdict criteria exactly as pre-registered without post-hoc threshold adjustment").
- **Resolution pathway:** Human confirmation required. Two interpretations:
  1. 0.70 is a minimum viable exploration threshold (not the formal PASS criterion) — pre-registered 0.80 remains authoritative. The experiment may still proceed if schema calibration achieves ≥0.70 early, but PASS verdict requires ≥0.80.
  2. 0.70 was intended as a downward amendment to the pre-registered threshold — requires explicit human amendment with rationale.
- **Validation method:** Human must confirm which threshold is authoritative before WHAT phase begins.
- **Status:** [conflicted — CRITICAL] — FPCR conflict between spec 017 brief and pre-registered experiment design. See also contradictions-and-gaps.md CRIT-001.
- **Sources:** [user] spec 017 brief; [NS-003] `ns003-experiment-design.md` Sections 4, 6, 8; [SCOUT] assumptions.md A-004; [SCOUT] unknowns.md U-001; [SCOUT] reasoning-journal.json RJ-005

---

## Critical Assumptions

### A-001: NS-003 Critic is a deterministic Python validator, NOT an LLM
- **Statement:** The Critic in NS-003-A validates agent outputs using a Python JSON Schema validator (jsonschema library) without invoking the Claude API. Pure function: (output, schema) → CriticReport, deterministic and reproducible.
- **Basis:** Stated consistently across all NS-003 artifacts: `ns003-experiment-design.md` Section 7 Phase 2, Phase 1 schema format requirement; glossary.md (spec 015): "The Critic is a deterministic function, not an LLM."
- **Risk if wrong:** NS-003 loses its "execution-grounded" novelty claim and conflates with Self-Refine (prior art). Patent claim collapses. Cost doubles (two API calls per rejection).
- **Cross-reference:** Consistent with A-002 (SDK not needed for Critic itself — only for Generator).
- **Status:** [validated] — directly stated across multiple NS-003 artifacts.

### A-002: The Anthropic API is accessible via the anthropic Python SDK in script context
- **Statement:** NS-003 Generator invocations use the Anthropic Python SDK. ANTHROPIC_API_KEY environment variable available. Token counts returned in API response.
- **Basis:** token-logger.py defines PROMPT_TOKEN_FIELDS and COMPLETION_TOKEN_FIELDS — indicating intended live API instrumentation. However: NO existing Python script calls anthropic SDK (confirmed via grep — zero `from anthropic` imports in scripts/).
- **Risk if wrong:** If CLI subprocess is the only option, token logging falls to word-count heuristic (×1.3 fallback), making NS-003 token measurements estimates rather than live data. REQ-015-003 baseline fidelity is compromised.
- **Cross-reference:** SCOUT reasoning-journal.json RJ-002: "NS-003 implementation must establish the first Python anthropic SDK usage pattern in this codebase."
- **Validation method:** Inspect extension.yml for invocation pattern. Check whether speckit extension framework supports direct Python SDK calls.
- **Status:** [unvalidated] — no Python script currently calls anthropic SDK directly; must confirm extension framework architecture.

### A-003: Schema formalization for 6 Echelon artifact types is feasible without ambiguity
- **Statement:** JSON Schema Draft 2020-12 schemas can be written for all 6 pipeline stage artifact types that are specific enough to reject invalid outputs and general enough to accept valid ones. Phase 1 criterion: zero false rejections on known-good samples from prior runs 008-014.
- **Basis:** contradiction-scanner.py ARTIFACT_STAGE_MAP maps 26 specific artifact filenames to 6 pipeline stages (lines 52-86), confirming taxonomy is well-established. Prior spec runs 008-015 exist as known-good sample pool.
- **Risk if wrong:** FPCR falls into INCONCLUSIVE zone due to schema over-specification or under-specification. Schema redesign required before re-measurement.
- **Cross-reference:** Unknown unknowns (unknowns.md): "Markdown schema specificity vs LLM output variability" — substantial prose in agent outputs may be unreachable by schema-based validation.
- **Validation method:** Build schemas for 2-3 artifact types; run against 5 known-good samples each; measure false rejection rate before committing to full Phase 1.
- **Status:** [unvalidated] — schema feasibility is the key open question for NS-003-A.

### A-005: U-CA-004 runs on the Echelon extension codebase, which is accessible at experiment time
- **Statement:** Test codebase (`/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/`) is available, unchanged, for all 60 experiment runs.
- **Basis:** Both experiment specs specify this codebase. Spec 014 analysis documented 42 agent definitions, 7 tiers.
- **Risk if wrong:** Known failure patterns (ISS-001: ASSESS reproducing DISCOVER findings) and agent count (42) are stale. AQS scoring calibration would be incorrect.
- **Cross-reference:** Both NS-003 and U-CA-004 use this codebase — must lock to the same commit hash for cross-experiment comparability. SYNTHESIZER flags this as a SHARED dependency risk.
- **Validation method:** Check commit hash at experiment start; lock before running either experiment.
- **Status:** [unvalidated] — codebase availability not verified during scouting.

---

## Standard Assumptions

### A-006: endocrine.sh wiring for NS-003 events requires only new command calls, no structural changes
- **Statement:** Integrating NS-003 ConflictSignal events requires calling existing endocrine.sh commands (on_gate_pass, on_gate_fail, on_quality_improvement) from COMMANDER. No new hormone dimensions or event types needed.
- **Basis:** endocrine.sh Phase 3 already provides all required hooks. ConflictSignal outcomes map cleanly: ESCALATED → on_gate_fail; resolved → on_gate_pass; multiple resolved → on_quality_improvement.
- **Cross-reference:** SCOUT reasoning-journal.json RJ-003: wiring is purely at COMMANDER.md level.
- **Status:** [validated] — all required hooks exist in Phase 3 command set.

### A-007: scipy is installable in the execution environment
- **Statement:** scipy can be installed via pip in the execution environment. Python 3 with pip is available.
- **Basis:** Python 3 is already used (contradiction-scanner.py, belief-parser.py, token-logger.py). pyyaml is already installed (system-wide). scipy is a standard scientific library.
- **Cross-reference:** A-007 and A-003 share the dependency management gap (U-003): no scripts/requirements.txt exists.
- **Status:** [low-risk] — standard scientific Python stack; dependency management approach unestablished.

### A-008: CA overlay test order starting with ACT-R Typed Buffer is maintained
- **Statement:** First CA overlay tested in U-CA-004 Condition C is ACT-R Typed Buffer. Subsequent overlays tested sequentially. Early termination on NEGATIVE enforced.
- **Basis:** u-ca-004-experiment-spec.md Section 8 testing order table. P-006 authorization does not change testing order.
- **Risk if wrong:** Testing multiple overlays simultaneously confounds results.
- **Status:** [validated] — explicitly pre-registered in experiment spec.

---

## Low-Risk Assumptions

### A-009: JSON Schema validation of Markdown artifacts requires a Markdown → dict parsing step
- **Statement:** The Critic cannot validate raw Markdown text directly against JSON Schema. A parsing layer must extract semantic structure (section headers, KV pairs, tables, lists) into a Python dict before validation.
- **Basis:** contradiction-scanner.py already implements `extract_assertions_from_file` — demonstrating Markdown → structured data extraction is feasible. The stop-key list (_GENERIC_STOP_KEYS, 25 keys) represents accumulated calibration knowledge for NS-003-B's false-positive prevention rules.
- **Status:** [validated] — existing parser demonstrates feasibility; stop-key list is reusable empirical data.

### A-010: N=30 for NS-003-A and N=20+20 for NS-003-B are fixed per pre-registered design
- **Statement:** Sample sizes cannot be adjusted post-hoc. Staged execution protocol in U-CA-004 (N=10 first, expand to N=20 on INCONCLUSIVE) applies to U-CA-004 only, not to NS-003 measurements.
- **Basis:** ns003-experiment-design.md Section 8 reproducibility requirement: "Apply verdict criteria exactly as pre-registered without post-hoc threshold adjustment."
- **Status:** [validated].

---

## Cross-System Assumption Dependencies

| Assumption | NS-003 | U-CA-004 | CA Overlays | Shared Risk |
|------------|--------|----------|-------------|-------------|
| A-001 (deterministic Critic) | Core | No | No | Low |
| A-002 (SDK availability) | Core | Core | Inherited | **Medium — first SDK usage in codebase** |
| A-003 (schema feasibility) | Core | No | No | High |
| **A-004 (FPCR threshold)** | **CRITICAL CONFLICT** | No | No | **CRITICAL — must resolve before WHAT** |
| A-005 (codebase accessible) | Core | Core | Core | **Medium — both experiments require same version** |
| A-006 (endocrine wiring) | Core | Peripheral | Core | Low |
| A-007 (scipy installable) | Peripheral | Core | No | Low |
| A-008 (test order) | No | Core | Core | Low |
| A-009 (Markdown parsing) | Core | No | No | Low |
| A-010 (sample sizes fixed) | Core | Core | No | Low |
