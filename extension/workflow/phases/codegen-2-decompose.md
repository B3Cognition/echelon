# Phase: codegen-2-decompose
# Source: echelon.codegen.md §Phase 2 — DECOMPOSE Task Decomposition
# Shared: used by both echelon.codegen and echelon.codegenlight
# Read by: echelon-orchestrator (ORCHESTRATOR) before Phase 2 DECOMPOSE execution

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

## Inject the mandatory COMPOSE task

After the feature task queue is written, append the single mandatory **COMPOSE**
task — it produces the runnable entry point and wires every component, and it
DEPENDS on all feature tasks (dependency-gated scheduling forces it to run last).
This guarantees composition is a tracked deliverable, never the agent's option.

```bash
python3 - <<'PY'
import json
from codegen.decompose.task_queue import TaskQueue, CodeTask, TaskStatus
from codegen.decompose.compose_task import inject_compose_task, dependency_safe_order
q = TaskQueue()
data = json.load(open("./codegen-staging/task-queue.json"))
for t in data["tasks"]:
    q.add(CodeTask(task_id=t["task-id"], description=t["description"], scope=t["scope"],
                   language=t["language"], module_boundary=t["module-boundary"],
                   depends_on=[d for d in t["depends-on"].split(",") if d]))
_tasks = q.all_tasks()
language = _tasks[0].language if _tasks else "typescript"
compose = inject_compose_task(q, language=language)
json.dump({"tasks": [t.to_wme_dict() for t in q.all_tasks()]},
          open("./codegen-staging/task-queue.json", "w"), indent=2)
print(f"injected {compose.task_id} depends_on={compose.depends_on}")
print("pending_order:", ",".join(dependency_safe_order(q)))
PY
```

After running the snippet above, `task_queue.pending` MUST be written to `codegen-state.json` using the dependency-safe order printed above (the `pending_order:` line) so that COMPOSE (`T-999`) is always dispatched last. The IMPLEMENT loop reads `task_queue.pending[0]` — if this list is not in dependency-safe order, COMPOSE may be popped before its feature dependencies are done.

ALWAYS inject exactly one COMPOSE task (`T-999`) depending on all feature tasks.
NEVER hand-author composition as an optional feature task or omit it.

Inject task WMEs into SOAR. Update `codegen-state.json` through the codegen pipeline state writer: `task_queue.pending = [all task IDs]`, `psi.denominator = |I_D|`.

**Write state checkpoint:** `current_phase: "IMPLEMENT"`

```bash
TOTAL_TASKS=$(jq '.task_queue.pending | length' codegen-state.json 2>/dev/null || echo 0)
write_state "codegen_implement" "building" 0 null null
```

**Print:** `[CODEGEN] Phase DECOMPOSE — COMPLETE ✓ (<N> tasks queued)`
