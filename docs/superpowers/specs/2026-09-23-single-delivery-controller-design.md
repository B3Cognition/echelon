# Single Delivery Controller Hard-Cutover Design

## Purpose

Replace the abandoned multi-strategy Delivery architecture with the product that
actually exists: one Delivery run, one controller, and one durable state stream.
Then decompose that controller around the durable checkpoints already proven by
the current implementation.

This is milestone S4 in `docs/simplification-control.md`. The priority is a
quick, deletion-first simplification that keeps the supported Delivery path
working. Historical multi-strategy runs are not a compatibility requirement.

## Evidence and Problem

Every supported Delivery run currently takes the same `default` strategy path,
but the active implementation still carries a dormant experiment framework:

- `StrategyCoordinator` accepts a list of strategies, loads strategy files,
  slices budgets, creates per-strategy state stores, optionally runs workers in
  a thread pool, cancels peers, and compares results;
- `RunIntent` parses `strategies=...` and `kill_losers` even though production
  usage always selects the single built-in `default` strategy;
- the Delivery CLI and service propagate a strategy option through run,
  continue, resume, status, checkpoint, and output rendering;
- state is named and shaped as though each build contains competing strategy
  executions;
- `StrategyCoordinator._run_strategy` is approximately 1,000 lines and
  `RalphController._run_loop_inner` is approximately 1,000 lines, so the
  obsolete abstraction also hides the real orchestration boundaries.

The strategy mechanism is not a viable product mode and will not return. Keeping
it as a deprecated or hidden execution path would preserve most of the
complexity S4 exists to remove.

## Decision

Perform a hard cutover to a single `DeliveryController`.

There is no Delivery strategy selection after S4. `default` is not a user
choice, a persisted identity, or an internal pseudo-option. New execution goes
directly from the Delivery service adapter to one controller instance and
returns one `DeliveryResult`.

Historical multi-strategy and `default.json` runs are deliberately unsupported:
S4 does not discover, read, migrate, resume, summarize, or render them. A user
who starts Delivery after the cutover starts under the new single-run state
contract.

This decision is specific to the removed Delivery experiment dimension. It does
not remove unrelated uses of the word `strategy`, including Git landing choices
such as merge versus rebase, Spec-authoring strategy artifacts, or sandbox
recommendation prose.

## Removed Surface

Delete, rather than deprecate:

- `StrategyCoordinator` and its multi-run `start`, status aggregation, result
  comparison, peer cancellation, and strategy-context machinery;
- strategy-file loading for Delivery execution and the built-in `default`
  `StrategySpec` path;
- thread-pool fan-out and convergence-event coordination;
- per-strategy budget splitting;
- `RunIntent.strategies`, `RunIntent.kill_losers`, their parsers, environment
  inputs, validation, and rendering;
- Delivery `--strategy`, `strategy=...`, and `kill_losers` inputs wherever they
  mean execution-strategy selection;
- strategy columns, maps, counts, comparison summaries, and phrases such as
  "N strategies" in Delivery run output and history;
- strategy-qualified Delivery checkpoint/status/resume lookup;
- tests and documentation whose only purpose is the removed execution model.

Removed options are not silently accepted or translated to `default`. Normal
CLI unknown-option handling is the migration signal. Natural-language adapter
text no longer recognizes strategy or `kill_losers` tokens as control fields.

## Single-Run Contract

### Entry and result

`run_skill._execute_delivery_run` constructs one `DeliveryController`, calls
`run(intent)`, and receives one `DeliveryResult`. History, landing, summary, and
exit-code decisions consume that result directly. They do not construct a
one-entry map merely to preserve the old comparison interface.

`RunIntent` retains only real run controls: spec, mode, iteration limits, token
budget, auto-merge, task description, reset, and resume.

### State identity

One build has one Delivery state:

- state: `<build>/state/delivery.json`;
- lock: `<build>/state/delivery.lock`;
- backup: `<build>/state/delivery.json.bak`.

`StateStore` is constructed from the state directory and spec ID only. New
state contains no `strategy_id`. State atomicity, lock ownership, backups,
transition validation, monotonic counters, operation journals, and phase
checkpoints remain unchanged.

All new Delivery-owned paths and artifact identities that currently vary only
by `strategy_id` become run-scoped. Where a downstream helper needs a stable
label for branch or evidence naming, it receives an explicit run/build identity
rather than the deleted strategy concept.

### Supported resume

Resume and continue operate only on `delivery.json` belonging to the current
single-run contract. They do not fall back to `default.json`, scan arbitrary
strategy files, or translate old operation journals. Status and checkpoint
commands follow the same rule.

## Controller Boundary

The first cutover is mechanical: move the current single-strategy body into
`DeliveryController.run` while preserving the order and conditions of all
supported effects. Do not redesign the Ralph state machine in the same edit.

`DeliveryController` owns:

1. acquiring and releasing the single run lock;
2. initializing or resuming the durable state;
3. resolving the current phase and validating its checkpoint;
4. invoking the phase executor;
5. persisting phase transitions, terminal blocks, and final results;
6. coordinating verified publication and landing handoff.

`RalphController` remains the implementation-phase engine during the mechanical
cutover. Its constructor loses `strategy_id`; run-scoped identity is supplied
only where an artifact actually requires it.

## Durable Decomposition

After the single-controller cutover passes, decomposition proceeds one existing
durable boundary at a time. The target steps are:

1. **Open run** — create or load state, validate phase/version, and establish
   the immutable run context.
2. **Recover pending operation** — reconcile the persisted
   `delivery_slice_operation` before selecting new work.
3. **Execute one controlled slice** — select one dependency-ready task,
   dispatch implementation and reviews, and return a typed outcome without
   advancing unrelated phases.
4. **Commit progress checkpoint** — apply accepted task progress and persist
   its operation accounting idempotently.
5. **Verify candidate checkpoint** — bind registered worktree, verified commit,
   source/spec inputs, and verification evidence.
6. **Process review re-entry** — consume `pending_review_reentry` and route one
   bounded repair or acceptance decision.
7. **Publish verified candidate** — consume
   `verified_publish_checkpoint` idempotently.
8. **Finalize run** — persist the terminal transition and return the single
   result.

Each extraction first characterizes the existing behavior, then moves it behind
an explicit typed method without changing durable keys or transition order.
Only the strategy identity removal changes the state schema in S4.

The desired control flow is:

```text
Delivery service
      |
      v
DeliveryController.run(intent)
      |
      +--> open/recover durable run
      +--> execute exactly one current phase step
      +--> checkpoint the result
      +--> repeat, block, or finalize
                  |
                  v
          one DeliveryResult
```

## Preserved Behavior

Except for removal of strategy selection and historical-state compatibility,
the supported single Delivery run preserves:

- status values and legal transitions;
- mode, iteration, token, and convergence accounting;
- escalation stickiness and user-answer semantics;
- controller-only durable state mutation;
- `delivery_slice_operation` recovery and receipt validation;
- task progress checkpoints and retry ceilings;
- registered-worktree and verified-candidate binding;
- visual, review, documentation, runnability, and fulfillment gates;
- `pending_review_reentry` and `verified_publish_checkpoint` semantics;
- polyrepo target containment and source authentication;
- provider-limit, interruption, block, publication, and terminal outcomes;
- active default-path output and errors after removing strategy-specific words
  and fields.

No extraction may invent a generic workflow framework, change retry policy, or
move mutation authority into a provider or agent response.

## Implementation Sequence

1. Characterize the active single-run contract and add structural tests that
   forbid the removed options and strategy execution imports.
2. Remove strategy controls from CLI/service input and `RunIntent`.
3. Convert `StateStore` and Delivery lookup to the fixed run-scoped files;
   remove `strategy_id` from new state.
4. Replace `StrategyCoordinator` with the mechanically equivalent
   `DeliveryController`; simplify run output/history to one result.
5. Remove strategy loader, budget-slicing, comparison, cancellation, and
   now-dead tests/code.
6. Extract Ralph/controller steps in the durable order above, running focused
   recovery tests after every boundary.
7. Update current documentation and run the focused and repository gates.

This ordering eliminates the dead product surface early, but postpones semantic
loop surgery until the supported path is again green.

## Verification

The S4 gate must prove:

- Delivery help and typed service requests expose no execution-strategy or
  `kill_losers` option;
- `RunIntent` contains and parses no strategy dimension;
- production Delivery execution imports no strategy loader, budget slicer,
  thread-pool fan-out, peer cancellation, or result-comparison path;
- one invocation creates only `state/delivery.json` and never writes
  `state/default.json` or `strategy_id`;
- run, continue, resume, status, checkpoints, escalation, and landing use the
  single result/state contract;
- interruption at each existing durable checkpoint resumes without skipped or
  duplicated controller effects;
- focused Delivery, Ralph, state, recovery, CLI, polyrepo, verification,
  publication, and landing suites pass;
- the repository merge-verification gate passes and its receipt is recorded in
  `docs/simplification-control.md`.

## Alternatives Rejected

### Keep only `default` as a validated strategy

This would retain strategy parsing, identity, state shape, loader seams, and
one-entry comparison structures for a choice that does not exist.

### Preserve historical non-default resume behind a hidden adapter

This would keep the old coordinator and state discovery reachable, defeating
the hard cutover. Historical runs have no compatibility requirement.

### Rewrite Delivery and Ralph together

This combines state-schema change, orchestration replacement, and recovery
redesign in one unreviewable step. Mechanical cutover followed by checkpoint-led
extraction is faster to verify and safer to land.

## Out of Scope

- Changing gate policy, retry budgets, provider contracts, or mode semantics.
- Redesigning the durable operation journal or checkpoint contents beyond
  deleting strategy identity.
- Renaming unrelated merge/rebase, Spec-authoring, discovery, or recommendation
  concepts that legitimately use the word `strategy`.
- Supporting or migrating any pre-S4 Delivery state.
- S5 Spec-controller consolidation, S6 RE-protocol consolidation, or S7-wide
  import-cycle cleanup.
