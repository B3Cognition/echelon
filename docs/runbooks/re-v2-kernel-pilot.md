# RE v2 Kernel Pilot Runbook

## Pilot boundary

RE v2 is an opt-in execution-kernel pilot. The default remains RE v1. The
production v2 registry currently creates and controller-certifies only two
deterministic L0 artifacts for the `inventory` goal:

- source inventory from an immutable source snapshot; and
- partition inventory, bound to the accepted source-inventory object.

This is not a full reverse-engineering outcome. L1-L4 producers, layered reuse,
cross-run checkpoint adoption, semantic audit, workspace synthesis, selective
deepening, and atomic element repair remain EGR-165 through EGR-170. In
particular, the kernel's exact-root publication primitive is generic
infrastructure; this pilot does not register synthesis or expose workspace
synthesis for v2.

## Start a pilot

Run from the workspace root. Shadow mode creates and activates a pinned run,
validates recovery and planning, and explains every L0 decision without
constructing the controller or dispatching work:

```bash
echelon re run --engine v2 --shadow
```

Run the deterministic L0 inventory live with:

```bash
echelon re run --engine v2
```

Both commands capture the source first, then write
`runs/<run-id>/v2/run.json` once. That manifest pins engine `re-v2`, protocol
`2.1`, the source snapshot and partition identities, requested goal, provider
and result contract, artifact policy, and independent initial budgets. A clean
Git worktree is materialized for each declared source repository and published
as one content-addressed, workspace-relative composite snapshot. Orchestration
tooling and Git-ignored dependencies are outside that snapshot. Providers read
the frozen composite path, not the mutable checkouts.

Every declared source must be Git-backed and clean before creation. Staged or
modified tracked files, untracked non-ignored files, uninitialized or divergent
submodules, and non-Git source roots block the command before a run ID is
allocated or `runs/.current-re` is changed. Resolve the diagnostic by doing one
of the following in every reported source, then retry
`echelon re run --engine v2`:

```bash
# Keep the work as a durable source revision.
git add -A && git commit

# Keep it locally without including it in RE; include untracked files.
git stash --include-untracked

# Or deliberately revert tracked changes and remove unwanted untracked files.
git status --short
git restore --staged .
git restore .
# Review untracked paths, then remove only the intended files.
```

Do not clean sources by blindly deleting files. Ignored files such as
`node_modules/` do not make a source dirty and are not captured. A declaration
or commit change requires a new run; continuation always uses the component set
and commits pinned by the existing run.

Existing protocol `2.0` runs remain supported and continue against their
original `git-worktree` or `content-snapshot` bundle. They are not rewritten or
upgraded to protocol `2.1`.

Unless `ECHELON_HOME` is set, snapshots are under
`~/.echelon/re-v2/snapshots/<source-snapshot-id>/`. Do not edit or recapture a
snapshot for an existing run.

## Read authoritative status

Use the active run selected by `runs/.current-re`:

```bash
echelon re status
echelon re status --json
```

The human and JSON views are derived from the same immutable manifest,
hash-chained events, object-backed ledger, budget history, and publication
index. They show the pinned identities, exact required L0 artifact progress,
current and next work, known token usage, unknown-token dispatches, independent
budgets, reason, next action, and an unambiguous final-state banner. Audit and
synthesis display `not registered` in this pilot.

`runs/<run-id>/v2/projection.json` is only a convenience view. Every v2 status
call validates the authoritative records, replays them, and atomically rebuilds
that file without reading its prior contents. To verify byte-identical replay
for the active run:

```bash
run_id="$(tr -d '\n' < runs/.current-re)"
run_dir="runs/$run_id"
echelon re status >/dev/null
cp "$run_dir/v2/projection.json" /tmp/re-v2-projection.before.json
echelon re status >/dev/null
cmp /tmp/re-v2-projection.before.json "$run_dir/v2/projection.json"
```

`cmp` produces no output on an identical replay. Never repair a run by editing
`projection.json`; status will overwrite it from authority. Status fails closed
on a broken manifest, event chain, ledger receipt, referenced object,
publication index, or unsupported goal/provider/result/artifact pin. It does not
inspect source-snapshot or candidate-store bytes; continuation performs those
additional recovery validations before provider or publication side effects.

## Continue or authorize more resources

A normal restart or recovery is:

```bash
echelon re continue
```

Recovery validates the pinned run and snapshot, inspects outstanding leases,
reconciles committed candidates, certifies or rejects them, rebuilds the
projection, and only then plans replacement work. A candidate made durable at
`candidate_renamed` or later is reused after restart and is not redispatched.
An interruption at `dispatch_started` or `provider_terminated`, before a
durable candidate exists, permits one replacement dispatch.

`paused` is continuable. If the status reason is token exhaustion, authorize a
strictly higher total token ceiling and continue the same pinned run:

```bash
echelon re continue --re-token-limit <new-total>
```

For active-time exhaustion, supply a strictly higher total in minutes:

```bash
echelon re continue --re-time-limit-minutes <new-total>
```

Authorization is accepted only for a paused run. It appends an authorization
event and a resume event; it does not rewrite `run.json` or increase provider
attempts, artifact-generation attempts, semantic rounds, or result-contract
retries. `--re-max-inner` is a v1-only coupling and is rejected for v2.

`complete`, `finalized_partial`, and `failed` are terminal. They cannot receive
new resource authorization or resume in place. Changed source, goals, provider
contract, result contract, or artifact policy requires a new run.

## Recovery decisions

- **Compatible restart:** keep the run directory and snapshot bundle intact,
  install an Echelon version supporting the recorded engine/protocol and exact
  provider/result/artifact pins, then run `echelon re status` followed by
  `echelon re continue` when the state is continuable.
- **Missing snapshot:** restore the exact content-addressed snapshot directory
  under `$ECHELON_HOME/re-v2/snapshots/` (or the default path). Do not substitute
  the current checkout, even if it appears unchanged.
- **Corrupt authority:** preserve the run for diagnosis and restore the exact
  manifest, event, ledger, object, or candidate bytes from a trusted copy. Do
  not truncate `events.jsonl`, edit a receipt, or infer authority from
  `projection.json`.
- **Unsupported immutable pins:** use a binary compatible with the recorded
  values. Continuation never upgrades a protocol, goal, provider/result
  contract, or artifact policy.
- **Changed analysis intent:** create another run. EGR-164 has no v1-to-v2 or
  v2-to-v1 migration and no cross-run checkpoint adoption.

## Explicit v1 fallback

Omitting `--engine` retains the existing v1 behavior. It can also be selected
explicitly for a new run:

```bash
echelon re run
echelon re run --engine v1
```

Existing v1 runs continue through their existing controller:

```bash
echelon re continue
```

Fallback means starting or continuing a v1 run, not converting a pinned v2
run. V1 state and artifacts are never treated as v2 authority, and a v1 run
does not invoke the v2 kernel.
