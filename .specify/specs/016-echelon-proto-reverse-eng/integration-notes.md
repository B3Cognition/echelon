# Integration Notes — T-002

**Date**: 2026-04-03
**Build Run**: build-1775167332

---

## Specialist Integration Summary

### INVESTIGATOR Findings → novelty-catalogue.md Cross-Reference

| Mechanism | INVESTIGATOR Verdict | Catalogue Rating | Gap? |
|-----------|---------------------|-----------------|------|
| NOVEL-001 Endocrine | PARTIALLY CONFIRMED / CHALLENGER | HIGH | YES — see Gap-001 |
| NOVEL-003 NS-003 | CONFIRMED | HIGH | NO — aligned |
| NOVEL-012 Contradiction Scanner | CONFIRMED LOW | LOW | NO — aligned |

---

### Gap-001: NOVEL-001 Endocrine — Characterization Mismatch

**INVESTIGATOR finding** (INV-001-endocrine-deep-analysis.md):
> The endocrine system is "engineered prompt injection with quantified state management, decay dynamics, and calibration feedback — not a structurally different mechanism from dynamic prompting."

**Recommendation from INVESTIGATOR**: Patent claim should be positioned around "six-dimensional quantified scalar state modulation with exponential decay and outcome-based calibration" — not around the biological metaphor, which is pedagogically useful but legally weak.

**novelty-catalogue.md NOVEL-001 current characterization** (lines 7-29):
- Describes mechanism accurately (six neuromodulator scalars, decay rates, phase-gated triggers, circuit breakers, 30% downstream propagation)
- States novelty confidence: HIGH
- States "No existing framework implements continuous hormone-like modulation with phase-gating, decay, and propagation"
- Does NOT acknowledge that "core mechanism remains prompt text injection (not learned, not neural)" — this is the INVESTIGATOR's key challenge

**Gap description**: The catalogue's novelty confidence of HIGH is not wrong but is incomplete. It does not document the critical weakness identified by INV-001: that the mechanism is, at its core, dynamic prompt injection — a technique with prior art in many forms. The catalogue's "Why Novel" section claims novelty on "dynamics," which is the INVESTIGATOR's same argument, but the catalogue does not surface the vulnerability that a competitor could argue the dynamics are implementation engineering rather than fundamental novelty.

**Specific text gap in novelty-catalogue.md NOVEL-001**: The "Weakest point" in the patent defensibility subsection mentions Ayouni et al. 2020 but does not include the INVESTIGATOR's recommendation to explicitly acknowledge "Core mechanism is prompt injection" and frame the claim narrowly around the six-dimensional quantification + decay calibration combination. INV-001's recommendation (search CrewAI, AutoGen, LangChain for "decay," "state modulation," or "feedback tuning") is an open action item not reflected as a gap in the catalogue.

---

### Gap-002: NOVEL-003 NS-003 — Aligned, No Catalogue Update Needed

**INVESTIGATOR finding** (INV-003-ns003-evidence-audit.md):
> "CONFIRMED — NS-003 NOVELTY CLAIM IS SUPPORTED BY EVIDENCE. Systematic search confirming no prior work combines all three components. Evidence grade: B (search is Grade B evidence; component evidence is Grade A)."

**novelty-catalogue.md NOVEL-003 current state** (lines 58-84):
- States "Zero papers found combining execution-grounded Generator-Critic with AGM belief revision in multi-agent artifact stores"
- Cites `U-015-002-novelty-search.md` as evidence source
- Cites arxiv:2510.09355 (NL2GenSym, 86% compliance) and arxiv:2603.17244 (Kumiho, 93.3% accuracy)
- Novelty confidence: HIGH (for combination)

**Gap**: NONE. The catalogue accurately reflects INV-003's confirmation. The Grade B limitation on the search evidence is noted in the catalogue's "What Would Constitute Full Proof" section (upgrade requires Semantic Scholar native API re-run). Alignment is complete.

---

### ORACLE New Claims Not in novelty-catalogue.md

**From patent-analysis.md Section 3 (Combination Claims)**:

1. **"Formal Cognitive Role Ontology" combination claim** (MAVERICK-sourced, incorporated into ORACLE Section 3):
   > "Per-tier endocrine baselines + model assignments + NEVER rules = formal cognitive role semantics with deterministically verifiable compliance." — Defensibility: HIGH

   This claim appears in patent-analysis.md Section 3 and Section 4 (IP Priority Matrix, Rank 4) but does NOT appear as a standalone NOVEL-NNN entry in novelty-catalogue.md. The catalogue covers NOVEL-007 (7-Tier Cognitive Specialization) but frames it as tier separation + role prompts, not as a "formal ontology with deterministically verifiable compliance." The ORACLE and MAVERICK both argue this framing upgrade is material to defensibility.

2. **"Endocrine + Constitutional Gate" combination claim**:
   > "Personality modulation (6-hormone state vectors) combined with constitutional pre-dispatch governance (FLAG/CONSULT/BLOCK), where endocrine state influences gate-severity decisions." — Defensibility: MEDIUM-HIGH

   This cross-mechanism combination is in patent-analysis.md Section 3 but has no corresponding entry in novelty-catalogue.md. The catalogue covers NOVEL-001 and NOVEL-006 individually.

3. **"Belief Freshness + Calibration Injection" combination claim**:
   > "Temporal belief freshness tracking combined with historical calibration data injection, where stale beliefs trigger higher calibration multipliers." — Defensibility: MEDIUM

   Present in patent-analysis.md Section 3; not in novelty-catalogue.md as a combination entry.

4. **"Constitutional + Endocrine + Belief System = Self-Modifying Trust Model"** (MAVERICK Section 1, Item 5):
   A three-way combination claim not present anywhere in novelty-catalogue.md. Described as "a formal model of self-modification under constraint — a rare and defensible innovation."

---

### MAVERICK Defensibility Upgrades

**MAVERICK report Section 2 (Blindspots) identifies two mechanisms that should be rated higher**:

1. **NOVEL-007 (7-Tier Specialization) — Current rating: MEDIUM → MAVERICK argues HIGH**
   > "This is catastrophically undervalued… not just separation of concerns — it's a formal ontology of cognitive roles… HIGH defensibility because it's structural (hard to copy without reimplementing the entire architecture) and measurable (role compliance is deterministically verifiable)."

   Current novelty-catalogue.md NOVEL-007: rated MEDIUM defensibility (evidence: agent prompt NEVER rules, COMMANDER enforcement, squad-config.yml model assignments). MAVERICK's argument is that framing as "Formal Cognitive Role Ontology" with immutable behavioral constraints + hormone baselines + model assignments is architecturally harder to substitute than the catalogue acknowledges.

2. **NOVEL-003 (NS-003) — Current rating: HIGH for novelty, LOW-MEDIUM for defensibility → MAVERICK argues the defensibility framing is understated**
   > "The defensible claim is not 'AGM is novel'… it's: 'A method for validating and revising multi-stage LLM outputs using formal logical consistency checking against an execution-grounded artifact protocol, with AGM doxastic logic for minimal belief revision.' The combination is novel: no other LLM orchestration framework applies formal doxastic logic to artifact validation."

   MAVERICK's framing is consistent with INVESTIGATOR INV-003 and ORACLE CLAIM-001, but specifically calls out that NS-003 is the "highest-defensibility claim in the entire portfolio" — a stronger assertion than the catalogue's current "HIGH (for combination), LOW-MEDIUM (for defensibility against alternative approaches)."

**MAVERICK also flags**:
- NOVEL-001 (Endocrine) has additional IP value as "AI transparency and debugging" IP (interpretability framing) — not just quality improvement IP. This could broaden the defensibility surface beyond what the current catalogue documents.
- The Inter-Run Learning Loop (NOVEL-008/calibration) implicitly supports a "cognitive marketplace" network effects claim that is not captured anywhere in the current catalogue.

---

### Recommended Updates to novelty-catalogue.md

The following are specific, actionable updates HOW should make to novelty-catalogue.md. This file documents the recommendations only — it does not edit novelty-catalogue.md.

**Recommended Update 1 — NOVEL-001 "Weakest point" amendment**:
Add acknowledgment that the core mechanism is prompt text injection, and that the patent claim must be framed narrowly around "six-dimensional quantified scalar state modulation with exponential decay and outcome-based calibration feedback loop" to withstand a competitor argument that prompt injection is not novel. Reference INV-001's recommendation: `investigation/INV-001-endocrine-deep-analysis.md`. Additionally add the MAVERICK interpretability framing (transparency/debugging IP angle) as an additional defensibility pathway under NOVEL-001.

**Recommended Update 2 — NOVEL-001 "What Would Constitute Full Proof" amendment**:
Add INV-001's recommended action: targeted search of CrewAI, AutoGen, LangChain GitHub for "decay," "state modulation," or "feedback tuning" on agent behavior. This search is currently a gap — INV-001 identified it but the catalogue does not surface it as a required evidence step.

**Recommended Update 3 — NOVEL-007 rating upgrade consideration**:
Document MAVERICK's argument that NOVEL-007 should be rated HIGH rather than MEDIUM when framed as "Formal Cognitive Role Ontology." Add a subsection within NOVEL-007: "MAVERICK Challenge (2026-04-02): See maverick-report.md Section 2, Blindspot A — argues structural + verifiable compliance makes this HIGH defensibility." HOW should evaluate whether to upgrade the rating or document the disagreement.

**Recommended Update 4 — Add NOVEL-013: Formal Cognitive Role Ontology (combination claim)**:
A new catalogue entry documenting the ORACLE/MAVERICK combination claim: per-tier endocrine baselines + model assignments + NEVER rules + COMMANDER enforcement = formal cognitive role semantics with deterministically verifiable compliance. Evidence: `squad-config.yml` (per-tier model assignments), per-agent NEVER rules, `agents/control/commander.md` (tier enforcement). Defensibility: HIGH per ORACLE IP Priority Matrix Rank 4. This claim is not currently captured as a standalone NOVEL-NNN entry.

**Recommended Update 5 — Add cross-mechanism combination section**:
A new section in novelty-catalogue.md covering the three ORACLE Section 3 combination claims (Endocrine + Constitutional Gate; Belief Freshness + Calibration Injection; MAVERICK's three-way Constitutional + Endocrine + Belief = Self-Modifying Trust Model). These are currently only in patent-analysis.md and not in the catalogue, creating a traceability gap if the catalogue is used as the authoritative novelty registry.

**Recommended Update 6 — NOVEL-003 defensibility qualifier**:
MAVERICK argues NS-003's defensibility framing should be upgraded from "HIGH (combination), LOW-MEDIUM (against alternatives)" to reflect that formal doxastic logic applied to LLM artifact stores is the primary defensible claim — not just the combination. Consider revising the "Patent Defensibility" subsection to lead with the formal logic framing rather than the combination framing, per ORACLE CLAIM-001 full claim text in patent-analysis.md Section 6.

---

## T-002 Result: DONE

**6 integration gaps documented: 1 characterization gap in NOVEL-001 (INV-001 challenge not reflected), 4 new claims from patent-analysis.md not in novelty-catalogue.md (Formal Cognitive Role Ontology, Endocrine+Constitutional, Belief+Calibration, three-way Trust Model), 1 NOVEL-007 defensibility rating dispute from MAVERICK. 6 specific actionable updates recommended for HOW to apply to novelty-catalogue.md.**
