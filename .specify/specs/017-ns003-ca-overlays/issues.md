# Issues — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)
**Produced by**: SAGE (WHY1 assumption-challenge + WHY2 spec-validation) | **Date**: 2026-04-03
**Run**: squad-1775169176 (WHY1) + WHY2 (post-WHAT)

---

## Issue Register

| ID | Severity | Title | Status | Owner |
|----|----------|-------|--------|-------|
| IS-001 | CRITICAL | FPCR threshold autonomous resolution exceeds agent authority | OPEN | [user] must confirm |
| IS-002 | CRITICAL | P-006 bypass not formally constitutionally amended | OPEN | [user] via /speckit.constitution |
| IS-003 | CRITICAL | Artifact write mechanism not audited — pre-commit NS-003 feasibility unconfirmed | OPEN | [domain-expert] audit commands/squad.run.md |
| IS-004 | CRITICAL | AQS scoring requires human evaluators — incompatible with BANZAI mode | OPEN | [user] confirm evaluation approach |
| IS-005 | HIGH | A-006 misclassified as [validated] — Phase 3 hooks exist but are not wired in COMMANDER | OPEN | SYNTHESIZER must correct assumptions.md |
| IS-006 | HIGH | Commit hash lock for test codebase not specified as required deliverable | OPEN | HOW phase must add to tasks |
| IS-007 | HIGH | RSK-010 underclassified — FPCR metric validity (structured-to-prose) is CRITICAL not MEDIUM | OPEN | SCIENTIST must measure before Phase 1 |
| IS-008 | MEDIUM | "BANZAI mode" undefined in glossary — authority scope relative to constitution unspecified | OPEN | WHAT agent must add to glossary |
| IS-009 | MEDIUM | ANTHROPIC_API_KEY propagation into subagent environment not confirmed | OPEN | [domain-expert] inspect extension.yml invocation |
| IS-010 | MEDIUM | Circular dependency: runs 008-014 required for Phase 1 criterion which itself certifies schema feasibility | OPEN | HOW phase must resolve with fallback design |

---

## CRITICAL Issues

### IS-001: FPCR Threshold Autonomous Resolution Exceeds Agent Authority

**Raised by**: SAGE (WHY1)
**Related to**: CRIT-001, A-004, risks.md RSK-001

**Finding**: SYNTHESIZER autonomously resolved the FPCR threshold conflict (0.70 brief vs 0.80 pre-registered) by declaring 0.80 authoritative. This resolution is documented in user-intent.md and the reasoning journal. SAGE challenges this on three grounds:

1. The constitution grants no agent authority to override a human-stated requirement. The brief was the human's own statement. Using the pre-registered threshold (written by ARCHITECT in spec 015, not the human) over the human's brief is a routing violation (P-003).

2. The pre-registration principle (ns003-experiment-design.md Section 8) constrains how verdict criteria are applied, not what the implementation target should be. Using it to justify overriding the human's stated target conflates two different requirements.

3. A FPCR result of 0.73 would be reported as INCONCLUSIVE under the SYNTHESIZER resolution, but as SUCCESS under the human's brief. The human may not know they set themselves up for an INCONCLUSIVE verdict if they target 0.73. This undisclosed failure mode should have been escalated, not resolved.

**Required action**: Human must confirm:
- (a) Is 0.70 the intended PASS criterion, or an exploration/minimum-viable threshold?
- (b) If 0.70 was the intent, should the pre-registered threshold be formally amended to 0.70 with documented scientific justification?
- (c) If 0.80 is accepted, the human should acknowledge that FPCR in [0.70, 0.80) will be reported as INCONCLUSIVE per the experiment design.

**Blocking**: WHAT phase cannot set implementation targets until this is resolved.

---

### IS-002: P-006 Bypass Not Formally Constitutionally Amended

**Raised by**: SAGE (WHY1)
**Related to**: constitution.md P-006, state.json human_override

**Finding**: P-006 (HUMAN-DEFINED) states: "The five CA overlays are GATE_BLOCKED. No implementation code may be written for these mechanisms until U-CA-004 resolves POSITIVE. This gate is absolute." The constitution states: "Only the human may amend this constitution via `/speckit.constitution`."

The current bypass exists only in state.json as `human_override.p006_ca_overlays = "AUTHORIZED"`. state.json is an agent-writable file. It is NOT a constitutional amendment mechanism. An agent (even COMMANDER in BANZAI mode) setting a field in state.json does not constitute a constitutional change.

**The practical consequence**: Any implementation artifact produced under the state.json authorization is technically in violation of P-006 until a formal constitutional amendment is made. If challenged (e.g., in a patent review or external validation), this gap would show that the team bypassed their own governance process informally.

**Scope clarification needed**: The authorization does NOT appear to conflict with:
- Building NS-003 prototype (not blocked by P-006)
- Building U-CA-004 experiment infrastructure (not blocked by P-006)
- Building the ACT-R preprocessing function for U-CA-004 Condition C (borderline — it is experimental, not production overlay)

The authorization DOES potentially conflict with:
- Writing production implementation code for any of the 5 CA overlays before U-CA-004 resolves POSITIVE

**Required action**: Human must either:
- (a) Run `/speckit.constitution` to formally amend P-006 to reflect the authorization scope, OR
- (b) Confirm that the current work scope (NS-003 + U-CA-004 experiment infrastructure + ACT-R preprocessing function for Condition C only) does NOT require a P-006 amendment because it does not constitute writing production implementation code for the CA overlays.

**Blocking**: Any WHAT-phase requirement that involves CA overlay implementation code.

---

### IS-003: Artifact Write Mechanism Not Audited — Pre-Commit NS-003 Feasibility Unconfirmed

**Raised by**: SAGE (WHY1)
**Related to**: GAP-001, U-009, A-001, risks.md RSK-002

**Finding**: The ns003-experiment-design.md specifies the Critic as "called by COMMANDER post-agent-LLM-call, pre-artifact-commit." This is a requirements statement about where the Critic should be called, not evidence that such a hook point exists. The actual mechanism by which agent outputs become artifact files has NOT been audited.

Two architecturally incompatible models exist:
- **Model A (COMMANDER-controlled write):** COMMANDER receives agent output as a return value, runs Critic, then writes the file. Requires agents NOT to self-write.
- **Model B (write-wrapper):** Agents must call a shared write utility that invokes the Critic. Requires modifying every agent's prompt instructions.

If current agents self-write via Write tool calls (the standard subagent pattern), Model A is infeasible and the "pre-commit" architecture requires Model B — a systemic change to agent protocols.

**Patent validity implication**: The NS-003 novelty claim rests on "pre-commit, not post-hoc." If the implementation degrades to post-hoc (because Model A is infeasible and Model B is not built), the novelty claim is not established. This must be resolved before designing the NS-003 architecture.

**Required action**: Audit `commands/squad.run.md` and `commands/squad.build.md` to determine whether agents self-write artifact files or whether COMMANDER controls the write step. This is a research task for [domain-expert] or SCIENTIST.

**Blocking**: All NS-003 architecture design (HOW phase). Cannot design NS-003 integration with COMMANDER without knowing the write mechanism.

---

### IS-004: AQS Scoring Requires Human Evaluators — Incompatible with BANZAI Mode

**Raised by**: SAGE (WHY1)
**Related to**: u-ca-004-experiment-spec.md Section 6, user-intent.md BANZAI mode

**Finding**: U-CA-004's primary dependent variable (AQS score) is defined in u-ca-004-experiment-spec.md Section 6 as a four-dimension human evaluation rubric (Completeness, Precision, Internal Consistency, Scope Compliance), each scored 0-3 by an evaluator with access to:
- The agent's prompt definition (to determine scope)
- All prior stage artifacts from the same run (to assess internal consistency)
- The test codebase itself (to assess completeness)

The experiment spec acknowledges: "Where only one evaluator is available, this limitation is stated in the experiment report." This is not AQS automation — it is single-evaluator human scoring.

In BANZAI mode ("no human in loop"), zero human evaluators are available. The U-CA-004 experiment CANNOT be executed as specified in fully autonomous mode. The AQS scores that drive the POSITIVE/NEGATIVE verdict cannot be generated.

**Three resolution options** (SAGE reports, does not choose):
1. **Automated AQS proxy**: Define a deterministic automated proxy for AQS scoring (e.g., using contradiction-scanner.py output for Internal Consistency, section header coverage for Completeness, etc.). This proxy must be validated against human AQS scores on a calibration set before the experiment. This is a significant additional deliverable.
2. **Split execution**: Human authorizes autonomous experiment execution (API calls, artifact generation) but commits to providing AQS scores post-execution. BANZAI mode for execution; human evaluation for scoring. Experiment is not fully autonomous.
3. **Revised experiment design**: Replace AQS with a fully automated metric (e.g., schema compliance rate from NS-003-A Critic, token efficiency). This changes the experiment design and requires pre-registration revision.

**Required action**: Human must confirm evaluation approach before U-CA-004 experiment infrastructure is built. The choice affects what infrastructure is built.

**Blocking**: U-CA-004 experiment runner design (HOW phase).

---

## HIGH Issues

### IS-005: A-006 Misclassified as [validated] — Phase 3 Hooks Not Wired in COMMANDER

**Raised by**: SAGE (WHY1)
**Related to**: assumptions.md A-006, commander.md Post-Dispatch Protocol, state.json endocrine_phase

**Finding**: assumptions.md A-006 states "All required hooks exist in Phase 3 command set" and is marked [validated]. This is factually correct in isolation (the commands exist in endocrine.sh lines 686-810). However, the [validated] status is misleading because:

1. The COMMANDER post-dispatch protocol (commander.md lines 226-234) calls only `decay_hormones` — NOT `on_gate_pass`, `on_gate_fail`, or `on_quality_improvement`. Phase 3 commands are available in endocrine.sh but not called from COMMANDER.

2. state.json confirms `endocrine_phase: 1`. Phase 3 is documented as not yet active.

3. CA overlay integration (Goal Stack, LIDA Broadcast) requires COMMANDER architecture changes, not just hook additions. The assumption that "wiring is purely at COMMANDER.md level" is correct for NS-003 but materially understates the scope for later CA overlays.

**Required action**: SYNTHESIZER must correct assumptions.md A-006 status from [validated] to [partially validated — hooks exist in endocrine.sh; wiring in COMMANDER and Phase 3 activation are outstanding deliverables for spec 017].

**Blocking**: Accurate risk assessment for HOW phase COMMANDER integration design.

---

### IS-006: Commit Hash Lock for Test Codebase Not Specified as Required Deliverable

**Raised by**: SAGE (WHY1)
**Related to**: A-005, ns003-experiment-design.md Section 8, u-ca-004-experiment-spec.md reproducibility

**Finding**: Both ns003-experiment-design.md and u-ca-004-experiment-spec.md use the test codebase at `/Users/ladislavbihari/myWork/competition/.specify/extensions/echelon/`. Neither specifies a commit hash for the codebase. The reproducibility requirement (Section 8: "use the same test codebase") cannot be met without a commit hash.

**Required action**: HOW phase must add "lock test codebase to commit hash and record in experiment metadata" as an explicit task deliverable. The hash must be recorded before either experiment begins.

---

### IS-007: RSK-010 Underclassified — FPCR Metric Validity is CRITICAL Not MEDIUM

**Raised by**: SAGE (WHY1)
**Related to**: risks.md RSK-010, SUSP-001, contradictions-and-gaps.md

**Finding**: RSK-010 (FPCR conflates schema coverage with artifact quality) is classified MEDIUM. SAGE reclassifies this to CRITICAL because:

1. It is not a risk — it is a structural certainty. JSON Schema cannot validate unstructured prose. The FPCR measurement will, by design, measure only structured-field compliance.

2. If prose content exceeds 40% of DISCOVER and WHY artifacts (highly probable — these agents produce reasoning sections), then FPCR ≥ 0.80 on structured fields is consistent with widespread prose-level scope violations that the Critic would not detect. This means a PASS verdict for NS-003-A is compatible with low actual artifact quality.

3. This directly affects the patent novelty claim validity: if FPCR is a partial quality signal, NS-003's claim to "improve artifact compliance" is overstated.

**Required action**: SCIENTIST must measure structured-to-prose ratio in runs 015-016 BEFORE Phase 1 schema design. If prose fraction > 40% in any agent type, the experiment report MUST include a coverage limitation section, and the NS-003-A schemas should include lightweight prose-structure checks (required section headers present) as a supplementary signal.

---

## MEDIUM Issues

### IS-008: "BANZAI Mode" Undefined in Glossary

**Raised by**: SAGE (WHY1)

**Finding**: "BANZAI mode" is used in state.json, user-intent.md, and reasoning journal entries without a formal definition in glossary.md. Key undefined properties: what decisions can be made autonomously, what decisions require escalation despite BANZAI, whether BANZAI mode can override constitutional principles.

**Required action**: WHAT agent must add BANZAI mode to glossary.md with explicit scope definition.

---

### IS-009: ANTHROPIC_API_KEY Propagation into Subagent Environment Not Confirmed

**Raised by**: SAGE (WHY1)
**Related to**: A-002, U-002

**Finding**: NS-003 Generator invocations require SDK authentication. The SDK authentication requires ANTHROPIC_API_KEY to be available in the Python environment. The speckit framework dispatches agents via `claude -p`. If the subagent's environment does not inherit ANTHROPIC_API_KEY from the parent shell, SDK calls will fail silently with authentication errors. This is a distinct failure mode from "SDK not installed."

**Required action**: [domain-expert] inspect extension.yml and the speckit invocation pattern to confirm environment variable inheritance.

---

### IS-010: Circular Dependency Between Phase 1 Calibration and Available Known-Good Samples

**Raised by**: SAGE (WHY1)
**Related to**: A-003, GAP-004, U-007

**Finding**: Phase 1 completion criterion requires known-good samples from runs 008-014. If these are unavailable, the fallback is runs 015-016 or synthetic samples. But this fallback changes the pre-registered Phase 1 completion criterion ("known-good samples from prior Echelon runs (runs 008-014)") without formal documentation. Under the reproducibility requirement (Section 8), this would require the fallback to be documented in the experiment report as a deviation from the pre-registered method.

**Required action**: HOW phase must design the Phase 1 calibration fallback explicitly, document it as a pre-registered deviation if runs 008-014 are unavailable, and include the fallback criteria in the experiment report template.

---

*Issues IS-001 through IS-010 registered by SAGE (WHY1). COMMANDER routes resolution to responsible agents. SAGE does not fix — SAGE reports.*

---

## WHY2 Issue Register (Spec-Validation — Post-WHAT)

| ID | Severity | Title | Status | Owner |
|----|----------|-------|--------|-------|
| IS-011 | CRITICAL | Three Understanding quality gates FAIL — spec blocked from HOW | RESOLVED_CARTOGRAPHER (SAGE verifies: Overall 70.29% ✓, Structure 71.76% ✓, Testability 70.13% ✓) | CARTOGRAPHER |
| IS-012 | CRITICAL | FR-NS3B-003 AGM postulates untestable as written — no reference implementation or falsifiability criterion | RESOLVED_CARTOGRAPHER (SAGE verifies: consistency predicate, minimality definition, K*3/K*5 out-of-scope statement, and concrete test oracle all present in FR-NS3B-003) | CARTOGRAPHER |
| IS-013 | HIGH | NFR-REPRO-001 (FPCR ±0.05 reproducibility) is infeasible with non-deterministic Claude API | RESOLVED_CARTOGRAPHER (SAGE verifies: NFR-REPRO-001 downgraded to SHOULD, temperature=0 documented, best-effort target for prose component, deterministic Critic component bound separated) | CARTOGRAPHER |
| IS-014 | HIGH | FR-NS3E-001 N=30 source ambiguity — "live invocations or existing artifacts" creates two incompatible experimental designs | RESOLVED_CARTOGRAPHER (SAGE verifies: FR-NS3E-001 now defines "live invocations unavailable" as API quota exhausted or key absent, labels historical_artifacts fallback as DEVIATION in both results file and report) | CARTOGRAPHER |
| IS-015 | HIGH | FR-CAO conditionality not enforced at requirement level — no explicit gate-check requirement exists | RESOLVED_CARTOGRAPHER (SAGE verifies: FR-CAO-000 added — gate-check service verifies uca004-results.json exists, verdict=POSITIVE, commit hash matches before any scripts/ca/ file is created; cross-referenced in NFR-SCOPE-001) | CARTOGRAPHER |
| IS-016 | HIGH | OQ-001 deferral is insufficient — pre-commit mode feasibility directly affects spec scope and patent claim | RESOLVED_CARTOGRAPHER (SAGE verifies: FR-NS3B-004 now includes explicit downgrade path — if pre-commit infeasible: (a) remove pre-commit scope, (b) amend Section 1 novelty claim, (c) HOW ARCHITECT documents ADR before implementation) | CARTOGRAPHER |
| IS-017 | MEDIUM | AQS dimension mismatch: spec uses 5 dimensions (0-5 scale), glossary.md defines 4 dimensions (0-3 scale) | RESOLVED_CARTOGRAPHER (SAGE verifies: glossary.md AQS entry now states five-dimension/0-5 definition is authoritative per P-021; four-dimension definition flagged as superseded pre-P-021 rubric) | CARTOGRAPHER |
| IS-018 | MEDIUM | FR-CAO-003 (LIDA Broadcast) missing consume semantics — single-use vs cumulative payload undefined | RESOLVED_CARTOGRAPHER (SAGE verifies: FR-CAO-003 now specifies payload consumed and deleted at start of next dispatch cycle; no subsequent dispatch = discard at run end; subsequent calls within same step replace not append) | CARTOGRAPHER |
| IS-019 | MEDIUM | FR-UCA-004/005 statistical edge case unspecified — behavior when N < 20 invocations complete | RESOLVED_CARTOGRAPHER (SAGE verifies: FR-UCA-ERR-002 added — N<16 completions = VOID verdict, not NEGATIVE; no Mann-Whitney on N<16; FR-UCA-005 cross-references VOID rule) | CARTOGRAPHER |
| IS-020 | MEDIUM | Structure gate failure: completeness_score 0.083 — tabular FR format incompatible with actor-action-object parsing | RESOLVED_CARTOGRAPHER (SAGE verifies: Understanding re-run shows Structure 71.76% ✓ — actor-action-object patterns improved sufficiently to pass gate) | CARTOGRAPHER |
| IS-021 | LOW | Glossary term "BANZAI Mode" added in spec Section 10 but not synchronized to glossary.md | RESOLVED_CARTOGRAPHER (SAGE verifies: BANZAI Mode now present in glossary.md Primary Terms section with full definition, disambiguation, sources, and conflicts fields) | CARTOGRAPHER |
| IS-022 | LOW | A-001 contradiction: spec FR-NS3A-003 requires Critic to use Claude API, but assumption A-001 states Critic is deterministic/no LLM | RESOLVED_CARTOGRAPHER (SAGE verifies: glossary.md Generator-Critic entry and FR-NS3A-003 now consistent — API is used by the Generator LLM, not by the deterministic Critic validator; A-001 validated status confirmed accurate) | CARTOGRAPHER |

---

## WHY2 CRITICAL Issues

### IS-011: Three Understanding Quality Gates FAIL — Spec Blocked from HOW

**Raised by**: SAGE (WHY2)
**Understanding scores**: Overall 0.6797 (gate 0.70 FAIL), Structure 0.6875 (gate 0.70 FAIL), Testability 0.6515 (gate 0.70 FAIL)
**Mode**: understanding-cli (deterministic — not heuristic)

**Finding**: The Understanding tool ran successfully against spec.md and returned failing scores on three gates. Per constitution P-008: "If overall < 0.60 at any gate: BLOCKED." Overall is 0.6797 — above the BLOCKED floor but below the PASS gate (0.70). The spec must not proceed to HOW until CARTOGRAPHER raises all three failing gates above threshold.

**Root causes identified**:
1. Structure fails primarily on `completeness_score = 0.083` — the tabular FR format suppresses actor-action-object triples that Understanding's parser expects. The requirement table rows lack explicit "The [actor] SHALL [action] [object]" patterns.
2. Testability fails primarily on `negative_space_coverage = 0.111` — only ~14 of 128 requirements address error paths, boundary conditions, or exclusions.
3. Overall is dragged by the above plus `trigger_presence = 0.344`, `outcome_presence = 0.508`, and `cross_reference_index = 0.038`.

**Required action**: CARTOGRAPHER must:
- Add error path requirements for NS-003-A (API auth failure mid-batch, malformed schema file, empty artifact), NS-003-B (malformed assertion, undefined field consistency rule, partial BeliefGraph write), and U-CA-004 (AQS score out-of-range, N < 20 completions, timeout handling).
- Either reformat FR table rows to include explicit actor-action-object structure, or add summary ACC-style sentences beneath table rows.
- Re-run Understanding after amendments; must achieve Overall ≥ 0.70, Structure ≥ 0.70, Testability ≥ 0.70 before HOW phase begins.

**Blocking**: HOW phase. COMMANDER must not dispatch ARCHITECT until re-validation passes.

---

### IS-012: FR-NS3B-003 AGM Postulates Untestable as Written

**Raised by**: SAGE (WHY2)
**Requirement**: FR-NS3B-003 (AGM postulates for minimal revision K*2)
**Related to**: Spec challenge area FR-NS3B (AGM belief revision)

**Finding**: FR-NS3B-003 lists four AGM postulates by name — Success, Consistency, Relevance, Vacuity — with prose descriptions. This is academically correct but operationally untestable in its current form. Specific problems:

1. **"Minimal contraction" is undefined operationally.** The spec states K*2 without defining what "minimal" means in the context of this specific domain (Markdown assertion graphs). AGM minimality is formally defined via epistemic entrenchment orderings or selection functions — neither is specified. A developer cannot write a passing test for "minimal" without knowing the ordering criterion.

2. **The four postulates as stated cannot be independently tested.** "Consistency (the revised belief set is internally consistent)" — what constitutes internal consistency for this belief set? There is no consistency predicate defined for BeliefNodes. Is it field_identifier uniqueness in the ACTIVE set? Value non-contradiction? Without a predicate, the postulate is aspirational, not testable.

3. **The postulate set is incomplete relative to full AGM.** AGM has six postulates, not four. The spec omits K*3 (Inclusion — no beliefs added beyond p's entailments) and K*5 (Extensionality — logically equivalent inputs produce equivalent revisions). The glossary.md correctly lists all six, but FR-NS3B-003 only implements four. This is either a deliberate scope reduction (which should be documented) or an omission.

4. **No reference implementation or test oracle cited.** A developer implementing this cannot verify correctness without a reference. The Kumiho paper (arxiv:2603.17244) is cited in glossary.md but not in FR-NS3B-003, and Kumiho's implementation details are not referenced.

**Required action**: CARTOGRAPHER must add to FR-NS3B-003 or split into sub-requirements:
- (a) A definition of the consistency predicate for BeliefNodes (e.g., "ACTIVE set has exactly one node per field_identifier at all times").
- (b) A definition of "minimal" in terms of what the module preserves (e.g., "The module removes from ACTIVE only the BeliefNode whose field_identifier matches the incoming assertion — no other nodes are removed or modified").
- (c) Explicit statement that K*3 and K*5 are out-of-scope for v1 (or add them if they are intended).
- (d) A concrete test oracle: given input [X, Y], the revised belief set is [Z].

**Blocking**: NS-003-B testability. SENTINEL cannot write a deterministic test for AGM compliance without this.

---

## WHY2 HIGH Issues

### IS-013: NFR-REPRO-001 Reproducibility Bound (±0.05) Infeasible with Non-Deterministic Claude API

**Raised by**: SAGE (WHY2)
**Requirement**: NFR-REPRO-001 ("FPCR variance ≤ ±0.05 across repeated runs on same commit hash")
**Related to**: Challenge area NFR-REP, A-001

**Finding**: NFR-REPRO-001 requires that re-running the experiment on the same commit hash produces FPCR within ±0.05. This is approximately a 5-percentage-point reproducibility bound. The implementation uses Claude API (model: claude-sonnet-4-6) for NS-003-A Critic evaluation and the Generator invocations. Claude API calls are inherently non-deterministic even with identical inputs — temperature is not set to 0, and even at temperature=0, the API is not guaranteed to return identical outputs across calls.

A-001 states "the Critic is deterministic" — but FR-NS3A-003 explicitly requires the Critic to use the Claude API LLM. If the Critic uses the LLM, the Critic is not deterministic. If A-001 is correct (Critic is a pure JSON Schema validator), then the LLM mentioned in FR-NS3A-003 is the Generator, not the Critic. This distinction matters for reproducibility: a deterministic Critic applied to non-deterministic Generator outputs will produce variable FPCR because the inputs vary, not because the Critic varies.

The ±0.05 bound is therefore either:
- (a) Achievable only if the Generator is run at temperature=0 AND the API determinism holds — neither is guaranteed.
- (b) A bound on what variance is acceptable, with the understanding that reproducibility is approximate — in which case the requirement should state the conditions under which reproducibility is expected.

**Required action**: CARTOGRAPHER must amend NFR-REPRO-001 to specify:
- Whether the Generator runs at temperature=0 (and whether that is a required configuration for the reproducibility claim).
- Whether the ±0.05 bound is a hard requirement (measured and failed if exceeded) or a target (documented but not a PASS/FAIL gate).
- If the Critic uses the Claude API (per FR-NS3A-003), the spec must acknowledge that Critic non-determinism contributes to FPCR variance and adjust the bound accordingly, or clarify that A-001 (deterministic Critic = no LLM in Critic) takes precedence over FR-NS3A-003.

---

### IS-014: FR-NS3E-001 N=30 Source Ambiguity Creates Two Incompatible Experimental Designs

**Raised by**: SAGE (WHY2)
**Requirement**: FR-NS3E-001 ("N=30 Echelon invocations, or uses existing spec artifacts from prior runs as test cases when live invocations are not available")
**Related to**: Challenge area FR-NS3E, A-010

**Finding**: FR-NS3E-001 presents two mutually incompatible data sources as alternatives:
- Option A: 30 live Echelon invocations (the LLM runs and produces outputs; Critic validates in real time).
- Option B: Existing spec artifacts from prior runs (pre-existing Markdown files processed by the Critic post-hoc).

These are not equivalent:
1. FPCR is defined as "invocations accepted on first attempt." Option B artifacts were not produced via the NS-003 Generator-Critic loop — they were produced by unvalidated agents. Applying the Critic to them measures "fraction of prior artifacts that would have passed the Critic," not "fraction of Critic-guided invocations that pass on first attempt." These are different quantities with different meanings for the patent claim.
2. The ns003-experiment-design.md (pre-registered) specifies N=30 live invocations with no post-hoc alternative. Using existing artifacts deviates from the pre-registered protocol, which under A-010 ("sample sizes and protocol are fixed per pre-registered design") would need to be documented as a deviation.
3. The "when live invocations are not available" condition is not defined — what makes them "not available"? API quota, compute cost, time constraint? This triggers the deviation path with no clarity on when it applies.

**Required action**: CARTOGRAPHER must either:
- (a) Remove the alternative (existing artifacts) from FR-NS3E-001 and state that N=30 live invocations are the only valid execution mode. If live invocations are unavailable, the experiment does not run — this is a blocking dependency, not a fallback.
- (b) Define the alternative as a clearly labeled deviation path with explicit documentation requirements: "If the live invocation path is used, the report MUST label the data source and acknowledge the deviation from pre-registered protocol."

---

### IS-015: FR-CAO Conditionality Not Enforced at Requirement Level

**Raised by**: SAGE (WHY2)
**Requirement**: FR-CAO-001 through FR-CAO-006 (CONDITIONAL)
**Related to**: P-020, P-006, NFR-SCOPE-001

**Finding**: The spec correctly marks Scenario 5 as CONDITIONAL and FR-CAO requirements as "Should-Have (CONDITIONAL)." NFR-SCOPE-001 states "Zero CA overlay implementation files committed before POSITIVE verdict." However, there is no functional requirement that enforces the gate check itself. The spec requires:
- The overlays to exist if U-CA-004 POSITIVE (FR-CAO-001 through FR-CAO-006).
- The overlays to not exist if NEGATIVE (NFR-SCOPE-001).
- But NO requirement specifies: "Before any CA overlay implementation file is committed, the system MUST verify that experiments/uca004-results.json exists and contains verdict=POSITIVE."

This gate-check requirement is missing. The IMPLEMENTER (or any developer) has no machine-verifiable gate to check before starting CA overlay work. The condition exists only as documentation — it has no enforcement mechanism in the spec.

**Required action**: CARTOGRAPHER must add a requirement (suggested ID: FR-CAO-000) that specifies the gate check: "Before any FR-CAO-001 through FR-CAO-006 implementation begins, the experiment runner MUST confirm that experiments/uca004-results.json exists, contains verdict=POSITIVE, and that the commit hash in that file matches the current codebase commit. If these conditions are not met, no CA overlay implementation file may be created."

---

### IS-016: OQ-001 Deferral to HOW is Insufficient — Affects MVP Scope and Patent Claim

**Raised by**: SAGE (WHY2)
**Requirement**: FR-NS3B-004 (dual-mode flag), OQ-001
**Related to**: IS-003 (WHY1), challenge area OQ-001

**Finding**: OQ-001 defers the write-time interception mechanism to HOW via a dual-mode flag design in FR-NS3B-004 (pre-commit vs post-hoc). SAGE WHY1 raised IS-003 on this. IS-003 was not closed in the WHAT phase — it was converted to OQ-001 and deferred. This is not a resolution; it is a deferral of a CRITICAL gap.

The problem is that the deferral creates a testability gap at the spec level: FR-NS3B-004 states "Default mode is post-hoc" but the acceptance criteria (AC-2.2) require pre-commit mode to function correctly. If pre-commit mode is infeasible (per IS-003's Model A vs Model B analysis), AC-2.2 cannot be satisfied. But the spec does not specify what happens if pre-commit mode is architecturally infeasible — there is no downgrade path.

Additionally, the patent novelty claim (P-019, section 1 of spec) states "pre-commit, not post-hoc" as the architectural differentiator. If HOW determines that only post-hoc mode is feasible, the novelty claim is materially weakened. The WHAT spec should not assert a claim in the overview that is contingent on an unresolved HOW decision.

**Required action**: CARTOGRAPHER must add to FR-NS3B-004 or as a new requirement: "If HOW-phase investigation (IS-003 / U-012 resolution) determines that pre-commit mode is architecturally infeasible, the spec overview (Section 1) novelty claim must be amended to reflect the actual implementation. HOW MUST document the feasibility verdict in its architecture decision record before any NS-003-B implementation begins."

---

## WHY2 MEDIUM Issues

### IS-017: AQS Dimension Mismatch — 5 Dimensions (spec) vs 4 Dimensions (glossary.md)

**Raised by**: SAGE (WHY2)
**Cross-artifact consistency check**

**Finding**: The spec (FR-UCA-002, Section 6 entity model) defines five AQS dimensions: completeness, consistency, specificity, actionability, innovation — each scored 0-5 (integer). The glossary.md (AQS definition) defines four dimensions: Coherence, Completeness, Scope_Compliance, Internal_Consistency — each scored 0-3. These are different dimension sets, different scales, and different labels. The AQS Evaluation Record entity (Section 6) uses the spec's 5-dimension model. The glossary.md definition is the pre-amendment definition from u-ca-004-experiment-spec.md Section 6 (which P-021 superseded per RJ-017).

Per RJ-017: "The five AQS dimensions in spec 017 (completeness, consistency, specificity, actionability, innovation, each 0-5) are drawn from the P-021 authorized rubric rather than the four-dimension human rubric from u-ca-004-experiment-spec.md Section 6. The constitution amendment is the authoritative source; the experiment spec is superseded for this dimension."

The glossary.md has not been updated to reflect this. A developer reading glossary.md independently of spec.md will implement the 4-dimension/0-3 model, which is wrong.

**Required action**: CARTOGRAPHER must update glossary.md AQS definition to reflect the P-021 rubric (5 dimensions, 0-5 scale) and flag the 4-dimension/0-3 definition as superseded.

---

### IS-018: FR-CAO-003 LIDA Broadcast Consume Semantics Undefined

**Raised by**: SAGE (WHY2)

**Finding**: FR-CAO-003 states "the broadcast payload is stored in a file accessible to COMMANDER during the next dispatch cycle." The requirement does not specify:
- Whether the payload is consumed once (deleted after first COMMANDER read) or retained for all agents in the subsequent cycle.
- What happens if COMMANDER runs multiple dispatch cycles before the payload file is explicitly cleared.
- Whether the payload file is cumulative (multiple broadcasts accumulate) or replaced per broadcast call.

Omitted behavior creates two divergent implementations that both satisfy the requirement as written.

**Required action**: CARTOGRAPHER must add consume semantics to FR-CAO-003: "The payload file is consumed (read and deleted) at the start of the next COMMANDER dispatch cycle. If no subsequent dispatch cycle occurs within the run, the payload file is discarded at run end. Subsequent LIDA Broadcast calls within the same pipeline step replace the payload file — they do not append."

---

### IS-019: FR-UCA-004/005 Statistical Edge Case Unspecified — N < 20 Completions

**Raised by**: SAGE (WHY2)

**Finding**: FR-UCA-004 applies the Mann-Whitney U test to AQS score distributions. FR-UCA-005 classifies POSITIVE if p < 0.05 AND Cohen's d ≥ 0.5. Neither requirement specifies what happens if fewer than N=20 invocations complete per condition due to timeouts or API failures. The Mann-Whitney U test with N < 20 has reduced statistical power — at N=15, the test loses approximately 25% power to detect d=0.5. The POSITIVE/NEGATIVE verdict may be wrong if N is reduced.

**Required action**: CARTOGRAPHER must add a requirement specifying minimum viable N for the statistical test: "If fewer than N=16 invocations complete for either condition, the experiment result is declared VOID and must be re-run. A VOID result is not a NEGATIVE verdict — it does not block CA overlay implementation but also does not authorize it."

---

### IS-020: Structure Gate Failure — Tabular FR Format Incompatible with Understanding Parser

**Raised by**: SAGE (WHY2)
**Score**: completeness_score = 0.083

**Finding**: Understanding's completeness_score measures the presence of complete actor-action-object triples in each requirement. The tabular FR format (table rows with dense prose in a single cell) suppresses the linguistic patterns Understanding uses to detect actor-action-object structure. This is a format-induced score penalty, not a genuine completeness failure for most requirements — the requirements do specify actors, actions, and objects, but in table-cell prose form rather than structured sentence form.

However, several FR requirements genuinely lack explicit actors: FR-NS3B-003 ("The belief revision module implements..."), FR-CAO-004 ("When content is added..."), FR-DEP-001 ("A scripts/requirements.txt file lists..."). These pass modal_strength (they use SHALL-equivalent constructions) but fail actor-presence because "the module," "the system," and "a file" are implicit rather than named actors.

**Required action**: CARTOGRAPHER should add explicit actor labeling to FR table rows that currently use implicit actors. The pattern: "The [named module/script] SHALL [action] [object]" is sufficient to raise completeness_score. A secondary option is adding an actor column to the FR table.

---

## WHY2 LOW Issues

### IS-021: Glossary Term "BANZAI Mode" Not Synchronized to glossary.md

**Raised by**: SAGE (WHY2)

**Finding**: Spec Section 10 defines "BANZAI Mode" in a local glossary additions table. This is correct per IS-008 (WHY1) resolution. However, the term is not added to the domain glossary.md file, which is the canonical term source for downstream agents (HOW, PLAN, BUILD). Agents reading glossary.md will not find BANZAI Mode unless it is added there.

**Required action**: CARTOGRAPHER must add BANZAI Mode to glossary.md using the definition in spec Section 10.

---

### IS-022: A-001 / FR-NS3A-003 Contradiction — Deterministic Critic vs API-Using Critic

**Raised by**: SAGE (WHY2)
**Contradiction type**: assumption_requirement_misalignment

**Finding**: assumption A-001 states: "The Critic in NS-003-A validates agent outputs using a Python JSON Schema validator (jsonschema library) without invoking the Claude API. Pure function: (output, schema) → CriticReport, deterministic and reproducible." The spec Section 9 (Assumptions in Effect) labels A-001 as [validated].

FR-NS3A-003 states: "The schema validator uses the Anthropic Claude API (model: claude-sonnet-4-6) as the Critic LLM."

These directly contradict: A-001 says no Claude API in Critic; FR-NS3A-003 says Claude API is the Critic LLM. One of them is wrong.

The glossary.md Generator-Critic definition ("Critic validates output against a JSON Schema Draft 2020-12 schema using a Python validator — no LLM involvement in the Critic step") supports A-001. The ns003-experiment-design.md Section 7 Phase 2 also supports A-001.

The most likely resolution: FR-NS3A-003 is using "Critic LLM" loosely to mean "the LLM used in the Generator-Critic pipeline" — i.e., the Generator LLM, not the Critic function. The Critic is the deterministic validator; the API is used by the Generator. But this is ambiguous as written.

**Required action**: CARTOGRAPHER must amend FR-NS3A-003 to make clear that the Claude API is used by the Generator (the LLM that produces artifact outputs), not by the Critic (the deterministic JSON Schema validator). Suggested wording: "The schema validator uses the Anthropic Claude API (model: claude-sonnet-4-6) as the Generator LLM that produces artifact outputs for validation. The Critic function itself is a deterministic Python JSON Schema validator (jsonschema library) that does not invoke the API."

---

## Systematic Contradiction Detection (WHY2 — Mandatory Sweep)

Artifacts scanned: spec.md, assumptions.md, unknowns.md, glossary.md, boundaries.md, mental-model.md, constitution.md (v1.1.0), ns003-experiment-design.md (spec 015), u-ca-004-experiment-spec.md (spec 015).
Contradiction types checked: requirement_conflict, assumption_requirement_misalignment, boundary_violation, priority_inversion, acceptance_criteria_conflict.

| # | Type | Artifact A | Artifact B | Description | Severity | Suggested Resolution |
|---|------|-----------|-----------|-------------|----------|---------------------|
| C-001 | assumption_requirement_misalignment | assumptions.md A-001 (Critic is deterministic, no LLM) | spec.md FR-NS3A-003 ("uses Anthropic Claude API as the Critic LLM") | A-001 says no API in Critic; FR-NS3A-003 says API is used by Critic | BLOCKING | IS-022 — clarify Generator vs Critic API usage |
| C-002 | assumption_requirement_misalignment | spec.md NFR-REPRO-001 (FPCR ±0.05 bound) | spec.md FR-NS3A-003 (Claude API used in pipeline) | Non-deterministic API cannot guarantee ±0.05 FPCR across re-runs without temperature=0 specification | WARNING | IS-013 — add temperature specification |
| C-003 | requirement_conflict | spec.md FR-NS3E-001 ("N=30 or existing artifacts") | ns003-experiment-design.md Section 3 (N=30 live invocations, pre-registered, no alternative) | Two valid execution paths produce different quantities; pre-registered design has no fallback | BLOCKING | IS-014 — remove or formally define fallback path |
| C-004 | assumption_requirement_misalignment | glossary.md AQS (4 dimensions, 0-3 scale) | spec.md FR-UCA-002 (5 dimensions, 0-5 scale) | Different AQS definitions; developer following glossary will build wrong scorer | WARNING | IS-017 — update glossary.md AQS entry |
| C-005 | acceptance_criteria_conflict | spec.md AC-4.3 ("INCONCLUSIVE is not a valid verdict state") | spec.md Section 2 In-Scope ("Negative outcome report if U-CA-004 resolves NEGATIVE or INCONCLUSIVE") | Section 2 explicitly anticipates INCONCLUSIVE as an outcome; AC-4.3 and FR-UCA-005 prohibit it as a verdict category | WARNING | Spec Section 2 should read "NEGATIVE (which subsumes INCONCLUSIVE per FR-UCA-005)" |
| C-006 | boundary_violation | spec.md Section 2 Out-of-Scope ("Evaluation of CA overlays 2-5 before ACT-R Typed Buffer experiment completes") | spec.md FR-CAO-001 through FR-CAO-006 (all 5 overlays defined, all CONDITIONAL on single POSITIVE verdict) | Out-of-scope says overlays 2-5 cannot be evaluated before overlay 1 (ACT-R) completes; FR-CAO-001 through FR-CAO-006 define all 5 as activated simultaneously on a single POSITIVE verdict | WARNING | Clarify whether POSITIVE verdict enables all 5 simultaneously or sequentially per A-008 |

**Six contradictions detected** across 9 artifacts. Two are BLOCKING (C-001, C-003); four are WARNING.

---

## Pre-Mortem — WHY2

**Assumption of failure**: The implementation fails because of a spec deficiency. Which deficiency is most likely?

1. **Most likely misimplemented requirement**: FR-NS3B-003 (AGM postulates). "Minimal contraction" has no operational definition. The developer will implement whichever interpretation comes naturally — most likely "delete the older node" (which violates Vacuity) or "always accept the newer assertion" (which violates Relevance). The result passes unit tests but violates the AGM postulate the patent claim depends on. **Probability: HIGH.**

2. **Most likely acceptance criterion to pass incorrectly**: AC-3.3 (FPCR ±0.05 reproducibility). An implementer who runs the experiment twice and gets 0.78 and 0.82 will note the 0.04 gap is within ±0.05 and call AC-3.3 satisfied — without noticing that the 0.82 result crosses the PATENT_GRADE threshold while the 0.78 does not, making the verdict unstable across runs. **Probability: MEDIUM.**

3. **Most likely missing requirement to cause rework**: The missing gate-check requirement for CA overlay implementation (IS-015). A developer in a future sprint will start building CA overlay scripts, reference FR-CAO-001, and not know they need to verify the experiment verdict file first. The rework is discovering that NFR-SCOPE-001 was violated after code was committed. **Probability: HIGH.**

4. **Most likely scope boundary to be violated under deadline pressure**: The out-of-scope statement "Cross-run BeliefGraph persistence — v1 is run-scoped only" combined with FR-CAO-005 (Episodic Memory indexes artifacts temporally and retrieves most recent). An implementer building Episodic Memory will realize it is useless within a single run and implement a minimal cross-run index to make it useful — violating the out-of-scope boundary while technically building a required feature. **Probability: MEDIUM.**

---

*Issues IS-011 through IS-022 registered by SAGE (WHY2). COMMANDER routes amendment work to CARTOGRAPHER. SAGE does not fix — SAGE reports.*
