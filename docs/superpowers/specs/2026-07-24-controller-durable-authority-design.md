# Controller Durable Authority Design

## Goal

Make controller state, phase-timing telemetry, and checkpoint preparation
fail closed across process crashes and power loss. A process-visible
`state.json` or `events.jsonl` postimage is not authority until its file and
parent directory have been durably synchronized and its exact identity and
contents have been revalidated.

This design closes three whole-branch review findings:

1. state replacement and ambiguity recovery do not prove directory-entry
   durability before publication, completion effects, or stage deletion;
2. phase-timing telemetry appends can leave a torn JSONL stream and cannot
   distinguish a durable tagged event from a visible ambiguous postimage;
3. checkpoint preparation substitutes an all-zero Git object ID when active
   `HEAD` capture fails.

## Root Causes

### State authority

`SquadStateStore._save_unlocked()` writes and fsyncs a sibling temporary file,
then replaces `state.json`, but does not fsync the squad directory. Its
ambiguity handlers reload the visible file and accept an exact-looking
postimage without proving the replacement is durable. Fresh controllers also
load pending publication and completion markers without a durability gate.
Finalizers delete their stages after observing a visible marker clear.

`SquadStateStore.__init__()` creates the squad and staging directories with
`mkdir(parents=True, exist_ok=True)` and does not synchronize newly created
directories into their parents.

### Phase timing

The phase-timing transaction correctly serializes readers and writers, but
`TelemetryStore.append_event()` appends directly to `events.jsonl`. A short,
torn, or mid-record write can corrupt the only stream. A failure after the
bytes become visible has no exact file-and-directory durability confirmation
before an idempotent completion timing effect is adopted.

### Checkpoint prestate

`SquadController._completion_checkpoint_prestate()` converts a failed
`git rev-parse HEAD^{commit}`, an invalid object ID, and an unborn `HEAD` into
`"0" * 40`. The resulting value passes the checkpoint-prestate schema and lets
route preparation continue with invented authority.

## Chosen Architecture

Use one proof rule across state and phase-timing persistence:

> A replacement is successful only after the complete new file and its parent
> directory are fsynced. An ambiguous visible postimage is adoptable only
> after an exact, under-lock confirmation reopens the file without following
> symlinks, validates its type, identity, and complete contents, fsyncs the
> file and parent, and revalidates identity and contents.

A distinct bounded post-replace durability error prevents generic reload
adoption from converting a failed parent-directory fsync into success during
the same operation. A later fresh controller may establish a new proof, but
until then it performs no diagnostic state write, external effect, or cleanup.

Checkpoint preparation has no ambiguity protocol: when a checkpoint effect is
active, failure to capture one valid 40- or 64-character lowercase Git commit
ID is a bounded preparation failure before state advance.

## State Persistence Contract

### Directory creation

The state store creates missing squad-path components one at a time. For each
new component it:

1. creates the directory;
2. opens it with `O_DIRECTORY | O_NOFOLLOW` where supported;
3. validates that the opened object is the same real directory named by its
   parent;
4. fsyncs the new directory;
5. fsyncs its parent; and
6. revalidates the directory identity.

The same rule applies to the run-local staging directory. Fsync retries only
`EINTR`; every other error fails closed. Existing completion and publication
outboxes continue to durably synchronize their transaction root and parent
before any state marker can reference them.

### Atomic state save

While holding the exclusive state lock, `_save_unlocked()`:

1. derives and validates the exact next revision and state body;
2. creates a sibling temporary file;
3. writes the complete JSON bytes;
4. flushes and fsyncs the temporary file, retrying only `EINTR`;
5. atomically replaces `state.json`;
6. fsyncs the no-follow opened squad directory; and
7. returns the exact saved state.

A failure before replacement leaves the old state authoritative. A failure
while synchronizing the parent after replacement raises a distinct bounded
`StateDurabilityError` whose stage is `post_replace`. Generic ambiguity
handlers must re-raise it and must not adopt its visible postimage in the same
operation.

### Exact durable confirmation

`SquadStateStore.confirm_durable_state(expected)` acquires the exclusive state
lock. Its ordered internal form:

- requires `expected` to be one exact detached state object;
- opens `state.json` using `O_RDONLY | O_NOFOLLOW`;
- requires a regular file and matches its `fstat` identity to `lstat`;
- reads a bounded complete byte stream and decodes one JSON object;
- requires exact equality with `expected`, including revision and all pending
  markers;
- fsyncs the open state file and no-follow opened squad directory, retrying
  only `EINTR`; and
- rechecks path type, device/inode identity, file metadata, complete bytes,
  decoded state, and directory identity before returning a detached copy.

Any mismatch or I/O failure raises a bounded state durability error. The
confirmation path never writes a diagnostic state.

### Ambiguity and recovery gates

The routed-save and exact completion-state ambiguity handlers may adopt a
save-then-raise postimage only through the ordered exact confirmation. They
never adopt a `post_replace` durability failure from `_save_unlocked()`.

Before a fresh controller executes any state-authorized publication or
completion effect, it confirms the exact loaded state. Confirmation failure
returns a pending/blocked outcome without writing state, publishing, applying
an effect, advancing a marker, deleting a stage, or cleaning an orphan.
Repeated failures repeat this fail-closed outcome.

After a publication or completion marker is cleared, stage deletion requires
exact durable confirmation of the clear postimage. If confirmation fails, the
stage remains for a later retry. Cleanup of an unreferenced stage likewise
requires a confirmed state snapshot.

## Power-Loss Model

For initial marker creation or marker replacement:

- If the old state survives, no new marker authority exists. No new effect is
  permitted, and the already durable stage is an inert, safely removable
  orphan after confirmed-state cleanup.
- If the new state survives, the referenced stage was durably sealed before
  the marker save. A fresh controller confirms the exact state and stage
  before replay.

For final marker clear:

- If the old marker state survives, the stage is retained and recovery
  idempotently resumes or verifies the already applied effect.
- If the new clear state survives, deletion is permitted only after exact
  durable confirmation of the clear state.

The tests model both outcomes explicitly instead of assuming which directory
entry survives a failed synchronization.

## Phase-Timing Persistence Contract

The public phase-timing API and event schema remain unchanged. Legacy untagged
events and completion-tagged events keep their current JSON shape and rank
order in the shared `events.jsonl` stream.

Under the existing process lock and file lock, a timing write:

1. reads the exact prior bytes;
2. validates every nonblank JSONL record as one JSON object and validates
   phase-timing records through `PhaseTimingEvent`;
3. rejects malformed JSON, invalid events, and a torn final line without
   truncation or repair;
4. forms new bytes as the exact prior bytes plus one canonical event record
   and newline;
5. writes the complete new bytes to a sibling no-follow exclusive temporary
   file;
6. fsyncs the temporary file;
7. replaces `events.jsonl`;
8. fsyncs the telemetry directory; and
9. returns the event.

Before replacement, failure leaves the exact prior file intact. A
post-replace directory-sync failure raises a distinct bounded telemetry
durability error and is not adopted by that operation.

If a true outer save-then-raise ambiguity occurs after a fully successful
rewrite, the timing operation may adopt the tagged event only after exact
stream durability confirmation. Confirmation no-follow opens the stream,
validates regular-file and path identity, requires exact expected bytes,
fsyncs the file and telemetry directory, and revalidates identity and bytes.
A fresh controller uses the same confirmation before treating an existing
completion-tagged event as an applied effect.

Telemetry-directory and first-file creation follow the same file-and-parent
durability rules. Parent-sync failure leaves the operation failed and a fresh
retry must confirm or rewrite; malformed existing streams remain fail closed.

## Checkpoint Prestate Contract

When `"checkpoint"` is absent from the completion effect plan, the sealed
prestate remains exactly `{"kind": "none"}`.

When `"checkpoint"` is present, the controller must successfully run:

```text
git rev-parse HEAD^{commit}
```

The output must be exactly one lowercase 40- or 64-character hexadecimal
object ID. Command execution failure, nonzero exit, empty output, uppercase or
otherwise invalid output, and an unborn repository all raise a bounded
`StateAdvanceError` with a checkpoint-prestate validator.

This failure occurs before route state advance and before publication or
completion markers become authoritative. The current phase, state revision,
dispatch metadata, artifacts, publication outbox, and completion outbox remain
unchanged.

## Verification

Focused tests must cover:

- initial state creation and replacement with file and parent fsync ordering;
- directory creation synchronization and non-directory/symlink rejection;
- pre-replace and post-replace state failures;
- exact save-then-raise confirmation and rejection of mismatched postimages;
- fresh publication/completion recovery confirmation;
- repeated confirmation failure with no diagnostics, effects, or cleanup;
- final-clear stage retention;
- both old-state and new-state power-loss outcomes;
- telemetry first creation, prior-byte preservation, atomic replacement,
  post-replace failure, exact tagged-event confirmation, fresh retry, and
  malformed/torn-stream rejection;
- checkpoint Git failure, invalid SHA, and unborn `HEAD` with no state,
  artifact, or outbox mutation.

The final gate runs the relevant state, timing, completion, checkpoint, and
controller suites, then the entire Python suite, workflow dry-run, compileall,
and `git diff --check`. No push or merge is part of this work.
