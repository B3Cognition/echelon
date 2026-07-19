# Independent verdict audit

## 1. Four-judge results

All 46 IDs occur exactly once in every judge file. Means below pool every item-level
score from the indicated judges; `Δ` is the change from the three-judge panel after
adding Judge 4.

| Arm | n | Prior panel sev/loc | Judge 4 sev/loc | All four sev/loc | Δ sev/loc |
|---|---:|---:|---:|---:|---:|
| A — batch | 6 | 2.667 / 2.000 | 2.333 / 1.833 | **2.583 / 1.958** | -0.083 / -0.042 |
| B — consensus | 8 | 2.542 / 2.000 | 2.500 / 2.000 | **2.531 / 2.000** | -0.010 / 0.000 |
| C — dialectic | 11 | 1.394 / 1.182 | 1.364 / 1.545 | **1.386 / 1.273** | -0.008 / +0.091 |
| D — one-shot graph | 21 | 2.492 / 1.921 | 2.000 / 1.905 | **2.369 / 1.917** | -0.123 / -0.004 |

The independent judge changes calibration, especially for D, but not the ordering:
severity is A ≈ B > D >> C; localization is B ≈ A ≈ D >> C.

### Cross-family divergences

Judge 4 exactly matched the panel mean on severity for 23/46 items (mean signed
difference -0.283; MAE 0.616) and on localization for 40/46 (signed +0.058;
MAE 0.116).

- **Higher than panel:** N01, N02, and N23 explicitly state opposed usages or
  incompatible routings, so I scored contradiction and exact localization, not a
  lower-level gap. N19, N34, and N46 place cached-display and unreadable-state
  commitments over the same active-dispatch failure case; N31 puts optional
  language against a binding acceptance case. N43 precisely identifies missing
  observable dispatch-detection behavior, so absence is severity 2.
- **Lower because the packaged text did not establish a defect:** N05, N24, N25,
  N29, and N30 state a rule or case analysis but omit the opposing commitment in
  the displayed last answer. N12 rests on an unsupported “aren't these fields
  non-null?” premise. N18's staging-file save and prohibition on direct
  state/journal writes can coexist. N38 does not say the chord must work while an
  input has focus (unlike N03/N06/N10).
- **Lower because the pair is compatible or weaker than claimed:** N07, N08, and
  N11 prohibit *entering* edit on an already-deleted row but allow a distinct
  concurrent-delete transition. N13/N26 do not define whether “time order” is
  ascending; N27's SHOULD-level pagination can coexist with a first-paint
  constraint, so these are at most definitional gaps. N40 is a behavioral
  omission about the post-delete save outcome, not necessarily a contradiction.

Those groups account for all severity divergences; localization was higher on
N01/N02/N23/N43 and lower on N12/N38 for the same reasons.

## 2. Threat audit

**C packaging handicap.** It is real. The last-answer-only presentation directly
explains my zeros on five C items (N05/N24/N25/N29/N30), and full chains could
restore their missing evidence and substantially raise C's raw score. Nevertheless,
C currently trails D by 0.983 severity and 0.644 localization. An intentionally
extreme sensitivity bound—rescore all five items for all judges as 3/2—raises C
only to about **2.43/1.73**: just above D in severity but still below it in
localization.

The budget makes reversal still less plausible. C used 24 calls for 11 items
(2.18 calls/item); D used 6 for 21 (0.286 calls/item). D therefore produced 7.64
times as many packaged items per call and used 25% of C's calls, satisfying the
rule's `<30% cost` limb. Apparent near-duplicates mean 7.64 is not a clean
unique-defect yield ratio, but even C's theoretical 3/2 ceiling offers only a
27% severity and 4% localization advantage over D—not enough to offset fourfold
call cost under the preregistered cost normalization. Fair packaging could alter
raw quality conclusions; it cannot plausibly establish an outcome-1 matched-budget
win from these data.

**Same-family judge correlation.** The concern is confirmed: Judges 1–3 agree on
40–44/46 severity scores (pairwise correlations 0.891–0.952) and 45–46/46
localization scores (0.940–1.000). Judge 4 correlations are lower
(severity 0.602–0.734; localization 0.592–0.684). Adding Judge 4 reduces severity
by 3.12% for A, 0.41% for B, 0.54% for C, and 4.94% for D; it raises C
localization by 7.69% while changing the other arms by at most 2.08%. Thus the
original panel was overconfident and somewhat generous to D, but the independent
correction does not change the architectural comparison.

## 3. Decision and follow-up

**Verdict: modify outcome 2.** Proceed with one-shot extraction as the only
automated Reasoning Graph candidate, and keep dialectic as a manual Forensic
deep-dive. However, treat the build as an instrumented pilot rather than a completed
promotion: the supplied audit package contains severity/localization findings, not
the preregistered H-D2 measurements needed to verify that D has at least 80% of
C-trace completeness and acceptable auditability. If D fails that direct test,
the rule selects outcome 3; it does not promote C.

The decision is carried by C's failure to improve severity or localization without
degradation, the robustness of that result after adding an independent judge, and
D's 25% call cost. The follow-up must (1) package full C chains and equivalently
complete D claim/evidence provenance within the same blinded size template,
(2) use matched calls **and** tokens, (3) deduplicate semantic defect families
before yield analysis, (4) recruit preregistered cross-family judges plus the human
primary judge, and (5) directly score precision, evidence-link completeness,
blind auditability, and graph-only contradiction detection. That experiment can
confirm full outcome 2 or fall back to outcome 3 without reopening outcome 1 on
packaging artifacts alone.
