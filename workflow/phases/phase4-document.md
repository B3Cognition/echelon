# Phase: phase4-document
# Source: echelon.run.md §12 — FINALIZE Phase
# Agent: speckit-echelon-commander (COMMANDER) internal (sequential: speckit-echelon-realist (REALIST), speckit-echelon-mirror (MIRROR), speckit-echelon-adaptive (ADAPTIVE), speckit-echelon-auditor (AUDITOR), speckit-echelon-scorekeeper (SCOREKEEPER))
# Read by: speckit-echelon-commander (COMMANDER) before executing finalization sequence

## 12. FINALIZE Phase

### 12.1 GROUND Agent

Context pack:

- All artifacts in `specs/{feature}/`
- `calibration-profile.yaml` + `estimates-log.yaml`
- `reasoning-journal.json`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in specs/{feature}/, calibration-profile.yaml, estimates-log.yaml, reasoning-journal.json]
  </context>

  <instructions>
  You are REALIST. Read agents/learning/realist.md for your complete protocol.
  Reality-check all artifacts. Connect plans to real-world data: infrastructure costs, production benchmarks, team capacity. Compare estimates to past outcomes via FEEDBACK data. Check architectural decisions against operational constraints. Flag disconnects. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-realist (REALIST): reality check and reference class forecasting"

Expected outputs: `reality-check.md`, `cost-analysis.md`, `benchmark-data.md`

### 12.2 REFLECT Agent

Context pack:

- All artifacts in `specs/{feature}/`
- `reasoning-journal.json`
- `knowledge-base/patterns.yaml` + `knowledge-base/pitfalls.yaml`

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in specs/{feature}/, reasoning-journal.json, knowledge-base/patterns.yaml, knowledge-base/pitfalls.yaml]
  </context>

  <instructions>
  You are MIRROR. Read agents/learning/mirror.md for your complete protocol.
  Perform post-run analysis. Extract what assumptions were wrong, which patterns worked, what the squad should do differently. Log reusable patterns and pitfalls to the knowledge base. Update `knowledge-base/patterns.yaml` and `knowledge-base/pitfalls.yaml`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-mirror (MIRROR): post-run learning extraction"

### 12.3 EVOLVE Agent (if re-run)

Only dispatch if `state.json.iteration > 0` or prior run artifacts exist.

Context pack:

- All current artifacts
- Prior run artifacts (for diffing)
- `reasoning-journal.json`
- `knowledge-base/` files

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all current artifacts, prior run artifacts for diffing, reasoning-journal.json, knowledge-base/ files]
  </context>

  <instructions>
  You are ADAPTIVE. Read agents/learning/adaptive.md for your complete protocol.
  Diff artifacts between this run and prior runs. Measure quality trajectory. Detect regressions. Flag stagnation (if no improvement, recommend triggering INNOVATE on next run). Check for confirmation bias in knowledge base entries. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-adaptive (ADAPTIVE): cross-run diffing and improvement measurement"

Expected outputs: `evolution-report.md`, `improvement-metrics.md`, `regression-alerts.md`

### 12.4 CALIBRATE Agent

Context pack:

- All artifacts in `specs/{feature}/`
- `knowledge-base/calibration-profile.yaml`
- `knowledge-base/estimates-log.yaml`
- `reasoning-journal.json`
- Quality scores from all WHY passes (from state.json)

Use the Agent tool:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in specs/{feature}/, knowledge-base/calibration-profile.yaml, knowledge-base/estimates-log.yaml, reasoning-journal.json, quality scores from all WHY passes in state.json]
  </context>

  <instructions>
  You are AUDITOR. Read agents/learning/auditor.md for your complete protocol.
  Track AI accuracy per domain. Build/update the confidence profile. Adjust ASSESS estimate multipliers based on historical data. Flag low-confidence domains for human input or speckit-echelon-investigator (INVESTIGATOR) investigation. Update `knowledge-base/calibration-profile.yaml`. Produce `confidence-flags.md` in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-auditor (AUDITOR): accuracy tracking and confidence profiling"

### 12.5 CALIBRATE Confidence Check

After CALIBRATE completes, read `confidence-flags.md`:

- If any domain has **confidence < 0.5** → summon speckit-echelon-investigator (INVESTIGATOR) for that domain (if not already investigated). This is a late-stage safety net.
- If speckit-echelon-investigator (INVESTIGATOR) was already summoned and confidence is still < 0.5 → flag for human in the final report (do not block delivery).

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
reasoning-journal.json            | ALL             | ...
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

### 12.7 Run speckit-echelon-scorekeeper (SCOREKEEPER)

Dispatch speckit-echelon-scorekeeper (SCOREKEEPER) to produce the final scorecard (see Section 13 for full protocol).
Read the scorecard output and apply any automatic self-healing actions.

### 12.8 Set Final State

Update `state.json`:

```json
{
  "status": "done",
  "phase": "done",
  "updated_at": "{ISO-8601}"
}
```

**Run History Write (mandatory at DONE):**
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

### 12.9 Print Final Summary

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

### 12.10 Archive and Cleanup Staging Area

Archive the completed run artifacts, then clean staging:

```bash
# Archive this run's artifacts
RUN_ID=$(python3 -c "import json; print(json.load(open('.specify/squad/state.json')).get('run_id','unknown'))" 2>/dev/null || echo "unknown")
ARCHIVE_DIR=".specify/squad/archive/${RUN_ID}"
mkdir -p "$ARCHIVE_DIR"
cp -r .specify/squad/staging/* "$ARCHIVE_DIR/" 2>/dev/null || true
cp .specify/squad/state.json "$ARCHIVE_DIR/state.json" 2>/dev/null || true
echo "Run archived → ${ARCHIVE_DIR}/"

# Clean staging for next run
rm -rf .specify/squad/staging
```

**What's preserved in the archive:**
- `spec.md`, `tasks.md`, `plan.md` — the analysis products
- `issues.md`, `quality-gates.md` — findings and quality scores
- `reasoning-journal.json` — full decision log
- `state.json` — run state snapshot
- All specialist outputs (threat-model.md, etc.)

**What lives in knowledge-base/ (already persistent):**
- `calibration-profile.yaml` — per-domain accuracy corrections
- `estimates-log.yaml` — predicted vs actual effort records
- `patterns.yaml`, `pitfalls.yaml` — reusable learnings
- `feedback/` — post-implementation outcome data
- `agent-scores.yaml` — agent performance history

### 12.11 Return to Default Branch

After archiving, switch the working directory back to the default branch so
harness.run can create clean worktrees without hitting a "branch already checked
out" conflict:

```bash
DEFAULT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "main")
# Resolve canonical default — prefer 'main', fall back to 'master', then HEAD
for branch in main master; do
  if git show-ref --quiet "refs/heads/$branch"; then
    DEFAULT_BRANCH="$branch"
    break
  fi
done
CURRENT=$(git branch --show-current)
if [ "$CURRENT" != "$DEFAULT_BRANCH" ]; then
  git checkout "$DEFAULT_BRANCH"
  echo "Switched from $CURRENT → $DEFAULT_BRANCH (harness handoff)"
fi
```

This is a non-destructive operation — all spec artifacts are committed on the
feature branch, and the staging area was already archived in step 12.9. The
feature branch remains intact; the working directory simply moves back to the
default branch so the next harness invocation finds a clean starting state.

### 12.12 Branch Stacking (Next Spec)

When the user starts a new squad run while implementation of the current spec is in progress:

1. The new spec will be created on a new branch via `speckit.specify`
2. Spec-kit handles branch stacking (new branch based on current feature branch)
3. This allows parallel specification work while implementation continues

**DONE.** The squad run is complete. The feature branch `{NNN}-{feature}` is ready for `speckit.echelon.build`.
