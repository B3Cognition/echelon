# Build 8 Summary Reference Appendix

Load this appendix when producing the final build summary, handling task/phase failures, applying degraded mode, or checking convergence limits.

## Final Summary Template

```text
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
  feedback-report.md
  post-build-validation.md
  intent-alignment-final.md

AGENT SCORECARD:
  Top performer: {agent} (+{score}) - {highlight}
  Badges earned: {list}
  Self-healing: {recommendations}

WARNINGS:
  {any DEGRADED tasks}
  {any BLOCKED tasks}
  {any drift alerts}

RISKS ACCEPTED AUTONOMOUSLY:
  {count from risk-acceptance-log.md, or "None"}
  {for each ACCEPT_WITH_MITIGATIONS: one-line summary + mitigation status}

HUMAN ACTIONS REQUIRED:
  {Always print this section, even if empty.}
  {If no human actions: "None - build completed autonomously."}
  {For each ESCALATE item from risk-acceptance-log.md:}
    [ ] {RAR-ID}: {one-line description} - {reason human must decide}
  {For each BLOCKED task needing external input:}
    [ ] {task ID}: {what is blocked} - {who/what can unblock}
  {For each HUMAN_REVIEW_REQUIRED flag:}
    [ ] {source agent}: {what needs review}
  {For each manual verification needed:}
    [ ] {what to verify} - {how to verify it}
  {For each deployment/release action:}
    [ ] {action}: {command or step}
============================================
```

## Error Handling

Task-level failures:

| Situation | Action |
| --- | --- |
| IMPLEMENTER timeout over 5 minutes | Retry once. If still timeout, skip task as BLOCKED. |
| Review agent timeout | Retry once. If still timeout, skip gate and flag as UNVALIDATED. |
| IMPLEMENTER produces no files | Flag as BLOCKED. Move to next task. |
| 3 or more tasks BLOCKED | Pause. MANAGER assesses whether build can continue or needs replanning. |

Phase-level failures:

| Situation | Action |
| --- | --- |
| INTEGRATOR finds more than 5 failures | Pause phase and assess whether tasks need reordering or respecification. |
| Build command fails completely | Check expected scripts. Flag as BLOCKED if missing. |
| All tasks in a phase BLOCKED | Skip phase, flag as PHASE_SKIPPED, continue to next phase. |
| `validate-deploy.sh` fails at 1.0b | Hard stop; deploy infrastructure is not ready. |

## Degraded Mode Banner

```markdown
> **DEGRADED** - This task passed with known issues after maximum fix cycles ({N} cycles). The following gates were not fully satisfied: {list}. Review before deployment.
```

## Convergence Rules

| Limit | Value |
| --- | --- |
| Max fix cycles per gate | 2 |
| Max IMPLEMENTER dispatches per task | 7 |
| Max BLOCKED tasks before pause | 3 |
| Max DEGRADED tasks before warning | 30% of total tasks |
| Token budget for build phase | Configurable in `echelon-config.yml`, default 2M tokens |
| Wall-clock time limit | 60 minutes, then force complete with completed work |

## Build Flow Reference

```text
BUILD_INIT
  -> validate Phase A artifacts, parse tasks, order by dependencies
  -> for each task:
       IMPLEMENTER writes code and tests
       SPEC GUARD verifies code against FR-* requirements
       CODE REVIEWER checks quality, ADRs, and constitution
       TEST GUARDIAN validates test quality and coverage
       PROGRESS TRACKER records effort and checks drift
  -> INTEGRATOR runs after each phase checkpoint
  -> FINAL INTEGRATION
  -> ENGINEERING MANAGER checks workflow compliance and readiness
  -> VERIFICATION proves implemented coverage with zero open gaps
  -> BUILD_DONE or RW-* rework loop
```
