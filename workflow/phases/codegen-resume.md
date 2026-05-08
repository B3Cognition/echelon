# Phase: codegen-resume
# Source: echelon.codegen.md §Resume Mode + §Error Handling
# Read by: ORCHESTRATOR when invoked with --resume, or on any error condition

## Resume Mode

If `$ARGUMENTS` is `--resume`:

```bash
if [ ! -f codegen-state.json ]; then
  echo "[ECHELON CODEGEN] ERROR: No codegen-state.json found. Cannot resume."
  exit 1
fi

RESUME_PHASE=$(jq -r '.current_phase' codegen-state.json | tr '[:upper:]' '[:lower:]')
RESUME_COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
TOTAL_TASKS=$(jq '(.task_queue.pending | length) + (.task_queue.completed | length)' codegen-state.json 2>/dev/null || echo 0)
WING=$(jq -r '.wing' codegen-state.json 2>/dev/null || echo "unknown")

write_state() {
  local phase="$1" status="$2" completed="${3:-0}" current="${4:-null}" verdict="${5:-null}"
  mkdir -p "$(dirname "$HARNESS_STATE_FILE")"
  cat > "$HARNESS_STATE_FILE" << STATEOF
{
  "status": "${status}", "phase": "${phase}",
  "build": { "total_tasks": ${TOTAL_TASKS:-0}, "completed_tasks": ${completed}, "current_task": ${current}, "verification_verdict": ${verdict} },
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
STATEOF
}
write_state "codegen_${RESUME_PHASE}" "building" $RESUME_COMPLETED null null
```

Display:
```
[CODEGEN RESUME]
Pipeline ID : <pipeline_id>
Wing        : <wing>
Resuming at : <current_phase>
Completed   : <phases_completed joined by " → ">
Tasks done  : <completed> / <total>
Ψ score     : <psi.score> (threshold 0.70)
Tier 1 gate : <tier1_gate>
```

Jump to `current_phase`. Do NOT re-mine specs — MemPalace already has them.

---

## Error Handling

| Error | Response |
|-------|----------|
| Missing Phase A artifact | STOP — print which file is missing + hint to run `speckit.echelon.run` |
| SOAR binary not found | HARD STOP — print `bash ~/echelon/scripts/install.sh` |
| codegen CLI not found | HARD STOP — print `bash ~/echelon/scripts/install.sh` |
| No test runner found | Warn, mark tier1 unavailable, generate CI config |
| Impasse (exit 2) | Stop, report `codegen-impasse.md` — do NOT enter feedback loop |
| Context window limit | Write state.json, print `[CODEGEN] Run speckit.echelon.codegen --resume to continue` |
| Filesystem write outside target | BLOCK — `[CODEGEN SECURITY] Write outside target blocked` |
