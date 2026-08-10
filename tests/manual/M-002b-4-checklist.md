# M-002b-4: Data Loss Interval — Manual Test Checklist

**Test:** TEST-002b-4 (manual-gated)  
**Story:** 002b — KB corruption detection and recovery within one run interval  
**Reviewer:** *(fill in)*  
**Date:** *(fill in)*  

---

## Pre-requisites

- A valid KB snapshot (baseline A) must exist in the `knowledge-base/` directory **before** the test.
- The `kb-recover.sh` and `kb-write.sh` scripts must be available in `runtime/scripts/bash/`.
- The `tests/fixtures/kb/valid-seeds/` directory must have the seed fixtures.

---

## Procedure

### Step 1 — Record Baseline A

- [ ] Identify the current valid snapshot as **baseline A**: note the `schema_version` and entry count in `knowledge-base/estimates-log.yaml`.
- [ ] Record: `baseline_A_entry_count = ___`, `baseline_A_schema_version = ___`

### Step 2 — Backup Baseline A

- [ ] Run: `bash runtime/scripts/bash/kb-recover.sh backup --file knowledge-base/estimates-log.yaml`
- [ ] Confirm the backup file appears in the active run's `recovery/` directory with an ISO-8601 timestamp in the filename.
- [ ] Record the backup path: `backup_path = ___`

### Step 3 — Add Current-Run Delta

- [ ] Run one `append_entry` write via `kb-write.sh` to represent the current-run delta:

  ```
  bash runtime/scripts/bash/kb-write.sh append_entry \
    --file knowledge-base/estimates-log.yaml \
    --payload 'id: m002b4-test\nagent: REVIEWER\ndomain: manual-test\nestimate_hours: 0.5\nconfidence: 1.0' \
    --run-id m002b4-run \
    --operation-id op-m002b4-001
  ```

- [ ] Confirm entry appears: `grep -q 'op-m002b4-001' knowledge-base/estimates-log.yaml`
- [ ] Record new entry count: `post_delta_entry_count = ___`

### Step 4 — Simulate Corruption

- [ ] Corrupt the KB file by removing the closing line or truncating:

  ```
  head -n -2 knowledge-base/estimates-log.yaml > /tmp/corrupt.yaml && mv /tmp/corrupt.yaml knowledge-base/estimates-log.yaml
  ```

- [ ] Confirm `kb-recover.sh detect` reports corruption (exits 1):

  ```
  bash runtime/scripts/bash/kb-recover.sh detect --file knowledge-base/estimates-log.yaml
  ```

- [ ] Record: detection exited `___` (should be 1)

### Step 5 — Trigger Recovery

- [ ] Run backup of corrupted file: `bash runtime/scripts/bash/kb-recover.sh backup --file knowledge-base/estimates-log.yaml`
- [ ] Run restore: `bash runtime/scripts/bash/kb-recover.sh restore --file knowledge-base/estimates-log.yaml`
- [ ] Confirm `recovery_mode=true` in the active run's `state.json`.
- [ ] Confirm restored file passes detect: `bash runtime/scripts/bash/kb-recover.sh detect --file knowledge-base/estimates-log.yaml` → exit 0.

### Step 6 — Verify "One Run Interval" Interpretation

> **Definition**: "One run interval" means the data loss window is bounded to entries written  
> **after** the most recent valid backup and **before** the corruption was detected. Entries  
> in the backup are fully restored. Any entries written after the last backup but before  
> corruption are the only interval that may be lost.

- [ ] Confirm restored file entry count equals **baseline A entry count** (backup restored correctly): `restored_entry_count = ___`
- [ ] Confirm the current-run delta entry (`op-m002b4-001`) is **not present** after restore (it was written after the backup).
- [ ] Reviewer acknowledges: the maximum data loss is bounded to the current-run delta (i.e., writes since last backup).
- [ ] Reviewer sign-off: the "one run interval" interpretation is understood and acceptable for Tier 1.

### Step 7 — Post-Recovery Cleanup

- [ ] Re-run the delta write to re-apply the current-run entry.
- [ ] Confirm system continues normally after recovery.

---

## Signoff

| Field | Value |
|-------|-------|
| Reviewer | |
| Date | |
| Decision | PASS / FAIL |
| Notes | |
| One-run-interval interpretation acknowledged | YES / NO |

---

## BUILD/QA Split Pilot Readiness (v0.4.0)

- [x] BUILD handoff contract validation passed
- [x] QA batch deterministic checks passed
- [x] Rework routing and iteration cap checks passed
- [x] Split metrics captured (rework count, fallback count, qa_coverage)
- [x] Final verification summary persisted for feature 002
