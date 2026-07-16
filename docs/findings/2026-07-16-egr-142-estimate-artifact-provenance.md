# EGR-142 Estimate Artifact Provenance And Consistency

**Review date:** 2026-07-16
**Priority:** P1
**Status:** open
**Source incident:** OptaSearch `001-vision-dashboards`

## Summary

The published `estimates.md` for OptaSearch contains contradictory effort
numbers and there is no durable artifact-level record explaining the estimate
change. The run and git metadata prove that the file changed, but they do not
explain why the estimate changed, what inputs changed, or which numbers are now
authoritative.

This is a planning-quality and auditability bug. Effort estimates drive scope,
staffing, and delivery decisions, so Echelon must not publish inconsistent
estimate artifacts without a deterministic provenance record and a consistency
gate.

## Evidence

Workspace:

- `/Users/michalbachorik/work/optasearch`

Published artifact:

- `specs/001-vision-dashboards/estimates.md`

Run-local artifact:

- `runs/spec-20260713-125624-949435/specs/001-vision-dashboards/estimates.md`

The published and run-local files are byte-identical:

- SHA-256: `f185bb086a6811dfbb65747ed99e568883ba1942ffc059d5fde9845c5cf24082`
- File mtime: `2026-07-15 19:07` local time

Git checkpoint:

- Commit: `1adf689844a8cc2fdd0686c7a20303a2ba3f9e3d`
- Message: `echelon-checkpoint: 001-vision-dashboards phase4-document`
- Metadata: `Echelon-Run: squad-1783940185`, `Echelon-Phase: phase4-document`

Previous checkpoint:

- Commit: `8e3a798`
- Previous `estimates.md` contained one detailed Function Point breakdown with
  `TOTAL UNADJUSTED FP: 144` and `Most Likely: 21.6 person-weeks`.

Current artifact inconsistency:

- New top summary says `Unadjusted FP: 257 UFP`.
- New top summary says `Adjusted FP: 201 UFP`.
- New top summary recommends `Most Likely: 18 person-weeks`.
- The retained detailed Function Point breakdown still says
  `TOTAL UNADJUSTED FP: 144`.
- The retained detailed conversion still says `144 FP x 6 hours/FP = 864 hours`
  and `Most Likely: 21.6 person-weeks`.

Journal evidence:

- `reasoning-journal.jsonl` entry `id=72`, phase `phase2-decide`, agent
  `speckit-echelon-gatekeeper (GATEKEEPER)`, timestamp
  `2026-07-15T17:07:53Z`, says the MVP scope is feasible and "RICE scores
  justify estimated 18 pw effort".
- `reasoning-journal.jsonl` entry `id=66`, phase `phase3-consensus`, timestamp
  `2026-07-15T16:58:26Z`, says "Effort refined to 18 pw +/- 25% (vs. 21.6 pw
  +/- 50% cold-start)".
- Later entries still reference `144 FP` and `21.6 pw`, including
  phase2-tracker-alignment and phase3-consensus evidence.

Run history limitation:

- `specs/001-vision-dashboards/run-history.json` records run completions only.
- It does not record artifact hashes, estimate totals, estimate deltas,
  previous/new values, producing phase, or change rationale.

## Root Cause Hypothesis

The estimate artifact appears to have been updated by prepending or inserting a
new estimate summary during a later GATEKEEPER/consensus pass while leaving the
old detailed Function Point Analysis section intact. The workflow accepted the
artifact because no deterministic consistency gate checked that summary numbers,
detailed FP breakdown, workstream totals, recommendation, and journal claims
agreed.

## Required Fix

1. Add a deterministic estimate parser/linter for `estimates.md`.
   It should extract the canonical UFP, adjusted FP, optimistic/likely/pessimistic
   person-week totals, tier totals, and any detailed FP totals, then fail or warn
   on contradictions.

2. Require estimate provenance for every estimate update.
   Add a sidecar such as `estimates.provenance.json` containing:
   previous artifact hash, new artifact hash, previous totals, new totals,
   producing phase, producing agent, timestamp, inputs used, calibration factors,
   calculation method, and rationale for each material delta.

3. Make estimate regeneration template-owned, not prepend-owned.
   GATEKEEPER/ASSESS and ASSESS2 must either rewrite a single canonical
   estimate document from a template or update named sections in place. They must
   not append a second summary above stale detailed calculations.

4. Add a Phase 4 artifact consistency gate.
   Before publication/checkpoint commit, `phase4-document` or the Python
   finalizer should validate high-stakes artifacts, including `estimates.md`.
   Contradictory estimates must block publication or mark the run with an
   explicit human-visible quality debt state.

5. Extend run history or ARTIFACTS metadata with artifact-level deltas.
   At minimum record `estimates.md` hash, producing phase, detected totals, and
   previous-to-current deltas.

6. Add regression tests.
   Tests should cover:
   - a valid single-source estimate artifact,
   - a stale appended-summary artifact with `257 UFP` summary and `144 UFP`
     detailed breakdown,
   - missing provenance after an estimate change,
   - Phase 4 refusing to publish contradictory estimates.

## Candidate Files

- `extension/workflow/phases/phase2-decide.md`
- `extension/workflow/phases/phase3-consensus.md`
- `extension/workflow/phases/phase4-document.md`
- `extension/agents/feasibility/gatekeeper.md`
- `src/echelon/artifact_index.py`
- `src/harness/squad.py`
- `src/harness/squad_executors.py`
- new `src/harness/estimate_artifact.py` or similar
- new focused tests under `tests/unit/` and `tests/integration/`

## Acceptance Criteria

- A contradictory `estimates.md` cannot be published as a clean Phase A artifact.
- Every material estimate change has a machine-readable provenance record.
- Published `run-history.json` or `ARTIFACTS.md` exposes the estimate artifact
  hash and key estimate totals.
- The final operator-facing output makes it clear when an estimate is refined
  from a prior value, and why.
