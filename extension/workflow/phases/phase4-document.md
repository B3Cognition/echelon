# Phase: phase4-document
# Source: echelon.run.md §12 — FINALIZE Phase
# Agent: speckit-echelon-commander (COMMANDER) internal (sequential: speckit-echelon-realist (REALIST), speckit-echelon-mirror (MIRROR), speckit-echelon-adaptive (ADAPTIVE), speckit-echelon-auditor (AUDITOR), speckit-echelon-scorekeeper (SCOREKEEPER))
# Read by: speckit-echelon-commander (COMMANDER) before executing finalization sequence

## 12. FINALIZE Phase

> **Always execute steps 12.1–12.7 in order before step 12.8. NEVER skip to step 12.8.** The learning agents (speckit-echelon-realist (REALIST), speckit-echelon-mirror (MIRROR), speckit-echelon-auditor (AUDITOR), speckit-echelon-scorekeeper (SCOREKEEPER)) are the system's only mechanism for improving accuracy and pattern knowledge across runs. Skipping them means every run starts cold, estimates drift uncorrected, and failure modes repeat. Each step below is mandatory.

### 12.1 GROUND Agent — MANDATORY

Context pack:

- All artifacts in `specs/{feature}/`
- `calibration-profile.yaml` + `estimates-log.yaml`
- `reasoning-journal.jsonl`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in specs/{feature}/, calibration-profile.yaml, estimates-log.yaml, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are REALIST. Read agents/learning/realist.md for your complete protocol.
  Reality-check all artifacts. Connect plans to real-world data: infrastructure costs, production benchmarks, team capacity. Compare estimates to past outcomes via FEEDBACK data. Check architectural decisions against operational constraints. Flag disconnects. Produce outputs in `specs/{NNN}-{feature}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-realist (REALIST): reality check and reference class forecasting"

Expected outputs: `reality-check.md`, `cost-analysis.md`, `benchmark-data.md`

### 12.2 REFLECT Agent — MANDATORY

Context pack:

- All artifacts in `specs/{feature}/`
- `reasoning-journal.jsonl`
- `knowledge-base/patterns.yaml` + `knowledge-base/pitfalls.yaml`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in specs/{feature}/, reasoning-journal.jsonl, knowledge-base/patterns.yaml, knowledge-base/pitfalls.yaml]
  </context>

  <instructions>
  You are MIRROR. Read agents/learning/mirror.md for your complete protocol.
  Perform post-run analysis. Extract what assumptions were wrong, which patterns worked, what the squad should do differently. Log reusable patterns and pitfalls to the knowledge base. Update `knowledge-base/patterns.yaml` and `knowledge-base/pitfalls.yaml`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-mirror (MIRROR): post-run learning extraction"

### 12.3 EVOLVE Agent (if re-run)

Only dispatch if `state.json.iteration > 0` or prior run artifacts exist.

Context pack:

- All current artifacts
- Prior run artifacts (for diffing)
- `reasoning-journal.jsonl`
- `knowledge-base/` files

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all current artifacts, prior run artifacts for diffing, reasoning-journal.jsonl, knowledge-base/ files]
  </context>

  <instructions>
  You are ADAPTIVE. Read agents/learning/adaptive.md for your complete protocol.
  Diff artifacts between this run and prior runs. Measure quality trajectory. Detect regressions. Flag stagnation (if no improvement, recommend triggering INNOVATE on next run). Check for confirmation bias in knowledge base entries. Produce outputs in `specs/{NNN}-{feature}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-adaptive (ADAPTIVE): cross-run diffing and improvement measurement"

Expected outputs: `evolution-report.md`, `improvement-metrics.md`, `regression-alerts.md`

### 12.4 CALIBRATE Agent — MANDATORY

**Precondition: run the Per-Agent Internalization Data Handoff before dispatching speckit-echelon-auditor (AUDITOR).**

speckit-echelon-internalizer (INTERNALIZER) must run first so speckit-echelon-auditor (AUDITOR) can incorporate per-agent accuracy data into the calibration profile. See `commander.md` §"Per-Agent Internalization Data Handoff" for the full sequence:

1. Collect internalization artifacts (speckit-echelon-checkpoint (CHECKPOINT)'s report, verdict reports, prior `agent-scores.yaml`)
2. Dispatch speckit-echelon-internalizer (INTERNALIZER) (Measurement pass — 16 metrics per agent)
3. Dispatch speckit-echelon-internalizer (INTERNALIZER) (Per-Agent Scoring pass)
4. **Then** dispatch speckit-echelon-auditor (AUDITOR) (Calibration Dashboard Generation — uses speckit-echelon-internalizer (INTERNALIZER) results)
5. speckit-echelon-auditor (AUDITOR) writes `calibration-dashboard.md` to `specs/{NNN}-{feature}/`

Context pack:

- All artifacts in `specs/{feature}/`
- `knowledge-base/calibration-profile.yaml`
- `knowledge-base/estimates-log.yaml`
- `reasoning-journal.jsonl`
- Quality scores from all WHY passes (from state.json)
- speckit-echelon-internalizer (INTERNALIZER) outputs (per-agent composite scores and trends)

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in specs/{feature}/, knowledge-base/calibration-profile.yaml, knowledge-base/estimates-log.yaml, reasoning-journal.jsonl, quality scores from all WHY passes in state.json, speckit-echelon-internalizer (INTERNALIZER) per-agent scores]
  </context>

  <instructions>
  You are AUDITOR. Read agents/learning/auditor.md for your complete protocol.
  Track AI accuracy per domain. Build/update the confidence profile. Adjust ASSESS estimate multipliers based on historical data. Flag low-confidence domains for human input or speckit-echelon-investigator (INVESTIGATOR) investigation. Update `knowledge-base/calibration-profile.yaml`. Produce `confidence-flags.md` and `calibration-dashboard.md` in `specs/{NNN}-{feature}/`. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-auditor (AUDITOR): accuracy tracking and confidence profiling"

### 12.5 CALIBRATE Confidence Check

After CALIBRATE completes, read `confidence-flags.md`:

- If any domain has **confidence < 0.5** → summon speckit-echelon-investigator (INVESTIGATOR) for that domain (if not already investigated). This is a late-stage safety net.
- If speckit-echelon-investigator (INVESTIGATOR) was already summoned and confidence is still < 0.5 → always flag for human in the final report (do not block delivery).

### 12.6 Collect Final Artifacts

Verify all expected artifacts exist in `specs/{feature}/`. Create a manifest:

```
Artifact                          | Producer        | Status
----------------------------------|-----------------|--------
glossary.md                       | DISCOVER        | OK/MISSING/UNVALIDATED
mental-model.md                   | DISCOVER        | ...
boundaries.md                     | DISCOVER        | ...
assumptions.md                    | DISCOVER+WHY    | ...
unknowns.md                       | DISCOVER+WHY    | ...
spec.md                           | WHAT            | ...
feasibility.md                    | ASSESS          | ...
prioritization.md                 | ASSESS          | ...
estimates.md                      | ASSESS          | ...
mvp-scope.md                      | ASSESS          | ...
plan.md                           | HOW             | ...
research.md                       | HOW+speckit-echelon-investigator (INVESTIGATOR)   | ...
data-model.md                     | HOW             | ...
contracts/                        | HOW             | ...
constitution.md                   | HOW             | ...
tasks.md                          | PLAN            | ...
critical-path.md                  | PLAN            | ...
risk-matrix.md                    | PLAN            | ...
dependencies.md                   | PLAN            | ...
test-strategy.md                  | TEST speckit-echelon-architect (ARCHITECT)  | ...
test-architecture.md              | TEST speckit-echelon-architect (ARCHITECT)  | ...
coverage-map.md                   | TEST speckit-echelon-architect (ARCHITECT)  | ...
issues.md                         | WHY             | ...
quality-gates.md                  | WHY             | ...
reality-check.md                  | GROUND          | ...
cost-analysis.md                  | GROUND          | ...
benchmark-data.md                 | GROUND          | ...
implementability-report.md        | ASSESS2         | ...
reasoning-journal.jsonl            | ALL             | ...
confidence-flags.md               | CALIBRATE       | ...
```

Additional artifacts (conditional):

- `reference-architectures.md` (greenfield only)
- `assumption-review.md` (if WHY1 produced it)
- `investigation/*.md` (if speckit-echelon-investigator (INVESTIGATOR) ran)
- `evidence-grades.md` (if speckit-echelon-investigator (INVESTIGATOR) ran)
- `experiment-results.md` (if speckit-echelon-investigator (INVESTIGATOR) ran)
- `recommendations.md` (if speckit-echelon-investigator (INVESTIGATOR) ran)
- `threat-model.md` (if SECURITY ran)
- `compliance-requirements.md` (if SECURITY ran)
- `performance-requirements.md` (if PERFORMANCE ran)
- `capacity-model.md` (if PERFORMANCE ran)
- `accessibility-requirements.md` (if UX/A11Y ran)
- `user-flow.md` (if UX/A11Y ran)
- `alternatives.md` (if INNOVATE ran)
- `evolution-report.md` (if EVOLVE ran)
- `risk-acceptance-log.md` (if speckit-echelon-guardian (GUARDIAN) produced Risk Acceptance Records)

### 12.7 Run speckit-echelon-scorekeeper (SCOREKEEPER) — MANDATORY

Dispatch speckit-echelon-scorekeeper (SCOREKEEPER) to produce the final scorecard (see Section 13 for full protocol). Pass the per-agent internalization composite scores from step 12.4 so SCOREKEEPER can incorporate the internalization trend into the scorecard.

Read the scorecard output and apply any automatic self-healing actions.

### 12.8 Prepare Final State

Prepare the final state update, but do not treat the run as complete until the run history is written and the final summary banner in 12.9 has been printed. Return the final status in `echelon_result.state_updates`:

```yaml
status: done
phase: done
updated_at: "{ISO-8601}"
```

**Run History Write — MANDATORY at DONE. Without this, future runs cannot detect that Phase A is complete and will redo all of Phase A unnecessarily.**

1. Read or create `{spec_dir}/run-history.json`.
2. Append to `runs` array:

   ```json
   {
     "run_id": "{state.json.run_id}",
     "phase": "A",
     "status": "done",
     "constitution_hash": "{sha256 of .specify/memory/constitution.md}",
     "spec_status": "{state.json.spec_status}",
     "timestamp": "{current UTC ISO-8601}"
   }
   ```

3. Write the updated file.
4. **Verify:**

   ```bash
   python3 -c "
   import json, sys
   run_id = open('${SQUAD_DIR}/state.json').read()
   run_id = json.loads(run_id)['run_id']
   runs = json.load(open('${spec_dir}/run-history.json'))['runs']
   assert any(r['run_id'] == run_id for r in runs), 'run_id not found in run-history.json'
   print('run-history.json OK')
   " || { echo "ERROR: run-history.json write failed" >&2; exit 1; }
   ```

### 12.9 Print Final Summary — MANDATORY

> **Always print this banner before returning `status: done` in `echelon_result.state_updates` or beginning staging cleanup (12.10). NEVER mark done or clean up first.** The banner is the human handoff. Skipping it leaves the user with no actionable output from the run.
>
> The **HUMAN ACTIONS REQUIRED** section is unconditionally required — always print it. If there are no pending actions, print `None — squad resolved all items autonomously.` Never omit the section.

Print to terminal:

```
============================================
  ECHELON RUN COMPLETE
============================================

Run ID:     {run_id}
Feature:    {NNN}-{feature}
Mode:       {greenfield|brownfield}
Iterations: {count}
Duration:   {elapsed time}

QUALITY SCORES (final WHY pass):
  Overall:     {score} {pass/fail}
  Structure:   {score} {pass/fail}
  Testability: {score} {pass/fail}
  Semantic:    {score} {pass/fail}
  Cognitive:   {score} {pass/fail}
  Readability: {score} {pass/fail}

SPECIALISTS SUMMONED: {list}

ARTIFACTS: {count} files in specs/{NNN}-{feature}/

AGENT SCORECARD:
  Top performer: {agent} (+{score}) — {highlight}
  Badges earned: {count} ({badge names})
  Peer appreciation: {count} exchanges
  Self-healing: {count} recommendations

WARNINGS:
  {any UNVALIDATED artifacts}
  {any low-confidence domains}
  {any unresolved unknowns}

RISKS ACCEPTED AUTONOMOUSLY:
  {count from risk-acceptance-log.md, or "None"}
  {for each ACCEPT_WITH_MITIGATIONS: one-line summary + mitigation task IDs}

──────────────────────────────────────────
  HUMAN ACTIONS REQUIRED
──────────────────────────────────────────
  {This section is MANDATORY. Always print it.}
  {If no human actions: "None — squad resolved all items autonomously."}
  {For each ESCALATE item from risk-acceptance-log.md:}
    [ ] {RAR-ID}: {one-line description} — {reason human must decide}
  {For each unresolved unknown:}
    [ ] {unknown}: {what info is needed and from whom}
  {For each blocked task:}
    [ ] {task ID}: {what is blocked and what human action unblocks it}
  {For each HUMAN_REVIEW_REQUIRED flag:}
    [ ] {source agent}: {what needs review}
──────────────────────────────────────────

Spec ID for feedback: {NNN}
Run: speckit.echelon.feedback {NNN} after implementation

BRANCH: {NNN}-{feature}
Ready for: speckit.echelon.build {NNN}-{feature}

NOTE: No application source files were modified by this command.
      Implementation is performed by speckit.echelon.build / harness.run.
============================================
```

### 12.10 Archive and Cleanup Staging Area — MANDATORY

**Precondition:** Only run after `run-history.json` is written (12.8) and the final `status: done` update has been prepared in `echelon_result.state_updates`. Always archive completed runs only; do not archive a partial run.

Archive the completed run artifacts, then clean staging:

```bash
# Archive this run's artifacts
RUN_ID=$(python3 -c "import json; print(json.load(open('${SQUAD_DIR}/state.json')).get('run_id','unknown'))" 2>/dev/null || echo "unknown")
ARCHIVE_DIR="${SQUAD_DIR}/archive/${RUN_ID}"
mkdir -p "$ARCHIVE_DIR"
cp -r ${STAGING_DIR}/* "$ARCHIVE_DIR/" 2>/dev/null || true
cp ${SQUAD_DIR}/state.json "$ARCHIVE_DIR/state.json" 2>/dev/null || true
echo "Run archived → ${ARCHIVE_DIR}/"

# Clean staging for next run
rm -rf "${STAGING_DIR}"
```

**What's preserved in the archive:**
- `spec.md`, `tasks.md`, `plan.md` — the analysis products
- `issues.md`, `quality-gates.md` — findings and quality scores
- `reasoning-journal.jsonl` — full decision log
- `state.json` — run state snapshot
- All specialist outputs (threat-model.md, etc.)

**What lives in knowledge-base/ (already persistent):**
- `calibration-profile.yaml` — per-domain accuracy corrections
- `estimates-log.yaml` — predicted vs actual effort records
- `patterns.yaml`, `pitfalls.yaml` — reusable learnings
- `feedback/` — post-implementation outcome data
- `agent-scores.yaml` — agent performance history

### 12.10b Commit Spec Artifacts and Return to Default Branch — MANDATORY

**Always execute this step as a Bash tool call. Do NOT implement git operations inline or in prose.**

This is the harness handoff: spec artifacts (including `constitution.md` copied from `.specify/memory/`) are committed to the feature branch, and the working directory is switched back to the default branch. If this step is skipped, the harness will stash uncommitted artifacts and worktrees will be missing files.

Read `RUN_ID` from state.json (squad runs are stored under `runs/`), then call `finalize-run.sh`:

```bash
# State is at runs/<run-id>/state.json — find the current run via .current pointer
CURRENT_RUN=$(cat "${PROJECT_ROOT}/runs/.current" 2>/dev/null || echo "")
if [ -n "${CURRENT_RUN}" ] && [ -f "${PROJECT_ROOT}/runs/${CURRENT_RUN}/state.json" ]; then
  RUN_ID=$(python3 -c "import json; print(json.load(open('${PROJECT_ROOT}/runs/${CURRENT_RUN}/state.json')).get('run_id','unknown'))" 2>/dev/null || echo "unknown")
else
  RUN_ID="unknown"
fi
ECHELON_EXT="${PROJECT_ROOT}/.specify/extensions/echelon"
bash "${ECHELON_EXT}/scripts/bash/finalize-run.sh" \
  "${PROJECT_ROOT}" "${SPEC_ID}" "${FEATURE_NAME}" "${RUN_ID}"
```

If exit code is non-zero, always report the error and stop. Do not proceed to §12.11.

The script handles: copying constitution.md, staging, conditional commit (skipped if nothing changed), and `git checkout <default-branch>`.

### 12.11 Branch Stacking (Next Spec)

When the user starts a new squad run while implementation of the current spec is in progress:

1. The new spec will be created on a new branch via `speckit.specify`
2. Spec-kit handles branch stacking (new branch based on current feature branch)
3. This allows parallel specification work while implementation continues

**DONE.** The squad run is complete. The feature branch `{NNN}-{feature}` is ready for `speckit.echelon.build`.
