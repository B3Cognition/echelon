# Destructive Spec Retarget Design

**Status:** Approved
**Date:** 2026-08-04
**Decision owners:** Echelon maintainers

## Summary

Add a first-class `echelon spec retarget` lifecycle for an existing Phase A
spec whose implementation targets were declared incorrectly. Retargeting keeps
the existing spec identity and original product request, but deliberately
invalidates the current Phase A result and rebuilds it from the workflow entry
phase with a replacement target set.

Retargeting is destructive. Before any invalidation, Echelon creates a mandatory
Git-backed checkpoint and prints the exact rewind command. After invalidation,
the spec is not buildable until the replacement Phase A run and its MemPalace
and graph finalization all succeed. The only supported rollback is rewinding to
the pre-retarget checkpoint.

## Goals

- Replace the complete implementation-target set of an unimplemented spec.
- Preserve the spec ID, feature branch, original prompt, product inputs, and
  durable Phase A history.
- Rebuild requirements, architecture, planning, test strategy, tasks, and
  documentation with the new target contract.
- Preserve the old result in Git and make the old-to-new diff easy to inspect.
- Remove stale spec-owned MemPalace drawers before the replacement run can use
  retrieval.
- Invalidate and later rebuild the persisted spec and workspace artifact graphs.
- Recover the exact pre-retarget result through the existing checkpoint rewind
  surface.

## Non-goals

- Retargeting a spec after Phase B delivery has started.
- Editing one target while implicitly retaining or inferring the others.
- Keeping the old canonical spec buildable while the replacement is generated.
- Treating old generated artifacts as authoritative inputs to the replacement.
- Re-running workspace-scoped reverse engineering solely because an
  implementation target changed.
- Mutating target repositories, pushing branches, or opening pull requests.

## Command Surface

```bash
# Preview target replacement and destructive effects.
echelon spec retarget <spec-id> \
  --target <source-id-or-path> \
  [--target <source-id-or-path> ...]

# Create the checkpoint, invalidate the current result, and start Phase A.
echelon spec retarget <spec-id> \
  --target <source-id-or-path> \
  [--target <source-id-or-path> ...] \
  --confirm
```

`--target` is repeatable and expresses the complete replacement set. The
command uses the same source-ID/path resolution rules as `echelon spec run`.
Duplicate resolved targets collapse in declaration order. An empty replacement
set and a replacement set equal to the current set are rejected.

The preview performs every read-only preflight and prints:

- the selected spec and original Phase A run;
- the old and resolved replacement target sets;
- whether the current result is Phase A incomplete or ready to build;
- the artifacts, memory domains, and graphs that confirmation will invalidate;
- the prospective checkpoint label and recovery command;
- a conspicuous statement that confirmation makes the spec non-buildable.

`--init` is not part of the first version. Missing targets must be prepared
before retargeting so the destructive command cannot mix repository creation
with lifecycle recovery.

## Eligibility Boundary

The operator-facing boundary is "ready to build or earlier." In the current
implementation, `ready_to_build` is derived rather than stored: the Phase A run
is terminal `done` and the canonical build-input readiness check succeeds.
Retarget eligibility therefore uses deterministic evidence, not a new spelling
in `state.json`.

A spec is eligible only when all of the following hold:

1. One canonical `specs/<id>/` directory resolves.
2. One latest Phase A run for that exact spec resolves and contains its original
   `user_message`, autonomy mode, implementation targets, and spec identity.
3. The run is not actively executing and all Phase A lifecycle locks can be
   acquired.
4. No Phase B entry exists in `run-history.json` or
   `harness-run-history.json`.
5. No delivery/build state matching the spec exists under `runs/build-*` or
   another canonical harness-state location.
6. The canonical lifecycle is not `in-progress`, `implemented`,
   `ready_to_land`, or `landed`.
7. The selected spec-owned paths are clean. Unrelated dirty paths do not block
   the operation and are never staged.
8. The original product-input contract and any selected published RE context
   can be reconstructed without consulting dirty target worktrees.

Any positive evidence that Phase B started rejects retargeting, even if delivery
failed before completing a task. Ambiguous or corrupt lifecycle evidence also
rejects the command. Rejection instructs the operator to start a new spec run
with the correct targets.

## Lifecycle and State Machine

Retargeting has a deterministic controller-owned state machine:

```text
previewed
  -> checkpointed
  -> invalidating
  -> rebuilding
  -> finalizing
  -> complete

checkpointed | invalidating | rebuilding | finalizing
  -> blocked
  -> recovered (only through checkpoint rewind)
```

The active Phase A state gains a bounded `retarget` object containing the
revision, operation ID, baseline run ID, replacement run ID, old/new targets,
checkpoint ID and commit, current stage, and last failure code. While this
object is active and not `complete` or `recovered`, readiness and delivery
preflight must reject the spec.

A separate runtime transaction record lives outside the resettable canonical
spec tree. It contains the minimum recovery projection of the baseline
`state.json`, operation receipts, and the canonical ledger path. This record
lets checkpoint rewind restore the prior controller state after Git moves the
branch back. It contains no prompt body or copied product evidence.

## Original Intent and Replacement Run

The original request is recovered from the latest Phase A run named by the
canonical run history. The command does not ask an LLM to infer a prompt from
`spec.md`. If the exact run or `user_message` cannot be recovered, retargeting
is rejected and a new spec run is required.

The replacement run preserves:

- canonical spec ID and feature branch;
- exact original `user_message`;
- autonomy mode;
- immutable product-input declarations and snapshots;
- explicitly selected published RE context and ignore-RE policy;
- project constitution and workspace configuration.

It replaces only `implementation_targets` and receives a new run ID. The
controller enters the normal Phase A graph at its entry phase, not at
`phase3-plan`. This ensures target-sensitive discovery, requirements,
architecture, specialist, test, planning, consensus, and documentation work is
re-evaluated.

## Pre-retarget Checkpoint and Destructive Boundary

Confirmation acquires the Phase A, spec-run, checkpoint, and retarget operation
locks in their established order. It then creates a mandatory checkpoint before
any canonical artifact or external memory mutation.

The checkpoint:

- has source `retarget-preflight` and a unique checkpoint ID;
- records the current spec branch commit;
- includes a `retarget-history.json` entry in `prepared` state;
- binds the original and replacement target sets and original run ID;
- captures hashes of the current target contract and generated artifacts;
- stores the recovery projection in the runtime transaction record.

Immediately after checkpoint creation, the CLI prints the exact recovery
command:

```bash
echelon spec rewind checkpoint:<checkpoint-id> --confirm
```

No destructive step runs if the checkpoint cannot be created and resolved back
from the ledger.

The destructive boundary begins only after successful checkpoint verification.
From that point onward, every failure persists `retarget.status: blocked`, the
failed stage, and the same recovery command. Delivery remains disabled.

## Artifact Invalidation

The invalidation step writes the complete replacement `targets.yml` and removes
the old generated Phase A result from both canonical and active run-shadow
locations. It preserves only lifecycle and immutable input material needed to
rebuild or recover:

- `retarget-history.json`;
- `run-history.json`;
- checkpoint runtime metadata;
- `inputs.yml` and immutable `inputs/` snapshots;
- promoted amendment input history;
- controller-owned recovery receipts.

Generated requirements, requirements overviews, architecture, research, data
models, contracts, specialist outputs, test strategy, coverage, plans, task
files, prioritization, risk/dependency files, completion reports, memory audit
reports, and persisted graph artifacts are invalidated. The exact inventory is
owned by a deterministic artifact-policy function and is included in preview
output and tests; it is not maintained as a second ad-hoc CLI list.

The replacement run receives checkpoint copies of the old generated artifacts
under its run-local context directory. Prompts label that directory
`NON-AUTHORITATIVE RETARGET COVERAGE CONTEXT`. Agents may use it to remember
covered product concerns, but must derive every new canonical decision from the
original request, immutable inputs, current workspace evidence, and replacement
targets. The old files are never copied back into `specs/<id>/`.

## Retarget History and Change Control

`specs/<id>/retarget-history.json` is a controller-owned append-only ledger.
Each revision records:

- revision and operation ID;
- status and timestamps;
- baseline and replacement Phase A run IDs;
- old and replacement targets;
- original prompt digest, not duplicate prompt content;
- checkpoint ID and commit;
- baseline artifact path/hash inventory;
- MemPalace cleanup and replacement-audit receipts;
- spec/workspace graph invalidation and rebuild receipts;
- replacement completion commit or recovery commit;
- bounded failure code and recovery outcome.

`run-history.json` retains both Phase A completions. The replacement entry adds
`retarget_revision`, `supersedes_run_id`, and `baseline_checkpoint` fields. The
normal history schema is extended for these optional Phase A fields.

On successful completion, the CLI prints:

```bash
git diff <checkpoint-commit>..<replacement-commit> -- specs/<spec-id>
```

This Git comparison is the authoritative old-to-new artifact diff. The retarget
ledger supplies lifecycle and external-state receipts that Git cannot capture.

## MemPalace Invalidation and Refresh

Retarget must not allow the replacement agents to retrieve canonical
requirements or plans spoiled by the old target contract.

After checkpoint creation and before canonical artifact deletion, Echelon runs
a spec-owned purge. The purge deletes only drawers whose metadata proves exact
ownership by the selected spec:

- canonical or canonical-support artifacts under `specs/<id>/`; or
- spec-scoped evidence whose exact `spec_id` is `<id>`.

It never deletes workspace-scoped RE drawers, immutable input source material,
another spec's drawers, or rows with ambiguous ownership. The purge uses a
complete bounded scan with truncation detection. Ambiguous ownership,
unsupported complete scanning, or a configured but unavailable MemPalace blocks
retargeting before canonical artifact invalidation. A workspace with no
configured MemPalace records `not_applicable` and proceeds.

The cleanup receipt records counts and drawer IDs/digests, never deleted
documents. The active replacement state also carries a memory-exclusion marker
so retrieval context assembly refuses old spec-owned memory until replacement
finalization succeeds.

After the replacement Phase A gates and publication succeed, finalization:

1. mines the new canonical requirements and supporting artifacts;
2. deletes any remaining stale deterministic drawers;
3. audits exact canonical memory and retrieval identity;
4. writes the new memory mine/audit receipts;
5. clears the memory-exclusion marker only after an acceptable audit.

When MemPalace is configured, a failed or unavailable replacement audit blocks
`ready_to_build`. Recovery re-mines and audits the checkpoint artifacts before
restoring the baseline readiness state.

## Spec and Workspace Graph Handling

At invalidation, Echelon removes `spec-artifact-graph.json` and its audit report
for the selected spec. It then rebuilds the persisted workspace graph from the
remaining current member graphs, so consumers cannot traverse stale
requirements, tasks, targets, or memory receipts for the retargeting spec.

After replacement memory is current, finalization:

1. builds and writes the replacement spec graph from canonical artifacts;
2. audits its source-set and memory receipts;
3. refreshes the workspace graph using the exact persisted member graph bytes;
4. audits and writes workspace graph receipts;
5. records all graph hashes and statuses in retarget history.

Graph or workspace-graph finalization failure blocks readiness. Checkpoint
recovery performs the same memory-first ordering for the restored artifacts,
then rebuilds the restored spec and workspace graphs before marking recovery
complete.

## Completion Gate

Normal Phase A artifact readiness is necessary but insufficient for an active
retarget revision. The spec becomes ready to build only when:

- all normal Phase A readiness checks pass;
- `targets.yml` equals the replacement target set;
- every canonical task declares exactly one replacement target;
- replacement memory is `pass` or `warn`, or explicitly `not_applicable`;
- spec graph audit is `pass` or `warn`;
- workspace graph audit is `pass` or `warn`;
- retarget history contains matching finalization receipts; and
- `retarget.status` is `complete`.

The completion transition is idempotent. A crash between individual external
refresh operations can resume finalization without creating a second revision
or losing the baseline checkpoint.

## Checkpoint Recovery

`echelon spec rewind` recognizes a checkpoint whose source is
`retarget-preflight`. Its normal Git rewind still creates a backup reference,
resets the active spec branch, and retains the ledger through the target entry.
The retarget recovery extension then:

1. restores the baseline controller-state projection;
2. purges replacement spec-owned memory;
3. mines and audits memory from the restored checkpoint artifacts;
4. rebuilds and audits the restored spec graph;
5. refreshes and audits the workspace graph;
6. marks the canonical retarget revision `recovered`;
7. clears the active retarget block; and
8. restores the baseline Phase A status, including `ready_to_build` when that
   was the checkpoint state.

If recovery finalization fails, the spec remains blocked rather than claiming
the old result is ready. Re-running the same rewind/finalization path is safe.

## Error Handling

Operator-facing failures use stable reason codes and always include the recovery
command after the destructive boundary. Principal failures include:

- `retarget_delivery_already_started`;
- `retarget_original_intent_missing`;
- `retarget_target_set_unchanged`;
- `retarget_checkpoint_failed`;
- `retarget_memory_purge_failed`;
- `retarget_artifact_invalidation_failed`;
- `retarget_rebuild_blocked`;
- `retarget_memory_refresh_failed`;
- `retarget_graph_refresh_failed`;
- `retarget_recovery_refresh_failed`.

No failure automatically creates a new spec, edits target repositories, or
silently restores old artifacts.

## Concurrency and Filesystem Safety

- A per-spec retarget lock prevents concurrent retarget, amendment, rewind, or
  delivery preparation for the same spec.
- Existing Phase A execution, spec-run execution, and checkpoint locks remain
  authoritative and follow the controller lock order.
- All state and ledger writes use atomic replacement and durable fsync patterns
  already used by squad state and checkpoints.
- Git commits stage only the selected spec directory and explicitly owned
  lifecycle files.
- Unrelated dirty files are preserved. Dirty selected-spec files block the
  operation before checkpoint creation.
- Symlinked or non-regular control files are rejected.
- Repeated `--confirm` after a crash resumes the recorded operation instead of
  creating another revision.

## Testing Strategy

Unit tests cover target parsing/resolution, lifecycle classification, original
intent recovery, artifact inventory, history transitions, memory ownership and
purge refusal, graph invalidation/finalization, readiness blocking, and special
checkpoint recovery.

CLI tests prove preview is read-only, confirmation requires a checkpoint,
delivery-started specs are rejected, the complete target set is replaced, and
every destructive failure prints the exact recovery command.

Integration tests exercise:

1. a ready-to-build single-target spec retargeted to another target;
2. an interrupted pre-ready Phase A spec retargeted to multiple targets;
3. a failure after invalidation followed by checkpoint recovery;
4. stale MemPalace drawers removed before replacement dispatch;
5. old spec/workspace graph edges disappearing during rebuild;
6. replacement memory and graphs becoming current before readiness;
7. any Phase B evidence rejecting retarget;
8. idempotent continuation after a finalization crash; and
9. preservation of unrelated dirty workspace files.

Contract tests update CLI help, state/history schemas, lifecycle documentation,
and installed command surfaces. Focused tests run before the wider unit,
kernel, integration, and dry-run wiring suites.

## Documentation

The README and workspace model document:

- when retarget is allowed;
- why it is destructive;
- preview and confirmation syntax;
- the mandatory checkpoint and recovery command;
- MemPalace and graph consequences;
- the old-to-new Git diff command; and
- the requirement to create a new spec after delivery starts.
