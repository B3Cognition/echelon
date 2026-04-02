# User Intent

**Question**: "Can you prove this outcomes?"
**Mode**: brownfield validation
**Context**: User received spec 014 answer and wants to know: which of these outcomes are already proven by evidence, which require a prototype experiment, and which are speculation?

**Interpretation**:
- "Prove" = classify each claim by its current evidentiary status (proven/testable design/requires experiment/speculation)
- Not asking for new research — asking for a clear verdict on what was already produced
- The 40-70% token reduction explicitly labeled SPECULATION in the original answer — user acknowledged this

**Success for this run**: A clear claim-by-claim proof status table with specific evidence citations or experiment designs for each claim that lacks Grade A evidence.

---

## Claim-by-Claim Proof Status

| Claim | Proof Status | Verdict | Evidence / Next Step |
|-------|-------------|---------|----------------------|
| NS-003-A: Generator-Critic (86%+ compliance) | PARTIALLY PROVEN | Component proven at Grade A by NL2GenSym; NOT yet measured on Echelon artifact schema | Prototype: instrument 20-30 Echelon agent calls with schema validator |
| NS-003-B: Belief Revision (93.3% accuracy) | PARTIALLY PROVEN | Component proven at Grade A by Kumiho; NOT yet measured on Echelon artifact contradictions | Prototype: labeled contradiction test set from prior spec run artifacts |
| NS-003-C: No prior literature for combination | SUPPORTED | No contradicting paper found in 13-source corpus; needs systematic Semantic Scholar search to confirm | 30-min search: ("execution-grounded" OR "schema validation") AND ("belief revision" OR "AGM") AND ("multi-agent") |
| NOVEL-004: Predictive coding inter-agent protocol | REQUIRES PROTOTYPE | Structural analogy to Speculative Decoding (Grade A); theoretical basis from Rao & Ballard; NO direct measurement for agent-level prediction | Prototype: forward model for DISCOVER→ASSESS pair; measure prediction accuracy across prior spec runs |
| NOVEL-004: 40-70% token reduction | SPECULATION | Explicitly labeled as such in spec 014. No measurement. No experiment design sufficient to claim this range. | Requires prototype + N=50+ instrumented runs before any quantitative claim |
| Goal Stack (Soar-inspired) | GATE-CONDITIONED | U-CA-004 not run. Cannot prove until CA-structured pipeline is compared to expert prompting on Echelon task class | Run U-CA-004 gate experiment (4-6 weeks) |
| ACT-R Typed Buffer | GATE-CONDITIONED | "Lost in the Middle" (Grade A) proves the problem (context non-uniformity). Solution unproven. U-CA-004 not run. | U-CA-004 gate + prototype context ordering experiment |
| LIDA Broadcast | GATE-CONDITIONED | Theoretical (Grade C). No empirical support for broadcast vs routing in LLM pipelines. U-CA-004 not run. | U-CA-004 gate; requires agent scope formalization (prerequisite) |
| GWT Bounded Workspace | GATE-CONDITIONED | Theoretical (Grade C). U-CA-004 not run. | U-CA-004 gate |
| Episodic Memory | GATE-CONDITIONED | MemGPT (Grade B) for memory in LLM agents. No embedding index over spec run corpus. U-CA-004 not run. | U-CA-004 gate + embedding index over prior 9 spec runs |
| AC-3 Constraint Propagation | REQUIRES PROTOTYPE | CSP algorithm proven (Grade A). LLM context injection analog is novel — no direct measurement. Provides soft guidance only. | Prototype: constraint certificate injection for DISCOVER→ASSESS; measure violation rate reduction |
| "ASSESS contradicts DISCOVER: caught at write-time" | SUPPORTED BY DESIGN | NS-003's Critic consistency check is explicitly designed for this. Integration test is straightforward once NS-003 is prototyped. | Binary test: inject known contradiction pair; verify ConflictSignal fires before commit |
| "40-70% token reduction for repeated codebases" | SPECULATION | Same as NOVEL-004 token claim. Explicitly labeled. | Same as NOVEL-004 |
| "WHY rejects spec 3x → COMMANDER knows in advance" | GATE-CONDITIONED | Goal Stack design claim. U-CA-004 not run. | U-CA-004 gate |
| "ACT-R buffer: only relevant context" | GATE-CONDITIONED | Problem proven (Grade A, Lost in the Middle); solution gate-conditioned | U-CA-004 gate + activation scoring prototype |
| "Critical findings missed → LIDA Broadcast" | GATE-CONDITIONED | No baseline measurement of missed finding rate; U-CA-004 not run | Baseline measurement first (scope violation annotation); then U-CA-004 gate |
| "Prior run reuse via episodic memory" | GATE-CONDITIONED | No content-addressed artifact index; U-CA-004 not run | Embedding index prerequisite; then U-CA-004 gate |

---

## Direct Answer to "Can You Prove This?"

**Already proven at component level (Grade A paper evidence, requires Echelon-specific prototype):**
- Generator-Critic mechanism achieves 86%+ schema compliance on structured rule generation (NL2GenSym, preprint Oct 2025)
- Belief revision with AGM postulates achieves 93.3% accuracy on multi-turn fact consistency tracking (Kumiho, March 2026)
- LLM attention is non-uniform with context position — the problem that ACT-R buffer addresses (Liu et al. "Lost in the Middle," peer-reviewed)

**Supported by design but not yet measured in Echelon context:**
- NS-003 contradiction catching (the design is logically correct; the measurement is pending)
- AC-3 constraint propagation reduces logically inconsistent outputs (CSP algorithm is proven; LLM instruction-following compliance is partially validated)
- Novelty of NS-003 combination (extensive literature search found no prior work; systematic confirmation needed)

**Requires prototype experiment (no direct measurement exists):**
- NOVEL-004 prediction accuracy and LLM call reduction
- Any of the 5 CA overlays in Echelon's task class

**Explicitly speculation (labeled as such in spec 014):**
- 40-70% token reduction for NOVEL-004 and repeated codebase scenarios

**Blocked by U-CA-004 gate experiment not run:**
- All 5 CA overlays and their associated use cases. The gate experiment is the prerequisite. Without it, no overlay claim can be called "proven" or even "likely to work better than expert prompting."

The most defensible single sentence: NS-003's two components are proven at the paper level and require a 2-4 week Echelon prototype to validate in this specific pipeline context; everything else is either gate-conditioned on U-CA-004 or explicitly labeled speculation.
