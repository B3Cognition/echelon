# EGR-152 Recover Completed RE Workspace Synthesis After Result Rejection

**Review date:** 2026-07-18
**Priority:** P0
**Status:** fixed

## Summary

A production `echelon re run` can finish the expensive workspace-synthesis
dispatch, write every requested staged artifact, and then block before
publication because the specifier returns a controller-owned completion flag in
`echelon_result.state_updates`. The controller rejects the otherwise successful
result, leaves the post-dispatch sentinel incomplete, and offers no deterministic
way to accept the already-written artifacts. A normal continue therefore risks
paying for the workspace synthesis again.

This is a P0 lifecycle defect because a valid, high-cost run is stranded at the
result/state ownership boundary after its durable output has already been
produced.

## Production Evidence

- Run `re-20260718-063615-364321` completed four-source, nineteen-domain
  extraction and workspace synthesis on Echelon 3.5.1.
- The final specifier response reported `verdict: DONE`, listed the staged
  workspace/source outputs, and returned
  `state_updates.re_workspace_synthesis_complete: true`.
- `kernel.re_state.complete_dispatch()` rejected that key because agents may
  update only the RE phase allowlist. The lifecycle surfaced only
  `re_agent_result_invalid`, while the precise validation error remained in
  run state.
- `ReExtractionController._complete_specification_target()` already owns the
  completion transition, so the agent flag was redundant rather than required
  work.
- The staged synthesis artifacts remain in the run directory; canonical RE
  publication did not occur.

## Root Cause

`ReExtractionController._agent_result_without_controller_keys()` filters some
controller-owned fields but does not enforce an empty state-update contract for
all controller-owned specification targets. The workspace-synthesis prompt and
phase schema also imply that agents may return descriptive or routing state.
The resulting rejected dispatch cannot be distinguished from a failed dispatch
by the current recovery loop even when its complete durable artifact set can be
validated locally.

Separately, `ReLifecycleResult` drops `ReControllerResult.blocked_detail`, so
the terminal reports the generic reason without the actionable validation
error.

## Required Fix

1. Treat every `re-extract-2-specify` target as a file-producing,
   controller-routed operation and normalize its agent `state_updates` to `{}`.
2. Make the prompt, phase contract, and agent result example explicitly require
   `state_updates: {}` for controller-owned specification targets.
3. Add deterministic workspace-synthesis validation covering the three
   workspace documents, every refreshed source overview, and every workspace
   domain document declared by the controller-owned architecture map.
4. On continue, recognize only the exact historical failure signature, validate
   the staged synthesis, complete the interrupted dispatch and target locally,
   and proceed without redispatch. Fail closed when any required artifact is
   absent or empty.
5. Propagate the controller's blocked detail through the lifecycle and terminal
   output.

## Recovery Contract

The recovery path is intentionally narrow. It may run only when the active RE
state is blocked in `re-extract-2-specify` with `re_agent_result_invalid`, the
validation detail names `re_workspace_synthesis_complete`, the incomplete
dispatch sentinel belongs to the specifier, and the first queued target is
`workspace-synthesis`. It must validate all required staged outputs before
marking the dispatch and target complete.

No source-domain extraction or workspace-synthesis provider call may occur on a
successful recovery. After recovery, the normal semantic validation, checklist,
constitution, and publication gates still run.

## Acceptance Criteria

- The production-shaped rejected result is sanitized before kernel state
  validation in future runs.
- A complete stranded synthesis resumes with zero specification redispatches.
- A missing or empty synthesis artifact prevents local recovery.
- Normal workspace synthesis cannot be accepted until its deterministic
  artifact contract passes.
- CLI blocked output contains both the stable reason and precise detail.
- Focused controller/lifecycle/prompt tests, extension dry-run, full tests, and
  `git diff --check` are recorded before this finding is marked fixed.
- `CHANGELOG.md` names EGR-152 and describes the operator-visible recovery.

## Implemented Resolution

- All controller-owned specification targets discard agent `state_updates`;
  their durable artifacts are the only accepted output surface.
- Workspace synthesis is checked for non-empty workspace overview,
  relationships, and contracts; every refreshed source overview; and every
  architecture-declared workspace-domain document. Symlinks are rejected.
- The controller recognizes the exact rejected-completion signature before any
  migration can erase its diagnostic, completes the sentinel and queued target
  locally only after validation, and then follows the ordinary semantic,
  checklist, constitution, and publication path.
- `ReLifecycleResult` carries precise controller detail and the terminal prints
  it below the stable blocked reason.
- Agent, phase, and controller-appended prompts now agree on
  `state_updates: {}`.

## Verification

- Regression tests were observed red before implementation: six failures
  covered leaked state, missing prompt contract, paid redispatch, incomplete
  artifact acceptance, dropped lifecycle detail, and hidden CLI detail.
- Focused RE controller/lifecycle/CLI/prompt matrix: `119 passed`.
- Extension dry-run: `138 passed`, `0 failed`, with the one expected warning
  that the retired `agents.yaml` registry is absent.
- Full pytest: `3991 passed`, `1 failed`, `7 deselected`. The sole failure,
  `test_blocked_non_escalation_run_does_not_claim_ready_to_build`, reproduces
  unchanged on a clean detached 3.5.1 `main` worktree and is unrelated to RE.
- `git diff --check` passed.
