# Phase: phase4-document
# Source: echelon.run.md §12 — FINALIZE Phase
# Agent: speckit-echelon-commander (COMMANDER) internal (sequential: speckit-echelon-realist (REALIST), speckit-echelon-mirror (MIRROR), speckit-echelon-adaptive (ADAPTIVE), speckit-echelon-auditor (AUDITOR), speckit-echelon-consolidator (CONSOLIDATOR), speckit-echelon-scorekeeper (SCOREKEEPER))
# Read by: speckit-echelon-commander (COMMANDER) before executing finalization sequence

## 12. FINALIZE Phase

> **Always execute steps 12.1–12.7 in order before step 12.8. NEVER skip to step 12.8.** The learning agents (speckit-echelon-realist (REALIST), speckit-echelon-mirror (MIRROR), speckit-echelon-auditor (AUDITOR), speckit-echelon-consolidator (CONSOLIDATOR), speckit-echelon-scorekeeper (SCOREKEEPER)) are the system's only mechanism for improving accuracy and pattern knowledge across runs. Skipping them means every run starts cold, estimates drift uncorrected, schemas fail to consolidate, and failure modes repeat. Each step below is mandatory.

### 12.1 GROUND Agent — MANDATORY

Context pack:

- All artifacts in `{spec_dir}/`
- `calibration-profile.yaml` + `estimates-log.yaml`
- `extension/templates/reality-check-template.md`
- `extension/templates/cost-analysis-template.md`
- `extension/templates/benchmark-data-template.md`
- `reasoning-journal.jsonl`

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in {spec_dir}/, calibration-profile.yaml, estimates-log.yaml, REALIST output templates, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are REALIST. Read agents/learning/realist.md for your complete protocol.
  Reality-check all artifacts. Connect plans to real-world data: infrastructure costs, production benchmarks, team capacity. Compare estimates to past outcomes via FEEDBACK data. Check architectural decisions against operational constraints. Flag disconnects. Produce outputs in `{spec_dir}/` using the provided templates. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-realist (REALIST): reality check and reference class forecasting"

Expected outputs: `reality-check.md`, `cost-analysis.md`, `benchmark-data.md`

### 12.2 REFLECT Agent — MANDATORY

Context pack:

- All artifacts in `{spec_dir}/`
- `reasoning-journal.jsonl`
- `knowledge-base/patterns.yaml` + `knowledge-base/pitfalls.yaml`
- `extension/templates/knowledge-transfer-assessment-template.md`

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in {spec_dir}/, reasoning-journal.jsonl, knowledge-base/patterns.yaml, knowledge-base/pitfalls.yaml, extension/templates/knowledge-transfer-assessment-template.md]
  </context>

  <instructions>
  You are MIRROR. Read agents/learning/mirror.md for your complete protocol.
  Perform post-run analysis. Extract what assumptions were wrong, which patterns worked, and what the squad should do differently. Write reusable pattern and pitfall proposal files under `${SQUAD_DIR}/kb-proposals/` using the KB proposal templates. Do not edit canonical knowledge-base files directly. Produce `knowledge-transfer-assessment.md` using the provided template. Return journal entries in `echelon_result.journal_entries`.
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
- `extension/templates/evolution-report-template.md`
- `extension/templates/improvement-metrics-template.md`
- `extension/templates/stagnation-flags-template.md`
- `extension/templates/regression-alerts-template.md`
- `extension/templates/bias-check-template.md`
- `extension/templates/prompt-recommendation-template.md`

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include all current artifacts, prior run artifacts for diffing, reasoning-journal.jsonl, knowledge-base/ files, ADAPTIVE output templates]
  </context>

  <instructions>
  You are ADAPTIVE. Read agents/learning/adaptive.md for your complete protocol.
  Diff artifacts between this run and prior runs. Measure quality trajectory. Detect regressions. Flag stagnation (if no improvement, recommend triggering INNOVATE on next run). Check for confirmation bias in knowledge base entries. Produce outputs in `{spec_dir}/` using the supplied templates; omit conditional signal artifacts when their condition is not met. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-adaptive (ADAPTIVE): cross-run diffing and improvement measurement"

Expected outputs: `evolution-report.md`, `improvement-metrics.md`; conditionally `stagnation-flags.md`, `regression-alerts.md`, `bias-check.md`, and `prompt-recommendations.md`

### 12.4 CALIBRATE Agent — MANDATORY

**Precondition: run the Per-Agent Internalization Data Handoff before dispatching speckit-echelon-auditor (AUDITOR).**

speckit-echelon-internalizer (INTERNALIZER) must run first so speckit-echelon-auditor (AUDITOR) can incorporate per-agent accuracy data into the calibration profile. See `commander.md` §"Per-Agent Internalization Data Handoff" for the full sequence:

1. Collect internalization artifacts (speckit-echelon-checkpoint (CHECKPOINT)'s report, verdict reports, prior `agent-scores.yaml`)
2. Dispatch speckit-echelon-internalizer (INTERNALIZER) (Measurement pass — 16 metrics per agent)
3. Dispatch speckit-echelon-internalizer (INTERNALIZER) (Per-Agent Scoring pass)
4. **Then** dispatch speckit-echelon-auditor (AUDITOR) (Calibration Dashboard Generation — uses speckit-echelon-internalizer (INTERNALIZER) results)
5. speckit-echelon-auditor (AUDITOR) writes `calibration-dashboard.md` to `{spec_dir}/`

Context pack:

- All artifacts in `{spec_dir}/`
- `knowledge-base/calibration-profile.yaml`
- `knowledge-base/estimates-log.yaml`
- `reasoning-journal.jsonl`
- Quality scores from all WHY passes (from state.json)
- speckit-echelon-internalizer (INTERNALIZER) outputs (per-agent composite scores and trends)
- `agents/learning/appendices/internalizer-output-formats.md`
- `agents/learning/appendices/internalizer-tier-definitions.md`
- `agents/learning/appendices/auditor-dashboard-template.md`
- `agents/learning/appendices/auditor-output-formats.md`
- `extension/templates/confidence-flags-template.md`
- `extension/templates/evolution-signals-review-template.md`
- `extension/templates/prompt-version-observations-template.md`
- `extension/templates/calibration-analytics-template.md`
- `extension/templates/feedback-report-template.md`

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in {spec_dir}/, knowledge-base/calibration-profile.yaml, knowledge-base/estimates-log.yaml, reasoning-journal.jsonl, quality scores from all WHY passes in state.json, speckit-echelon-internalizer (INTERNALIZER) per-agent scores, auditor appendices, and AUDITOR run-local artifact templates]
  </context>

  <instructions>
  You are AUDITOR. Read agents/learning/auditor.md for your complete protocol.
  Track AI accuracy per domain. Build the confidence profile and adjust ASSESS estimate multipliers based on historical data. Flag low-confidence domains for human input or speckit-echelon-investigator (INVESTIGATOR) investigation. Write any durable calibration observations as proposals under `${SQUAD_DIR}/kb-proposals/` using `extension/templates/kb-proposals/calibration-observation-proposal-template.yaml`; do not edit canonical KB files directly. Produce `confidence-flags.md` and `calibration-dashboard.md` in `{spec_dir}/` using the provided appendices and their supplied template contracts: use the confidence-flags template and the dashboard appendix respectively. When triggered, use the supplied standalone templates for evolution signals, prompt-version observations, and calibration analytics. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-auditor (AUDITOR): accuracy tracking and confidence profiling"

### 12.5 CALIBRATE Confidence Check

After CALIBRATE completes, read `confidence-flags.md`:

- If any domain has **confidence < 0.5** → summon speckit-echelon-investigator (INVESTIGATOR) for that domain (if not already investigated). This is a late-stage safety net.
- If speckit-echelon-investigator (INVESTIGATOR) was already summoned and confidence is still < 0.5 → always flag for human in the final report (do not block delivery).

### 12.6 Prepare Artifact Manifest

Prepare a manifest of expected artifacts in `{spec_dir}/`; refresh its statuses
after KB proposal processing in 12.7b:

```
Artifact                          | Producer        | Status
----------------------------------|-----------------|--------
00-overview.md                    | FINALIZE        | OK/MISSING/UNVALIDATED
requirements-overview.md          | WHAT            | OK/MISSING/UNVALIDATED
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
plan-conformance.md               | FINALIZE        | ...
plan-conformance.json             | FINALIZE        | ...
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
- `improvement-metrics.md` (if EVOLVE ran)
- `stagnation-flags.md` (if EVOLVE detected stagnation)
- `regression-alerts.md` (if EVOLVE detected regression)
- `bias-check.md` (if EVOLVE detected bias)
- `evolution-signals-review.md` (if AUDITOR detected qualified signals)
- `prompt-version-observations.md` (if AUDITOR recorded observations)
- `calibration-analytics.md` (if AUDITOR produced analytics)
- `constitution-amendment-candidates.md` (if ARCHITECT or consolidation proposed amendments)
- `risk-acceptance-log.md` (if speckit-echelon-guardian (GUARDIAN) produced Risk Acceptance Records)

### 12.6a Write Plan Conformance and Final Overview — MANDATORY

Before writing `ARTIFACTS.md`, produce the final delivery entry point and its
conformance evidence:

- `plan-conformance.md`
- `plan-conformance.json`
- `00-overview.md`

Read `spec.md`, `requirements-overview.md`, `mvp-scope.md`, `plan.md`,
`tasks.md`, `dependencies.md`, `critical-path.md`, `risk-matrix.md`,
`test-strategy.md`, `coverage-map.md`, `quality-gates.md`, `issues.md`, and
`implementability-report.md` when present.

`plan-conformance.md` must answer these checks explicitly:

- Does every major requirement in `spec.md` have implementation coverage in
  `plan.md` and canonical `tasks.md` rows?
- Does every major behavior in `plan.md` and `tasks.md` trace to `spec.md`,
  `mvp-scope.md`, an ADR/research decision, or an explicit follow-up/deferred
  scope record?
- Do MVP, post-MVP, and conditional work agree across `mvp-scope.md`,
  `plan.md`, and `tasks.md`?
- Do `requirements-overview.md`, `plan.md`, and `tasks.md` disagree on any user
  visible behavior?
- Are all final overview claims backed by the conformant artifacts above?

`plan-conformance.json` must be machine-readable and contain at least:

```json
{
  "status": "pass",
  "findings": [],
  "sources": [
    "spec.md",
    "requirements-overview.md",
    "mvp-scope.md",
    "plan.md",
    "tasks.md",
    "dependencies.md",
    "critical-path.md"
  ]
}
```

Use `"status": "needs_repair"` when a drift finding requires artifact repair
before build readiness. Do not hide drift by rewriting `00-overview.md` around
it; record the drift and route repair through the responsible artifact.

`00-overview.md` is the final PM/developer brief. It must be generated only
after the conformance checks above are complete, and it must say that it is
derived from the final Phase A artifacts. It should tell a developer how to
start, what delivery slices the plan/tasks define, which dependencies need
control first, what partial result is allowed by the existing scope artifacts,
and where to stop and ask.

NEVER let `00-overview.md` introduce new scope, new sequencing, or a new
MVP/post-MVP split. If final overview guidance would conflict with
`spec.md`, `mvp-scope.md`, `plan.md`, or `tasks.md`, fix the conflicting
artifact first or record the conformance finding.

### 12.6b Run speckit-echelon-consolidator (CONSOLIDATOR) — MANDATORY

Dispatch speckit-echelon-consolidator (CONSOLIDATOR) in `offline_consolidation` mode before speckit-echelon-scorekeeper (SCOREKEEPER). This turns run episodes and learning outputs into reusable schemas while the full run context is still available.

Context pack:

- All artifacts in `{spec_dir}/`
- `reasoning-journal.jsonl`
- `knowledge-base/patterns.yaml`
- `knowledge-base/pitfalls.yaml`
- `knowledge-base/calibration-profile.yaml`
- speckit-echelon-mirror (MIRROR), speckit-echelon-adaptive (ADAPTIVE), and speckit-echelon-auditor (AUDITOR) outputs from this FINALIZE run
- `extension/templates/schema-consolidation-template.md`

The active runtime dispatches this role with the following request:

- **prompt:**

  ```xml
  <context>
  [include all artifacts in {spec_dir}/, reasoning-journal.jsonl, knowledge-base/patterns.yaml, knowledge-base/pitfalls.yaml, knowledge-base/calibration-profile.yaml, FINALIZE learning outputs, extension/templates/schema-consolidation-template.md]
  </context>

  <instructions>
  You are CONSOLIDATOR. Read agents/learning/consolidator.md for your complete protocol.
  Run offline consolidation. Promote cross-run patterns into schemas, reinforce or decay existing schemas, mark consolidated traces, and produce `{spec_dir}/patterns/schema-consolidation.md` using the provided template. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-consolidator (CONSOLIDATOR): offline schema consolidation before scoring"

If speckit-echelon-consolidator (CONSOLIDATOR) is unavailable, record the skip in the final warnings and continue to speckit-echelon-scorekeeper (SCOREKEEPER). Do not block run completion on consolidation availability.

### 12.7 Run speckit-echelon-scorekeeper (SCOREKEEPER) — MANDATORY

Dispatch speckit-echelon-scorekeeper (SCOREKEEPER) to produce the final scorecard (see Section 13 for full protocol). Pass the per-agent internalization composite scores from step 12.4 so SCOREKEEPER can incorporate the internalization trend into the scorecard.

Include `agents/control/appendices/scorekeeper-output-template.md` and `agents/control/appendices/scorekeeper-scoring-reference.md` in the context pack. Produce `agent-scorecard.md` using the provided template. Write durable per-agent internalization observations as proposals under `${SQUAD_DIR}/kb-proposals/` using `extension/templates/kb-proposals/internalization-observation-proposal-template.yaml`; do not edit canonical KB files directly.

Read the scorecard output and apply any automatic self-healing actions.

### 12.KB Apply KB Proposals - NON-BLOCKING

After MIRROR, AUDITOR, and SCOREKEEPER have written their run-local proposals,
read `RUN_ID` from `runs/.current`, then run:

```bash
if [ -f "${PROJECT_ROOT}/runs/.current" ]; then
  RUN_ID=$(cat "${PROJECT_ROOT}/runs/.current")
else
  RUN_ID=""
fi

if KB_VALIDATE_OUTPUT="$(echelon kb validate --run-id "${RUN_ID}" 2>&1)"; then
  :
fi
printf '%s\n' "${KB_VALIDATE_OUTPUT}"
if printf '%s\n' "${KB_VALIDATE_OUTPUT}" | grep -Fxq "kb_validation_status: valid"; then
  KB_VALIDATION_STATUS=validated
else
  KB_VALIDATION_STATUS=degraded
fi

if KB_APPLY_OUTPUT="$(echelon kb apply --run-id "${RUN_ID}" 2>&1)"; then
  :
fi
printf '%s\n' "${KB_APPLY_OUTPUT}"
if printf '%s\n' "${KB_APPLY_OUTPUT}" | grep -Fxq "kb_apply_status: applied"; then
  KB_APPLY_STATUS=applied
else
  KB_APPLY_STATUS=degraded
fi
```

Record `kb_validation_status` from `KB_VALIDATION_STATUS` and `kb_apply_status`
from `KB_APPLY_STATUS` in `echelon_result.state_updates`. The commands remain
non-blocking, but their printed status values are authoritative because they may
exit zero while reporting a degraded result.
Record proposal-read or usage failures as `kb_usage_status: degraded`, and preserve
any deterministic contract findings in `kb_contract_violations` and `kb_apply_report`.
A KB failure does not stop finalization, agent dispatch, phase transitions, or publication.

The Python controller publishes KB provenance reports best-effort under
`{spec_dir}/kb/` using deterministic `publish_kb_reports`, including
`kb-apply-report.yaml` and `kb-usage-summary.yaml` when available. COMMANDER
does not publish these reports manually.

### 12.7b Collect Final Artifacts

Refresh the artifact manifest prepared in 12.6 after KB proposal processing. Verify
all expected artifacts exist in `{spec_dir}/`, including
`kb/kb-apply-report.yaml` when the deterministic apply command produced it.

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

> **Always print this banner before returning `status: done` in `echelon_result.state_updates` or completing run preservation checks (12.10). NEVER mark done first.** The banner is the human handoff. Skipping it leaves the user with no actionable output from the run.
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

ARTIFACTS: {count} files in {spec_dir}/

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

### 12.10 Preserve Run Directory — MANDATORY

**Precondition:** Only run after `run-history.json` is written (12.8) and the final `status: done` update has been prepared in `echelon_result.state_updates`.

The active `${SQUAD_DIR}` is already the durable `runs/<run-id>/` record. Do not
copy artifacts into a nested archive and do not clean staging: it contains the
control-plane history needed to explain clarifications and governance decisions.
Verify the run-local record instead:

```bash
test -f "${SQUAD_DIR}/state.json"
test -f "${SQUAD_DIR}/reasoning-journal.jsonl"
test -d "${STAGING_DIR}"
test -d "${spec_dir}"
echo "Run directory preserved → ${SQUAD_DIR}"
```

**Run-local ownership:**
- `{spec_dir}/` — canonical analysis products, findings, quality gates, and specialist outputs
- `${SQUAD_DIR}/reasoning-journal.jsonl` — full decision log
- `${SQUAD_DIR}/state.json` — run state snapshot
- `${STAGING_DIR}/` — discovery remnants and control-plane inputs

**What lives in knowledge-base/ (already persistent):**
- `calibration-profile.yaml` — per-domain accuracy corrections
- `estimates-log.yaml` — predicted vs actual effort records
- `patterns.yaml`, `pitfalls.yaml` — reusable learnings
- `feedback/` — post-implementation outcome data
- `agent-scores.yaml` — agent performance history

### 12.10 Python-owned finalization — mandatory boundary

After COMMANDER returns the Phase 4 result, the Python squad controller copies
the run-local artifacts into the published spec, publishes the constitution and
KB provenance, validates the complete build-ready artifact set, writes
`ARTIFACTS.md`, and creates the terminal checkpoint commit containing the
active and published spec trees.

ALWAYS report the Phase 4 result and allow the controller to complete this
boundary. NEVER call Git, `echelon spec artifacts`, or an external finalizer
from this phase. In particular, do not stage files, create commits, push, stash,
reset, or change branches.
NEVER hand-author `ARTIFACTS.md`; it is Python-owned and overwritten during
controller finalization.

### 12.11 Next spec

Start another specification only through `echelon spec run`. After the active
run passes checkpoint and cleanliness validation, Echelon creates its sibling branch from the configured default branch. The new spec is not stacked on the current feature branch.

**DONE.** The squad run is complete. The feature branch `{NNN}-{feature}` is ready for `speckit.echelon.build`.
