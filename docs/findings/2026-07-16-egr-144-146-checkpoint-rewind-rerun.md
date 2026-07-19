# EGR-144..146 Phase Checkpoint, Rewind, And Rerun Semantics

**Review date:** 2026-07-16
**Status:** open
**Source incident:** OptaSearch `001-vision-dashboards`

## Summary

The OptaSearch estimate-regeneration question exposed three separate Phase A
operability gaps:

1. Echelon records checkpoints for only some phases, without an obvious
   operator-facing policy explaining why those phases are checkpointed and
   others are not.
2. `echelon spec rewind` validates against a hardcoded safe phase list before
   checking the actual checkpoint ledger, so it can reject checkpointed phases
   and accept phase names that are not checkpointed for the current spec.
3. There is no supported `echelon spec rerun` operation for regenerating a
   specific artifact-producing phase such as `phase2-decide`.

These should be tracked separately because they have different design and safety
boundaries.

## Evidence

Workspace:

- `/Users/michalbachorik/work/optasearch`

Run:

- `runs/spec-20260713-125624-949435`
- Current state: `status=done`, `phase=done`

Completed phases in `state.json`:

- `init`
- `phase1-constitution`
- `phase1-what`
- `phase1-discover`
- `phase1-synthesizer`
- `phase1-modeler`
- `phase1-tracker`
- `phase1-why1`
- `phase1-why2`
- `checkpoint-assess`
- `phase2-decide`
- `phase2-strategic-overview`
- `phase2-tracker-alignment`
- `phase4-document`
- `phase3-specialists`
- `phase3-how`
- `phase3-sentinel`
- `phase3-plan`
- `phase3-consensus`
- `checkpoint-plan`

Checkpoint ledger:

- `specs/001-vision-dashboards/.echelon/checkpoints.json`

Checkpointed phases:

- `phase1-what`
- `phase1-why2`
- `phase1-constitution`
- `phase1-discover`
- `phase2-decide`
- `phase3-specialists`
- `phase4-document`

CLI behavior:

- `echelon spec rewind --help` advertises only:
  - `phase3-how`
  - `phase3-sentinel`
  - `phase3-plan`
- `echelon spec rewind phase3-plan` failed for this spec because no
  `phase3-plan` checkpoint exists.
- `phase2-decide` has a checkpoint, but the CLI rejects it before using the
  checkpoint ledger because it is not in the hardcoded safe rewind list.

Operational impact:

- `estimates.md` is produced by `phase2-decide` and refined by
  `phase3-consensus`, but there is no safe public command to regenerate it for
  this completed run.

## EGR-144: Investigate And Define Phase Checkpoint Coverage Policy

**Priority:** P2

### Finding

Phase A checkpoints are created for a subset of phases, but the policy is not
obvious from the operator surface. In the OptaSearch run, phases that clearly
produced durable artifacts, such as `phase3-how`, `phase3-sentinel`,
`phase3-plan`, `phase3-consensus`, and `checkpoint-plan`, appear in
`completed_phases` but not in the checkpoint ledger.

### Why It Matters

Operators cannot reason about recovery or rerun options when checkpoint coverage
is implicit. Missing checkpoints also prevent targeted repair of downstream
artifacts when a late quality issue is discovered.

### Required Work

- Document the intended checkpoint policy:
  - all phases,
  - only publication boundaries,
  - only phases with stable artifact sets,
  - or another explicit rule.
- Compare the implemented checkpoint writer against that policy.
- Decide whether artifact-producing phases such as `phase2-decide`,
  `phase3-how`, `phase3-sentinel`, `phase3-plan`, and `phase3-consensus` must
  all produce checkpoints.
- Add deterministic tests proving expected checkpoint coverage for a normal
  Phase A run.
- Expose checkpoint coverage in `echelon spec status` or `checkpoint list` so
  operators can see what recovery/rerun points exist.

### Candidate Files

- `src/harness/squad.py`
- `src/harness/squad_state.py`
- `src/echelon/checkpoint_cli.py`
- `src/echelon/cli.py`
- `extension/workflow/definition.yaml`
- `tests/integration/test_squad_controller.py`
- `tests/unit/test_cli_continue.py`

## EGR-145: Make `echelon spec rewind` Validate Against Actual Checkpoints

**Priority:** P1

### Finding

`echelon spec rewind` currently uses a hardcoded safe phase list:

- `phase3-how`
- `phase3-sentinel`
- `phase3-plan`

This list is not reconciled with the actual checkpoint ledger. In OptaSearch,
`phase3-plan` is accepted by the CLI surface but then fails because no checkpoint
exists; `phase2-decide` exists as a checkpoint but is rejected because it is not
in the hardcoded list.

### Why It Matters

Rewind must be grounded in actual recovery points for the current spec. A static
allowlist creates confusing behavior and blocks valid recovery paths while
advertising invalid ones.

### Required Work

- Make rewind target validation ledger-driven.
- The command must accept only checkpoint IDs/phases that exist for the active
  spec, unless an explicit future mode supports state-only rewind without a
  checkpoint.
- The help/status output should show available rewind targets for the active
  run/spec, not only a global hardcoded list.
- If a checkpoint is present but semantically unsafe, the ledger or checkpoint
  metadata should say why.
- Add tests for:
  - checkpointed phase accepted,
  - uncheckpointed phase rejected before state mutation,
  - hardcoded safe phase not offered when absent from ledger,
  - checkpointed `phase2-decide` behavior is either supported or rejected with
    a precise documented reason.

### Candidate Files

- `src/echelon/cli.py`
- `src/echelon/rewind.py`
- `src/echelon/checkpoint_cli.py`
- `tests/unit/test_cli_continue.py`
- new focused rewind tests under `tests/unit/`

### Resolution (2026-07-18)

Fixed. The active run's `spec_dir/.echelon/checkpoints.json` is now the sole
rewind-target authority. `echelon spec rewind <checkpoint-phase-or-id>` resolves
that ledger before any branch or state mutation, reports its available entries
for an unknown target, and no longer has a static Phase 3 allowlist. The same
ledger gates automatic retry-to-rewind guidance. On confirmed rewind, Git resets
to the selected checkpoint and state retains only phases recorded before that
ledger entry. Real-Git coverage exercises `phase1-what` preview and confirmation;
focused lifecycle/checkpoint/rewind verification passed 276 tests without an
LLM, Docker, or network access. Checkpoint coverage policy remains EGR-144, and
explicit phase rerun remains EGR-146.

## EGR-146: Define And Implement `echelon spec rerun` Phase Semantics

**Priority:** P1

### Finding

There is no supported command to rerun a specific Phase A phase, even when the
phase is the known producer of a flawed artifact. The estimate incident needs a
safe way to regenerate `phase2-decide` or re-run `phase3-consensus` without
manual state/git surgery.

### Design Question

Should `echelon spec rerun` be able to rerun any workflow phase, or only phases
with checkpoints?

Recommended design direction:

- Default to checkpoint-backed reruns only.
- Allow rerun from an actual checkpoint and then re-execute the selected phase
  plus required downstream phases according to `workflow/definition.yaml`.
- Do not rerun arbitrary phases without a checkpoint unless a later explicit
  expert/unsafe mode defines cleanup, dependency, and provenance semantics.

### Required Work

- Add a documented `echelon spec rerun <phase-id>` or equivalent command.
- Define whether the phase ID names:
  - the phase to restore before,
  - the phase to execute,
  - or the first downstream phase to invalidate.
- Compute downstream invalidation from the workflow graph, not a hardcoded list.
- Clean or mark stale outputs from downstream phases before rerun.
- Preserve run history and write artifact provenance explaining that artifacts
  were regenerated.
- Add dry-run mode showing:
  - checkpoint used,
  - artifacts that will be invalidated,
  - phases that will rerun,
  - publication/checkpoint behavior.
- Add tests for estimate regeneration:
  - rerun `phase2-decide` from checkpoint,
  - rerun downstream consensus after estimate changes,
  - reject rerun when no checkpoint exists,
  - no stale published artifact survives without provenance.

### Candidate Files

- `src/echelon/cli.py`
- `src/echelon/rewind.py`
- new `src/echelon/rerun.py` or similar
- `src/harness/phase_graph.py`
- `src/harness/squad.py`
- `src/harness/squad_state.py`
- `extension/workflow/definition.yaml`
- tests under `tests/unit/` and `tests/integration/`
