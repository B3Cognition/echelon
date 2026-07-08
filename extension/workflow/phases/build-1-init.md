# Phase: build-1-init
# Source: echelon.build.md §1 — Build Initialization (BUILD_INIT)
# Read by: speckit-echelon-commander (COMMANDER) before starting build workflow

---

## Harness Continuity Rule

When this phase is executed by `echelon delivery run`, Ralph invokes one
LLM-backed build process and waits for `.harness-build-status.json`.
Ralph does not consume `next_phase` from the final message and does not
automatically re-dispatch `build-2-implement` after this response.

Do not return `next_phase: build-2-implement` and stop. After initialization,
continue directly into `build-2-implement` in the same build invocation. If an
Agent/subagent tool is unavailable, execute the required build role inline in
the main conversation and continue through the quality gates.

When `HARNESS_BUILD_STATUS_FILE` is set, do not wait for full-spec BUILD_DONE to
report success. The harness invocation boundary is one bounded verified progress
slice: after a task or coherent small batch passes the required gates, write
`.harness-build-status.json` with `{"status":"done","reason":"..."}` and stop.
Ralph owns verification, commit, and the next build invocation. Stop without a
`done` marker only on a real BLOCKED or ERROR condition, and write the matching
status marker before stopping.

## 1. Initialization (BUILD_INIT)

**Build Start State Update (mandatory, runs once before first task):**

1. Count only canonical task rows in `{spec_dir}/tasks.md` (top-level rows with `T-###`, or `T-S##` / `T-S##x` for spike/user-decision tasks) and include the count in `echelon_result.state_updates.build.total_tasks`. Acceptance-criteria checkboxes are not tasks.
2. Return the full initialized `build` object in one `echelon_result.state_updates.build` value; the harness applies it to `state.json`.

### 1.0 Anchor Project Root

Before any file operation, establish the absolute project root:

```bash
PROJECT_ROOT=$(pwd)
echo "PROJECT_ROOT=${PROJECT_ROOT}"
```

When running under `echelon delivery run`, use the exact paths provided in the
prompt's `Harness Context`:

- `worktree` / `target_repo_worktree` — implementation project root for code reads, searches, edits, and tests
- `spec_dir` — authoritative spec artifact directory
- `spec_file` — authoritative spec markdown file
- `tasks_file` — authoritative tasks markdown file
- `state_file` — harness state path, for read-only orchestration context only

Do not search for `state.json`, `${SQUAD_DIR}`, `runs/`, legacy `.specify/squad`
paths, `tasks.md`, `spec.md`, or `specs/` directories. Do not use `find`, `ls`,
globbing, or parent-directory scans to discover spec artifacts. If `spec_dir`,
`spec_file`, or `tasks_file` is `MISSING`, STOP and report a harness setup
failure.

All implementation paths used in file operations and passed to agents **must be
absolute paths** derived from `${PROJECT_ROOT}`. All spec artifact paths must be
absolute paths derived from `spec_dir`.

Before running any snippet that references `${SPEC_DIR}`, set it to the exact
`spec_dir` value from `Harness Context`:

```bash
SPEC_DIR="<spec_dir from Harness Context>"
echo "SPEC_DIR=${SPEC_DIR}"
```

### 1.0b Validate Deploy Infrastructure

Before loading Phase A artifacts, confirm the deploy pipeline is intact:

```bash
ECHELON_EXT="${PROJECT_ROOT}/.specify/extensions/echelon"
bash "${ECHELON_EXT}/scripts/bash/validate-deploy.sh" "${PROJECT_ROOT}"
```

If exit code is non-zero, HARD STOP. Always stop and follow the error output fix instructions. Do not proceed with the build.

### 1.1 Validate Phase A Artifacts

Read and verify these files exist in `{spec_dir}/`:

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

Do not copy, synthesize, or repair `constitution.md` in this build phase.
`spec_dir/constitution.md` is a published Phase A snapshot, and the terminal
harness preflight must already have verified that it exists and contains no
unresolved constitution template markers.

If `constitution.md`, `tasks.md`, or `spec.md` is missing, or if
`constitution.md` contains unresolved template markers such as
`[PROJECT_NAME]`, `[PRINCIPLE_1_NAME]`, or `[CONSTITUTION_VERSION]`, STOP with
error: "Phase A artifacts are not build-ready. Run `echelon spec continue` first."

### 1.2 Parse Tasks

Read `tasks.md` and parse all tasks into a structured list:

- Canonical task row (e.g., `- [ ] T-001 [P] complexity=standard phase=foundation req=FR-001 depends=none`; spike/user-decision rows may use `T-S01b`)
- Task ID (`T-###` for normal tasks; `T-S##` / `T-S##x` for spike/user-decision tasks)
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

- `{spec_dir}/spec-compliance-report.md`
- `{spec_dir}/code-review-report.md`
- `{spec_dir}/test-quality-report.md`
- `{spec_dir}/progress-report.md`

**Transition:** Proceed immediately to task iteration in this same build
invocation. Do not end the response at BUILD_INIT.
