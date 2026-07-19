# SUE v3 — Semantic Reproducibility Instrument Design

**Date:** 2026-07-19
**Status:** approved (session mandate: "execute full v3")
**Scope (v3.0):** `scripts/sue_reproducibility.py` — interpretation-graph extraction,
anchor-aligned convergence scoring, grounded divergence witnesses, and
provenance-based divergence localization. Counterfactual (ddmin-style) minimal
clarification search is explicitly **v3.1**, not built here. v1/v2 unchanged.

## What v3 measures

> Understanding confidence is the degree to which independently produced,
> source-grounded, internally valid interpretations converge on behaviourally
> compatible models.

v3 outputs that degree as numbers: an overall **semantic-reproducibility score**,
a per-requirement breakdown, exhibited **witnesses** where interpretations are
behaviourally incompatible, and the spec lines each divergence traces to.

## Interface

```
python3 scripts/sue_reproducibility.py <spec.md> [--readers K=3] [--claude-cmd CMD]
    [--timeout SECS=300] [--json]
```

Outputs: `semantic-reproducibility.md` beside the spec + `semantic-reproducibility.json`
sidecar (machine-readable, for the SRP experiment). Exit codes as v1 (0/1/2/3);
`--json` prints the sidecar to stdout as well. Empty-spec and report-collision
guards as v1/v2. Plumbing (subprocess, extraction, retry, neutral cwd, debug dumps)
reused from v1 via importlib.

## Reader extraction (K calls, 1 per reader)

One model call per reader (framings cycle as v2). The prompt embeds the
line-numbered spec, the fixed ontology, a **shared exemplar block** (the probe's
extraction-stability fix: worked example pinning label style — lowercase, singular,
spec vocabulary, no articles), and demands strict JSON:

```json
{"requirements": {"REQ-001": {
  "edges": [{"s": "builder", "type": "performs", "t": "open home view",
              "line": 6, "conf": 0.9}],
  "assumptions": [{"text": "...", "line": 5}],
  "assertions": [{"given": "...", "when": "...", "then": "...", "lines": [7]}]
}}}
```

- Edge types (closed set): `performs, acts_on, applies_when, results_in,
  except_when, assumes, requires, transitions_to`.
- Requirement keys must match units found in the spec (validated against a
  deterministic scan for `REQ-`/`FR-`/`AC-`/`NFR-` ids; unknown keys = parse
  failure → v1 retry path). Every edge needs a line; ungrounded edges are dropped
  and counted as `ungrounded` (diagnostic, excluded from scoring).
- 1–3 assertions per requirement, given/when/then, line-cited.

## Deterministic alignment and scoring (no model calls)

- Label normalization: lowercase, whitespace/hyphen collapse, article strip,
  conservative singularization (the probe's `norm()`).
- Per requirement r and reader pair (i,j): typed-edge Jaccard over normalized
  `(s, type, t)` triples → pairwise agreement; `score(r)` = mean over pairs.
  Both-empty pairs score 1.0 (agreeing the requirement contributes no edges is
  agreement).
- **Overall SR score** = mean of `score(r)` over requirements present in ≥1 reader.
  Reported alongside: per-requirement table (sorted ascending — worst first),
  assumption-load per requirement (mean count), ungrounded rate per reader.
- Vocabulary vs interpretation divergence: pairs failing exact-normalized match
  but sharing type + one endpoint are counted `near-miss` (diagnostic column),
  per the anchor-alignment principle: never force-merged.

## Witnesses (deterministic)

For each requirement, group assertions across readers by normalized `(given, when)`.
A **witness candidate** is a group where two readers' `then` clauses differ after
normalization. It is a **witness** when both assertions cite spec lines (grounded)
— rendered side by side with both line citations and both readers named. Witness
count feeds the report and JSON; witnesses are ranked by (requirement score
ascending) — divergence in already-low-agreement requirements first.

## Localization (provenance attribution, v3.0)

For each requirement with `score(r) < 0.5` and each witness: collect the spec
lines cited by the *disagreeing* elements (edges present in one reader but not
others; both sides of a witness). Rank lines by citation frequency across
divergent elements. Report the top lines per divergence as "fracture lines" —
the sentences a clarification pass should target. No counterfactual re-runs
(v3.1); the report labels this "attributed, not verified".

## Report + JSON sidecar

Markdown: header (spec, date, K, overall SR score, grade), per-requirement table
(score, edges, assumptions, near-misses), witnesses section, fracture-lines
section, diagnostics (ungrounded rates, dropped readers). JSON mirrors all of it
with raw per-reader graphs included — the SRP experiment consumes this.

## Degradation

Reader failure → drop; ≥2 readers required (as v2). Score computed over surviving
pairs. Extraction returning zero requirements = reader failure.

## Testing

`tests/unit/test_sue_reproducibility.py`, same replay-stub seam:
- Pure units: normalization, requirement-id scan, Jaccard/scoring (incl.
  both-empty=1.0, near-miss counting), witness grouping + grounding rule,
  fracture-line ranking, report/JSON rendering.
- Scenarios: identical graphs → SR=1.0, no witnesses; disjoint graphs → low SR;
  conflicting `then` → witness rendered with both citations; reader dropout;
  unknown requirement key → retry path; empty spec / collision guards.

## Validation experiment (in-session, smoke scale)

1. Self-run on `specs/030-build-sue-challenge-script/spec.md` → baseline SR.
2. Clean vs mutant: run on `specs/029-builder-spec-workbench/spec.md`, then on an
   M1-ambiguity mutant (probe method: one determinate term → vague synonym, one
   line, ground truth known). Success criteria (smoke): `SR(mutant REQ) <
   SR(clean REQ)` for the mutated requirement, and the mutated line appears in
   that requirement's fracture lines. Mutant lives in scratchpad, never in specs/.

## Non-goals (v3.1+)

Counterfactual minimal-clarification search, Justification Graph claim records,
cross-model-family readers, workflow integration, full SRP corpus run.

## Addendum 2026-07-19 — debt to the research report (review findings)

Post-build review against the source research report identified four gaps;
two fixed in v3.2, two recorded as v4 scope:

1. **Fixed — no single-scalar headline:** the report warns against one
   confidence number; reports now headline a measurement vector (convergence,
   witness candidates + filtered phrasing variants, assumption load, thin
   consensus, coverage). SR remains one component, never the story.
2. **Fixed — witness honesty:** normalized-string inequality mistook phrasing
   variants for behavioural conflict (live case W1: one spec line restated
   twice). Witnesses are now word-overlap-screened, reported as *candidates*,
   and the section is labelled heuristic. Exhibited behavioural verification
   (the report's Grounded Divergence Witness standard) is v4.
   **Fixed — untrusted convergence:** per-requirement `thin_consensus` flag
   (high agreement over minimal content) operationalizes the report's "the
   agents converged, but the convergence is not trustworthy" state, matching
   the live vagueness result.
3. **v4 debt — two-layer separation:** the report requires distinct
   Understanding and Reasoning graphs; v3 merges knowledge, assumptions and
   assertions into one requirement-local object. The Justification Graph
   (claims/evidence/inference records) restores the second layer.
4. **v4 debt — critical-fact retention + cross-model-family readers:**
   retention exists only in v2's elenchus guard; v3 has no multi-round
   evidence-retention measure. Heterogeneous model families remain the H4
   experiment prerequisite.
