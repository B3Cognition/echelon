# Phase: codegen-2-decompose
# Source: echelon.codegen.md §Phase 2 — DECOMPOSE Task Decomposition
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: ORCHESTRATOR before Phase 2 DECOMPOSE execution

---

## Phase 2: DECOMPOSE — Task Decomposition

**Print:** `[CODEGEN] Phase DECOMPOSE — Starting...`

```
Agent: Decompose the intent into implementation tasks.

Intent: <intent>

Retrieved requirements from MemPalace (RE phase):
<re_phase context from codegen-state.json>

Each task must:
  - Have a unique task-id (T-NNN)
  - Specify: description, scope (module/component), language, estimated complexity
  - Reference the specific FR-*/NFR-*/AC-* IDs from the retrieved requirements that gate it
  - Map to one or more CQ-ISC entries from the library

Output: ./codegen-staging/task-queue.json
```

Inject task WMEs into SOAR. Update state.json: `task_queue.pending = [all task IDs]`, `psi.denominator = |I_D|`.

**Write state checkpoint:** `current_phase: "IMPLEMENT"`

```bash
TOTAL_TASKS=$(jq '.task_queue.pending | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_implement" "building" 0 null null
```

**Print:** `[CODEGEN] Phase DECOMPOSE — COMPLETE ✓ (<N> tasks queued)`
