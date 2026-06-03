# Phase: build-1-init
# Source: echelon.build.md §1 — Build Initialization (BUILD_INIT)
# Read by: speckit-echelon-commander (COMMANDER) before starting build workflow

---

## 1. Initialization (BUILD_INIT)

**Build Start State Update (mandatory, runs once before first task):**

1. Count only canonical task rows in `{spec_dir}/tasks.md` (top-level lines matching `^- \[[ xX]\] T-[0-9]{3,4}\b`) and include the count in `echelon_result.state_updates.build.total_tasks`. Acceptance-criteria checkboxes are not tasks.
2. Return the full initialized `build` object in one `echelon_result.state_updates.build` value; the harness applies it to `state.json`.

### 1.0 Anchor Project Root

Before any file operation, establish the absolute project root:

```bash
PROJECT_ROOT=$(pwd)
echo "PROJECT_ROOT=${PROJECT_ROOT}"
```

Read `project_root` from `${SQUAD_DIR}/state.json` and verify it matches. All paths used in file operations and passed to agents **must be absolute paths** derived from `${PROJECT_ROOT}`. Always use `${PROJECT_ROOT}/specs/{NNN}-{feature}` for the feature directory — never a bare relative path.

### 1.0b Validate Deploy Infrastructure

Before loading Phase A artifacts, confirm the deploy pipeline is intact:

```bash
ECHELON_EXT="${PROJECT_ROOT}/.specify/extensions/echelon"
bash "${ECHELON_EXT}/scripts/bash/validate-deploy.sh" "${PROJECT_ROOT}"
```

If exit code is non-zero, HARD STOP. Always stop and follow the error output fix instructions. Do not proceed with the build.

### 1.1 Validate Phase A Artifacts

Read and verify these files exist in `specs/{NNN}-{feature}/`:

**Required:**

- `tasks.md` — The implementation plan (task list with IDs, descriptions, acceptance criteria, dependencies)
- `spec.md` — The specification (for FR-* requirement references)
- `constitution.md` — Non-negotiable coding rules
- `research.md` — ADRs and architectural decisions
- `test-strategy.md` — Test approach per component type
- `coverage-map.md` — Requirement-to-test mappings

**Optional (used if present):**

- `data-model.md` — Entity shapes and relationships
- `contracts/` — API and component interface definitions
- `estimates.md` — Effort estimates per task
- `calibration-profile.yaml` — Historical accuracy data

Before validating, resolve `constitution.md` from `.specify/memory/` if missing from the spec dir:

```bash
if [ ! -f "${SPEC_DIR}/constitution.md" ]; then
  if [ -f "${PROJECT_ROOT}/.specify/memory/constitution.md" ]; then
    cp "${PROJECT_ROOT}/.specify/memory/constitution.md" \
       "${SPEC_DIR}/constitution.md"
    echo "[RECOVERY] constitution.md copied from .specify/memory/ ✓"
  fi
fi
```

If `tasks.md` or `spec.md` is missing, STOP with error: "Phase A artifacts not found. Run `speckit.echelon.run` first."

### 1.2 Parse Tasks

Read `tasks.md` and parse all tasks into a structured list:

- Canonical task row (e.g., `- [ ] T-001 [P] complexity=standard phase=foundation req=FR-001 depends=none`)
- Task ID (`T-###`)
- Phase/group (`phase=<token>`)
- Complexity (`trivial`, `standard`, or `complex`)
- Description
- File paths (where code goes)
- Acceptance criteria
- Dependencies (`depends=none` or comma-separated task IDs)
- Referenced requirements (`req=FR-*` or `INFRA`)
- Estimated effort (from `estimates.md` if available)

### 1.3 Determine Build Order

Order tasks by:

1. Phase/group order (Foundation before Core before Polish)
2. Within a phase: dependency order (dependencies before dependents)
3. Within same dependency level: critical path first (from `critical-path.md` if available)

If user specified task IDs, filter to only those tasks. Verify dependencies are met (either already built or included in the filter).

### 1.4 Initialize Build State

Return these state updates in `echelon_result`; the harness applies them to `${SQUAD_DIR}/state.json`:

```yaml
echelon_result:
  state_updates:
    status: building
    spec_status: in-progress
    phase: build_init
    build:
      total_tasks: "{count}"
      completed_tasks: 0
      tasks_completed_pct: 0
      current_task: null
      current_phase_group: null
      task_results: {}
      phase_checkpoints: []
    updated_at: "{ISO-8601}"
```

### 1.5 Initialize Build Reports

Create empty report files (or clear prior content):

- `specs/{feature}/spec-compliance-report.md`
- `specs/{feature}/code-review-report.md`
- `specs/{feature}/test-quality-report.md`
- `specs/{feature}/progress-report.md`

**Transition:** Proceed to task iteration.
