# Phase: codegen-3-implement
# Source: echelon.codegen.md §Phase 3 — IMPLEMENT Dispatch Loop
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: echelon.orchestrator (ORCHESTRATOR) before each IMPLEMENT loop iteration

---

## Phase 3: IMPLEMENT — echelon.implementer (IMPLEMENTER) Dispatch Loop

**Print:** `[CODEGEN] Phase IMPLEMENT — Starting (<N> tasks)...`

For each task in `task_queue.pending`:

### 3.1 SOAR dispatches task

Inject task WME into SOAR. SOAR selects DISPATCH_IMPLEMENTER operator.
Print: `[CODEGEN] Task <task-id>: DISPATCHING to echelon.implementer (IMPLEMENTER)...`

### 3.2 echelon.implementer (IMPLEMENTER) executes task

```
Agent (echelon.implementer (IMPLEMENTER) role): Implement task <task-id>: <description>
Scope: <scope>, Language: <language>

Requirements this task must satisfy (from MemPalace):
<FR-*/AC-* entries cited by this task>

CQ-ISC advisory (informational — not enforcement): <relevant CQ-ISC rule texts>

IMPORTANT: You are ADVISING SOAR. Output best-preference recommendations only.
Always leave final quality gate decisions to SOAR. Do NOT make final quality gate decisions.
Generate the implementation files. Write tests.
Report: status (DONE/BLOCKED/NEEDS_CONTEXT), files modified, test results.
```

### 3.3 Static analysis

```bash
ruff check --output-format=json <files> 2>/dev/null || true          # Python
npx eslint --format json <files> 2>/dev/null || true                  # TypeScript
golangci-lint run --out-format json <files> 2>/dev/null || true       # Go
```

### 3.4 Gate evaluation

```bash
codegen gate --phase IMPLEMENT --language <language> --files <files> --state-file codegen-state.json
```

- Exit 0 (ADVANCE): task complete → move to `completed`
- Exit 1 (RETRY): re-dispatch echelon.implementer (IMPLEMENTER) with violation details + failed FR citation
- Exit 2 (ESCALATE): write `codegen-impasse.md`, halt, wait for human

```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
CURRENT_TASK=$(jq -r '.task_queue.pending[0] // "null"' codegen-state.json 2>/dev/null || echo null)
if [ "$CURRENT_TASK" = "null" ]; then
  write_state "codegen_implement" "building" $COMPLETED null null
else
  write_state "codegen_implement" "building" $COMPLETED "\"${CURRENT_TASK}\"" null
fi
```

On ESCALATE (exit 2):
```bash
COMPLETED=$(jq '.task_queue.completed | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_implement" "escalated" $COMPLETED null null
```

**Print:** `[CODEGEN] Phase IMPLEMENT — COMPLETE ✓ (<done> done, <blocked> blocked)`
