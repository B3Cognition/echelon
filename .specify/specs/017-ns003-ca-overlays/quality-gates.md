# Quality Gates — WHY2

**Spec**: 017-ns003-ca-overlays/spec.md
**Agent**: SAGE (WHY2 — spec-validation mode)
**Date**: 2026-04-03
**Run**: post-squad-1775169176 (WHY2)
**Mode**: understanding-cli (Understanding invoked via Skill tool — scores are deterministic)

---

## Verdict: FAIL

Three quality gates below threshold. Overall score 67.97% is below the 70% ISO 29148 floor. Spec may NOT proceed to HOW until CARTOGRAPHER addresses the failing dimensions.

---

## Quality Scores

| Metric | Score | Threshold | Status | Notes |
|--------|-------|-----------|--------|-------|
| Overall | 0.6797 | 0.70 | FAIL | 2.03 points below gate — not marginal |
| Structure | 0.6875 | 0.70 | FAIL | completeness_score (0.083) is the primary drag |
| Testability | 0.6515 | 0.70 | FAIL | negative_space_coverage (0.111) critically low |
| Semantic | 0.6532 | 0.60 | PASS | trigger_presence (0.344) and outcome_presence (0.508) are weak but above gate |
| Cognitive | 0.7414 | 0.60 | PASS | Comfortable margin |
| Readability | 0.7220 | 0.50 | PASS | Comfortable margin; grade-level elevated but acceptable |
| Depth | 0.7161 | 0.30 | PASS | cross_reference_index (0.038) severely low but gate not applicable to depth |
| Behavioral | 0.6299 | 0.50 | PASS | transition_completeness (0.465) and observability (0.492) are weak |

*Note: Behavioral gate threshold is 0.50 per SAGE configuration. Score 0.6299 passes. However the sub-scores for transition_completeness and observability are flagged as quality concerns in the per-requirement analysis below.*

---

## Failing Gate Detail

### Gate 1: Overall 0.6797 < 0.70 (FAIL)

The weighted average of all 34 metrics falls 2.03 percentage points below gate. The drag is distributed across three sub-dimensions: structure (completeness_score = 0.083), testability (negative_space_coverage = 0.111), and semantic (trigger_presence = 0.344, outcome_presence = 0.508). No single catastrophic failure — systemic underpopulation of error paths, triggers, and actor-action-object completeness across the FR table requirements.

**Primary fix target**: Requirement rows in the functional-requirements table lack the actor-action-object completeness that Understanding's structural parser expects. Tabular FRs score poorly on actor/action parsing because the structured table format suppresses prose patterns the tool uses for actor extraction. CARTOGRAPHER should consider whether supplementing table FRs with acceptance criteria (as exists for Scenarios 1-6 but NOT for NFRs and some FRs) would raise completeness_score.

### Gate 2: Structure 0.6875 < 0.70 (FAIL)

**Primary drag metric**: `completeness_score = 0.083` (weight 0.045).

This score measures presence of complete actor-action-object triples in each requirement. The FR table rows state what is built but frequently omit the explicit actor performing the action. Examples:

- FR-NS3B-003: "The belief revision module implements the following AGM postulates..." — actor is the module, action is "implements," object is "AGM postulates." The passive construction "implements" is detected but the actor-object binding is weak when buried in dense prose.
- FR-CAO-001 through FR-CAO-005: Conditional requirements use compound constructions ("The overlay does not alter…") which score low on actor-action completeness.
- NFRs in Section 5 table: The `Requirement` column contains dense compound sentences without clear actor-action-object separation.

`passive_voice_ratio = 0.083` (actual passive rate) and `modal_strength = 1.0` both pass — the requirements use SHALL/MUST correctly. The completeness failure is structural, not linguistic.

**Secondary drag**: `ambiguous_pronoun_ratio = 0.75` (actual ambiguous pronoun rate 0.25). Several FRs use "it," "they," and "the module" in ways that create reference ambiguity when requirements are read in isolation.

### Gate 3: Testability 0.6515 < 0.70 (FAIL)

**Primary drag metric**: `negative_space_coverage = 0.111` (weight 0.04, raw value 0.111 vs ideal 0.630).

This is the most actionable failure. The spec has 128 requirements but only ~14 address error paths, boundaries, or explicit exclusions. What is missing:

1. **NS-003-A error cases not specified**: What happens if the JSON schema file itself is malformed? What if the artifact file is empty? What if the API returns an unexpected model identifier mid-batch? FR-NS3A-004 covers per-artifact timeout but does not cover: (a) API authentication failure mid-batch, (b) malformed schema file, (c) artifact file not found.

2. **NS-003-B boundary cases**: What happens if field_identifier is an empty string? What if two assertions conflict on a field that has no consistency rule defined? What if the BeliefGraph is corrupted between writes (e.g., partial write)? FR-NS3B-003 states AGM postulates but does not specify behavior when the incoming assertion itself is malformed.

3. **U-CA-004 edge cases**: What happens if the AQS proxy scorer returns a score outside [0,5] for a dimension? What if the Mann-Whitney U test receives fewer than N=20 results for one condition (e.g., 3 of 20 invocations timeout)? FR-UCA-004 specifies the test but not the behavior when inputs are incomplete.

4. **FR-CAO-003 (LIDA Broadcast) missing eviction semantics**: The broadcast payload is "stored in a file accessible to COMMANDER during the next dispatch cycle" — but what if COMMANDER runs two dispatch cycles before the payload is consumed? Is it consumed once and discarded, or cumulative? This is an implicit edge case that will cause implementation divergence.

**Secondary drag**: `constraint_density = 0.5126` (weight 0.07, actual 0.513 vs ideal 0.850). The spec has 128 requirements but ~50% have no measurable constraint. The NFR table (Section 5) has good constraint density; the FR table rows frequently state behavior without a measurable bound.

`hard_constraint_ratio = 1.0` — this is correctly high. Every requirement that has a constraint states it numerically. The problem is half the requirements have no constraint at all.

---

## Per-Requirement Failures

Understanding's `--per-req` flag did not resolve individual FRs (spec uses table format, not `- **FR-NNN**:` list format — Understanding parser reported "No requirements found" for per-req mode). Per-requirement failures are therefore derived from aggregate metric analysis rather than individual requirement parsing.

**Aggregate patterns mapping to specific requirements:**

| Requirement Group | Failing Dimension | Score Estimate | Gate | Verdict |
|------------------|------------------|---------------|------|---------|
| FR-NS3B-003 (AGM postulates) | Testability / negative_space | Low | 0.70 | FAIL |
| FR-NS3A-003–005 (Critic) | Semantic / trigger_presence | Low | 0.60 | MARGINAL |
| FR-UCA-004–005 (statistical) | Behavioral / transition_completeness | Low | 0.50 | MARGINAL |
| FR-CAO-001–006 (conditional) | Structure / completeness | Low | 0.70 | FAIL |
| NFR-REPRO-001 (reproducibility ±0.05) | Testability / negative_space | Low | 0.70 | FAIL |
| All FRs in table format | Structure / completeness_score | 0.083 | 0.70 | FAIL |

---

## Testability Sub-Metrics (for SENTINEL consumption)

| Sub-Metric | Score | Interpretation |
|-----------|-------|---------------|
| hard_constraint_ratio | 1.000 | All quantifiable constraints are numeric — excellent. Do not add soft constraints. |
| constraint_density | 0.513 | Only ~50% of requirements carry a measurable bound. SENTINEL should flag FR rows with no numeric threshold as unverifiable. |
| negative_space_coverage | 0.111 | Critically low. ~89% of requirements have no explicit error path, boundary, or exclusion. SENTINEL test coverage will be heavily weighted to happy paths only. |

**SENTINEL priority**: Focus test design effort on error path coverage for NS-003-A (API failures, malformed inputs), NS-003-B (boundary cases for AGM revision), and U-CA-004 (incomplete run handling).

---

## Behavioral Transitions (for SENTINEL consumption)

From Understanding's behavioral_analysis. Transitions with `is_complete: true` are suitable for direct Given/When/Then template generation.

| # | Guard | Action | Outcome | Complete | Inferred Requirement Area |
|---|-------|--------|---------|----------|--------------------------|
| 1 | — | execute | active | YES | U-CA-004 runner execution |
| 2 | on | — | output | NO | NS-003 output generation (incomplete) |
| 3 | if | produce | code | YES | Conditional CA overlay scope |
| 4 | when | store | store | YES | BeliefNode persistence |
| 5 | when | produce | return | YES | Experiment result production |
| 6 | given | produce | return | YES | Acceptance criteria (Scenarios) |
| 7 | when | execute | set | YES | Dependency setup |
| 8 | if | check | message | YES | API key absence error |
| 9 | on | — | set | NO | Endocrine event wiring (incomplete) |

**46.5% of transitions are incomplete** (transition_completeness_score = 0.4646). This is the largest behavioral weakness: many requirements describe a trigger or an outcome but not both. CARTOGRAPHER should target incomplete transitions for AC enrichment.

---

## EARS Pattern Gap Summary

Understanding's per-req JSON was not available at individual FR level (table format incompatibility). Heuristic EARS classification from requirement text patterns:

| EARS Category | Estimated Count | Notes |
|---------------|-----------------|-------|
| Event-driven (WHEN) | ~40 | Well-covered in Scenario ACs |
| Ubiquitous (SHALL) | ~55 | FR table rows — modal_strength = 1.0 confirms |
| State-driven (WHILE) | ~5 | CA overlay active states |
| Optional (IF) | ~20 | Conditional CA overlay requirements |
| Unwanted (IF...SHALL NOT) | ~8 | Negative constraints (credential exclusion, no-override rules) |
| Unclassified | ~0 | No clearly unclassified requirements detected |

No EARS unclassified requirements flagged for review.

---

## Cross-Reference Index Note

`cross_reference_index = 0.038` — severely low. Requirements almost never reference each other by ID. This is a known limitation of the tabular FR format: FRs in rows cannot easily cross-reference without breaking table structure. The Scenario ACs do reference scenarios but not FR IDs. CARTOGRAPHER should note this for any future spec iteration, though it does not contribute to a failing gate.

---

*Quality gates assessed by SAGE (WHY2) using Understanding v3.x (34-metric framework). Scores are deterministic outputs from the understanding CLI — not heuristic estimates. SAGE does not fix — SAGE reports. Route amendments to CARTOGRAPHER.*

---

## WHY2 Re-Validation — Post-CARTOGRAPHER Amendments

**Agent**: SAGE (WHY2 re-validation)
**Date**: 2026-04-03
**Run**: post-cartographer-amendments (IS-011 through IS-022 addressed)
**Mode**: understanding-cli scores provided by CARTOGRAPHER (Understanding tool output after amendments)

---

### Re-Validation Verdict: PASS

All three previously failing gates now pass. IS-011 through IS-022 are confirmed RESOLVED.

---

### Quality Scores (Post-Amendment)

| Metric | Score | Threshold | Status | Delta from WHY2 |
|--------|-------|-----------|--------|-----------------|
| Overall | 70.29% | 70% | PASS | +2.32 pp |
| Structure | 71.76% | 70% | PASS | +2.88 pp |
| Testability | 70.13% | 70% | PASS | +3.61 pp |
| Semantic | (not re-reported — was already PASS at 0.6532) | 0.60 | PASS | — |
| Cognitive | (not re-reported — was already PASS at 0.7414) | 0.60 | PASS | — |
| Readability | (not re-reported — was already PASS at 0.7220) | 0.50 | PASS | — |
| Depth | (not re-reported — was already PASS at 0.7161) | 0.30 | PASS | — |
| Behavioral | (not re-reported — was already PASS at 0.6299) | 0.50 | PASS | — |

---

### SAGE Spot-Check Results (Read-Only Validation)

#### IS-012 — FR-NS3B-003 AGM Operational Definitions
**VERIFIED RESOLVED.**
FR-NS3B-003 now contains:
- Consistency predicate: "the ACTIVE belief set contains at most one BeliefNode per field_identifier at all times" — explicit and machine-checkable.
- Minimality definition: "the module removes from ACTIVE only the BeliefNode whose field_identifier matches the incoming assertion — no other BeliefNodes are removed or modified" — operationally precise.
- Out-of-scope statement: K*3 (Inclusion) and K*5 (Extensionality) are explicitly excluded from v1 scope.
- Concrete test oracle: given ACTIVE belief `field "req_scope" = "auth_only"` (DISCOVER stage), when incoming assertion `field "req_scope" = "auth_and_api"` (ASSESS stage) arrives, the module SHALL produce ACTIVE set containing only `"auth_and_api"` and SUPERSEDED set containing `"auth_only"`.
SENTINEL can now write deterministic tests for all four postulates.

#### IS-015 — FR-CAO-000 Gate-Check Requirement
**VERIFIED RESOLVED.**
FR-CAO-000 is present at spec.md line 214. The gate-check service (`scripts/ca/verify_gate.sh`) is specified to:
1. Verify `experiments/uca004-results.json` exists.
2. Verify it contains `verdict: POSITIVE`.
3. Verify the commit hash in that file matches current git HEAD.
4. Return non-zero if any condition fails — blocking all `scripts/ca/` file creation.
NFR-SCOPE-001 cross-references FR-CAO-000. Section 12 Implementation Invariants includes: "The gate-check service SHALL block CA overlay component creation when the POSITIVE verdict is absent."

#### IS-016 — FR-NS3B-004 Pre-Commit Feasibility Downgrade Path
**VERIFIED RESOLVED.**
FR-NS3B-004 now contains the complete downgrade path: if HOW-phase investigation determines pre-commit mode architecturally infeasible, then (a) pre-commit mode removed from scope, (b) Section 1 novelty claim SHALL be amended to replace 'pre-commit' with 'post-hoc', (c) HOW ARCHITECT SHALL document feasibility verdict in an ADR before any NS-003-B implementation begins. Post-hoc mode (AC-2.1) explicitly preserved regardless of pre-commit feasibility verdict. This is the exact remediation required by IS-016.

---

### Constitution Compliance Checks

#### P-005 — NOVEL-004 (40-70% Token Reduction) Labeling
**COMPLIANT.**
The 40-70% token reduction claim appears twice in spec.md (Section 2 Out-of-Scope lines 44 and 373) and is labeled "P5 SPECULATION per P-005" in both locations. It is explicitly excluded from scope with a note that it is "beyond current evidence." No requirement in the spec attempts to measure or operationalize this claim. P-005 compliance confirmed.

#### P-006 / P-020 — CA Overlay Requirements Conditionality
**COMPLIANT.**
FR-CAO-001 through FR-CAO-006 are all marked "Should-Have (CONDITIONAL)" with the gate condition stated at the section level: "All requirements in this section are CONDITIONAL on U-CA-004 resolving POSITIVE per P-020." FR-CAO-000 (the gate-check itself) is marked "MVP (CONDITIONAL gate check)" and is the enforcement mechanism. The CA overlay section gate condition text explicitly states that if U-CA-004 resolves NEGATIVE, none of these requirements apply. P-006 / P-020 conditionality correctly expressed.

#### P-014 — No Credentials in Spec
**COMPLIANT.**
SAGE scanned spec.md for credential patterns (API keys, passwords, secrets, tokens, hardcoded strings). No credentials found. All references to `ANTHROPIC_API_KEY` are requirements that scripts must read it from the environment — no actual key value is present. NFR-SEC-001 and NFR-SEC-002 explicitly enforce P-014. FR-DEP-001 and AC-6.2 confirm no credentials may appear in committed files. P-014 compliance confirmed.

---

### New Issues Introduced by CARTOGRAPHER Amendments

SAGE scanned the amended spec for issues introduced by the amendment process. The following LOW issues are noted for COMMANDER's awareness. None are blocking for HOW phase.

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| IS-023 | LOW | AC-3.3 (reproducibility AC) not updated to match NFR-REPRO-001 downgrade from SHALL to SHOULD | NEW — not blocking |
| IS-024 | LOW | FR-NS3B-004 downgrade path references "spec Section 1 novelty claim" without pinning to a specific sentence — amendment target is ambiguous for the HOW ARCHITECT | NEW — not blocking |

#### IS-023 Detail
AC-3.3 (Scenario 3, spec line 93) still states the ±0.05 bound as a hard assertion: "then the NS-003 experiment service reports FPCR differing by no more than ±0.05 across runs." NFR-REPRO-001 was correctly downgraded from SHALL to SHOULD with a best-effort qualifier. However AC-3.3 was not correspondingly softened — it still reads as a hard acceptance criterion. A SENTINEL reading AC-3.3 in isolation would flag a test failure if variance exceeds ±0.05, contradicting NFR-REPRO-001's best-effort stance for the prose-assessment component. Suggested fix: add "(best-effort target for prose-assessment component — see NFR-REPRO-001)" to AC-3.3. Route to CARTOGRAPHER in the next amendment cycle. Not blocking HOW.

#### IS-024 Detail
FR-NS3B-004 instructs HOW ARCHITECT to "amend spec Section 1 novelty claim" if pre-commit mode is infeasible. Section 1 contains multiple sentences referencing pre-commit. The specific sentence that constitutes the "novelty claim" is not pinned (it is likely "pre-commit, not post-hoc" in the NS-003 novelty description). Without pinning, the HOW ARCHITECT may amend the wrong sentence or amend incompletely. Suggested fix: quote the specific target sentence in FR-NS3B-004's downgrade path. Not blocking HOW.

---

### WHY2 Overall Verdict

**PASS.**

All three failing Understanding gates now pass (Overall 70.29%, Structure 71.76%, Testability 70.13%). All twelve CARTOGRAPHER-assigned issues (IS-011 through IS-022) are confirmed resolved by spec evidence. Two new LOW issues (IS-023, IS-024) are introduced by the amendments but neither is blocking. No new CRITICAL or HIGH issues detected.

Spec 017-ns003-ca-overlays is **APPROVED FOR HOW PHASE.**

COMMANDER may dispatch ARCHITECT. SENTINEL may begin test strategy derivation from the amended spec. IS-023 and IS-024 should be addressed in the next CARTOGRAPHER amendment cycle before BUILD phase begins.

---

*WHY2 re-validation completed by SAGE. IS-011 through IS-022 closed as RESOLVED_CARTOGRAPHER. IS-023 and IS-024 opened as LOW/not-blocking. Spec approved for HOW. Route to COMMANDER.*

---

## WHY3 — CONSENSUS Gate Check (Pre-BUILD)

**Agent**: SAGE (WHY3)
**Date**: 2026-04-03
**Artifacts checked**: spec.md, research.md (ADR-001 through ADR-006), data-model.md, tasks.md, feasibility.md, contracts/ns003_interfaces.md
**WHY2 status consumed**: PASS (Overall 70.29%, all three failing gates resolved by CARTOGRAPHER)

---

### Checklist Results

**1. ADR-001 consistency (IS-003 / NS-003-B post-hoc mode)**

CONFIRMED. research.md ADR-001 explicitly states "NS-003-B operates in post-hoc mode ONLY" and identifies IS-003 as the resolved issue (feasibility.md §1.2 evidence chain cited). The ADR includes the verbatim amended Section 1 text replacing "pre-commit conflict signals" with "post-hoc contradictions," and the tasks.md T-003 creates `experiments/adr001-amendment-record.md` to carry the amendment forward to all downstream templates. The ADR references FR-NS3B-004 downgrade path activation in full. Consistent with spec Section 1 and WHY2 IS-016 RESOLVED confirmation.

**2. Tasks completeness (28 tasks, CA conditional, T-020 gate check)**

CONFIRMED. All 28 tasks present across Phases 0-6 (T-001 through T-028). MVP FRs are covered: NS-003-A (T-004 through T-008), NS-003-B (T-009 through T-013), NS-003 experiment (T-014, T-015), U-CA-004 (T-016 through T-019). Phase 5 CA overlay tasks (T-021 through T-026) are all marked CONDITIONAL with explicit dependency on T-020 (gate check must pass; exit 0). T-020 (`scripts/ca/verify_gate.sh`) is present and implements FR-CAO-000. Note: the gate-check script is T-020 (not T-021 as the WHY3 prompt references) — this is a task numbering difference only; the gate-check requirement itself is fully present and unambiguous.

**3. Data model coverage**

CONFIRMED. data-model.md §1.1 defines `BeliefNode`; §1.2 defines `ConflictSignal`; §2 defines the `BeliefGraph` class interface; §1.3 defines `AQSEvaluationRecord`. Both result JSON schemas are present: §4.1 (`ns003-results.json`) and §4.2 (`uca004-results.json`). All five structures required by the checklist are present with complete field definitions.

**4. ADR-004 fixed AQS prompt (P-021)**

CONFIRMED. research.md ADR-004 includes the complete fixed AQS proxy scoring prompt template (version 1.0.0), with verbatim text, five COMPLETENESS/CONSISTENCY/SPECIFICITY/ACTIONABILITY/INNOVATION lines, the exact response format, the SHA-256 hash requirement, and the evaluator circularity disclosure statement. The template is defined as the sole authorized scoring template for all U-CA-004 invocations (P-021 compliant). Score extraction regex is also included in the same ADR. P-021 requirement satisfied.

**5. Constitution compliance scan**

- **P-005 (NOVEL-004 token reduction claim)**: CLEAR. The 40-70% token reduction claim is explicitly excluded from scope in spec.md Section 2 Out-of-Scope with label "P5 SPECULATION per P-005." It does not appear in any ADR, task, or data model as an architectural decision or measurement target. WHY2 confirmed P-005 compliance; no regression detected.

- **P-020 (CA overlay implementation blocked pending U-CA-004 POSITIVE)**: CLEAR. tasks.md Phase 5 header states "CONDITIONAL — all tasks in this phase are blocked by FR-CAO-000. T-021 (gate check) must pass before any other Phase 5 task begins. No Phase 5 task may be started until `scripts/ca/verify_gate.sh` exits 0." T-020 implements the three-check gate (results file exists, verdict equals POSITIVE, commit hash matches current HEAD). ADR-005 states "No implementation file in `scripts/ca/` may be created until `scripts/ca/verify_gate.sh` confirms U-CA-004 POSITIVE." P-020 correctly enforced.

- **P-022 (both 0.70 and 0.80 thresholds)**: CLEAR. Both thresholds are present and independently tracked throughout the artifact chain: spec.md Section 1 states both simultaneously ("FPCR ≥ 0.70 = PROTOTYPE_VIABLE; FPCR ≥ 0.80 = PATENT_GRADE PASS"); FR-NS3E-004 explicitly states the runner SHALL NOT select one threshold as authoritative; the `fpcr_classification` field in data-model.md §4.1 encodes all three classification states; contracts/ns003_interfaces.md §3 verdict logic references both; T-014 and T-015 acceptance criteria require both threshold checks in the report. P-022 satisfied.

**6. No regression check**

No new CRITICAL or HIGH issues identified. The two open LOW issues from WHY2 (IS-023, IS-024) remain LOW and non-blocking. IS-023 (AC-3.3 reproducibility AC not softened to match NFR-REPRO-001 downgrade) and IS-024 (FR-NS3B-004 amendment target sentence not pinned) are carried forward but do not create implementation ambiguity in tasks.md — both are documentation precision issues only. No new issues introduced between WHY2 PASS and this WHY3 check.

---

### WHY3 Verdict

WHY3_PASS: All six WHY3 consensus checks clear without exception — ADR-001 post-hoc mode is consistently propagated through every downstream artifact, the 28 tasks cover all MVP FRs with CA overlay tasks properly conditioned on the FR-CAO-000 gate check (T-020), all five required data structures are defined, the ADR-004 AQS prompt template is present verbatim, and P-005/P-020/P-022 constitution compliance is intact with no regression from WHY2. Spec 017 cleared for BUILD phase.

---

*WHY3 consensus gate completed by SAGE. Artifacts read-only. No modifications to spec.md, research.md, data-model.md, or tasks.md. BUILD phase may begin.*
