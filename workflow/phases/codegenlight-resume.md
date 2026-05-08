# Phase: codegenlight-resume
# Source: echelon.codegenlight.md §RESUME Mode + §Error Handling
# Read by: ORCHESTRATOR when invoked with --resume, or on any error condition

## RESUME Mode

If `--resume`:

1. Read `./codegen-state.json`
2. Display:
   ```
   [CODEGEN RESUME]
   Pipeline ID : <pipeline_id>
   Wing        : <wing>
   Resuming at : <current_phase>
   Completed   : <phases_completed joined by " → ">
   Requirements: <re_phase.requirements_retrieved>
   Tasks done  : <completed> / <total>
   Ψ score     : <psi.score> (threshold <psi.threshold>)
   Tier 1 gate : <tier1_gate>
   ```

3. Restore harness state from `codegen-state.json`:

```bash
RESUME_PHASE=$(jq -r '.current_phase' codegen-state.json | tr '[:upper:]' '[:lower:]')
RESUME_COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
TOTAL_TASKS=$(jq '(.task_queue.pending | length) + (.task_queue.completed | length)' codegen-state.json 2>/dev/null || echo 0)

# Restore harness integration env (written by echelon.codegen on first run)
[ -f .codegen-harness-env ] && source .codegen-harness-env
write_state() {
  [ -z "${HARNESS_STATE_FILE:-}" ] && return 0
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
echo "[CODEGEN RESUME] state.json restored — phase=codegen_${RESUME_PHASE}"
```

4. Jump to `current_phase`. Do NOT re-mine specs on resume — MemPalace already has them.

---

## Error Handling

| Error | Response |
|-------|----------|
| SOAR bridge fails to start | Fall back to Model B, log warning, continue |
| Spec glob matches no files | Warn, continue without requirement mining |
| MemPalace unavailable | Warn, continue without RE lookup — pipeline still runs |
| No test runner found | Warn, mark tier1 unavailable, generate CI config |
| Context window approaching limit | Write state.json, print `[CODEGEN] Context limit — checkpoint written. Run /codegen --resume to continue.` |
| Git auth failure | Log error, skip git, deliver files as-is |
| Filesystem write outside target | BLOCK — `[CODEGEN SECURITY] Write outside target blocked (FR-CMD-006)` |
