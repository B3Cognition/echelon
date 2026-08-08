# SUE v2 — Consensus + Elenchus Design

**Date:** 2026-07-19
**Status:** approved (brainstorming session; chain scope = consensus + elenchus on survivors)
**Scope:** `scripts/sue_consensus.py` — multi-reader consensus over SUE v1 single-reader
challenges, plus one bounded Socratic follow-up (elenchus) round on stable findings.
v1 (`sue_challenge.py`) is unchanged and remains the single-reader tool.

## Motivation

v1 findings are samples from a deep question reserve (fixing 11 produced 13 fresh ones),
and nothing measured question quality or maintained the Socratic chain (follow-up
premised on the previous answer). v2 addresses both:

- **Reproducibility as quality:** a finding supported by ≥2 of K isolated readers is
  load-bearing; support=1 findings are sampling noise (reported, not ranked).
- **Enforced chain:** stable findings get exactly one follow-up round whose questions
  must be premised on the parent's verdict and quoted evidence — checked structurally,
  not stylistically.

## Interface

```
python3 scripts/sue_consensus.py <spec.md> [--readers K] [--min-support M]
    [--questions N] [--claude-cmd CMD] [--timeout SECS] [--no-elenchus]
```

Defaults: K=3, M=2, N=15, cmd=claude, timeout=300. Exit codes identical to v1
(0 success / 1 bad input / 2 model command missing / 3 unusable output).
Report: `socratic-consensus.md` beside the spec (overwrites; regenerable).

## Pipeline

1. **K isolated readers.** Each reader runs v1's two rounds via v1's own functions
   (module loaded with importlib from the sibling file — v1 is import-safe by design).
   Reader k's round-1 prompt = v1 prompt + a framing suffix from the cycle
   (structural / behavioural / adversarial), the probe-validated variation axis.
   Isolation: v1's per-call neutral temp cwd; readers never see each other's output.
2. **Deterministic consensus clustering — no LLM merging.** Findings cluster iff:
   same `target` requirement id AND same `category` AND evidence-line overlap
   (any shared line, or both citing no lines). Cluster support = number of distinct
   readers contributing. `stable` = support ≥ M; support < M → sampling appendix.
3. **Elenchus round on survivors** (skippable via --no-elenchus, auto-skipped when
   no stable findings): two model calls total, batched.
   - Call 1 (follow-up generator): receives, per stable cluster, the representative
     parent question (deterministically the contributing finding from the
     lowest-numbered reader), its verdict, and its quoted evidence lines; must return per
     cluster exactly 1 follow-up question premised on them, JSON:
     `{"followups": [{"id": "F1", "parent": "C1", "question": str,
     "premise_lines": [int]}]}`.
   - **Chain validation (structural):** every follow-up must name an existing cluster
     id and cite ≥1 of the parent's evidence lines in `premise_lines` when the parent
     cited any (parents with no cited lines are exempt); violations are parse failures
     on v1's retry path.
   - Call 2 (fresh answerer): v1's round-2 machinery over the follow-up questions —
     spec text + questions only, no chain rationale. Verdicts as v1.
   - **Evidence-retention guard:** a follow-up answer whose evidence contradicts the
     parent's quoted lines cannot silently supersede — both are rendered; the pair is
     flagged `RETENTION-CHECK` in the report.
4. **Report** (`socratic-consensus.md`): header (spec, date, readers, per-reader
   finding counts, stable/noise split) → stable findings ranked (CONTRADICTED first,
   then support desc, then parent rank), each with support count, per-reader question
   variants, evidence, and the elenchus chain (follow-up + verdict + evidence) →
   sampling appendix (support < M) → per-reader audit note. Terminal summary mirrors
   v1: counts + top 3 stable findings.

## Degradation and errors

- A reader whose rounds end in RoundExit is dropped; the run proceeds if ≥2 readers
  survive (noted in report header). <2 survivors → exit 3 with v1-style diagnostic.
- Elenchus failure after retry → report ships without the chain section, noted; exit 0
  (consensus results are already valuable; the chain is enhancement, not gate).
- Pre-flight identical to v1 (including the report-path collision guard, applied to
  `socratic-consensus.md`).

## Cost model

K=3 × 2 calls + 2 elenchus calls = 8 model calls ≈ 4× a v1 run per spec.

## Testing

`tests/unit/test_sue_consensus.py`, same stub-executable seam as v1:
- Pure units: clustering (anchor rules, overlap edge cases, support counting),
  chain validation (missing parent, uncited premise), ranking, report rendering.
- Scenario tests with canned stub scripts: full 3-reader run to report; 1 reader
  failing → degraded note; all failing → exit 3; --no-elenchus path; retention flag.
- Live acceptance: run against `specs/030-build-sue-challenge-script/spec.md` (the
  self-run) — success = report produced, stable/noise split non-trivial, chain
  sections present and structurally valid.

## Non-goals (v3+)

Deeper chains, interpretation graphs, convergence scores, Minimal Clarification Set
search, workflow/WHY3 integration, cross-model-family readers.
