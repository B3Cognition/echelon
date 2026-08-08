# Semantic Reproducibility Probe v0 — Smoke Run Record (2026-07-18)

**Scale:** 1 spec, 2 mutation operators, K=3 isolated runs per variant (9 runs total).
Smoke scale — not the full v0 protocol (which requires 10-15 specs, 5 operators, K=5).

## Setup

- **Source spec:** `specs/028-builder-spec-workbench/spec.md` (controlled-grammar, 20 REQs).
- **M1 ambiguity** (ground truth REQ-005, line 34): "a spec run that is not currently
  executing a squad dispatch" → "a spec run that is not busy".
- **M2 contradiction** (ground truth REQ-011, line 80): added "read the complete journal
  from the beginning", contradicting REQ-012's incremental loading + AC-012.
- **Interpretation runs:** fresh isolated subagents (spec variant + schema only; no shared
  context, no journal). Framings: structural / behavioural / adversarial. Same model family.
- **Alignment:** deterministic normalization only (steps 1-2; no glossary file for this
  spec, so alias resolution skipped). Typed-edge triples per REQ, mean pairwise Jaccard.

## Results

| Measurement | clean | M1 | M2 |
|---|---|---|---|
| Overall typed-edge agreement (noise floor = clean) | 0.346 | 0.276 | 0.407 |
| Ground-truth REQ localization rank (by agreement drop) | — | **#1** (REQ-005, drop +0.382) | #14 (REQ-011) |
| Conflict reports (across 3 runs) | 0 | 0 | **3/3 runs: REQ-011↔REQ-012** |
| `understanding` overall score (34 metrics) | 77.13% ✓ | 77.13% ✓ | 77.16% ✓ |
| `lexicon` validate | valid, all gates 1.00 | valid, all gates 1.00 | valid, all gates 1.00 |

## Findings

1. **A1 fails at smoke scale: noise floor 0.346 (target ≥ 0.80).** Extraction variance
   dominates the typed-edge channel. Per the spec, absolute-divergence claims are
   *inconclusive* until extraction stabilizes (shared few-shot exemplar, tighter label
   canon, glossary-anchored labels). This was the predicted first bottleneck.
2. **Localization survives the noise (M1).** Relative per-requirement agreement drop
   ranked the mutated REQ-005 #1 despite the noisy extractor. Assumption load on REQ-005
   also rose (2/2/4 → 3/3/4).
3. **Contradictions need the conflict channel, not the divergence channel.** M2 *raised*
   overall agreement (0.407 > 0.346): the contradictory sentence is individually clearer,
   so per-edge extraction got more consistent while the spec became jointly unsatisfiable.
   The explicit `conflicts_with` channel caught it 3/3 with 0 false positives across the
   6 control runs. **Design consequence for v0: map operators to detection channels**
   (M1/M5 → divergence; M2 → conflict reports; M3/M4 → assumption load / boundary gaps),
   instead of expecting one divergence score to catch every defect class.
4. **Incremental value over the deterministic stack is real (P3, anecdotal n=2).** Both
   mutants pass `lexicon` with perfect gate scores and move the 34-metric overall score
   by ≤ 0.03 points. Neither deterministic layer can see either defect; the probe caught
   both (M1 via localization, M2 via conflict consensus).

## Caveats on the injections (post-hoc review)

Post-hoc inspection of the mutations found four flaws; the affected conclusions are
marked here and the experiment spec has been amended to prevent recurrence.

1. **M2 violated the spec's own distance rule.** The conflict was injected into REQ-011
   against the *adjacent* REQ-012 over the same view — close to the easiest detectable
   contradiction. The 3/3 detection shows the channel works *at all*, not that it works
   at realistic difficulty. Discount accordingly.
2. **The clean control was not clean at the M2 site.** Original REQ-011 "in time order"
   vs AC-012 "most recent entries render first" is a latent ordering tension; the
   mutation amplified an existing seam rather than injecting into a defect-free site.
   Corollary false-negative data point: 0/3 clean runs flagged the latent tension —
   the conflict channel misses subtle latent defects at K=3.
3. **M2's bindingness rests on the AC, not the REQ.** REQ-012 is a SHOULD; the hard
   contradiction only exists because AC-012 is binding. All three detections cited
   AC-012 — the agents decided AC bindingness themselves, an undocumented degree of
   freedom now fixed in the spec (ACs/ERRORs/CONSTRAINTs are declared binding).
4. **M1 was a *recoverable* ambiguity.** REQ-006 and ERR-EDIT-LOCKED still spell out
   "dispatch in progress", so the intended meaning is reconstructible from context.
   Fair as a vagueness test (divergence concentrated exactly where the disambiguation
   burden sits), but weaker than unrecoverable ambiguity; the spec now distinguishes
   the two sub-classes.

Unaffected by these flaws: incremental value over `lexicon` + 34 metrics, M1
localization rank, 0 false positives on controls, and the noise-floor finding.

## Amendments to carry into the v0 experiment spec

All folded into `2026-07-18-semantic-reproducibility-probe-v0.md` as of 2026-07-18:

- Operator→channel detection matrix; detection scored per channel (§7).
- Extraction-stabilization work (exemplar-anchored labels) before the full corpus run;
  re-measure A1 after (§5).
- Normalize per-requirement agreement drops by the requirement's clean-floor variance
  (low-floor REQs like REQ-009 are noisy localization candidates) (§7).
- M2 distance rule enforced + defect-free-site pre-screening for all mutation sites (§4).
- ACs / ERROR blocks / CONSTRAINT lines declared binding constraint sources (§5).
- M1 split into recoverable vs unrecoverable sub-classes, reported separately (§4).

Artifacts (session scratchpad, not persisted): variants, 9 interpretation graphs,
`analyze.py`.
