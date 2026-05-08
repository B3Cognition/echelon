# Phase: build-8-finalize
# Source: echelon.build.md §8–§12 — Build Complete through Harness Integration
# Read by: speckit-echelon-commander (COMMANDER) after all phase checkpoints pass

## 8. Build Complete (BUILD_DONE)

After all tasks are built and all phase checkpoints pass:

### 8.1 Final Integration

Run speckit-echelon-integrator (INTEGRATOR) one last time against the complete codebase (all phases combined).

### 8.1b Engineering Manager Sign-Off

Before completion, dispatch speckit-echelon-engineering-manager (ENGINEERING MANAGER) with:

- `tasks.md`
- `spec.md`
- `traceability-matrix.md`
- `coverage-map.md`
- `process-metrics.md`
- `integration-report.md`
- `progress-report.md`
- all build gate reports
- `state.json`
- `reasoning-journal.json`

Use the Agent tool:

- **subagent_type:** `speckit-echelon-engineering-manager`
- **prompt:**

  ```xml
  <context>
  [include tasks.md, spec.md, traceability-matrix.md, coverage-map.md, process-metrics.md, integration-report.md, progress-report.md, all build gate reports, state.json, reasoning-journal.json]
  </context>

  <instructions>
  You are ENGINEERING MANAGER. Read agents/build/engineering-manager.md for your complete protocol.
  Validate workflow compliance, report consistency, and readiness for final verification.
  </instructions>
  ```

- **description:** "speckit-echelon-engineering-manager (ENGINEERING MANAGER): final pre-verification sign-off"

speckit-echelon-engineering-manager (ENGINEERING MANAGER) must confirm:

1. Spec-kit task workflow was actually followed.
2. Task status, state tracking, and reports are internally consistent.
3. The build is ready for full speckit-echelon-verification (VERIFICATION).
4. **`verify.sh` exists and contains a smoke test** (see below).

If any of these fail, do not proceed to BUILD_DONE. Route to rework first.

### 8.1b.1 verify.sh Smoke Test Requirement (MANDATORY)

Every build must produce a `verify.sh` in the repo root. This script is what the harness runs in Docker to verify the build.

**`verify.sh` MUST include a smoke test that starts the application and verifies it responds.** "All unit tests pass" is not sufficient — a blank page with passing unit tests is a failed build.

Minimum smoke test pattern for web applications:

```sh
# After npm test passes:
npm run build
npx vite preview --port 4173 &
PREVIEW_PID=$!
sleep 3
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:4173)
kill $PREVIEW_PID 2>/dev/null || true
if [ "$STATUS" != "200" ]; then
  echo "Smoke test FAILED: app returned HTTP $STATUS (expected 200)"
  exit 1
fi
echo "Smoke test PASSED: app served HTTP 200"
```

Adapt for other stacks:
- **Node/Express:** `node server.js & sleep 2 && curl -s http://localhost:3000`
- **Python/FastAPI:** `uvicorn main:app & sleep 2 && curl -s http://localhost:8000/health`
- **Static site:** `npx serve dist & sleep 2 && curl -s http://localhost:3000`
- **No HTTP server (CLI tool, library):** smoke test = `node dist/index.js --version` or equivalent invocation that proves the artifact runs

**Next.js apps require stricter smoke testing.** `next build` can exit 0 while producing a broken production bundle — pages that use modules requiring runtime initialization (auth providers, i18n, database clients, React context) crash during SSG with errors like `TypeError: (0, t) is not a function`. The bundle looks built but every page returns 500 at runtime.

For Next.js, `verify.sh` MUST:

1. **Capture build output and check for SSG errors** — `next build` prints these to stdout even when it exits 0:

```sh
# Capture build output; fail if Next.js emitted SSG errors
next build 2>&1 | tee /tmp/nextbuild.log
if grep -qE "(TypeError|ReferenceError|Error:.*is not a function|Error:.*Cannot read)" /tmp/nextbuild.log; then
  echo "✗ Next.js build contains SSG errors — pages will crash at runtime"
  echo "  Fix: add 'export const dynamic = \"force-dynamic\"' to affected pages"
  cat /tmp/nextbuild.log >&2
  exit 1
fi
```

1. **Start the server and test a health endpoint with strict 2xx** — a permissive "server responded" check misses broken bundles. The app MUST expose a health endpoint (e.g. `app/api/health/route.ts`) that returns 2xx only when the app initialised correctly:

```sh
PORT=3099 node server.js &
SERVER_PID=$!
sleep 4
STATUS=$(curl -so /dev/null -w '%{http_code}' http://localhost:3099/api/health 2>/dev/null)
kill $SERVER_PID 2>/dev/null || true
if [[ ! "$STATUS" =~ ^2 ]]; then
  echo "✗ Health check failed: /api/health returned HTTP $STATUS (expected 2xx)"
  exit 1
fi
echo "Smoke test PASSED: /api/health returned HTTP $STATUS"
```

**Pages that use provider-dependent modules must be `force-dynamic`.** The general rule: if a page imports from an auth provider, i18n library, ORM, or any module that reads from React context or makes async calls at module scope — it cannot be statically generated. Add `export const dynamic = 'force-dynamic'` to the page file. speckit-echelon-implementer (IMPLEMENTER) must audit pages for this pattern during implementation and flag any that need it. speckit-echelon-sentinel (SENTINEL) must include a render test for each such page.

If `verify.sh` does not contain a smoke test, speckit-echelon-engineering-manager (ENGINEERING MANAGER) must request speckit-echelon-implementer (IMPLEMENTER) add one before sign-off. This is not optional.

### 8.1b.2 verify.sh Security and License Gate (MANDATORY)

Every `verify.sh` must also run a security scan and dependency license check
after the smoke test. These run inside the same Docker sandbox — no extra
infrastructure required.

**Security scan** — detect known vulnerabilities in dependencies:

| Ecosystem | Command |
| --- | --- |
| Node.js (npm/pnpm/yarn/bun) | `npm audit --audit-level=high 2>&1 \| tee /tmp/audit.txt \|\| { echo "✗ Security audit failed — see /tmp/audit.txt"; exit 1; }` |
| Python | `pip install pip-audit --quiet && pip-audit 2>&1 \| tee /tmp/audit.txt \|\| { echo "✗ pip-audit found vulnerabilities — see /tmp/audit.txt"; exit 1; }` |
| Go | `go install golang.org/x/vuln/cmd/govulncheck@latest 2>/dev/null && govulncheck ./... 2>&1 \| tee /tmp/audit.txt \|\| { echo "✗ govulncheck found vulnerabilities — see /tmp/audit.txt"; exit 1; }` |
| Rust | `cargo install cargo-audit --quiet 2>/dev/null && cargo audit 2>&1 \| tee /tmp/audit.txt \|\| { echo "✗ cargo audit found vulnerabilities — see /tmp/audit.txt"; exit 1; }` |
| Ruby | `gem install bundler-audit --quiet 2>/dev/null && bundle-audit check --update 2>&1 \| tee /tmp/audit.txt \|\| { echo "✗ bundle-audit found vulnerabilities — see /tmp/audit.txt"; exit 1; }` |

**License check** — verify all dependencies use permissive licenses:

Permitted: `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`,
`Unlicense`, `CC0-1.0`, `Python-2.0`, `BlueOak-1.0.0`.

| Ecosystem | Command |
| --- | --- |
| Node.js | `npx --yes license-checker --onlyAllow "MIT;Apache-2.0;BSD-2-Clause;BSD-3-Clause;ISC;Unlicense;CC0-1.0;BlueOak-1.0.0" 2>&1 \| tee /tmp/licenses.txt \|\| { echo "✗ License check failed — review /tmp/licenses.txt"; exit 1; }` |
| Python | `pip install pip-licenses --quiet && pip-licenses --allow-only="MIT;Apache Software License;BSD License;ISC License (ISCL);Public Domain;Python Software Foundation License" 2>&1 \|\| { echo "✗ pip-licenses check failed"; exit 1; }` |
| Go | `go install github.com/google/go-licenses@latest 2>/dev/null && go-licenses check --allowed_licenses=MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,ISC,Unlicense,CC0-1.0 ./... 2>&1 \| tee /tmp/licenses.txt \|\| { echo "✗ go-licenses check failed — see /tmp/licenses.txt"; exit 1; }` |
| Rust | `cargo install cargo-license --quiet 2>/dev/null; cargo license 2>&1 \| grep -vE "^(name\|MIT\|Apache-2.0\|BSD-2-Clause\|BSD-3-Clause\|ISC\|Unlicense\|CC0-1.0)" \| grep -v "^$" > /tmp/licenses.txt; [ ! -s /tmp/licenses.txt ] \|\| { echo "✗ Non-permissive license detected — see /tmp/licenses.txt"; exit 1; }` |
| Ruby | `gem install license_finder --quiet 2>/dev/null && license_finder 2>&1 \| tee /tmp/licenses.txt \|\| { echo "✗ License check failed — see /tmp/licenses.txt"; exit 1; }` |

> Note: `pip-licenses` reports license names in its own format (e.g. "Apache Software License", "BSD License") rather than SPDX identifiers. The `--allow-only` list must use pip-licenses' display names, not SPDX IDs.

For polyglot projects (e.g., both `package.json` and `requirements.txt` present),
run the checks for every detected ecosystem — not just the primary one.

speckit-echelon-implementer (IMPLEMENTER) must select the correct commands for the detected ecosystem and add
them to `verify.sh` after the smoke test block. If the audit or license check
fails, `verify.sh` must exit non-zero so the harness marks the build as failed.

If a security vulnerability or non-permissive license is found:

- Print the finding clearly
- Exit 1 — do not suppress or work around the failure
- The squad must address the finding (update dependency, get license exception
  documented in `specs/{NNN}-{feature}/license-exceptions.md`) before the
  build can proceed

### 8.1c Final Verification

Dispatch speckit-echelon-verification (VERIFICATION) after final integration and EM pre-check.

Use the Agent tool:

- **subagent_type:** `speckit-echelon-verification`
- **prompt:**

  ```xml
  <context>
  [include spec.md, all implemented code, all gate reports, traceability-matrix.md, coverage-map.md, state.json, reasoning-journal.json]
  </context>

  <instructions>
  You are VERIFICATION agent. Read agents/build/verification.md for your complete protocol.
  Run full backpropagation verification against spec requirements.
  Produce `gap-report.md`, `excess-report.md`, updated `traceability-matrix.md`, and `verification-summary.md`.
  </instructions>
  ```

- **description:** "speckit-echelon-verification (VERIFICATION): final backpropagation check"

speckit-echelon-verification (VERIFICATION) must:

1. Check every FR-*, AC-*, and NFR-* in `spec.md`.
2. Verify code, tests, integration evidence, and gate evidence.
3. Produce `gap-report.md`, `excess-report.md`, updated `traceability-matrix.md`, and `verification-summary.md`.

Handle result:

- **PASS** — continue to BUILD_DONE
- **FAIL** — create RW-* tasks, route through speckit-echelon-implementer (IMPLEMENTER) and quality gates, then re-run speckit-echelon-verification (VERIFICATION)

BUILD_DONE is forbidden while `verification-summary.md` is FAIL or `gap-report.md` contains open gaps.

**Specification Complete (mandatory on speckit-echelon-verification (VERIFICATION) PASS):**

1. Set `state.json.spec_status` to `"implemented"`.
2. Update `{spec_dir}/spec.md`: change `**Status**: In Progress` to `**Status**: Implemented`.
3. Confirm `state.json.build.tasks_completed_pct` is `100`. If not, recompute from `tasks.md`.
4. Log journal entry: `{ "type": "milestone", "event": "spec_implemented", "spec_id": "{spec_id}", "spec_dir": "{spec_dir}" }`.

### 8.2 Collect Reports

Verify all report files are populated:

- `spec-compliance-report.md` — One section per task
- `code-review-report.md` — One section per task
- `test-quality-report.md` — One section per task
- `integration-report.md` — One section per phase checkpoint + final
- `progress-report.md` — One section per task + summary
- `gap-report.md` — Verification coverage and gaps
- `verification-summary.md` — Final PASS / FAIL completion verdict

### 8.3 Update State

```json
{
  "status": "build_done",
  "phase": "build_done",
  "build": {
    "completed_tasks": "{total}",
    "verification_verdict": "PASS",
    "coverage_score": "100%",
    "current_task": null
  },
  "updated_at": "{ISO-8601}"
}
```

**Run History Write (mandatory at BUILD_DONE):**
1. Read `{spec_dir}/run-history.json` (must exist from Phase A run).
2. Append to `runs` array:
   ```json
   {
     "run_id": "{state.json.run_id}",
     "phase": "B",
     "status": "done",
     "verification_result": "{PASS|FAIL from verification-summary.md}",
     "spec_status": "{state.json.spec_status}",
     "timestamp": "{current UTC ISO-8601}"
   }
   ```
3. If `verification_result` is `"PASS"`: set `authoritative_run` to `"{state.json.run_id}"`.
4. Write the updated file.

### 8.4 Run speckit-echelon-scorekeeper (SCOREKEEPER)

After all build tasks complete, dispatch speckit-echelon-scorekeeper (SCOREKEEPER) to produce the build phase scorecard:

Use the Agent tool:

- **subagent_type:** `speckit-echelon-scorekeeper`
- **prompt:**

  ```xml
  <context>
  [include state.json, progress-report.md, all gate reports, reasoning-journal.json, knowledge-base/agent-scores.yaml]
  </context>

  <instructions>
  You are SCOREKEEPER. Read agents/control/scorekeeper.md for your complete protocol.
  Score all build agents: speckit-echelon-implementer (IMPLEMENTER) (first-pass approvals vs rework), speckit-echelon-spec-guard (SPEC GUARD) (gaps caught vs missed by speckit-echelon-verification (VERIFICATION)), speckit-echelon-code-reviewer (CODE REVIEWER) (issues found), speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)) (coverage improvements). Collect peer appreciation from reasoning-journal.json. Check badge criteria. Produce `agent-scorecard.md`. Update `knowledge-base/agent-scores.yaml`.
  </instructions>
  ```

- **description:** "speckit-echelon-scorekeeper (SCOREKEEPER): build phase scoring and badges"

Build-specific scoring:

```
Per task completed:
  speckit-echelon-implementer (IMPLEMENTER) first-pass approval: +3
  speckit-echelon-implementer (IMPLEMENTER) rework required: -1
  speckit-echelon-implementer (IMPLEMENTER) third rework: -3
  speckit-echelon-spec-guard (SPEC GUARD) caught gap: +3
  speckit-echelon-code-reviewer (CODE REVIEWER) found issue: +2
  speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)) improved coverage: +2

Per phase gate:
  speckit-echelon-integrator (INTEGRATOR) pass: +2
  speckit-echelon-visual-validator (VISUAL speckit-echelon-validator (VALIDATOR)) caught visual issue: +4

End of build:
  speckit-echelon-verification (VERIFICATION) 100% coverage: speckit-echelon-spec-guard (SPEC GUARD) gets +5 (Guardian Angel badge candidate)
  speckit-echelon-verification (VERIFICATION) found gaps: speckit-echelon-spec-guard (SPEC GUARD) gets -2 per gap (Blind Spot badge candidate)
```

---

## 8.5 Auto-Feedback & Post-Build Validation (Phase 5)

After speckit-echelon-scorekeeper (SCOREKEEPER) and before final summary, speckit-echelon-commander (COMMANDER) runs the autonomous feedback pipeline. This closes the learning loop without human input.

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.auto_feedback` (default: `true`). If `false`, skip to Section 8.6 Print Summary.

### 8.5.1 Dispatch speckit-echelon-auditor (AUDITOR) (Post-Build Self-Assessment)

Use the Agent tool:

- **subagent_type:** `speckit-echelon-auditor`
- **prompt:**

  ```xml
  <context>
  [include all build artifacts, spec artifacts, state.json, reasoning-journal.json, knowledge-base/]
  </context>

  <instructions>
  You are AUDITOR. Read agents/learning/auditor.md for your complete protocol. Operate in **Mode 4: Post-Build Self-Assessment**.
  Compare squad predictions against build outcomes using build artifacts as ground truth. Read: estimates.md (predicted), state.json + progress-report.md (actual), plan.md + research.md (architecture decisions), spec.md + verification-summary.md + gap-report.md (requirements), risk-matrix.md + reasoning-journal.json (risks), test-strategy.md + test-quality-report.md (tests).
  Produce `auto-feedback.yaml` and `feedback-report.md`. Flag any CRITICAL findings for speckit-echelon-commander (COMMANDER) triage.
  </instructions>
  ```

- **description:** "speckit-echelon-auditor (AUDITOR): post-build self-assessment — auto-feedback generation"

Context pack: all build artifacts + spec artifacts + state.json + reasoning-journal.json + knowledge-base/

### 8.5.2 speckit-echelon-commander (COMMANDER) Triage of Critical Findings

Read `auto-feedback.yaml` → `critical_findings[]`. For each CRITICAL finding (max `feedback.max_expert_dispatches` from config, default 3):

| Finding Type | Expert Dispatched | Prompt Focus |
|---|---|---|
| `architecture_pivot` | speckit-echelon-investigator (INVESTIGATOR) + speckit-echelon-maverick (MAVERICK) | "Why was this ADR abandoned? What should the analysis have caught?" |
| `unpredicted_risk` | speckit-echelon-investigator (INVESTIGATOR) (+ speckit-echelon-guardian (GUARDIAN) if security) | "This risk was not predicted. Is it a known domain pattern?" |
| `effort_overrun` (ratio > 2.0) | speckit-echelon-realist (REALIST) | "Run reference class forecasting. What do similar tasks actually take?" |
| `requirements_gap` (missing > 3) | speckit-echelon-sage (SAGE) | "Why did Understanding miss these? Which metric should have caught them?" |
| `test_gap` | speckit-echelon-sentinel (SENTINEL) | "What coverage pattern would have caught these gaps?" |

For each expert dispatch:
1. Include the specific CRITICAL finding as context
2. Include relevant build artifacts
3. Expert produces investigation results
4. speckit-echelon-commander (COMMANDER) writes expert findings back into `auto-feedback.yaml` → `critical_findings[].expert_finding`

**Non-critical findings** (HIGH/MEDIUM/LOW/INFO): auto-update KB directly in Step 8.5.4 without expert dispatch.

### 8.5.3 Post-Build Validation (optional)

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.post_build_validation` (default: `true`). If `false`, skip to 8.5.4.

**a) Understanding re-scan:**

Dispatch speckit-echelon-sage (SAGE) in post-build-validation mode using the Agent tool:

- **subagent_type:** `speckit-echelon-sage`
- **prompt:**

  ```xml
  <context>
  [include spec.md, quality-gates.md from WHY3, auto-feedback.yaml, reasoning-journal.json]
  </context>

  <instructions>
  You are SAGE. Read agents/exploration/sage.md for your complete protocol. Operate in **post-build-validation mode**.
  Run `speckit.echelon.understanding-validate` against the final `spec.md`. Compare scores against the last WHY3 `quality-gates.md`. If any category dropped > 0.05: flag as REGRESSION. If overall improved: log as IMPROVEMENT.
  Produce `post-build-validation.md`.
  </instructions>
  ```

- **description:** "speckit-echelon-sage (SAGE): post-build Understanding re-scan"

**b) Intent alignment check:**

**Config gate:** Run `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh feedback.post_build_intent_check` (default: `true`).

Dispatch speckit-echelon-tracker (TRACKER) in post-build-alignment mode using the Agent tool:

- **subagent_type:** `speckit-echelon-tracker`
- **prompt:**

  ```xml
  <context>
  [include user-intent.md, verification-summary.md, gap-report.md, implemented code, reasoning-journal.json]
  </context>

  <instructions>
  You are TRACKER. Read agents/control/tracker.md for your complete protocol. Operate in **post-build-alignment mode**.
  Read `user-intent.md` (original user request) and the build output (verification-summary.md, gap-report.md, implemented code). Answer: "Does what was built match what the user asked for?" If MISALIGNED, describe the divergence.
  Produce `intent-alignment-final.md`.
  </instructions>
  ```

- **description:** "speckit-echelon-tracker (TRACKER): post-build intent alignment check"

**Drift Severity Gate (mandatory after speckit-echelon-tracker (TRACKER) produces `intent-alignment-final.md`):**

Read `drift_severity` from `intent-alignment-final.md`.

- **`ALIGNED`:** Log in `feedback-report.md` as INFO. Continue to BUILD_DONE.

- **`MINOR_DRIFT`:** Log in `feedback-report.md` as WARNING with the specific unmet intent points. Continue to BUILD_DONE. No correction dispatched.

- **`MAJOR_DRIFT` AND `autonomy_mode != "banzai"`:**
  1. Dispatch speckit-echelon-change-controller (CHANGE CONTROLLER) with the unmet intent points as the change description.
  2. speckit-echelon-change-controller (CHANGE CONTROLLER) assesses blast radius and creates RW-* rework tasks (max 1 rework pass — `state.json.rework_iteration_count` must be < 1 before entering this path; if already 1, log and continue without rework).
  3. speckit-echelon-engineering-manager (ENGINEERING MANAGER) executes the rework loop for the RW-* tasks.
  4. After rework: re-dispatch speckit-echelon-tracker (TRACKER) for a second alignment check. If still MAJOR_DRIFT after one rework pass, log as CRITICAL in `feedback-report.md` and continue — no infinite loop.

- **`MAJOR_DRIFT` AND `autonomy_mode == "banzai"`:**
  1. Set `state.json.requires_human_review` to `true`.
  2. Write `{spec_dir}/drift-escalation.md`:
     ```
     # Intent Drift Escalation
     **Run:** {state.json.run_id}
     **Severity:** MAJOR_DRIFT
     **Unmet intent points:** {list from intent-alignment-final.md}
     **Action required:** Human review needed before this spec can be marked complete.
     ```
  3. Log CRITICAL in `feedback-report.md`: `[speckit-echelon-commander (COMMANDER)] MAJOR_DRIFT detected in banzai mode — requires_human_review set. See drift-escalation.md.`
  4. Continue to BUILD_DONE (banzai no-checkpoint contract preserved).

### 8.5.4 Auto-Update Knowledge Base

After all expert investigations complete (or immediately for non-critical findings):

1. **calibration-profile.yaml:** Update domain accuracy based on effort ratio, architecture decisions, requirements coverage. Use KB Bootstrap Protocol.
2. **estimates-log.yaml:** Append per-task predicted vs actual effort entries.
3. **patterns.yaml:** Reinforce architecture decisions that held. Add caveats for decisions that broke.
4. **pitfalls.yaml:** Add entries for unpredicted risks and missing requirements patterns.

All writes go through `kb-write.sh append_entry` with locking.

### 8.5.5 Produce Final Feedback Summary

Append to `feedback-report.md`:

```markdown
## Auto-Feedback Summary

- Effort accuracy: {ratio}x ({severity})
- Architecture decisions held: {count}/{total}
- Requirements correct: {count}/{total}
- Risks predicted accurately: {count}/{total}
- Test coverage: {actual}% (planned: {planned}%)
- Critical findings: {count} ({count} investigated by experts)
- KB entries updated: {count}
- Post-build validation: {PASS|REGRESSION|N/A}
- Intent alignment: {ALIGNED|MISALIGNED|N/A}
```

---

### 8.6 Consolidation Phase — Constitution Amendment Candidates

Dispatch speckit-echelon-mirror (MIRROR) and speckit-echelon-veteran (VETERAN) in parallel to extract amendment candidates from this run's learnings.

**Dispatch speckit-echelon-mirror (MIRROR)** (`mode: "consolidation"`):

- Context pack: `feedback-report.md`, `intent-alignment-final.md`, `reasoning-journal.json` (last 20 entries), `traceability-matrix.md`
- Output required: `amendment_candidates` list (may be empty)

**Dispatch speckit-echelon-veteran (VETERAN)** (`mode: "consolidation"`):

- Context pack: `{spec_dir}/run-history.json`, speckit-echelon-mirror (MIRROR)'s `amendment_candidates` (pass directly)
- Output required: `veteran_amendment_candidates` list (may be empty)

**speckit-echelon-commander (COMMANDER) consolidation (after both complete):**

1. Merge both candidate lists — deduplicate by principle text (exact or near-exact match).
2. Filter: keep only `confidence: high` or `confidence: medium` candidates.
3. If merged list is empty: skip the remaining steps. Set `state.json.constitution_amendments_pending` to `0`.
4. Write `{spec_dir}/constitution-amendment-candidates.md`:

   ```markdown
   # Constitution Amendment Candidates
   **Run:** {state.json.run_id}  **Spec:** {spec_id}  **Date:** {timestamp}

   Review each proposal and run `speckit.constitution` to apply approved ones.
   Reject by deleting the [PROPOSED] block.

   ---
   [PROPOSED: {principle text}]
   **Source:** {source from speckit-echelon-mirror (MIRROR)/speckit-echelon-veteran (VETERAN)}
   **Confidence:** {high|medium}
   **Category:** {category}
   ```

5. Append each candidate as a `[PROPOSED: ...]` block to `.specify/memory/constitution.md` (the existing file). Append after the last existing section — never edit existing content.
6. Set `state.json.constitution_amendments_pending` to the count of candidates appended.
7. If `constitution_amendments_pending > 0`: add to the final run summary: `{N} constitution amendment candidate(s) pending human review — see {spec_dir}/constitution-amendment-candidates.md. Run speckit.constitution to approve or reject.`

**Important:** speckit-echelon-commander (COMMANDER) never auto-amends constitution content. Only humans can promote `[PROPOSED]` blocks to permanent principles via `speckit.constitution`. Human review is required.

---

### 8.7 Print Summary

```
============================================
  ECHELON BUILD COMPLETE
============================================

Feature:    {NNN}-{feature}
Tasks:      {completed}/{total} ({degraded} degraded, {blocked} blocked)

QUALITY GATES:
  Spec Guard:     {passed}/{total} PASS
  Code Review:    {approved}/{total} APPROVED
  Test Guardian:  {passed}/{total} PASS
  Integration:    {checkpoints_passed}/{total_checkpoints} PASS
  Verification:   PASS ({coverage_score} coverage, {gap_count} gaps)

EFFORT:
  Estimated total: {sum}
  Actual total:    {sum}
  Burn rate:       {ratio}x
  Drift status:    {ON_TRACK | DRIFT_WARNING | OVERRUN}

AUTO-FEEDBACK (closed loop):
  Effort accuracy:      {ratio}x
  Architecture held:    {count}/{total} decisions
  Requirements correct: {count}/{total}
  Risk predictions:     {count}/{total} accurate
  Test coverage:        {actual}% (planned {planned}%)
  Critical findings:    {count} ({investigated} expert-investigated)
  Post-build validation:{PASS|REGRESSION|N/A}
  Intent alignment:     {ALIGNED|MISALIGNED|N/A}
  KB entries updated:   {count}

REPORTS:
  spec-compliance-report.md
  code-review-report.md
  test-quality-report.md
  integration-report.md
  progress-report.md
  gap-report.md
  verification-summary.md
  feedback-report.md          (NEW — auto-generated)
  post-build-validation.md    (NEW — if enabled)
  intent-alignment-final.md   (NEW — if enabled)

AGENT SCORECARD:
  Top performer: {agent} (+{score}) — {highlight}
  Badges earned: {list}
  Self-healing: {recommendations}

WARNINGS:
  {any DEGRADED tasks}
  {any BLOCKED tasks}
  {any drift alerts}

RISKS ACCEPTED AUTONOMOUSLY:
  {count from risk-acceptance-log.md, or "None"}
  {for each ACCEPT_WITH_MITIGATIONS: one-line summary + mitigation status}

──────────────────────────────────────────
  HUMAN ACTIONS REQUIRED
──────────────────────────────────────────
  {This section is MANDATORY. ALWAYS print it, even if empty.}
  {If no human actions: "None — build completed autonomously."}
  {For each ESCALATE item from risk-acceptance-log.md:}
    [ ] {RAR-ID}: {one-line description} — {reason human must decide}
  {For each BLOCKED task that needs external input:}
    [ ] {task ID}: {what is blocked} — {who/what can unblock}
  {For each HUMAN_REVIEW_REQUIRED flag:}
    [ ] {source agent}: {what needs review}
  {For each manual verification needed:}
    [ ] {what to verify} — {how to verify it}
  {For each deployment/release action:}
    [ ] {action}: {command or step}
──────────────────────────────────────────

============================================
```

---

## 9. Error Handling

### Task-Level Failures

| Situation | Action |
|-----------|--------|
| speckit-echelon-implementer (IMPLEMENTER) timeout (> 5 min) | Retry once. If still timeout, skip task as BLOCKED. |
| Review agent timeout | Retry once. If still timeout, skip gate (flag as UNVALIDATED). |
| speckit-echelon-implementer (IMPLEMENTER) produces no files | Flag as BLOCKED. Move to next task. |
| 3+ tasks BLOCKED | Pause. MANAGER assesses whether build can continue or needs re-planning. |

### Phase-Level Failures

| Situation | Action |
|-----------|--------|
| speckit-echelon-integrator (INTEGRATOR) finds > 5 failures | Pause phase. Assess whether tasks need re-ordering or re-specification. |
| Build command fails completely | Check if `package.json` has the expected scripts. Flag as BLOCKED if not. |
| All tasks in a phase BLOCKED | Skip phase. Flag as PHASE_SKIPPED. Continue to next phase (may also fail). |
| `validate-deploy.sh` fails at 1.0b | HARD STOP. Deploy infrastructure not ready. Follow error output to fix, then re-run build. |

### Degraded Mode

Tasks or gates flagged as DEGRADED must have this banner in their report section:

```markdown
> **DEGRADED** — This task passed with known issues after maximum fix cycles ({N} cycles). The following gates were not fully satisfied: {list}. Review before deployment.
```

---

## 10. Convergence Rules

- **Max fix cycles per gate:** 2 (speckit-echelon-implementer (IMPLEMENTER) gets 2 chances to fix issues per quality gate)
- **Max total speckit-echelon-implementer (IMPLEMENTER) dispatches per task:** 7 (1 initial + 2 per gate for 3 gates)
- **Max BLOCKED tasks before pause:** 3
- **Max DEGRADED tasks before warning:** 30% of total tasks
- **Token budget for build phase:** Configurable in `echelon-config.yml`. Default: 2M tokens.
- **Wall-clock time limit:** 60 minutes. Force complete with whatever is done.

---

## 11. Quick Reference: Build Flow

```
BUILD_INIT
  │ validate Phase A artifacts, parse tasks, order by dependencies
  │
  ▼
FOR EACH task (ordered by phase, then dependencies):
  │
  speckit-echelon-implementer (IMPLEMENTER) → writes code + tests
    │
    ├─ DONE → continue
    ├─ NEEDS_CONTEXT → MANAGER provides, re-dispatch (max 2)
    └─ BLOCKED → skip task, log
    │
  speckit-echelon-spec-guard (SPEC GUARD) → verifies code vs FR-* requirements
    │
    ├─ PASS → continue
    └─ FAIL → speckit-echelon-implementer (IMPLEMENTER) fixes (max 2 cycles)
    │
  speckit-echelon-code-reviewer (CODE REVIEWER) → checks quality + ADR + constitution
    │
    ├─ APPROVED → continue
    └─ CHANGES_REQUESTED → speckit-echelon-implementer (IMPLEMENTER) fixes (max 2 cycles)
    │
  speckit-echelon-test-guardian (TEST speckit-echelon-guardian (GUARDIAN)) → validates test quality + coverage
    │
    ├─ PASS → continue
    └─ FAIL → speckit-echelon-implementer (IMPLEMENTER) adds tests (max 2 cycles)
    │
  speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) → records effort, checks drift
  │
END FOR
  │
speckit-echelon-integrator (INTEGRATOR) → runs after each phase checkpoint
  │
  ├─ PASS → next phase
  └─ FAIL → speckit-echelon-implementer (IMPLEMENTER) fixes integration issues
  │
FINAL INTEGRATION → whole-system integration pass
  │
speckit-echelon-engineering-manager (ENGINEERING MANAGER) → workflow compliance + readiness sign-off
  │
speckit-echelon-verification (VERIFICATION) → full backpropagation check against spec
  │
  ├─ PASS → BUILD_DONE
  └─ FAIL → RW-* tasks + rework loop

Before BUILD_DONE can succeed:
  speckit-echelon-engineering-manager (ENGINEERING MANAGER) → verifies workflow compliance and readiness
  speckit-echelon-verification (VERIFICATION) → proves 100% implemented coverage with zero open gaps
```

---

## 12. Harness Integration: Report Build Status

If the environment variable `HARNESS_BUILD_STATUS_FILE` is set, write the build outcome so the Python harness can detect success or impasse:

**On successful completion (BUILD_DONE reached):**

```bash
if [ -n "$HARNESS_BUILD_STATUS_FILE" ]; then
  printf '{"status":"done"}' > "$HARNESS_BUILD_STATUS_FILE"
fi
```

**On unresolvable impasse (skill escalates after exhausting all retries):**

```bash
if [ -n "$HARNESS_BUILD_STATUS_FILE" ]; then
  printf '{"status":"impasse","reason":"gate escalation after retries"}' > "$HARNESS_BUILD_STATUS_FILE"
fi
```

If `HARNESS_BUILD_STATUS_FILE` is not set (standalone invocation), skip this step entirely.
