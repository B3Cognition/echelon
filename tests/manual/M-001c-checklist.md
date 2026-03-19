# M-001c: Fallback Recovery — Manual Test Checklist

**Test:** TEST-001c (manual-gated)  
**Story:** 001c — Fallback recovery and state reconciliation  
**Reviewer:** *(fill in)*  
**Date:** *(fill in)*  

---

## Pre-requisites

- A prior squad run with `fallback_mode=true` (spec-kit was unavailable) must exist.
- A recovery run with spec-kit available must have completed after the fallback run.
- Artifacts: `spec.md`, `00-overview.md`, `reasoning-journal.json` from both runs.

---

## Checklist

### 1. `fallback_recovery` Journal Linkage

- [ ] `reasoning-journal.json` contains an entry with `"type": "fallback_recovery"`.
- [ ] The `prior_run_id` field in the `fallback_recovery` entry matches the `run_id` from the fallback run's `state.json`.
- [ ] The `recovery_run_id` field matches the `run_id` from the recovery run's `state.json`.
- [ ] Both run IDs are distinct (not the same string).

### 2. Recovery Checklist Coverage

- [ ] `templates/recovery-checklist.md` exists.
- [ ] The checklist includes at least one item for **spec.md** (compare fallback spec with spec-kit-generated spec).
- [ ] The checklist includes at least one item for **00-overview.md** (verify feature branches created manually match spec IDs).
- [ ] The checklist includes at least one item for **reasoning-journal.json** (confirm `fallback_recovery` entry links correct run IDs).
- [ ] All items have a marked status column (e.g., `[ ]` or `[X]`).

### 3. `docs/fallback-mode.md` Accuracy

- [ ] `docs/fallback-mode.md` exists and references `templates/recovery-checklist.md`.
- [ ] The document explains the `fallback_recovery` journal event and what it means for artifact validity.
- [ ] Remediation steps (re-run with spec-kit available, compare, reconcile) are described.
- [ ] The document is sufficient for an operator who has never seen the system before.

### 4. Artifact Banner Inspection

- [ ] The fallback-run `spec.md` contains the `UNVALIDATED_DEPENDENCY` banner.
- [ ] The recovery-run `spec.md` does **not** contain the `UNVALIDATED_DEPENDENCY` banner.
- [ ] All 5 fields are present in the banner: FALLBACK STATUS, Run ID, Detected, Provenance, Remediation.

### 5. State Field Verification

- [ ] Fallback run `state.json` has `fallback_mode: true` and `spec-kit` in `dependency_fallbacks`.
- [ ] Recovery run `state.json` has `fallback_mode: false` and `dependency_fallbacks` does not contain `spec-kit`.

---

## Signoff

| Field | Value |
|-------|-------|
| Reviewer | |
| Date | |
| Decision | PASS / FAIL |
| Notes | |
