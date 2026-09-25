# Spec Recovery Regression Checklist

Use this checklist when refactoring Echelon's specification controller. It
captures recovery failures observed in a real Phase A run and the controller
invariants that prevent them from recurring.

The implementation may move during a refactor. Verify the behavior and durable
state transitions rather than matching the current function names.

## Scope

The regression surface includes:

1. preserving resolved human-decision authority during later issue repair;
2. replaying pending controller-owned completion;
3. persisting explicit autonomy-mode changes before recovery routing; and
4. exposing and routing structured Phase 3 consensus blockers; and
5. preserving SAGE's bounded write capability and rejecting unpublished review
   reports.

## 1. Preserve decision authority during issue repair

### Failure

A human resolves a material decision. A later proportional-quality gate raises
an issue, and `echelon spec resolve <issue> <resolution>` starts a targeted
repair. The resolve operation deletes the prior `blocked_decision`, so the
repair phase loses the authoritative answer and either reports incomplete
context or asks the same product question again.

### Required invariant

Starting a later issue repair MUST preserve a prior resolved decision in durable
state, including its answer, provenance, classification, resolution metadata,
and sealed autonomy mode. Clearing transient block fields MUST NOT erase that
authority.

For legacy state without `blocked_decision`, obsolete escalation question and
option fields may still be cleared.

### Regression scenario

1. Create blocked run state containing a resolved versioned
   `blocked_decision`.
2. Publish an eligible issue in `issues.md`.
3. Invoke `echelon spec resolve` for that issue.
4. Assert that the run becomes `running` at the selected repair phase.
5. Assert that `selected_issue_resolution` is recorded.
6. Assert that `blocked_decision` is byte-for-byte/equality preserved.

Current regression test:

```text
test_resolve_preserves_prior_resolved_decision_authority
```

## 2. Replay pending controller completion

### Failure

Run state with `blocked_reason: controller_completion_pending` is classified as
manual or unrecognized recovery even though the controller already persisted a
valid `pending_controller_completion` record.

### Required invariant

`controller_completion_pending` MUST classify as a retry of the recorded phase.
The recommended command is `echelon spec continue`; it MUST NOT request a human
repair or discard the pending completion record.

### Regression scenario

Given blocked state containing a valid pending-completion envelope, assert that
recovery classification returns:

```text
kind: retry_phase
reason: controller_completion_pending
phase: <recorded current phase>
command: echelon spec continue
```

Current regression test:

```text
test_continue_retries_pending_controller_completion
```

## 3. Persist explicit autonomy-mode changes

### Failure

`echelon spec continue --mode banzai` displays and passes `banzai` to the
immediate invocation but leaves `state.json` with `autonomy_mode: semi`.
Downstream routing reads durable state, declines Banzai automation, and returns
the run to the same blocker.

### Required invariant

When no active sealed decision owns the mode, an explicit `--mode` override MUST
be written to durable run state before recovery classification and dispatch.
Subsequent controller code and later continuation commands MUST observe the new
mode.

An active sealed decision remains authoritative: a continuation-time flag MUST
NOT reclassify that decision's autonomy policy.

### Regression scenario

1. Create an unsealed, Semi-mode run blocked at Phase 3 consensus.
2. Continue it with `--mode banzai`.
3. Assert that `state.json` contains `autonomy_mode: banzai` before nested run
   dispatch.
4. Assert that the retried phase is `phase3-consensus`.
5. Assert that the nested invocation receives Banzai mode.
6. Separately assert that an active sealed decision retains its sealed mode.

Current regression tests:

```text
test_continue_persists_explicit_mode_override_for_unsealed_consensus_retry
test_continue_uses_sealed_v2_decision_mode_not_cli_override
```

## 4. Make Phase 3 consensus blockers actionable

### Failure

The controller persists a structured `phase3_last_blocker`, but the user-facing
recovery renderer discards it and prints only:

```text
stopped agent_blocked
note will retry the blocked phase without rewind
next echelon spec continue
```

Repeated continuation produces the same output while hiding the issue owner,
problem, and required repair.

### Required structured input

An actionable blocker contains all of:

```json
{
  "issue_id": "ISS-001",
  "owner_phase": "phase3-how",
  "detail": "Assignment capacity predicates disagree.",
  "next_action": "Apply the shared predicate to both constraints."
}
```

The currently eligible repair owners are:

```text
phase3-how
phase3-sentinel
phase3-plan
```

### Required Semi behavior

Semi mode MUST show the issue ID, owner, detailed problem, and required repair.
It MUST produce an executable command equivalent to:

```bash
echelon phase run phase3-how \
  --message "Apply the shared predicate to both constraints."
```

It MUST NOT recommend another bare `echelon spec continue` when that command
cannot change the blocking condition.

### Required Banzai behavior

Banzai mode MUST expose the same diagnostic information and automatically route
the eligible issue to its owner phase. Its summary MUST say which issue is being
routed where; it MUST NOT present a generic retry loop.

Current regression tests:

```text
test_consensus_agent_block_recovery_exposes_owner_and_required_repair
test_banzai_consensus_agent_block_recovery_explains_automatic_route
```

## 5. Keep SAGE review writes bounded and usable

### Failure

WHY3 tells SAGE to update `issues.md` and `quality-gates.md`, but the Claude
adapter combines `dontAsk` with an OS sandbox that permits only direct writes to
the final filenames. Claude's Write/Edit implementation uses a temporary sibling
and atomic rename, so both writes fail with `EPERM`. Absolute paths in Claude's
tool allowlist are also rendered with an extra leading slash. A blocking SAGE
decision is told to publish a run-local KB proposal, but no proposal path is
authorized.

The staged consensus executor then accepts `output_files: []`. Pre-existing
reports make the run look complete even though they are stale, and consensus
can retry indefinitely without presenting the actual publication failure.

### Required invariant

For an exclusive SAGE review dispatch:

- Claude tool rules MUST contain canonical absolute paths;
- the OS sandbox MUST permit only temporary siblings derived from each exact
  authorized filename for atomic replacement, while Claude's tool allowlist
  remains restricted to the exact final paths;
- the controller MUST inject one deterministic, exact run-local KB proposal
  path and authorize it; and
- WHY3 MUST block with `missing_phase_outputs` unless both review files exist
  and are declared in that dispatch's `echelon_result.output_files`.

Stale files from an earlier dispatch MUST NOT satisfy the declaration check.
The failure text MUST name the missing reports and the `output_files` contract.

Current regression tests:

```text
test_claude_backend_enforces_prompt_file_scopes
test_claude_workspace_sandbox_allows_atomic_replace_for_declared_output
test_claude_exclusive_scope_wires_atomic_write_profile
test_sage_prompt_names_exact_authorized_decision_proposal_path
test_staged_why3_requires_current_review_reports_in_output_files
```

## Verification procedure for a refactored repository

1. Locate the durable state writer, recovery classifier, continuation command,
   and Phase 3 repair router. Do not assume their old names or locations.
2. Confirm that all five invariants above have a single state owner and that
   presentation code does not silently discard structured recovery data.
3. Port or locate the named regression tests and run them.
4. Run the broader continuation, status, and controller-routing suites.
5. Exercise one temporary run state end to end and inspect `state.json` after
   every transition.
6. Report each invariant as **present**, **missing**, or **changed intentionally**,
   with file/line evidence and test output.

Useful discovery command:

```bash
rg -n \
  'blocked_decision|controller_completion_pending|autonomy_mode|phase3_last_blocker' \
  src tests runtime
```

Focused tests in the source branch can be found with:

```bash
pytest -q \
  tests/unit/test_cli_continue.py \
  tests/unit/test_cli_resume_escalation_options.py \
  -k 'pending_controller_completion or persists_explicit_mode_override or consensus_agent_block or preserves_prior_resolved_decision_authority or sealed_v2_decision_mode'
```

## Expected review output

The reviewing agent should return a table with these columns:

```text
Invariant | Status | Implementation evidence | Test evidence | Required action
```

Do not treat renamed functions or reorganized modules as regressions. Treat a
missing durable-state guarantee, lost authority, ineffective next command, or
Semi/Banzai behavior mismatch as a regression.
