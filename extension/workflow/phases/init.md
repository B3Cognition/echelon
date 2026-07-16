# Phase: init
# Source: echelon.run.md §1 — Initialization (INIT)
# Read by: speckit-echelon-commander (COMMANDER) before starting any phase dispatch

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
ECHELON_EXT="${PROJECT_ROOT}/.specify/extensions/echelon"
if [ ! -f "${ECHELON_EXT}/echelon-config.yml" ]; then
  echo "✗ echelon-config.yml not found at ${ECHELON_EXT}/echelon-config.yml" >&2
  echo "  Run 'speckit.echelon.init' first to create the project configuration." >&2
  exit 1
fi
echo "✓ echelon-config.yml found at ${ECHELON_EXT}/echelon-config.yml"
```

If this exits non-zero: **HARD STOP**. Always print the message below. Do not proceed.

```text
✗ echelon-config.yml not found.
  Run speckit.echelon.init first, then re-run speckit.echelon.run.
```

> **Note:** `validate-deploy.sh` is only relevant for `speckit.echelon.build` and `speckit.echelon.codegen` (it validates deploy infrastructure written by `echelon workspace init`). Always leave `echelon.run` startup deploy-neutral. Do NOT call `validate-deploy.sh` from `echelon.run` — it will fail on fresh projects that have not yet run a build.

### 1.1 Detect Greenfield vs Brownfield

The `startup-banner.sh` frontmatter script chains to `detect-project.sh` and its output (`"greenfield"` or `"brownfield"`) is available as `$SH_OUTPUT`.

**MANDATORY — always use `$SH_OUTPUT` as the authoritative mode signal. Do NOT detect mode ad hoc by examining file counts or directory structure yourself.**

```bash
mode = $SH_OUTPUT        # "greenfield" | "brownfield"
```

Override rules:

- If the user explicitly provided a repo path as an argument: re-run `detect-project.sh` against that path and use its output instead.
- If `$SH_OUTPUT` is empty or unavailable (script failed): default to `greenfield` and log a `cold_start_warning` journal entry noting that mode detection was skipped.

### 1.2 Create Staging Area

The UNDERSTAND phase (DISCOVER → WHY1) runs BEFORE we know what to build. Outputs go to a staging area.

**Archive prior run before wiping.** If staging contains artifacts from a completed prior run, archive them so project knowledge persists:

```bash
# Archive prior staging artifacts if they exist
if [ -d "${STAGING_DIR}" ] && [ "$(ls ${STAGING_DIR}/ 2>/dev/null)" ]; then
  # Read prior run_id from state.json (if available)
  PRIOR_RUN_ID=$(python3 -c "import json; print(json.load(open('${SQUAD_DIR}/state.json')).get('run_id','unknown'))" 2>/dev/null || echo "unknown")
  ARCHIVE_DIR="${SQUAD_DIR}/archive/${PRIOR_RUN_ID}"
  mkdir -p "$ARCHIVE_DIR"
  cp -r ${STAGING_DIR}/* "$ARCHIVE_DIR/" 2>/dev/null || true
  # Also archive state.json snapshot
  cp ${SQUAD_DIR}/state.json "$ARCHIVE_DIR/state.json" 2>/dev/null || true
  echo "Archived prior run ${PRIOR_RUN_ID} → ${ARCHIVE_DIR}/"
fi

# Now safe to wipe staging
rm -rf "${STAGING_DIR}"
mkdir -p "${STAGING_DIR}"
```

**Archive structure:** `${SQUAD_DIR}/archive/{run_id}/` preserves all analysis artifacts (spec.md, issues.md, tasks.md, reasoning-journal.jsonl, etc.) from each completed run. This is the project's institutional memory — it survives across runs and enables EVOLVE to diff artifacts between runs.

**Important:** Always let the WHAT phase create `specs/{NNN}-{feature}/` via `speckit.specify`. Do NOT create it yet.

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
  "split_metrics": { "fallback_count": 0, "qa_coverage": 0.0, "rework_count": 0 },
  "fallback_mode": false,
  "published_re_context": null
}
```

Note: `project_root` is set immediately from `${PROJECT_ROOT}` (absolute path). `spec_id` and `spec_dir` are set later when `speckit.specify` creates the branch — `spec_dir` is always stored as an absolute path (`${PROJECT_ROOT}/specs/{NNN}-{feature}`). `constitution_status` is set to `"exists"` in section 1.7 if constitution already exists, or updated in section 3.5 after constitution creation.

### Run History Check — MANDATORY STEP

> **Always run this check. Do not skip it.** Skipping it breaks Phase A → Phase B continuity: future runs cannot detect that Phase A is already complete, causing duplicate work.

1. Check if `{spec_dir}/run-history.json` exists (only possible if `spec_dir` was specified as an argument — if starting fresh with no spec_dir yet, proceed to step 3).
2. If `run-history.json` exists:
   - Read `runs` array. Find the latest entry where `phase: "A"` and `status: "done"`.
   - Compare `constitution_hash` from that entry against current SHA of `.specify/memory/constitution.md`.
   - If Phase A is done AND constitution hash matches: log `[speckit-echelon-commander (COMMANDER)] Phase A already complete for run {run_id} — skipping to Phase B routing` and jump to the ASSESS/DECIDE section. Return `phase: phase1-constitution` in `echelon_result.state_updates` to signal resume.
   - If Phase A is done but constitution hash differs: log `[speckit-echelon-commander (COMMANDER)] Constitution changed since last Phase A run — re-running Phase A to update spec/plan/tasks`, continue normally.
3. If `run-history.json` does not exist: continue normally (new spec, first run).

### 1.4 Initialize Staging Reasoning Journal

Create `${SQUAD_DIR}/reasoning-journal.jsonl`:

```json
{
  "entries": []
}
```

This will be moved to the spec directory after `speckit.specify` creates it.

### 1.5 Load Prior Run Data (if re-run)

If user specifies a prior spec (e.g., "continue with 012-feature"):

- Find `specs/{NNN}-{feature}/` directory
- Read `reasoning-journal.jsonl` for continuity
- Read `evolution-report.md` if it exists
- Set `iteration` to prior iteration + 1
- Set `spec_id` and `spec_dir` in state.json
- Note: EVOLVE will diff against prior artifacts during FINALIZE

**Load from archive (automatic):** If no explicit prior spec is given but `${SQUAD_DIR}/archive/` contains prior runs:

```bash
# Find the most recent archived run
LATEST_ARCHIVE=$(ls -td ${SQUAD_DIR}/archive/squad-* 2>/dev/null | head -1)
if [ -n "$LATEST_ARCHIVE" ]; then
  echo "Prior run found: ${LATEST_ARCHIVE}"
  # Read prior reasoning journal for continuity
  if [ -f "${LATEST_ARCHIVE}/reasoning-journal.jsonl" ]; then
    # Include prior journal entries as context for all agents
    PRIOR_JOURNAL="${LATEST_ARCHIVE}/reasoning-journal.jsonl"
  fi
  # Read prior issues for regression tracking
  if [ -f "${LATEST_ARCHIVE}/issues.md" ]; then
    PRIOR_ISSUES="${LATEST_ARCHIVE}/issues.md"
  fi
  # Read prior quality scores for convergence comparison
  if [ -f "${LATEST_ARCHIVE}/state.json" ]; then
    PRIOR_QUALITY=$(python3 -c "import json; s=json.load(open('${LATEST_ARCHIVE}/state.json')); print(json.dumps(s.get('quality_scores',[])))" 2>/dev/null)
  fi
fi
```

Prior run data is included in agent context packs so the squad can track improvement, detect regressions, and avoid re-discovering the same issues.

### 1.6 Load Configuration — MANDATORY

**Reading threshold values:** COMMANDER's preferred path is `specify extension config resolve echelon --format env --prefix ECHELON_CFG_`, which would layer manifest defaults → project overrides → local overrides → env vars and emit `ECHELON_CFG_*` env vars for the current shell.

```bash
# Optional layered-config attempt (resolver may not be installed):
_resolver_out=$(specify extension config resolve echelon --format env --prefix ECHELON_CFG_ 2>/dev/null)
if [[ -n "$_resolver_out" ]] && printf '%s\n' "$_resolver_out" | grep -q '^ECHELON_CFG_'; then
  eval "$_resolver_out"
  _ECHELON_RESOLVER_OK=true
fi
```

**However: the `config` subcommand is not implemented in the currently installed `specify` CLI.** The endocrine.sh bootstrap (commit `df99b73`, post-DEP-FIX T2) detects this and falls through to reading `echelon-config.yml` directly. COMMANDER should also treat the direct YAML read via `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh <key>` as the production-equivalent path, not a degraded fallback. Log `dependency_failure` (`dependency: specify_extension_config_resolve`) once per run if the resolver attempt failed.

This merges manifest defaults → `echelon-config.yml` (project overrides) → `local-config.yml` → `SPECKIT_ECHELON_*` env vars. Key defaults when no project config exists:

- `ECHELON_CFG_CONVERGENCE_MAX_ITERATIONS`: 5
- `ECHELON_CFG_CONVERGENCE_DELTA`: 0.02
- `ECHELON_CFG_MAX_ACTIVE_SPECIALISTS`: 3
- `ECHELON_CFG_BUDGET_TOKEN_BUDGET_K`: 1000
- Quality gates: overall >= 0.70, structure >= 0.70, testability >= 0.70, semantic >= 0.60, cognitive >= 0.60, readability >= 0.50

> **Authoritative values:** `echelon-config.yml` (project overrides) / manifest `config.defaults` (fallback) is the single source of truth for all tunable thresholds (`convergence:`, `budget:`, `quality_gates:`). `workflow/definition.yaml` is the authority for the phase graph and routing structure only.

### 1.7 Check Constitution Status

Check if `.specify/memory/constitution.md` exists and note the status:

**If EXISTS:**

- Read the constitution — it will guide all architectural decisions
- Store constitution principles in context for speckit-echelon-architect (ARCHITECT) and all build agents
- Return `constitution_status: exists` in `echelon_result.state_updates`

**If MISSING:**

- Return `constitution_status: pending` in `echelon_result.state_updates`
- Always continue with `constitution_status: "pending"`. **Do NOT block** — constitution will be created after UNDERSTAND phase when we have enough context
- Note: Constitution creation happens in section 3.5 (after WHY1) using UNDERSTAND findings

### Spec-kit Availability

spec-kit skill availability is validated at install time (`specify extension add echelon`). speckit-echelon-commander (COMMANDER) assumes `fallback_mode = false` at run start. If a skill invocation fails during the run, speckit-echelon-commander (COMMANDER) returns the fallback fields in `echelon_result.state_updates` at that point:

```yaml
fallback_mode: true
execution_mode: manual_specification
```

Always continue routing in both available and fallback paths (AC-001a-4). speckit-echelon-cartographer (CARTOGRAPHER) dispatch must never be blocked by fallback detection.

For reconciliation after recovery, reference `templates/recovery-checklist.md` and operational guidance in `docs/fallback-mode.md`.

### Preflight: KB Evolution Validation

If `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh evolution.enabled` returns `true`:

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
