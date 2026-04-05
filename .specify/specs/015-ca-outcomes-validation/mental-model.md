# Mental Model — Spec 015 (CA Outcomes Validation)
**Agent**: SCOUT | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Purpose**: Map the relationships between claims, evidence sources, proof categories, and Echelon pain points. Establish the Proof Topology that clarifies what is already settled vs what requires an experiment.

---

## 1. Claims Map

Six distinct claims from spec 014 require validation:

```
CLAIM-1: NS-003 — Self-Correcting Artifact Store
  └── Component A: Generator-Critic (86%+ schema compliance via NL2GenSym)
  └── Component B: Belief Revision (93.3% vs 45.7% via Kumiho)
  └── Novelty claim: the combination has no prior literature

CLAIM-2: NOVEL-004 — Predictive Coding Broadcast
  └── Token cost reduction: "40-70% (speculation: needs measurement)"
  └── Mechanism: upstream predictions gate downstream LLM calls

CLAIM-3: 5 CA Mechanism Overlays (Gate-Conditioned on U-CA-004)
  └── Goal Stack (Soar-inspired)
  └── ACT-R Typed Buffer
  └── LIDA Broadcast
  └── GWT Bounded Workspace
  └── Episodic Memory

CLAIM-4: AC-3 Constraint Propagation
  └── Pre-generation pruning of logically impossible outputs
  └── Constraint certificate injected into agent context

CLAIM-5: Use case improvements (6 specific assertions)
  └── "40-70% token reduction for repeated codebases" — SPECULATION
  └── "ASSESS contradicts DISCOVER: caught at write-time" — NS-003 design
  └── "WHY rejects spec 3x → COMMANDER knows in advance" — Goal Stack
  └── "ACT-R buffer: only relevant context" — ACT-R overlay
  └── "Critical findings missed → LIDA Broadcast" — LIDA overlay
  └── "Prior run reuse via episodic memory" — Episodic memory overlay

CLAIM-6: Novelty of NS-003 combination (no prior literature)
```

---

## 2. Evidence Sources Map

| Source ID | Source | Type | Grade | What It Supports |
|-----------|--------|------|-------|-----------------|
| SRC-A1 | NL2GenSym (arxiv:2510.09355, Oct 2025) | Preprint with measured results | A | Generator-Critic mechanism, 86%+ schema compliance on Soar rule generation |
| SRC-A2 | Kumiho (arxiv:2603.17244, Mar 2026) | Preprint with measured results | A | Belief revision via AGM postulates, 93.3% vs 45.7% on LoCoMo-Plus |
| SRC-A3 | MAP — Webb et al. (Nature Communications 2025) | Peer-reviewed | A | CA-structured pipeline outperforms GPT-4 CoT on planning tasks; closest CA vs prompting comparison |
| SRC-A4 | "Lost in the Middle" — Liu et al. 2023 | Peer-reviewed | A | LLM attention is non-uniform with context position; validates ACT-R-inspired context ordering rationale |
| SRC-A5 | Leviathan et al. Speculative Decoding (arxiv:2211.17192, 2022) | Peer-reviewed | A | Token throughput 2-3x via predict-then-verify at token level; structural analog for NOVEL-004 |
| SRC-B1 | CoALA (arxiv:2309.02427, TMLR 2024) | Peer-reviewed framework | B | CA vocabulary maps to LLM agents; NOT structural equivalence |
| SRC-B2 | ADaPT (NAACL Findings 2024) | Peer-reviewed | A (its results), B (for CA claim) | Adaptive decomposition ≈ Soar subgoaling analogy; 27-28% gain over ReAct/Reflexion baselines |
| SRC-B3 | LLM-ACTR (AAAI-SS 2024) | Conference proceedings | B | ACT-R injection via residual stream; BLOCKED by API constraint |
| SRC-B4 | Wray, Kirk, Laird (AGI25, arxiv:2505.07087) | Position paper (oral, Soar authors) | B | CA design patterns; explicitly uses "analogy" language, not equivalence |
| SRC-B5 | ACPO (arxiv:2505.16315) | Preprint (peer-review unconfirmed) | B (downgraded from A per ISS-006) | Dual-process architecture; no expert-prompt baseline |
| SRC-C1 | Rao & Ballard 1999 | Classic neuroscience paper | C (for agent-level analog) | Predictive coding in visual cortex; theoretical motivation for NOVEL-004 |
| SRC-C2 | AC-3 / Mackworth 1977; Bessiere 2006 | Classic CS paper | C (for LLM context analog) | CSP arc consistency; theoretical motivation for CLAIM-4 |
| SRC-C3 | Friston 2010 (Free Energy Principle) | Theoretical neuroscience | C (for agent routing analog) | Active Inference framing; theoretical motivation for NOVEL-001 |
| SRC-D1 | U-CA-004 gate experiment | Not yet run | D (INCONCLUSIVE) | CA vs expert prompting on identical tasks — the critical unresolved comparison |
| SRC-D2 | U-CA-009 CA overhead cost analysis | Not yet measured | D (NO DATA) | Net token efficiency of CA mechanisms vs baseline |

---

## 3. Proof Categories

**Category P1 — Proven by Paper**: The component has direct Grade A empirical support on a comparable task. The claim holds as stated, with explicit scope qualifications.

**Category P2 — Proven by Design**: The mechanism is logically coherent and the underlying CS/formal method is well-established. The benefit is a logical consequence of the design, not yet measured in the Echelon-specific context. Grade B evidence. Requires prototype to confirm.

**Category P3 — Requires Prototype**: The mechanism has theoretical motivation (Grade C) and analogical support (Speculative Decoding, Phi-proxy in RAG systems) but no direct empirical measurement for multi-agent LLM pipelines. Requires a prototype run with instrumentation before any verdict.

**Category P4 — Gate-Conditioned**: The claim CANNOT be evaluated without a prerequisite gate experiment resolving. The 5 CA overlays fall here: U-CA-004 must resolve positively before any overlay implementation is justified.

**Category P5 — Speculation**: The claim is directionally motivated but the specific quantitative range (40-70%) has no empirical grounding. The original spec 014 answer explicitly applied this label. Verdict: plausible but not provable without measurement.

---

## 4. Proof Topology Table

| Claim | Primary Evidence | Evidence Grade | Proof Category | Proof Status | What Would Constitute Full Proof |
|-------|-----------------|----------------|----------------|--------------|----------------------------------|
| NS-003-A: Generator-Critic (86%+ compliance) | NL2GenSym (SRC-A1) | A | P1 | PROVEN for rule generation task. PARTIAL for Echelon artifact schema | First-pass compliance rate ≥ 70% on Echelon artifact protocol schema across N=30+ agent invocations on a fixed test codebase |
| NS-003-B: Belief Revision (93.3% accuracy) | Kumiho (SRC-A2) | A | P1 | PROVEN for conversational fact tracking. PARTIAL for multi-stage artifact store | Contradiction catch rate ≥ 80% on a labeled test set of artificially contradicted Echelon artifact pairs, with revision producing AGM-consistent belief graph |
| NS-003-C: Novelty of combination | Literature search (spec 014 research corpus) | B | P2 | SUPPORTED — no prior work combining execution-grounded Generator-Critic with AGM belief revision found across 13+ sources reviewed | Systematic literature review on Google Scholar / Semantic Scholar with search terms {Generator-Critic, belief revision, multi-agent, artifact consistency} returning zero results matching the combination |
| NOVEL-004: Predictive Coding inter-agent protocol | Speculative Decoding (SRC-A5, analog), Rao & Ballard (SRC-C1, theoretical) | C (direct), A (analog) | P3 | NOT PROVEN — no direct measurement for agent-level prediction. Analogy to Speculative Decoding is structural but not identical | Prototype implementation: measure prediction accuracy rate and LLM-call elimination rate across N=10+ Echelon runs on varied codebases. Full proof requires prediction accuracy ≥ 40% (break-even) and net token reduction > AC-3 overhead cost |
| NOVEL-004: 40-70% token reduction | No source | — | P5 | SPECULATION — explicitly labeled in spec 014 original answer | Prototype measurement with instrumented token counters across N=50+ runs; requires break-even analysis against prediction-generation overhead |
| CA Overlay — Goal Stack (U-CA-004 conditioned) | ADaPT (SRC-B2, analogy), CoALA (SRC-B1) | B (weak) | P4 | BLOCKED by U-CA-004 gate experiment not run | U-CA-004 resolves positively (CA-structured > expert-prompt on Echelon tasks) + reduction in COMMANDER routing failure rate with goal stack active |
| CA Overlay — ACT-R Typed Buffer (U-CA-004 conditioned) | "Lost in the Middle" (SRC-A4), LLM-ACTR (SRC-B3, blocked) | A (for context non-uniformity), B (for mechanism) | P4 | BLOCKED by U-CA-004 + API constraint (no residual stream injection) | Token reduction per agent call ≥ 20% vs full artifact concatenation, on same-LLM same-task comparison |
| CA Overlay — LIDA Broadcast (U-CA-004 conditioned) | LIDA (Franklin et al. 2014), CoALA (SRC-B1) | C | P4 | BLOCKED by U-CA-004 | Measurable reduction in "missed critical findings" rate; requires labeled evaluation of prior runs |
| CA Overlay — GWT Bounded Workspace (U-CA-004 conditioned) | Baars 1988 GWT, CoALA (SRC-B1) | C | P4 | BLOCKED by U-CA-004 | Scope violation rate reduction; requires baseline measurement first |
| CA Overlay — Episodic Memory (U-CA-004 conditioned) | MemGPT (SRC, Grade B), CoALA | B | P4 | BLOCKED by U-CA-004 + no content-addressing scheme defined | Artifact retrieval precision > random baseline; requires prior run artifact corpus and embedding index |
| AC-3 Constraint Propagation | Mackworth 1977, Bessiere 2006 (CSP literature) | C (for LLM context analog) | P2 | PROVEN for CSP domain. NOT PROVEN for LLM semantic constraint injection | Prototype: measure logically inconsistent agent output rate with vs without constraint certificate injection, on labeled test set. Target: > 20% reduction in inconsistency rate |
| Use case — "ASSESS contradicts DISCOVER: caught at write-time" | NS-003 design (SRC-A1, SRC-A2 combined) | A (components), B (combination) | P2 | SUPPORTED BY DESIGN — NS-003's Critic consistency check and belief graph are explicitly designed to catch this | Integration test: inject known contradictory artifact pair, measure whether ConflictSignal fires before commit. Binary yes/no measurable. |
| Use case — "40-70% token reduction for repeated codebases" | No source | — | P5 | SPECULATION | Same as NOVEL-004 token reduction above |
| Use case — "WHY rejects spec 3x → COMMANDER knows in advance" | Goal Stack design, CoALA | C | P4 | BLOCKED by U-CA-004 | Goal stack tracks rejection history; requires prototype + U-CA-004 gate |
| Use case — "ACT-R buffer: only relevant context" | "Lost in the Middle" (SRC-A4) | A (problem), C (solution) | P4 | PARTIALLY SUPPORTED — problem is Grade A proven; solution requires prototype | Context ordering experiment: compare agent outputs with typed buffer vs full concatenation |
| Use case — "Critical findings missed → LIDA Broadcast" | LIDA (theoretical) | C | P4 | BLOCKED by U-CA-004 | Labeled evaluation of prior runs for missed critical findings |
| Use case — "Prior run reuse via episodic memory" | MemGPT, CoALA | B | P4 | BLOCKED by U-CA-004 + no content-addressing scheme | Retrieval precision experiment across prior run corpus |

---

## 5. Echelon Pain Point to Claim Mapping

The Echelon codebase analysis reveals these observable pain points. Each CA claim is mapped to the pain point it addresses:

| Pain Point | Evidence in Echelon | Addressing Claim | Baseline Measured? |
|------------|--------------------|-----------------|--------------------|
| Reactive routing (COMMANDER dispatches agents based on fixed sequence + EVOI, no goal tree) | commander.md routing protocol: sequential dispatch with EVOI check; no explicit goal stack or precondition schema | Goal Stack (CA Overlay) | No — routing failure rate unknown |
| Token waste (full artifact concatenation injected as context pack into every agent) | commander.md: "context pack" injected; squad-config.yml: no retrieval budget per call, token_budget_k=999999 (unlimited) | ACT-R Typed Buffer, NOVEL-004 | No — tokens-per-run not measured |
| Scope violations (agents produce off-scope output) | issues.md ISS-001 mentions ASSESS reproducing DISCOVER findings; no automated detection exists | NS-003 Critic (consistency check), AC-3, NOVEL-002 Phi-proxy | No — scope violation rate unknown |
| Artifact contradictions (prior stage assertions contradicted by later stages without detection) | No contradiction detection in current COMMANDER protocol | NS-003 Belief Revision, AC-3 domain emptiness signal | No — contradiction rate unknown |
| Cross-run inefficiency (each run re-analyzes artifacts from scratch) | squad-config.yml: no episodic memory or run-to-run artifact retrieval configured | Episodic Memory (CA Overlay) | No — cross-run overlap rate unknown |
| Critical finding propagation gaps (critical findings may not reach all relevant agents) | COMMANDER routes sequentially; no broadcast mechanism | LIDA Broadcast (CA Overlay) | No — missed finding rate unknown |

---

## 6. Key Structural Relationship

The claims form a dependency tree, not a flat list:

```
NS-003 (CLAIM-1) — Independent. Proven at component level. Requires prototype for Echelon-specific validation.
  └── Enables: AC-3 (CLAIM-4) domain-emptiness → NS-003 revision trigger
  └── Enables: NOVEL-004 (CLAIM-2) prediction acceptance → NS-003 Critic backstop

U-CA-004 gate experiment — GATE for 5 overlays (CLAIM-3)
  └── ALL 5 CA overlay claims depend on this resolving positively
  └── Goal Stack
  └── ACT-R Typed Buffer
  └── LIDA Broadcast
  └── GWT Bounded Workspace
  └── Episodic Memory

NOVEL-004 (CLAIM-2) — Semi-independent. Theoretical + analogy evidence. Requires prototype.
  └── Token reduction claim (40-70%) — SPECULATION within CLAIM-2

AC-3 (CLAIM-4) — Independent of U-CA-004. Proven for CSP domain. Requires prototype for LLM context.
```

NS-003 is the only claim that is independent, has Grade A component evidence, and does not depend on the gate experiment. This is why ADR-001 in spec 014 correctly designated NS-003 as the primary architecture.
