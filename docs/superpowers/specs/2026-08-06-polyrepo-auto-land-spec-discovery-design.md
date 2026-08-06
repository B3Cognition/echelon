# Polyrepo Auto-Land Spec Discovery Design

## Context

Delivery of spec `911-new-prosaic-distribution-feature` converged successfully:
all 123 requirements were verified, the delivery branch was pushed, and the
verified branch was merged into the harness mirror. The subsequent auto-land
step nevertheless returned `False` with:

```text
problem  spec status is (missing), not ready_to_land or landed
```

The spec was not missing and its frontmatter contained
`status: ready_to_land`. The target-side delivery used
`runs/targets/prosaic` as the harness `base_dir`. `run_skill.run()` passed that
directory to `land()` as its `project_dir`. `land()` therefore searched for
`specs/911-*` from the target harness directory. `find_spec_dir()` correctly
refused to cross the orchestration repository's Git boundary, so the lookup
returned `None` and the branchless landing diagnostic incorrectly described
the result as a missing status.

This is a root-ownership defect: the target harness state root, orchestration
spec root, and implementation repository are distinct paths in a polyrepo run.
They must not be represented by one overloaded `base_dir` value.

## Goals

- Make target-side auto-land discover lifecycle state from the orchestration
  workspace that owns `specs/`.
- Keep target mirror, worktree, branch, and implementation operations owned by
  the target-specific `GitOpsManager` and the target declared by the spec.
- Preserve the Git-boundary safety behavior of `find_spec_dir()`.
- Distinguish "spec directory not found" from "spec found without a status"
  in branchless landing diagnostics.
- Preserve current behavior for single-repository delivery runs.
- Add regression coverage for the observed Prosaic failure path.

## Non-Goals

- Cleaning the stale `harness/911/default/iter-4` worktree.
- Resolving or discarding the dirty Prosaic authoring checkout.
- Changing fulfillment, convergence, branch-selection, or merge semantics.
- Making `find_spec_dir()` cross Git boundaries.
- Changing PR-tool discovery or degraded no-PR behavior.

## Root Ownership Contract

`run_skill.run()` will distinguish two inputs:

- `base_dir`: the existing harness state and target GitOps root. In a target
  run this remains `runs/targets/<target>`.
- `orchestration_root`: the workspace that owns `specs/`, orchestration run
  artifacts, and lifecycle status. It defaults to `base_dir` for backwards
  compatibility and single-repository runs.

Polyrepo CLI dispatch already resolves both paths. Every CLI path that calls
`run_skill.run()` for run, resume, or continue will pass the resolved workspace
root explicitly as `orchestration_root`. The delivery coordinator and harness
state continue using `base_dir`; spec history discovery and auto-land use
`orchestration_root`.

Auto-land will call:

```text
land(spec_id, project_dir=orchestration_root, gitops=target_gitops)
```

This matches the existing explicit `echelon delivery land` contract: the
wrapper project locates the spec and declared target, while the supplied
target GitOps instance owns mirror and branch operations.

No environment-variable inference will be added inside `land()`. Callers own
root resolution and pass the result explicitly, keeping the lander usable and
deterministic in tests and non-CLI integrations.

## Spec Discovery And Diagnostics

`land()` continues to call `find_spec_dir(spec_id, wrapper_project_dir)` and
continues to respect its repository-boundary rule.

When branchless landing is evaluated, diagnostics will separate these cases:

1. `spec_dir is None`: report that the spec directory was not found from the
   supplied orchestration root and include that root in the message.
2. The spec directory exists but frontmatter has no `status`: retain the
   explicit `spec status is (missing), not ready_to_land or landed` message.
3. The status exists but is not landable: report the actual status as today.

This preserves existing lifecycle validation while preventing a path lookup
failure from masquerading as malformed spec metadata.

## Data Flow

For a target-side polyrepo continuation:

1. The CLI resolves the orchestration workspace and target harness root.
2. The CLI constructs target-scoped GitOps from the target harness root.
3. The CLI calls `run_skill.run(base_dir=target_harness_root,
   orchestration_root=workspace_root)`.
4. Build and verification continue to use target harness state and target
   worktrees.
5. After convergence, auto-land calls `land()` with the workspace root and the
   target-scoped GitOps instance.
6. `land()` finds the workspace spec, reads `ready_to_land`, resolves its
   declared target, and performs the existing readiness and landing flow.

## Error Handling

- A nonexistent explicit orchestration root is not silently replaced by
  `base_dir`; spec discovery fails with the new root-specific diagnostic.
- A found spec without status remains a lifecycle-data error.
- A non-landable status remains a normal blocked landing.
- Target mirror or branch failures remain GitOps errors and are not converted
  into spec-discovery errors.
- Auto-land continues returning `False` on controlled landing failure so the
  delivery summary remains truthful.

## Tests

### Run Skill

- A single-repository run without `orchestration_root` still passes `base_dir`
  to `land()`.
- A polyrepo-style run with distinct roots passes `orchestration_root` to
  `land()` while constructing coordinator state under `base_dir`.
- Resume and continue CLI paths forward the resolved orchestration root.

### Landing Diagnostics

- Branchless landing with no discoverable spec reports `spec directory not
  found` and the searched root; it does not report a missing status.
- Branchless landing with a discoverable spec lacking `status` reports the
  existing missing-status lifecycle error.
- Branchless landing with `ready_to_land` continues into normal provenance and
  ancestry checks.

### Polyrepo Regression

- Build a temporary workspace shaped like the Prosaic case:
  `workspace/specs/911-*`, `workspace/runs/targets/prosaic`, and a separate
  target repository.
- Converge a mocked target delivery with auto-merge enabled.
- Assert auto-land receives the workspace root, resolves the spec as
  `ready_to_land`, and never emits the `(missing)` status diagnostic.

## Live Validation

After automated tests pass, use the existing Prosaic spec 911 state as a live
validation case. Before running it, record the target default branch, verified
branch, mirror main, spec status, registered worktrees, and dirty local
checkout. The live action is expected to mutate lifecycle state by completing
landing. Success requires:

- the lander reads `ready_to_land` from the orchestration spec;
- the verified commit is present in the landed default-branch history;
- the spec advances to `landed`;
- the dirty local checkout is not overwritten;
- no `(missing)` status diagnostic appears.

The stale legacy worktree and skipped dirty-checkout synchronization are
reported separately and are not success criteria for this focused fix.

