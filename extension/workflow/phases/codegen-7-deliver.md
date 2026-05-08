# Phase: codegen-7-deliver
# Source: echelon.codegen.md §Phase 7 + Terminal Summary + Harness Integration
# Read by: speckit-echelon-orchestrator (ORCHESTRATOR) after TEST (and SECURITY) gates pass

## Phase 7: DELIVER

**Print:** `[CODEGEN] Phase DELIVER — Assembling delivery package...`

SOAR selects DELIVER only when: all Tier 1 tests pass, Ψ ≥ 0.70, zero CQ-ISC violations.

1. Write `./codegen-report.md` — human-readable summary with requirement citations per delivered feature.
2. Export EPMEM:
   ```bash
   codegen gate --phase DELIVER --language <language> --files <files> --state-file codegen-state.json
   ```
3. Update `codegen-state.json`: `wall_clock_end = now`.

**Git operations:** Present for user approval — do NOT execute without it:
```
[CODEGEN] Proposed git operations:
  git add <generated files>
  git commit -m "codegen: <intent summary>"
Approve? (yes/no):
```

```bash
rm -f .codegen-active
write_state "done" "build_done" $TOTAL_TASKS null '"PASS"'
```

---

## Terminal Summary

```
╔══════════════════════════════════════════════════════╗
║         CODEGEN — Pipeline Summary                   ║
╠══════════════════════════════════════════════════════╣
║ Pipeline ID : <pipeline_id>                          ║
║ Wing        : <wing>                                 ║
║ Feature     : <feature_path>                         ║
║ Final phase : <DELIVER|BLOCKED|ESCALATED>            ║
╠══════════════════════════════════════════════════════╣
║ Requirements: <N> retrieved from MemPalace           ║
║ Ψ score     : <score> (threshold 0.70)               ║
║ Tier 1 gate : <PASS|FAIL|UNAVAILABLE>                ║
║ CQ-ISC violations blocked : <count>                  ║
║ Impasse escalations       : <count>                  ║
║ Wall-clock time           : <HH:MM:SS>               ║
╠══════════════════════════════════════════════════════╣
║ Tasks: <done> done / <blocked> blocked / <total> total║
╚══════════════════════════════════════════════════════╝
```

---

## Harness Integration: Report Build Status

If `$HARNESS_BUILD_STATUS_FILE` is set, write the outcome after the skill completes so the Python harness can detect success or impasse:

```bash
if [ -n "$HARNESS_BUILD_STATUS_FILE" ]; then
  if [ -f "codegen-impasse.md" ]; then
    printf '{"status":"impasse","impasse_file":"codegen-impasse.md"}' > "$HARNESS_BUILD_STATUS_FILE"
  else
    printf '{"status":"done"}' > "$HARNESS_BUILD_STATUS_FILE"
  fi
fi
```

If `$HARNESS_BUILD_STATUS_FILE` is not set (standalone invocation), skip this step entirely.
