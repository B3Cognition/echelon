# Domain Glossary — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: SYNTHESIZER (FUSE) | **Date**: 2026-04-03 | **Supersedes**: SCOUT glossary.md (retained as glossary-scout.md for traceability)

---

## Synthesis Note

All terms below are merged from three source layers:
- **NS-003**: `ns003-experiment-design.md` (pre-registered experiment design for spec 015, governing NS-003 formal PASS/FAIL criteria)
- **U-CA-004**: `u-ca-004-experiment-spec.md` (CA overlay gate experiment spec)
- **CA Overlay**: `novelty-catalogue-final.md`, `agents/control/commander.md`, `scripts/bash/endocrine.sh` (existing system context)

Conflicts between sources are flagged inline. No conflicts are resolved here — they are surfaced for WHY1.

---

## Primary Terms

### BANZAI Mode
- **Definition:** Fully autonomous execution mode for the Echelon cognitive squad with no human in the loop for routine decisions. In BANZAI mode, agents make all routine routing, scoring, and artifact-writing decisions autonomously within the bounds of the active constitution. Human escalation is triggered only for: (1) BLOCKED states (a critical dependency cannot be resolved autonomously), (2) constitutional violations (any action that would breach P-001 through P-022), and (3) CRITICAL issue resolution (issues at CRITICAL severity in the issue register where the resolution requires human authority). BANZAI mode does NOT override constitutional principles — P-001 through P-022 remain fully in force regardless of BANZAI activation. BANZAI mode does NOT grant agents authority to resolve CRITICAL WHY1/WHY2 issues autonomously — those are routed to the issue register for human decision.
- **Sub-component:** Echelon squad orchestration (COMMANDER). Activation state stored in state.json under `squad_mode`.
- **Disambiguation:** BANZAI mode is an execution policy, not a capability expansion. It removes routine human checkpoints but does not change what agents are constitutionally permitted to do. Contrast with HUMAN-ASSISTED mode where human confirmation is requested at each phase gate.
- **Sources:** [state] `state.json` squad_mode field; [spec 017] spec.md Section 10; [constitution] P-001 through P-022 (all in force during BANZAI mode)
- **Conflicts:** None — BANZAI mode is newly defined here per IS-008 and IS-021 resolution.

### AGM Belief Revision
- **Definition:** A formal framework for updating a belief set K when a new proposition p is incorporated and p contradicts a belief in K. The six AGM postulates (Alchourrón-Gärdenfors-Makinson 1985) constrain any rational revision operation: Success (p always enters K*p), Inclusion (no beliefs added beyond p's entailments), Vacuity (unchanged when consistent), Consistency (K*p consistent if p consistent), Extensionality (logically equivalent inputs produce equivalent revisions). Minimal change (K*3) is operationalized by retaining the superseded node with a SUPERSEDED flag rather than deleting it.
- **Sub-component:** NS-003-B (belief revision component of the self-correcting artifact store). Used to resolve ConflictSignal events.
- **Disambiguation:** AGM revision is deductive and consistency-preserving, not Bayesian/probabilistic. Also distinct from "overwrite last-write-wins," which violates K*3 and K*5.
- **Sources:** [standard] Alchourrón et al. 1985; [NS-003] `ns003-experiment-design.md` Section 7 Phase 3; [external] arxiv:2603.17244 (Kumiho, 93.3% accuracy on LoCoMo-Plus)
- **Conflicts:** None.

### AQS (Artifact Quality Score)
- **Definition [SUPERSEDED for U-CA-004 by P-021 — see amended definition below]:** A composite score in [0.0, 1.0] computed as `(Coherence + Completeness + Scope_Compliance + Internal_Consistency) / 12`. Each of the four dimensions is scored 0-3 on anchored scales. Coherence: internal logical non-contradiction. Completeness: all expected content sections populated. Scope Compliance: no out-of-phase assertions. Internal Consistency: no contradictions with prior pipeline stage artifacts. **This four-dimension/0-3-scale definition reflects the pre-P-021 human-evaluator rubric and is SUPERSEDED by the following amendment for all U-CA-004 experiment scoring.**
- **Definition [Amended per P-021 — authoritative for U-CA-004]:** A composite score in [0.0, 1.0] computed as `(completeness + consistency + specificity + actionability + innovation) / 25`. Five dimensions, each scored as an integer in [0, 5] by the AQS Proxy Scorer LLM judge. Completeness: all expected content sections populated. Consistency: internal logical non-contradiction and alignment with prior stage artifacts. Specificity: assertions are concrete and measurable, not vague. Actionability: requirements and findings can be acted upon by a developer without additional clarification. Innovation: the artifact reflects novel insight beyond baseline Echelon behavior.
- **Sub-component:** U-CA-004 primary evaluation metric (Conditions A/B/C). Defined in `u-ca-004-experiment-spec.md` Section 6, amended per constitution P-021.
- **Disambiguation:** AQS evaluates artifact quality within a single run; it does not measure cross-run efficiency or token counts. SVR (Scope Violation Rate) is a companion metric. The automated AQS Proxy Scorer (P-021) replaces human evaluators for U-CA-004 — it is not applicable to other experiment types without explicit authorization.
- **Sources:** [U-CA-004] `u-ca-004-experiment-spec.md` Section 6; [spec 017] spec.md Section 10; [constitution] P-021
- **Conflicts:** The four-dimension/0-3 definition (pre-P-021) and the five-dimension/0-5 definition (post-P-021) are both present in source documents. P-021 governs: the five-dimension/0-5 definition is authoritative for all U-CA-004 scoring.

### Artifact Store
- **Definition:** The collection of structured Markdown artifacts produced across all pipeline stages within a single Echelon spec run. Organized by agent pipeline stage: DISCOVER (glossary.md, mental-model.md, boundaries.md, assumptions.md, unknowns.md), ASSESS (feasibility.md, risks.md, estimates.md), HOW (spec.md, data-model.md, test-strategy.md), PLAN (tasks.md, plan.md), BUILD/FINALIZE (ground-check.md, learnings.md). Each artifact is written by one stage and read by subsequent stages.
- **Sub-components:** Used by NS-003 (write-time validation target) and U-CA-004 (analysis context for AQS evaluation).
- **Disambiguation:** Distinct from endocrine state (hormone scalars in state.json) and from the knowledge base (patterns.yaml, calibration-profile.yaml).
- **Sources:** [NS-003] `ns003-experiment-design.md` Section 7; [code] `scripts/contradiction-scanner.py` ARTIFACT_STAGE_MAP lines 52-86
- **Conflicts:** None — both sub-systems agree on the artifact store structure.

### BeliefNode (to be built — NS-003-B)
- **Definition:** The unit of storage in the NS-003-B belief graph. A BeliefNode has: `content` (the assertion text), `source_agent` (which pipeline stage wrote it), `version_counter` (integer, monotonically increasing), `confidence_score` (0.5-0.95 per contradiction type), `field_identifier` (the schema field this assertion populates), `status` (ACTIVE | SUPERSEDED), `superseded_by` edge. On ConflictSignal, the superseded node receives a `SUPERSEDED` flag and a `superseded_by` edge to the new node.
- **Disambiguation:** BeliefNode is a logical concept from the experiment design, not a class in existing code. The closest existing construct is the `Assertion` class in `contradiction-scanner.py` (entity, text, line_no, stage) — but Assertion is ephemeral (computed per scan, not persisted), whereas BeliefNode is persistent across the run.
- **Sources:** [NS-003] `ns003-experiment-design.md` Section 7 Phase 3; [code] `contradiction-scanner.py` lines 149-176
- **Conflicts:** None — BeliefNode is a new concept with no conflicting prior definition.

### CA Overlay (Cognitive Architecture Overlay)
- **Definition:** A prompt engineering addition that structures agent context packs according to a cognitive architecture framework. Five overlays are gate-conditioned under P-006 on the U-CA-004 experiment: (1) Goal Stack — precondition-checking sequential dispatch; (2) ACT-R Typed Buffer — four-buffer context preprocessing (goal_buffer ~200 tokens, retrieval_buffer ≤4,000 tokens, imaginal_buffer variable, stable_buffer ~500 tokens) with activation formula `recency_weight × cosine_similarity`; (3) LIDA Broadcast — concurrent agent invocation; (4) GWT Bounded Workspace — bounded working memory for cross-agent context; (5) Episodic Memory — content-addressed prior run artifact indexing.
- **Disambiguation:** CA overlays are prompt-level modifications external to LLM calls (API-only constraint, ADR-003). They do not require model fine-tuning, weight changes, or learned parameters.
- **Sources:** [U-CA-004] `u-ca-004-experiment-spec.md` Sections 2, 8; [NS-003] `ns003-experiment-design.md` Section 9; [catalogue] `novelty-catalogue-final.md` NOVEL-010
- **Conflicts:** None — all three sources agree on the overlay definitions and testing order.

### ConflictSignal (to be built — NS-003-B)
- **Definition:** An event emitted by the NS-003-B belief graph when a new assertion submitted for a field already populated by a BeliefNode violates the field's consistency rule. Consistency rules by field type: integer fields — contradiction if |new_value - existing_value| > 0; string enum fields — contradiction if new_value ≠ existing_value; categorical fields — contradiction if new_value is logically exclusive with existing_value (per per-field exclusion lists). A ConflictSignal MUST fire BEFORE the contradictory assertion is committed to the artifact store. Post-commit detection does not count as a correct catch in the NS-003-B CCR metric.
- **Disambiguation:** ConflictSignal is a write-time event (pre-commit). The existing `contradiction-scanner.py` fires post-scan — it reads completed artifacts and compares, making it a post-hoc upper-bound detector, not a ConflictSignal emitter. This is the core architectural difference between the heuristic baseline and NS-003-B.
- **Sources:** [NS-003] `ns003-experiment-design.md` Sections 3, 7 Phase 3; [code] `contradiction-scanner.py` lines 393-490 (heuristic detection — baseline, not NS-003)
- **Conflicts:** None — the distinction between ConflictSignal (pre-commit) and Contradiction/contradiction-scanner.py (post-hoc) is clearly delineated across both sources.

### CriticReport (to be built — NS-003-A)
- **Definition:** The structured output of the Critic function (`critic.validate(output, schema, artifact_store) → CriticReport`). Contains: field name, error type (schema violation or cross-artifact inconsistency), and conflicting existing assertion if applicable. On first-pass failure, CriticReport is injected into the retry prompt with the instruction to revise only the fields listed in the violation report. Maximum retries per invocation: 2. After 2 failures, the invocation is marked ESCALATED.
- **Sources:** [NS-003] `ns003-experiment-design.md` Section 7 Phase 2
- **Conflicts:** None.

### Endocrine System (existing, Phase 3 active)
- **Definition:** A real-time agent behavior modulation system that maintains six hormone scalars per agent in [0.0, 1.0]: adrenaline (urgency), dopamine (reward/motivation), cortisol (vigilance), serotonin (stability), oxytocin (collaboration trust), norepinephrine (focus). Hormones are initialized from per-archetype baselines (exploration: [0.3, 0.7, 0.3, 0.6, 0.5, 0.4]; build: [0.7, 0.5, 0.5, 0.4, 0.7, 0.9]). Phase-gated event triggers update hormone values. Decay per cycle: adrenaline 0.6×, serotonin 0.95×. Hormone state is stored in state.json under `endocrine_state.agents`.
- **NS-003 / CA overlay integration point:** NS-003 ConflictSignal events and CA overlay gate outcomes must be wired as endocrine events. The wiring requires only COMMANDER.md changes and endocrine.sh command calls — no structural changes to endocrine.sh itself.
- **Sources:** [code] `scripts/bash/endocrine.sh` lines 83-93, 654-780; `squad-config.yml` lines 469-532; `agents/control/commander.md` Pre-Dispatch Protocol section
- **Conflicts:** None across sub-systems. Both NS-003 and CA overlays treat the endocrine system as a shared integration target.

### FPCR (First-Pass Compliance Rate)
- **Definition:** `FPCR = (invocations accepted by Critic on attempt 1) / (total invocations)`.
- **CONFLICT — CRITICAL:** Two sources define different PASS thresholds for this metric:
  - **Source A** (spec 017 user brief): target ≥ 0.70 first-pass compliance
  - **Source B** (ns003-experiment-design.md Section 6, pre-registered): FPCR ≥ 0.80 = PASS; 0.50 ≤ FPCR < 0.80 = INCONCLUSIVE
  - **Implication:** Under Source B (pre-registered), achieving FPCR = 0.70 is explicitly INCONCLUSIVE, not PASS. These thresholds produce directly contradictory experiment verdicts for any result in [0.70, 0.80). See `contradictions-and-gaps.md` CRIT-001 for full treatment.
- **Sources:** [user] spec 017 brief (0.70); [NS-003] `ns003-experiment-design.md` Section 6 (0.80 pre-registered)

### Generator-Critic (to be built — NS-003-A)
- **Definition:** A two-component pipeline mechanism: Generator produces structured Markdown output conforming to the Echelon artifact protocol; Critic validates output against a JSON Schema Draft 2020-12 schema using a Python validator (no LLM involvement in the Critic step). On Critic rejection, a retry prompt is constructed containing the original prompt, raw LLM output, CriticReport, and targeted correction instruction. Maximum 2 retries per invocation.
- **Disambiguation:** The Critic is NOT an LLM-as-judge. The Critic is a deterministic schema validator (jsonschema library or equivalent). This distinguishes NS-003 from Self-Refine (Madaan et al. 2023) which uses LLM self-critique in prose.
- **Sources:** [NS-003] `ns003-experiment-design.md` Section 7 Phase 2; `novelty-catalogue-final.md` NOVEL-003
- **Conflicts:** None — deterministic Critic is consistently stated across all NS-003 artifacts.

### Mann-Whitney U Test
- **Definition:** A non-parametric statistical test for comparing two independent groups without assuming normal distributions. Used in U-CA-004 to compare AQS values from Condition B (expert prompt) vs Condition C (CA overlay). Significance threshold: p < 0.05, two-tailed. At N=20 per condition, the test has ~80% power to detect an effect size of 0.5 standard deviations.
- **Sources:** [standard] scipy documentation; [U-CA-004] `u-ca-004-experiment-spec.md` Section 4
- **Conflicts:** None.

### P-006 (Human Override Authorization)
- **Definition:** A constitution constraint that gates all five CA overlay implementations on a positive U-CA-004 experiment result. P-006 was authorized 2026-04-03 (spec 017 brief), meaning the human override has been issued to proceed with both the experiment design and the conditional implementation work. P-006 does NOT authorize implementation of CA overlays before the experiment — it authorizes building the experiment infrastructure and conditional implementation artifacts.
- **Sources:** [user] spec 017 brief; [code] `novelty-catalogue-final.md` preamble; [state] `state.json` human_override.p006_ca_overlays = "AUTHORIZED"
- **Conflicts:** None — state.json confirms AUTHORIZED status consistent with spec 017 brief.

### SVR (Scope Violation Rate)
- **Definition:** `SVR = (output sections classified OUT-OF-SCOPE) / (total sections evaluated)`. U-CA-004 POSITIVE criterion 2 requires SVR(Condition C) ≤ SVR(Condition B) × 0.85 (≥15% relative reduction).
- **Sources:** [U-CA-004] `u-ca-004-experiment-spec.md` Section 6
- **Conflicts:** None.

---

## Overloaded Terms (Cross-System Disambiguation)

| Term | Context A | Meaning A | Context B | Meaning B | Resolution |
|------|-----------|-----------|-----------|-----------|------------|
| Contradiction | `contradiction-scanner.py` | Post-hoc heuristic pattern match between adjacent artifact assertions (count/status/boolean mismatch) | NS-003-B | Pre-commit ConflictSignal when new assertion violates BeliefNode consistency rule | Both meanings are valid simultaneously — they describe different points in the pipeline. No conflict, just scope distinction. |
| Critic | NS-003-A | Deterministic JSON Schema validator — no LLM involvement | General AI discourse | LLM-as-judge (explicitly NOT what NS-003 uses) | NS-003 meaning is canonical for this project. Any use of "Critic" in spec 017 = deterministic validator. |
| Compliance | NS-003-A FPCR | Fraction of first-pass schema validations that succeed | Squad/endocrine | Constitution P-004/P-005/P-006 adherence | Context-dependent — always qualified (FPCR vs constitution compliance). |
| Phase | `endocrine.sh` | Endocrine phase (1=adrenaline only, 2=+dopamine/cortisol/nor, 3=all 6 hormones) | Echelon pipeline | Analysis phase (DISCOVER, ASSESS, HOW, PLAN, BUILD, FINALIZE) | Always qualify: "endocrine Phase 3" vs "DISCOVER phase." |
| Gate | U-CA-004 | Binary experiment verdict gate (POSITIVE/NEGATIVE/INCONCLUSIVE) blocking CA overlay implementation | Build pipeline | SPEC_GUARD / CODE_REVIEWER / TEST_GUARDIAN quality gates | Context-dependent — always qualified. |
| Assertion | `contradiction-scanner.py` | Ephemeral factual claim object (entity, text, line_no, stage) — discarded after scan | NS-003-B | Content of a BeliefNode (persistent, schema-field-scoped) | Two different lifecycles — ephemeral vs persistent. NS-003 uses BeliefNode.content for the persistent form. |
