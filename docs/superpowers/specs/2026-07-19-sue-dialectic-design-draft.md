# SUE Dialectic (`sue_dialectic.py`) — Design Draft (pre-v4 gate)

**Date:** 2026-07-19
**Status:** draft — user-proposed design + review refinements; build in a fresh session
**Position:** experimental intermediate BEFORE v4. Causal hypothesis to verify first:

> An adaptive dialectic sequence surfaces more precise and more severe problems
> than an independent batch of questions.

v4's full Justification Graph, temporal retention, and exhibited behavioural
witnesses proceed only after this gate, so improvements are attributable to one
variable at a time. Heterogeneous provider adapters and the unconfounded
model × framing matrix already exist in v3.3 because they do not depend on
dialectic traces.

## Tool shape

```
python3 scripts/sue_dialectic.py spec.md --lens euthyphro --max-turns 7
```

Outputs: `socratic-dialogue.md` (readable dialogue) + `socratic-dialogue.json`
(full machine trace). NO understanding score, NO graph convergence, NO automatic
spec edits.

## Dialectic core

Platonic lens names are ONLY question-selection policies over generic operators:

`DEFINE, DISTINGUISH, CAUSE_OR_CRITERION, COUNTEREXAMPLE, FOLLOW_CONSEQUENCE,
TEST_OPPOSITE, DIVIDE, REVISE`

`APORIA` is a terminal state, never an operator.

## Adaptive state machine (per turn)

previous claim → dialectic operator → new question → answer FROM SPEC TEXT ONLY
→ cited evidence → turn evaluation → next-operator selection.

Turn verdicts (4-state; PARTIAL is the growth point for follow-ups):
`SUPPORTED / PARTIAL / SILENT / CONTRADICTED` (mapping: SILENT ≈ v1 UNANSWERABLE).

Termination states only: `RESOLVED, APORIA_UNDEFINED, APORIA_CONTRADICTED,
APORIA_UNDERDETERMINED, BOUNDED_STOP` — the turn limit is a safety bound, never
evidence of convergence. APORIA_UNDERDETERMINED is the dialectic-side detector
of the Grounded Divergence Witness (two equally valid readings via one chain).

## Review refinements (2026-07-19)

1. **Evidence-retention invariant from turn 1:** every turn cites; a REVISE that
   abandons previously cited lines is flagged (Deliberative-Illusion guard —
   7 turns is more exposure than v2's single elenchus).
2. **Turn evaluation is a new stochastic layer:** answer classification
   (`answer_type: definition|example|criterion|...`) is structured output in the
   answering call, validator-checked, trace-logged. Measure PATH STABILITY:
   repeat the same dialogue K times, compare operator sequences — the dialectic
   gets its own reproducibility test.
3. **Budget-normalized gate:** promotion criteria compare severity/localization
   at MATCHED budget (per dollar), not per run.
4. **Anchoring + lens scope:** dialogues seed from v2 stable findings (natural
   corpus; positions the tool as the Forensic tier: Lite=v1, Deep=v2/v3,
   Forensic=dialectic). Gate starts with TWO lenses — Euthyphro (definition/
   essence/circularity) + Parmenides (consequences of claim and negation) —
   covering the two strongest defect channels. Meno (criterion of recognition)
   and Cratylus (naming/synonymy) are added only after checking redundancy vs
   `understanding` testability metrics and lexicon term-resolution respectively.
5. **Provider control:** path-stability experiments use v3.3's explicit provider
   adapters and full provider × framing matrix. Provider, model tag, and lens are
   separate factors; cycling each model through a different lens is forbidden
   because it confounds model-family and question-policy effects.

## Experimental gate (same corpus: v2 stable findings + labelled mutants)

Compare: v1 batch questions · v2 consensus+elenchus · dialectic chains ·
mutant ground truth. Dialectic promotes to v4 ONLY if it shows at least one of:
higher finding precision; sharper localization of the breakdown point; higher
severity of stable findings; fewer shallow phrasing findings — at matched budget.

## Experimental protocol (2026-07-19 — the reasoning-layer decision)

The gate decides the ARCHITECTURE question: **what source should the Reasoning
Graph be built from?** Two hypotheses:

- **H-D1 (detection):** adaptive chains (question_{t+1} conditioned on
  answer_t) surface more severe, better-localized defects than independent
  batch questioning at MATCHED budget.
- **H-D2 (representation):** a reasoning graph built from the dialogue trace
  is more complete and auditable than one built by one-shot introspection.

**Four arms, one model family (cross-family is the separate H4 axis):**
A) v1 batch (data exists: 030, 029, 071, 063, 064, 069, 070);
B) v2 consensus+elenchus (data exists: 029, 030);
C) dialectic — 2 lenses, ≤7 turns, seeded from v2 stable findings;
D) **one-shot J-graph extraction** — reader emits claims/evidence/inference in
one call (v3 extractor with a different schema). Arm D is mandatory: if C beats
questions but not D, building the dialogue engine for the graph is unjustified.

**Corpus, three ground-truth tiers:** (1) injected mutants (absolute truth,
probe method, 2-3 per 2 specs); (2) documented known issues (029 list, 030
committed reports); (3) novel findings on the ru-sixth-sense corpus
(063/064/069/070/071 — v1 reports committed 2026-07-19), blind-adjudicated.

**Metrics.** H-D1: precision (text-verifiable share), severity profile
(contradiction > behavioural gap > boundary > definitional), localization
(names the minimal missing decision — binary, adjudicated), all normalized
per token/dollar including retries. H-D2: graph completeness (% claims with
evidence links), auditability (blind 1-5: can a human reconstruct WHY),
contradiction detection from the graph alone. Stability: K=3 reruns —
operator-sequence agreement (C), graph agreement (D); the A/B discipline.

**Blinding:** findings from all arms pooled, deduplicated, presented WITHOUT
arm labels; primary judge = the operator, secondary = LLM panel (judge-panel
agreement is itself reported).

**Pre-registered decision rule (all three outcomes legitimate):**
1. C wins H-D1 and H-D2 → Reasoning Graph from dialectic traces.
2. C adds nothing over B but D yields a usable graph (≥80% of C-trace
   completeness at <30% cost) → build the layer via one-shot; dialectic stays
   a manual Forensic tool.
3. Neither adds value → the reasoning layer waits; question tiers suffice.

Thresholds: C promotes iff at matched budget it improves ≥1 of {precision,
severity, localization} AND degrades none. Expected outcomes are WRITTEN DOWN
before the runs (falsification twice paid for itself; now it is standard).

Smoke scale: 2 specs × (2-3 mutants + known issues); C: 2 lenses × ~5 seeds ×
≤7 turns + 3× stability; D: 3 readers × 2 specs. ≈ $40-60.

## v4 hand-off (after the gate)

Dialogue trace maps natively to the Justification Graph:
question→challenge node, answer→claim node, citation→evidence node,
operator→inference edge, counterexample→attack edge, revision→revision edge,
aporia→unresolved conflict. v4 thus receives reasoning as an auditable trace of
a real dialogue, not a one-shot model introspection.
