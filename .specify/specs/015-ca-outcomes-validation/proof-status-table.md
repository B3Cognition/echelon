# Proof Status Table — Spec 015
**Agent**: ARCHITECT (HOW) | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Covers**: All 17 rows from mental-model.md Section 4 (Proof Topology Table)
**Status**: REQ-015-001 deliverable

---

## Proof Status Table (17 Rows)

| # | Claim ID | Claim Summary | Primary Evidence Source | Evidence Grade | Proof Category | Proof Status | What Would Constitute Full Proof |
|---|----------|---------------|------------------------|----------------|----------------|--------------|----------------------------------|
| 1 | NS-003-A | Generator-Critic achieves 86%+ schema compliance | arxiv:2510.09355 (NL2GenSym) | A | P1 | PROVEN (component level, NL2GenSym) / PARTIAL (Echelon-specific) | First-pass compliance rate ≥ 0.80 on Echelon artifact protocol schema across N=30 agent invocations on the Echelon extension test codebase, using a deterministic Critic with machine-parseable schemas for all 6 analysis-tier agent output types |
| 2 | NS-003-B | AGM belief revision achieves 93.3% contradiction catch accuracy | arxiv:2603.17244 (Kumiho) | A | P1 | PROVEN (component level, Kumiho) / PARTIAL (Echelon-specific) | Contradiction catch rate ≥ 0.80 on a labeled test set of N=20 artificially contradicted Echelon artifact pairs, with false positive rate ≤ 0.20, revision producing AGM-consistent belief graph |
| 3 | NS-003-C | Generator-Critic + AGM belief revision combination has no prior literature | Systematic search: U-015-002-novelty-search.md (8 query variants, Google Scholar proxy + Semantic Scholar, 2026-04-02) | B | P2 | NOVELTY CONFIRMED as of 2026-04-02 systematic search. No prior work found combining execution-grounded Generator-Critic with AGM belief revision in multi-agent artifact store context | Reproduction of the U-015-002 search on Semantic Scholar native API (not proxy) with zero-result confirmation; additionally: exhaustive ACL Anthology + AAAI proceedings search using the exact query from AC-002-001; phrasing per AC-002-003: this constitutes "no prior literature found in the reviewed corpus," not a universal no-existence claim |
| 4 | NOVEL-004 (mechanism) | Upstream predictions gate downstream LLM calls to reduce token cost | arxiv:2211.17192 (Speculative Decoding, analog); Rao & Ballard 1999 (theoretical) | C (direct), A (structural analog) | P3 | NOT PROVEN — no direct measurement for agent-level prediction. Speculative Decoding analogy is structural, not identical. No prototype run exists. | Prototype: measure prediction accuracy rate across N=10+ Echelon runs; prediction accuracy ≥ 40% (break-even per REQ-015-007 formula); net token reduction > prediction-generation overhead; measured with instrumented token counters |
| 5 | NOVEL-004 (40-70% token reduction) | NOVEL-004 reduces tokens 40-70% for repeated codebases | No source | — | P5 | SPECULATION: no empirical grounding | Prototype measurement with instrumented token counters across N=50+ runs; break-even analysis against prediction-generation overhead; N=50 is the minimum to upgrade this label |
| 6 | CA Overlay — Goal Stack | Soar-inspired goal stack reduces COMMANDER routing failures | ADaPT (NAACL Findings 2024, SRC-B2, analogy); CoALA (arxiv:2309.02427, SRC-B1) | B (weak) | P4 | GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001) | U-CA-004 resolves POSITIVE (Condition C AQS exceeds Condition B by ≥ 10 pp, p < 0.05); plus: measurable reduction in COMMANDER routing failure rate with goal stack active, on labeled agent dispatch evaluation set; goal stack must specify tier-level vs agent-level granularity per U-015-007 Finding 1 |
| 7 | CA Overlay — ACT-R Typed Buffer | ACT-R-inspired context ordering reduces tokens per agent call | "Lost in the Middle" (Liu et al. 2023, SRC-A4); LLM-ACTR (AAAI-SS 2024, SRC-B3, blocked) | A (for context non-uniformity problem), B (for mechanism) | P4 | GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001) | U-CA-004 resolves POSITIVE; plus: token reduction per agent call ≥ 20% vs full artifact concatenation on same-LLM same-task comparison; buffer granularity decision (7 tier-level vs up to 42 agent-level buffers per U-015-007 Finding 2) must be documented before measurement |
| 8 | CA Overlay — LIDA Broadcast | LIDA-inspired broadcast reduces missed critical findings rate | Franklin et al. 2014 LIDA specification; CoALA (SRC-B1) | C | P4 | GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001) | U-CA-004 resolves POSITIVE; plus: measurable reduction in missed critical findings rate; requires: (a) labeled evaluation of prior runs for missed findings baseline (REQ-015-004), (b) broadcast implementation with NS-003 Critic serialization per ADR-004 |
| 9 | CA Overlay — GWT Bounded Workspace | GWT-inspired workspace constraint reduces scope violations | Baars 1988 GWT; CoALA (SRC-B1) | C | P4 | GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001) | U-CA-004 resolves POSITIVE; plus: scope violation rate reduction ≥ 15% vs expert-prompt baseline; requires scope violation baseline from REQ-015-004 before reduction can be measured |
| 10 | CA Overlay — Episodic Memory | Episodic memory enables prior-run artifact reuse | MemGPT (Grade B); CoALA (SRC-B1) | B | P4 | GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001) | U-CA-004 resolves POSITIVE; plus: artifact retrieval precision > random baseline; requires: content-addressing scheme defined, prior run corpus indexed, retrieval precision measured across N=5+ distinct codebase pairs |
| 11 | AC-3 Constraint Propagation | AC-3 arc consistency reduces logically impossible agent outputs | Mackworth 1977; Bessiere 2006 CSP literature (SRC-C2) | C (for LLM semantic constraint injection) | P2 | PROVEN for CSP domain / NOT PROVEN for LLM semantic constraint injection | Prototype: measure logically inconsistent agent output rate with vs without constraint certificate injection, on labeled test set; target: > 20% reduction in inconsistency rate; evaluation must distinguish schema violations (NS-003-A scope) from semantic constraint violations (AC-3 scope) |
| 12 | Use case — ASSESS contradicts DISCOVER: caught at write-time | NS-003 design catches ASSESS-vs-DISCOVER contradictions before commit | arxiv:2510.09355 (SRC-A1); arxiv:2603.17244 (SRC-A2); combination design | A (components), B (combination) | P2 | SUPPORTED BY DESIGN — NS-003 Critic consistency check and belief graph are explicitly designed to catch this violation mode | Integration test: inject known contradictory ASSESS artifact (asserting value X for a field where DISCOVER asserted value Y across 20 pairs); measure whether ConflictSignal fires before commit for ≥ 80% of pairs; binary PASS/FAIL per injection |
| 13 | Use case — 40-70% token reduction for repeated codebases | Running Echelon on same codebase repeatedly reduces tokens 40-70% | No source | — | P5 | SPECULATION: no empirical grounding | Same requirement as NOVEL-004 token reduction row: N=50+ prototype runs with instrumented token counters; this label cannot be upgraded by retrospective analysis alone |
| 14 | Use case — WHY rejects spec 3x → COMMANDER knows in advance | Goal stack tracks WHY rejection history; COMMANDER adapts routing in advance | Goal Stack design (ADaPT SRC-B2 analogy); CoALA (SRC-B1) | C | P4 | GATE-CONDITIONED on U-CA-004 | U-CA-004 resolves POSITIVE (Goal Stack variant); plus: prototype demonstrates COMMANDER reads goal stack state and modifies dispatch before the third rejection, on labeled sequence of WHY rejection events (N=10+ labeled sequences) |
| 15 | Use case — ACT-R buffer delivers only relevant context | ACT-R typed buffer eliminates irrelevant context from agent prompts | "Lost in the Middle" (SRC-A4) — establishes problem; no source for solution | A (for attention non-uniformity problem), C (for buffer solution) | P4 | GATE-CONDITIONED on U-CA-004. PARTIALLY SUPPORTED — the problem (LLM attention non-uniformity) is Grade A proven; the typed buffer as solution requires prototype | U-CA-004 resolves POSITIVE (ACT-R Typed Buffer variant); plus: context ordering experiment comparing agent outputs (AQS score) with typed buffer vs full artifact concatenation on same-LLM same-task (N=20 pairs); buffer granularity decision per U-015-007 Finding 2 must precede measurement |
| 16 | Use case — Critical findings missed → LIDA Broadcast | LIDA broadcast propagates critical findings to all relevant agents | LIDA (Franklin et al. 2014, theoretical) | C | P4 | GATE-CONDITIONED on U-CA-004 | U-CA-004 resolves POSITIVE; plus: labeled evaluation of prior Echelon runs establishes baseline missed-critical-finding rate (REQ-015-004); prototype demonstrates that broadcast reduces that rate by ≥ 15% on the same labeled corpus |
| 17 | Use case — Prior run reuse via episodic memory | Episodic memory enables retrieval and reuse of prior run artifacts | MemGPT (Grade B); CoALA (SRC-B1) | B | P4 | GATE-CONDITIONED on U-CA-004 | U-CA-004 resolves POSITIVE; plus: retrieval precision experiment across prior run corpus (runs 008-014 minimum); precision > random baseline with cosine similarity or equivalent content-addressing scheme; content-addressing scheme must be defined before measurement |

---

## Summary by Proof Category

### P1 — Proven by Paper (Grade A empirical support on comparable task)
- NS-003-A (Generator-Critic, NL2GenSym, 86%+ compliance)
- NS-003-B (Belief Revision, Kumiho, 93.3% accuracy)

*Note*: Both P1 rows carry a PARTIAL qualifier for Echelon-specific deployment. The component-level proof is by paper. Echelon-specific proof requires the NS-003 prototype experiment (REQ-015-006).

### P2 — Proven by Design (Grade B evidence; logical consequence of well-established CS/formal method)
- NS-003-C (Novelty of combination — confirmed by systematic search, no prior art found)
- AC-3 (Constraint Propagation — proven in CSP domain; requires prototype for LLM semantic analog)
- Use case: ASSESS contradicts DISCOVER caught at write-time (supported by NS-003 design logic; requires integration test)

### P3 — Requires Prototype (Grade C or structural analog; no direct measurement)
- NOVEL-004 mechanism (Predictive Coding inter-agent protocol; Speculative Decoding is a structural analog, not equivalent)

### P4 — Gate-Conditioned (Cannot be evaluated without U-CA-004 resolving positively)
- CA Overlay — Goal Stack
- CA Overlay — ACT-R Typed Buffer
- CA Overlay — LIDA Broadcast
- CA Overlay — GWT Bounded Workspace
- CA Overlay — Episodic Memory
- Use case: WHY rejects spec 3x → COMMANDER knows in advance
- Use case: ACT-R buffer delivers only relevant context
- Use case: Critical findings missed → LIDA Broadcast
- Use case: Prior run reuse via episodic memory

### P5 — Speculation (Directionally motivated; quantitative range has no empirical grounding)
- NOVEL-004 40-70% token reduction
- Use case: 40-70% token reduction for repeated codebases

---

## Notes on Evidence Grade Assignments

**Grade A** — Peer-reviewed or preprint with measured results on a comparable task: NL2GenSym (arxiv:2510.09355), Kumiho (arxiv:2603.17244), "Lost in the Middle" (Liu et al. 2023), Speculative Decoding (arxiv:2211.17192), MAP (Webb et al., Nature Communications 2025).

**Grade B** — Peer-reviewed framework or results with weak task match: CoALA (arxiv:2309.02427), ADaPT (NAACL Findings 2024), MemGPT, U-015-002 systematic search record (evidence boundary stated per AC-002-003).

**Grade C** — Theoretical motivation or structural analogy without LLM-agent empirical measurement: Rao & Ballard 1999, Mackworth 1977, Bessiere 2006, Franklin et al. 2014 LIDA, Baars 1988 GWT.

**Grade D / No Source** — Gate experiment not run or no evidence at all: U-CA-004 (not yet run), NOVEL-004 40-70% token reduction (no source).

---

## AC Compliance Verification

- **AC-001-001**: 17 rows present, one per claim from mental-model.md Section 4. Rows 5 and 13 are the two SPECULATION rows. Confirmed.
- **AC-001-002**: All rows contain claim identifier, evidence source (arxiv ID or citation), evidence grade, proof category, proof status, and "What Would Constitute Full Proof" (non-empty for all non-P1 rows). Confirmed.
- **AC-001-003**: Rows 5 and 13 carry "SPECULATION: no empirical grounding" verbatim. Not softened to "probable" or "supported." Confirmed.
- **AC-001-004**: Rows 6, 7, 8, 9, 10 (all five CA overlays) carry "GATE-CONDITIONED on U-CA-004 (blocking ref: U-015-001)" in proof status. Confirmed. (TASK-010 correction: U-015-001 blocking reference added per AC-001-004.)
- **AC-001-005**: Rows 1 and 2 carry "PROVEN (component level) / PARTIAL (Echelon-specific)" and cite arxiv:2510.09355 and arxiv:2603.17244 respectively. Confirmed.
