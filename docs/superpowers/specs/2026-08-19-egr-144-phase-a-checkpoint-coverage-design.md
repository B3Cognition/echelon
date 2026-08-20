# EGR-144 Phase A Checkpoint Coverage Design

**Date:** 2026-08-19
**Status:** Revised after engineering review; approved direction retained
**Scope:** Define and enforce operator-visible, Git-backed Phase A checkpoint coverage without making unsupported rewind points appear safe.

## Goal

Close EGR-144 by making checkpoint coverage explicit, deterministic, testable,
and visible. A new `echelon spec run` records an attributed Git checkpoint after
every executed Phase A workflow node whose policy is `checkpoint: required`,
including discovery nodes before `phase1-what`.

The same contract must distinguish:

- an executed node with a recorded checkpoint;
- a conditionally skipped node;
- a node intentionally excluded by policy;
- a legacy completion created before this policy existed;
- a missing required checkpoint; and
- a recorded checkpoint that is or is not certified as a rewind target.

## Non-Goals

This design does not:

- implement `echelon spec rerun`;
- infer checkpoints by scanning arbitrary Git history;
- commit arbitrary `runs/<run>/staging` contents;
- change delivery checkpoint behavior;
- make provider agents responsible for Git operations;
- silently migrate legacy staging artifacts; or
- make every recorded boundary rewindable without an explicit rewind contract.

## Existing Foundation

Fresh Phase A starts reserve a run-local artifact root:

```text
runs/<run-id>/specs/<spec-id>/
```

`state.spec_dir` points to this directory from bootstrap. Completion checkpoint
commits already:

- use a completion identity for crash recovery and idempotency;
- require `HEAD` to match the captured prestate;
- commit only controller-owned paths;
- serialize ledger writes with a spec-local lock;
- run while the controller holds the project-wide Phase A execution lease and
  run-local execution lease; and
- use Echelon commit trailers, including
  `Co-authored-by: Echelon <echelon@b3cognition.dev>`.

Two gaps prevent complete coverage:

1. Early providers write durable artifacts to `staging/`, outside checkpoint
   ownership, until `phase1-what` moves them.
2. The workflow does not declare which nodes require checkpoints, whether a
   completion executed or was skipped, which paths the node owns, or whether
   its checkpoint is rewindable.

## Phase A Scope

Phase A scope is graph-derived, not name-prefix-derived.

The scoped node set is every top-level workflow node reachable from `init`
through `transitions`, including terminal targets. Traversal stops at terminal
nodes. Command-specific graphs such as `bugfix-*` and `build-*`, and standalone
experimental nodes that are not reachable from `init`, are outside this policy.

This rule includes `done`, `terminal-blocked`, and `escalate` without relying on
their spelling. Static validation uses the same helper as runtime coverage.

## Workflow Metadata

Every graph-reachable Phase A node declares:

```yaml
checkpoint: required | none
rewind: supported | none
```

Rules:

- `checkpoint: required` means every executed completion must create one ledger
  row and one attributed Git commit, including an empty commit when no owned
  bytes changed.
- `checkpoint: none` means no checkpoint is expected.
- `rewind: supported` is valid only with `checkpoint: required` and means the
  ledger row may be offered to `echelon spec rewind`.
- `rewind: none` means the boundary is visible but cannot be selected for
  rewind. The ledger row records a stable reason code.
- Missing or invalid values fail workflow validation. Runtime code never
  defaults an unknown node to `required`.

Initial policy:

```text
checkpoint: required, rewind: supported
  phase1-discover
  phase1-synthesizer
  phase1-modeler
  phase1-tracker
  phase1-why1
  phase1-constitution
  phase1-what
  phase1-understanding
  phase1-why2
  phase1-investigate
  phase1-lexicon-derive
  phase1-lexicon
  phase2-decide
  phase2-feasibility-structural
  phase2-strategic-overview
  phase2-tracker-alignment
  phase2-intent-alignment-structural
  phase3-specialists
  phase3-how
  phase3-sentinel
  phase3-plan
  phase3-tasks-lexicon
  phase3-understanding
  phase3-consensus
  phase3-consensus-tasks-lexicon
  phase4-document

checkpoint: none, rewind: none
  init
  checkpoint-assess
  checkpoint-plan
  done
  terminal-blocked
  escalate
```

Conditionally skipped required nodes keep this declared policy but produce no
commit and no ledger row for that completion.

## Policy Versioning

New runs persist:

```json
"checkpoint_policy_version": 2
```

Version 2 means:

- durable early artifacts belong in `state.spec_dir`;
- completion outcomes are recorded;
- required checkpoint enforcement is active; and
- rewind eligibility is ledger-backed.

Runs without this field are legacy version 1 runs. They are never subjected to
version 2 missing-checkpoint enforcement until explicitly migrated.

## Durable Completion Outcomes

`completed_phases` is insufficient because it contains conditionally skipped
nodes and only stores distinct phase names. Version 2 state adds an append-only
controller-owned list:

```json
"phase_completion_outcomes": [
  {
    "completion_id": "<controller completion id>",
    "phase": "phase1-modeler",
    "next_phase": "phase1-tracker",
    "outcome": "executed",
    "checkpoint": "required"
  },
  {
    "completion_id": "<controller completion id>",
    "phase": "phase1-investigate",
    "next_phase": "phase1-what",
    "outcome": "skipped",
    "checkpoint": "required"
  }
]
```

Allowed outcomes are `executed` and `skipped`. The record is written in the
same state transition that authorizes controller completion. Completion ID is
unique and makes replay idempotent. Coverage joins ledger rows to executed
outcomes by completion ID, not only by phase name, so loops and repeated phases
remain distinguishable.

## Artifact Ownership

`state.spec_dir` is the durable root for normal Phase A provider and
deterministic outputs from run bootstrap onward.

Early provider outputs move from prompt-level `staging/` ownership to
`{spec_dir}` ownership:

- discovery and synthesis artifacts;
- `mental-model-code.md` and `codebase-graph.md`;
- `user-intent.md` and `stakeholder-model.md`; and
- WHY1 updates to assumptions and unknowns.

`staging/` remains reserved for control-plane and transient material:

- `user-clarifications.md`;
- escalation request and response artifacts;
- gate response material;
- transient provider dispatch material; and
- quarantined malformed outputs.

Some durable Phase A artifacts live outside `spec_dir`. Workflow policy does
not accept arbitrary path strings from YAML. A controller-owned phase-path
resolver returns a narrow allowlist:

```python
checkpoint_owned_paths(phase, state) -> tuple[Path, ...]
```

Initial exceptional ownership:

- `phase1-constitution`: `.echelon/constitution.md`;
- `phase4-document`: the already supported published spec directory and
  accepted knowledge-base target paths.

The constitution path is included in the checkpoint commit, so the
`phase1-constitution` recovery point restores the artifact it represents.
Checkpoint ledger files, locks, receipts, staging, and state files remain
excluded from commits.

## Controller Behavior

For an executed version 2 node with `checkpoint: required`:

1. Resolve `state.spec_dir` and validate that it is a real directory inside the
   project root.
2. Resolve the phase-owned path allowlist.
3. Prepare the completion with a captured Git `HEAD` prestate.
4. Persist the executed completion outcome and pending completion authority.
5. Apply normal completion effects.
6. Create or recover the completion checkpoint using the completion ID.
7. Force an empty attributed commit only when owned paths have no changes.
8. Record the ledger row, including checkpoint and rewind policy.
9. Finish the controller completion before dispatching the next node.

For a skipped node, persist `outcome: skipped`, omit the checkpoint effect, and
advance without a commit.

For `checkpoint: none`, persist the completion outcome when applicable but omit
the checkpoint effect.

Missing required targets fail closed with:

```text
phase_checkpoint_target_missing: <phase>
```

Other checkpoint failures use:

```text
phase_checkpoint_failed: <phase>: <detail>
```

Failure persistence must use the existing pending-controller-completion failure
path. Helpers must not directly overwrite an authorized state transition with
an ad hoc `terminal-blocked` save.

## Commit Attribution

Every automatic or migration commit uses `build_echelon_commit_message()` and
must contain all of:

```text
Co-authored-by: Echelon <echelon@b3cognition.dev>
Echelon-Origin: phase-a
Echelon-Action: checkpoint
Echelon-Spec: <spec-id>
Echelon-Run: <run-id>
Echelon-Phase: <phase-id>
Echelon-Checkpoint: <checkpoint-id>
Echelon-Completion: <completion-id>
Echelon-Checkpoint-Source: auto | user-committed | legacy-migration
```

Tests assert the co-author trailer as well as machine-readable Echelon fields.

## Ledger And Rewind Contract

Checkpoint ledger rows add:

```json
{
  "rewind": "supported",
  "rewind_reason": "",
  "boundary_completion_id": "<executed controller completion id>"
}
```

For `rewind: none`, `rewind_reason` is a stable non-empty reason code. Ledger
loading remains backward compatible: legacy rows are treated as supported
because EGR-145 already exposed them as rewind targets.

Automatic rows use their own `completion_id` as `boundary_completion_id`.
Manual rows created by `accept` or `commit` bind to the latest executed outcome
for the requested phase. Rewind state pruning uses `boundary_completion_id`, so
a manually moved checkpoint retains the original phase boundary while pointing
Git recovery at the operator-selected commit.

## Manual Artifact Adjustment

The existing commands remain distinct:

- `echelon spec checkpoint accept --phase <phase>` creates no Git commit. It
  requires a clean worktree and moves the phase's latest rewind target to the
  current user-created commit by appending a `user-accepted` ledger row bound to
  the latest executed completion for that phase.
- `echelon spec checkpoint commit --phase <phase>` commits owned spec changes
  with full Echelon attribution and appends a `user-committed` row bound to the
  latest executed completion for that phase.

Both commands reject version 2 phases with no executed outcome to bind. They do
not satisfy a missing automatic completion row in strict coverage; the original
automatic row remains the proof that the controller checkpointed the boundary.

`echelon spec rewind` remains ledger-driven but offers only rows whose effective
rewind value is `supported`. Version 2 rewind tests must prove whole-commit
reset and state pruning for every newly supported policy class:

- early artifact producer;
- deterministic gate;
- conditional branch producer;
- repeated phase with multiple completion IDs;
- constitution with its additional owned path; and
- final publication checkpoint.

For version 2 state, completed-phase pruning is derived from
`phase_completion_outcomes` and ledger order. It does not synthesize completion
from the linear `_ROADMAP_PHASES` backbone. Legacy runs retain the current
fallback behavior.

If any policy class cannot satisfy those tests, its workflow declaration must
be changed to `rewind: none` before release. Checkpoint coverage and rewind
certification are related but not conflated.

## Legacy Migration

Legacy runs remain runnable under version 1 behavior. Coverage reports their
early completed nodes as `legacy-untracked`, not `missing`, and `--strict` does
not fail on those rows.

An explicit command promotes a legacy run:

```text
echelon spec checkpoint migrate [--spec <run-or-spec-id>] [--confirm]
```

Preview mode lists the exact allowlisted files that would be copied from the
run's `staging/` directory into `spec_dir`. It rejects symlinks, directories,
path collisions with different bytes, dirty owned paths, and an active
controller lease. Unknown regular files are listed as ignored and are never
copied.

Confirmed migration:

1. acquires the Phase A execution lease and run execution lease;
2. re-resolves the same run and spec after locking;
3. seals a run-local migration intent containing source hashes, destination
   preimages, captured `HEAD`, and a completion ID;
4. copies only known early durable artifact names, preserving staging originals;
5. creates or recovers one attributed migration commit and ledger row with
   `source: legacy-migration` and `rewind: none`;
6. writes `checkpoint_policy_version: 2` and reconstructs explicit legacy
   completion outcomes from `completed_phases` as `outcome: executed` with a
   `legacy: true` marker;
7. marks the migration intent complete; and
8. leaves pre-migration phases visible as `legacy-migrated`, not as fabricated
   per-node checkpoints.

The command never claims that historical node boundaries existed when they did
not. After migration, only future executed required nodes are enforced.
Before the commit exists, failure restores destination preimages and leaves
version 1 state authoritative. After the commit exists, retry recovers it by
completion identity and finishes the state transition without creating another
commit.

## Operator UX

`echelon spec checkpoint list` always renders both the ledger and coverage,
including when the ledger is empty:

```text
CHECKPOINTS - spec 001-simple-notes - run spec-20260819-101500-123456

(none)

COVERAGE
COMPLETION  PHASE                STATUS             REWIND
...a12      phase1-discover      recorded           yes
...b34      phase1-modeler       skipped            -
...c56      phase1-tracker       missing            -
legacy      phase1-why1          legacy-untracked    legacy
```

Status values:

- `recorded`
- `missing`
- `skipped`
- `not-checkpointed`
- `legacy-untracked`
- `legacy-migrated`

`--strict` exits `2` only for version 2 executed outcomes whose policy is
required and whose completion ID has no ledger row.

`--spec` resolves an exact `SpecRun` using existing lifecycle resolution. An
ambiguous numeric spec prefix reports all matching run IDs and requires the
operator to choose one. Coverage never scans Git history and never borrows
state from another run with the same spec ID.

Checkpoint rows display rewind eligibility. `echelon spec rewind` rejects a
recorded but unsupported row with its ledger reason and lists supported rows.

## Concurrency Contract

Automatic completion checkpointing is valid only while the controller holds:

1. `PhaseAExecutionLock` for the project checkout;
2. `SpecRunExecutionLock` for the run; and
3. the existing completion and checkpoint locks in rank order.

The project lease serializes agents sharing one checkout. Separate Git
worktrees have independent `HEAD`, runtime locks, and run state. External Git
mutation in the same checkout remains a fail-closed checkpoint prestate error.

Tests verify that a second controller or migration command cannot enter while
the lease is held and that no checkpoint commit is attempted after lease
acquisition fails.

## Test Strategy

Tests require no LLM, Docker, or network access.

Required coverage:

- graph-derived Phase A scope and explicit policy validation;
- workflow parsing without runtime fallback defaults;
- new-run policy version bootstrap;
- early prompt output contracts and legacy-compatible input handling;
- executed versus skipped completion outcomes, including replay;
- required target failure through pending-completion recovery;
- phase-specific owned paths, especially constitution;
- changed and no-change attributed commits;
- co-author and machine-readable trailers on every Echelon commit path touched;
- empty-ledger coverage output;
- exact run resolution and ambiguity handling;
- legacy preview, rejection, confirmed migration, and post-migration resume;
- strict coverage using completion IDs across repeated phases;
- rewind filtering and representative whole-commit rewind certification;
- project/run lease exclusion; and
- a synthetic controller-driven Phase A path using fake provider results and a
  real temporary Git repository.

The focused suite must pass with zero failures. Broad-suite failures may be
reported only when the same failure is reproduced on the pre-change baseline.

## Open Follow-Ups

- EGR-146 defines explicit rerun semantics. Rewind restores a recorded boundary;
  rerun remains a separate operation.
- Delivery may adopt the same outcome and coverage model only after Phase A is
  stable; EGR-144 does not change delivery.
