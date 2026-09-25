# Spec Recovery Regression Checklist

Use this checklist when refactoring Echelon's specification controller. It
captures recovery failures observed in a real Phase A run and the controller
invariants that prevent them from recurring.

The implementation may move during a refactor. Verify behavior and durable
state transitions rather than matching historical function or field names.

## Scope

The regression surface includes:

1. preserving resolved human-decision authority during later issue repair;
2. replaying the current pending durable spec step;
3. persisting explicit autonomy-mode changes before recovery routing; and
4. exposing and routing structured Phase 3 consensus blockers.

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

For state without `blocked_decision`, obsolete escalation question and option
fields may still be cleared.

### Regression scenario

1. Create current-version blocked run state containing a resolved versioned
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

## 2. Replay the pending durable spec step

### Failure

The current controller has a valid `pending_spec_step`, but `echelon spec
continue` classifies `spec_step_pending` as manual recovery. The command never
re-enters the controller, so its recovery kernel cannot replay the sealed step.

### Required invariant

A current `pending_spec_step` MUST classify as a controller retry. The
recommended command is `echelon spec continue`; it MUST delegate to the
controller without changing the pending marker, phase, or status first. The
controller's single spec-step recovery kernel remains the only replay owner.

The retired `pending_controller_completion` protocol is not supported and MUST
NOT be restored.

### Regression scenario

1. Create and begin a real sealed `pending_spec_step`.
2. Record a bounded effect failure so state becomes blocked with
   `blocked_reason: spec_step_pending`.
3. Invoke `echelon spec continue` with controller dispatch recorded.
4. Assert that the controller is invoked with the durable run mode.
5. Assert that the service did not mutate the marker, phase, or status before
   controller recovery.
6. Separately verify crash replay and exactly-once receipt adoption in the
   spec-step kernel suite.

Current regression test:

```text
test_continue_replays_current_pending_spec_step_without_reclassifying_phase
```

## 3. Persist explicit autonomy-mode changes

### Failure

`echelon spec continue --mode banzai` displays and passes `banzai` to the
immediate invocation but leaves `state.json` with `autonomy_mode: semi`.
Downstream routing reads durable state, declines Banzai automation, and returns
the run to the same blocker.

### Required invariant

When no active sealed decision owns the mode, an explicit `--mode` override MUST
be written through the current state owner before recovery classification and
dispatch. Subsequent controller code and later continuation commands MUST
observe the new mode.

An active sealed decision remains authoritative: a continuation-time flag MUST
NOT reclassify that decision's autonomy policy. A pending spec step is replayed
before accepting a mode change so its sealed transition is not invalidated.

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
recovery renderer discards it and prints only a generic retry message. Repeated
continuation produces the same output while hiding the issue owner, problem,
and required repair.

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

## Verification procedure

1. Locate the durable state writer, recovery classifier, continuation command,
   spec-step kernel, and Phase 3 repair router.
2. Confirm that all four invariants have one state owner and that presentation
   code does not silently discard structured recovery data.
3. Run the six named regression tests.
4. Run the broader continuation, status, spec-step, and controller-routing
   suites.
5. Exercise one temporary current-version run state end to end and inspect
   `state.json` after every transition.
6. Report each invariant as **present**, **missing**, or **changed
   intentionally**, with file/line evidence and test output.

Useful discovery command:

```bash
rg -n \
  'blocked_decision|pending_spec_step|autonomy_mode|phase3_last_blocker' \
  src tests runtime
```

Focused regression command:

```bash
pytest -q \
  tests/unit/test_cli_continue.py \
  tests/unit/test_cli_resume_escalation_options.py \
  -k 'replays_current_pending_spec_step or persists_explicit_mode_override or consensus_agent_block or preserves_prior_resolved_decision_authority or sealed_v2_decision_mode'
```

## Expected review output

The reviewing agent should return a table with these columns:

```text
Invariant | Status | Implementation evidence | Test evidence | Required action
```

Do not treat renamed functions or reorganized modules as regressions. Treat a
missing durable-state guarantee, lost authority, ineffective next command, or
Semi/Banzai behavior mismatch as a regression.
