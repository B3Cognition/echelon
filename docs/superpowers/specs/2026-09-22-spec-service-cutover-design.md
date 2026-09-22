# Spec Service Cutover Design

## Purpose

Complete the active `spec` portion of the S3 Typer cutover without redesigning
the Phase A controller. The command surface must call typed application
services, `cli.py` must stop owning active spec workflows, and existing
durability, recovery, output, and exit behavior must remain intact.

This is an ownership extraction, not the S5 controller simplification. S5
remains responsible for reducing Phase A to a smaller recover-plan-execute-
commit kernel.

## Chosen Approach

Use one mechanical ownership cutover implemented as two tight commits:

1. Move leaf spec workflows and the shared skill-command dispatcher.
2. Move the Phase A run and recovery core.

The alternative of adding a facade that delegates back into `cli.py` is
rejected because it hides rather than removes the legacy ownership boundary.
Immediate decomposition into separate run, recovery, status, and maintenance
services is also rejected because it would pull S5 into S3 and increase the
risk of behavioral drift.

## Architecture

### `echelon.cli_app`

`cli_app.py` continues to own Typer declarations and command-line parsing. Its
active `spec` commands call typed functions in `echelon.spec_service`; they do
not import `echelon.cli` or invoke private legacy handlers.

### `echelon.spec_service`

`spec_service.py` becomes the application-service boundary for active Phase A
commands. Its public functions accept typed values for declared command
options. The existing Phase A workflow and recovery implementation moves into
this module mechanically, retaining its private helpers and observable
behavior.

Where the current controller still requires an argument vector internally, a
private adapter may construct it inside `spec_service.py`. This adapter is not
a second public dispatch layer and is temporary until S5. Typer itself must no
longer construct full legacy argument arrays for active spec commands.

### `echelon.skill_command_service`

The small shared Prosaic skill dispatcher moves to
`skill_command_service.py`. It serves `spec reopen`, `spec bugfix`, and
`spec change`, plus the retained root `review` compatibility alias. This keeps
generic skill dispatch out of both the spec service and `cli.py`.

### `echelon.phase_service`

Manual phase replay continues to own its existing typed command surface. The
Phase A helpers it shares with spec recovery are imported from
`spec_service.py`, removing its temporary dependency on `echelon.cli`.

### `echelon.cli`

`cli.py` retains delivery and RE workflows until their scheduled S3 slices.
All active spec handlers and their spec-only helpers are deleted after they
move. The dead `_cmd_spec` dispatcher is deleted rather than preserved as a
compatibility layer.

Generic helpers still needed by delivery, RE, and spec may remain in `cli.py`
for this slice when moving them would broaden the change. Such helpers must
not dispatch or own an active spec workflow. Remaining cross-module cleanup is
owned by the later delivery, RE, and S7 cycle-removal work.

## Command Boundary

The cutover covers these active commands:

- `spec run`
- `spec retarget`
- `spec status`
- `spec continue`
- `spec resume`
- `spec add-input`
- `spec resolve`
- `spec rewind`
- `spec repair-traceability`
- `spec drop-target`
- `spec targets`
- `spec artifacts`
- `spec reopen`
- `spec bugfix`
- `spec change`
- `spec amend`

The hidden `spec target` compatibility rejection also moves out of `cli.py` so
the spec command family has no legacy CLI dependency. Already modular spec
commands remain on their current services.

## Commit 1: Leaf Workflows

Move the bounded workflows that do not drive the full Phase A controller:

- add input;
- resolve an issue;
- drop a target;
- show target ownership;
- write the artifact index;
- prepare an amendment;
- run the reopen, bugfix, and change skills;
- reject the retired `spec target` mutation path.

Move the shared skill dispatcher to `skill_command_service.py` and update the
retained root `review` alias to use it. Delete the corresponding handlers and
spec-only helper functions from `cli.py` in the same commit. Update focused
tests to exercise the Typer or service surface instead of importing deleted
legacy handlers.

## Commit 2: Phase A Core

Move the remaining spec application workflow:

- run and retarget;
- status;
- continue and resume;
- rewind and traceability repair;
- run discovery, selection, summary, recovery classification, and manual phase
  replay helpers owned by those workflows.

Update `phase_service.py` to use the moved helpers. Delete the original
implementations and the dead `_cmd_spec` dispatcher from `cli.py` in the same
commit. No forwarding aliases remain for active spec handlers.

## Data Flow

1. Typer parses declared command arguments and options.
2. `cli_app.py` passes typed values and the current project root to a public
   `spec_service` function.
3. The service performs runtime, workspace, provider, and persisted-state
   validation.
4. The relocated Phase A kernel performs the existing locked state transition
   or read-only query.
5. The service renders the existing result and preserves the existing exit
   status.

No persisted schema, checkpoint format, lock protocol, publication boundary,
or provider contract changes in this slice.

## Error Handling

Preserve the existing fail-closed behavior for:

- nested squad invocation;
- missing or incompatible runtime/configuration;
- unavailable provider capabilities;
- dirty or missing workspace Git state;
- active execution leases;
- stale or mismatched recovery authority;
- invalid rewind checkpoints;
- destructive operations without confirmation;
- missing specs, runs, targets, artifacts, or user input.

Existing messages and exit codes remain unchanged unless a focused test proves
that the current Typer surface already has a different contract. There is no
fallback from `spec_service` to a removed `cli.py` handler.

## Verification

After commit 1, run focused tests for leaf spec commands, skill dispatch, and
Typer command contracts. After commit 2, run focused Phase A, recovery, phase,
and Typer tests.

Then run:

1. the established CLI regression gate;
2. an import/search guard proving active spec commands and `phase_service` do
   not import `echelon.cli`;
3. the repository verification gate once for the completed slice.

Record exact commands and results in `docs/simplification-control.md`.

## Acceptance Criteria

- Every active `spec` command invokes a typed application-service entry point.
- `cli_app.py` has no `echelon.cli` import inside the active spec command
  family.
- `phase_service.py` does not import `echelon.cli`.
- `cli.py` contains no active spec handler or dead `_cmd_spec` dispatcher.
- Each moved implementation is deleted from `cli.py` in the commit that adds
  its new owner; there is no duplicate transitional implementation.
- Existing Phase A state, locking, checkpoint, publication, console, and exit
  contracts remain unchanged.
- Focused tests, the CLI regression gate, and the full repository gate pass.
- The S3 control sheet records the cutover and verification evidence.

## Explicit Non-Goals

- Decomposing the Phase A controller kernel; that is S5.
- Changing persisted run or decision schemas.
- Changing recovery policy or automatic-decision eligibility.
- Changing publication or checkpoint semantics.
- Refactoring delivery or RE workflows.
- General import-cycle cleanup beyond removing the spec and phase dependency on
  `cli.py`.
