# Phase: init
# Source: echelon.run.md §1 — Initialization (INIT)
# Read by: echelon.commander (COMMANDER) before starting any phase dispatch

## 1. Initialization (INIT)

### 1.0 Anchor Project Root

Before any file operation, establish and record the absolute project root:

```bash
PROJECT_ROOT=$(pwd)
echo "PROJECT_ROOT=${PROJECT_ROOT}"
```

Store `PROJECT_ROOT` in your context. All paths written to state.json, passed to agents, or used in file operations **must be absolute paths** derived from `${PROJECT_ROOT}`. Always use `${PROJECT_ROOT}/specs/003-...` paths — never bare relative paths like `specs/003-...`.

**MANDATORY — Run this check with the Bash tool before any other init step:**

```bash
ECHELON_EXT="${PROJECT_ROOT}/.echelon/runtime"
ECHELON_CONFIG="${PROJECT_ROOT}/.echelon/config.yml"
if [ ! -f "${ECHELON_CONFIG}" ]; then
  echo "✗ Echelon config not found at ${ECHELON_CONFIG}" >&2
  echo "  Run 'echelon workspace init' first." >&2
  exit 1
fi
echo "✓ Echelon config found at ${ECHELON_CONFIG}"
```

If this exits non-zero: **HARD STOP**. Always print the message below. Do not proceed.

```text
✗ Echelon config not found.
  Run echelon workspace init first, then re-run echelon spec run.
```

> **Note:** `validate-deploy.sh` is only relevant to `echelon delivery run` (it validates deploy infrastructure written during workspace initialization). Always leave `echelon spec run` startup deploy-neutral. Do NOT call `validate-deploy.sh` from `echelon spec run` — it will fail on fresh projects that have not yet run delivery.

### 1.1 Detect Greenfield vs Brownfield

The Echelon controller initializes `state.json.mode` before phase dispatch. It
uses the deployed `.echelon/runtime/scripts/bash/detect-project.sh` helper for
automatic detection, preserves an explicit project-mode override, and falls
back to `greenfield` if detection is unavailable or invalid.

**MANDATORY:** Treat `state.json.mode` as authoritative. Do not run a second
model-side detection or infer mode ad hoc from file counts.

### 1.2 Create Staging Area

The UNDERSTAND phase (DISCOVER → WHY1) runs BEFORE we know what to build. Its
discovery outputs go to the current run's staging area. `${SQUAD_DIR}` is already
a unique `runs/<run-id>/` directory created by the harness, so it is also the
durable archive for this run. Never copy it into a nested archive and never wipe
staging during initialization or resume.

```bash
mkdir -p "${STAGING_DIR}"
```

Before WHAT, staging owns discovery artifacts. After WHAT, `{spec_dir}` owns
canonical product artifacts while staging remains a control-plane inbox for
files such as `user-clarifications.md` and `governance-trail.json`.

**Important:** Echelon's Phase A bootstrap creates the feature branch and
reserves the full run-local `spec_dir` before squad dispatch. WHAT authors
content only in that controller-provided directory; it does not create a branch
or choose a spec directory.

### 1.3 Initialize State

Create `${SQUAD_DIR}/state.json`:

```json
{
  "run_id": "squad-{unix_timestamp}",
  "status": "running",
  "phase": "init",
  "mode": "{greenfield|brownfield}",
  "iteration": 0,
  "project_root": "{absolute path from PROJECT_ROOT}",
  "spec_id": null,
  "spec_dir": null,
  "constitution_status": "pending",
  "created_at": "{ISO-8601}",
  "updated_at": "{ISO-8601}",
  "token_usage": 0,
  "quality_scores": [],
  "active_specialists": [],
  "issues_log": [],
  "blocked_reason": null,
  "escalation_question": null,
  "dispatch_counters": {},
  "fallback_mode": false,
  "published_re_context": null
}
```

Note: `project_root` is set immediately from `${PROJECT_ROOT}` (absolute path).
Phase A bootstrap sets the immutable full `spec_id`, `spec_dir`,
`published_spec_dir`, and `feature_branch` before dispatch; `spec_dir` is the
run-local path (`${SQUAD_DIR}/specs/{NNN}-{feature}`). `constitution_status` is
set to `"exists"` in section 1.7 if constitution already exists, or updated in
section 3.5 after constitution creation.

### Run History Check — MANDATORY STEP

> **Always run this check. Do not skip it.** Skipping it breaks Phase A → Phase B continuity: future runs cannot detect that Phase A is already complete, causing duplicate work.

1. Check if `{spec_dir}/run-history.json` exists (only possible if `spec_dir` was specified as an argument — if starting fresh with no spec_dir yet, proceed to step 3).
2. If `run-history.json` exists:
   - Read `runs` array. Find the latest entry where `phase: "A"` and `status: "done"`.
   - Compare `constitution_hash` from that entry against current SHA of `.echelon/constitution.md`.
   - If Phase A is done AND constitution hash matches: log `[echelon.commander (COMMANDER)] Phase A already complete for run {run_id} — skipping to Phase B routing` and jump to the ASSESS/DECIDE section. Return `phase: phase1-constitution` in `echelon_result.state_updates` to signal resume.
   - If Phase A is done but constitution hash differs: log `[echelon.commander (COMMANDER)] Constitution changed since last Phase A run — re-running Phase A to update spec/plan/tasks`, continue normally.
3. If `run-history.json` does not exist: continue normally (new spec, first run).

### 1.4 Initialize Staging Reasoning Journal

Create `${SQUAD_DIR}/reasoning-journal.jsonl`:

```json
{
  "entries": []
}
```

This remains at the run root for the lifetime of the run. Agents receive it via
the harness context pack; it is not moved into the spec directory.

### 1.5 Load Prior Run Data (if re-run)

If user specifies a prior spec (e.g., "continue with 012-feature"):

- Find `specs/{NNN}-{feature}/` directory
- Read `reasoning-journal.jsonl` for continuity
- Read `evolution-report.md` if it exists
- Set `iteration` to prior iteration + 1
- Set `spec_id` and `spec_dir` in state.json
- Note: EVOLVE will diff against prior artifacts during FINALIZE

**Load from prior runs (automatic):** If no explicit prior spec is given, use the
harness-provided prior/current feature context assembled from sibling
`runs/<prior-run-id>/` directories. Each prior run keeps its own `state.json`,
`reasoning-journal.jsonl`, staging control inputs, and run-local spec tree.
Never search for or create a nested archive beneath the active run.

### 1.6 Load Configuration — MANDATORY

**Reading threshold values:** COMMANDER reads `.echelon/config.yml` plus optional `.echelon/local.yml` through the deployed Echelon runtime resolver. It emits `ECHELON_CFG_*` values for the current shell.

```bash
eval "$(bash "${PROJECT_ROOT}/.echelon/runtime/scripts/bash/echelon-config-get.sh" --env convergence)"
```

For a scalar or a different mapping, call `bash .echelon/runtime/scripts/bash/echelon-config-get.sh <key>` or use `--env <mapping>` as above. Treat resolver failure as a configuration error; do not substitute inferred defaults.

This merges `.echelon/config.yml` (project config) and `.echelon/local.yml` (local overrides). Key defaults when no project config exists:

- `ECHELON_CFG_CONVERGENCE_MAX_ITERATIONS`: 5
- `ECHELON_CFG_CONVERGENCE_DELTA`: 0.02
- `ECHELON_CFG_MAX_ACTIVE_SPECIALISTS`: 3
- `ECHELON_CFG_BUDGET_TOKEN_BUDGET_K`: 1000
- Quality gates: use the Resolved Quality Gates injected from the project configuration; workflow files never restate numeric thresholds.

> **Authoritative values:** `.echelon/config.yml` plus optional `.echelon/local.yml` are the source of truth for all tunable thresholds (`convergence:`, `budget:`, `quality_gates:`). `workflow/definition.yaml` is the authority for the phase graph and routing structure only.

### 1.7 Check Constitution Status

Check if `.echelon/constitution.md` exists and note the status:

**If EXISTS:**

- Read the constitution — it will guide all architectural decisions
- Store constitution principles in context for echelon.architect (ARCHITECT) and all build agents
- Return `constitution_status: exists` in `echelon_result.state_updates`

**If MISSING:**

- Return `constitution_status: pending` in `echelon_result.state_updates`
- Always continue with `constitution_status: "pending"`. **Do NOT block** — constitution will be created after UNDERSTAND phase when we have enough context
- Note: Constitution creation happens in section 3.5 (after WHY1) using UNDERSTAND findings

### Provider Availability

Provider availability is validated by Echelon before dispatch. echelon.commander (COMMANDER) assumes `fallback_mode = false` at run start. If a provider invocation fails during the run, echelon.commander (COMMANDER) returns the fallback fields in `echelon_result.state_updates` at that point:

```yaml
fallback_mode: true
execution_mode: manual_specification
```

Always continue routing in both available and fallback paths (AC-001a-4). echelon.cartographer (CARTOGRAPHER) dispatch must never be blocked by fallback detection.

For reconciliation after recovery, reference `templates/recovery-checklist.md` and operational guidance in `docs/fallback-mode.md`.

### Preflight: KB Evolution Validation

If `bash .echelon/runtime/scripts/bash/echelon-config-get.sh evolution.enabled` returns `true`:

```bash
scripts/bash/kb-validate-evolution.sh --state ${SQUAD_DIR}/state.json
```

- Exit 0: Continue
- Exit 1: Log validation failures to `state.json.issues_log` with severity `MEDIUM`, continue execution (non-blocking — data quality issues should not prevent runs)

### 1.8 Published RE context (optional read-only input)

The harness records `state.json.published_re_context` before workflow dispatch.
When its status is `attached`, include only its run-local snapshot paths in Phase 1
context packs. Never dispatch reverse engineering from the spec workflow and never
read the mutable canonical `re/` tree.

**Transition:** `phases[phase1-discover]` — see `workflow/definition.yaml`
