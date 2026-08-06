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
- Keep target mirror and delivery-worktree paths under the target harness root,
  while branch, merge, remote, and implementation operations remain owned by
  the target-specific `GitOpsManager` and target declared by the spec.
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
- Implementing aggregate auto-land for specs with multiple implementation
  targets. Normal `land()` currently requires exactly one declared target;
  multi-target landing needs orchestration after every target converges and is
  a separate design.

## Root Ownership Contract

The production contract has three distinct roots:

- the orchestration workspace owns canonical specs, tasks, run history, and
  lifecycle state;
- the target harness root owns delivery build state, PR URLs, mirrors, and
  delivery worktrees;
- the resolved target checkout and target-scoped `GitOpsManager` own Git
  readiness, merge, branch, and remote operations.

`run_skill.run()` will distinguish two inputs through this backwards-compatible
signature addition:

```python
def run(
    user_message: str,
    provider: Any,
    gitops: Any,
    base_dir: str = ".",
    config: Any = None,
    resume_build_id: str | None = None,
    orchestration_root: str | Path | None = None,
) -> None:
```

- `base_dir`: the existing harness state root associated with the
  target-scoped GitOps instance. In a target run this remains
  `runs/targets/<target>`.
- `orchestration_root`: the workspace that owns `specs/`, orchestration run
  artifacts, and lifecycle status. It defaults to `base_dir` for backwards
  compatibility and single-repository runs.

At entry, a private root-resolution helper resolves both values once without
changing their ownership and validates an explicitly supplied workspace root:

```python
def _resolve_run_roots(
    base_dir: str,
    orchestration_root: str | Path | None,
) -> tuple[Path, Path]:
    """Return (harness_root, workspace_root)."""
```

Invalid explicit context raises a dedicated `RunContextError(ValueError)` so
CLI boundaries can distinguish configuration/root failures from coordinator,
provider, and GitOps failures.

Its result is equivalent to:

```text
harness_root = Path(base_dir).resolve()
workspace_root = (
    Path(orchestration_root).resolve()
    if orchestration_root is not None
    else harness_root
)
```

When `orchestration_root` is explicitly supplied and is not a directory,
`run()` raises `RunContextError("orchestration root is not a directory:
<path>")`
before coordinator construction. It never falls back to `base_dir`. After
intent parsing, an explicit valid root without the selected spec raises
`RunContextError("spec directory for <spec-id> was not found from
orchestration root <path>")`, also before coordinator construction. Spec
lookup, run-history reads/writes, and auto-land use the same resolved
`workspace_root` for the lifetime of the call.

Polyrepo CLI dispatch already resolves both paths. The caller contract is:

| Caller | `base_dir` | `orchestration_root` |
| --- | --- | --- |
| `_cmd_harness_run` | target harness root | existing `spec_search_root` |
| `_cmd_harness_resume` retry/recovery/normal paths | target harness root | existing `spec_search_root` |
| legacy `resume_skill.resume` | supplied base directory | optional new argument, defaulting through `run()` |
| `harness.__main__` standalone entry | current/default base directory | omitted; single-repo default applies |
| direct Python/test callers | existing value | omitted unless modeling a polyrepo |

The delivery coordinator receives both roots through this backwards-compatible
final parameter:

```python
class StrategyCoordinator:
    def __init__(
        self,
        provider: SandboxProvider,
        gitops: Any,
        config: HarnessConfig,
        base_dir: str = ".",
        build_id: str = "",
        orchestration_root: str | Path | None = None,
    ) -> None: ...
```

`base_dir` remains the coordinator state and worktree root. When
`orchestration_root` is supplied, it is authoritative for canonical spec and
task discovery and for the persisted workspace context, even if environment
roots conflict. When omitted, direct legacy coordinator callers retain the
existing `ECHELON_POLYREPO_ROOT`/`ECHELON_WORKSPACE_ROOT` fallback. `run()`
always passes its resolved `workspace_root` explicitly.

That authority also applies when resuming an existing interrupted, running, or
explicitly resumed blocked state. Before Ralph reads the state, the coordinator
refreshes `workspace_root`, `spec_dir`, `spec_file`, `tasks_file`, and the
canonical target-task slice from the current explicit orchestration context.
Iteration counters, token usage, logs, and all other delivery progress remain
owned by and preserved in the target harness state.

The legacy resume adapter receives the matching backwards-compatible signature
addition:

```python
def resume(
    user_message: str,
    provider: Any,
    gitops: Any,
    base_dir: str = ".",
    orchestration_root: str | Path | None = None,
) -> None:
```

It forwards `orchestration_root` unchanged to `run()`. Existing delivery
run/resume CLI paths keep their generic exception boundary and route
`RunContextError` through the current harness-error output and blocked-state
handling. Only the standalone `harness.__main__` and legacy `resume_skill`
adapters add explicit `RunContextError` catches; they print the following
controlled message without a traceback and exit 1:

```text
HARNESS — INVALID ORCHESTRATION CONTEXT
spec          <spec-id>
problem       <RunContextError message>
next step     run delivery from the workspace that owns specs/, or repair the supplied orchestration root
```

Library callers continue receiving the typed exception.

Landing exposes the matching backwards-compatible final parameter:

```python
def land(
    spec_id: str,
    *,
    project_dir: Path,
    gitops: Any,
    state_dir: Optional[Path] = None,
    options: Optional[LandOptions] = None,
    harness_root: Path | None = None,
) -> bool: ...
```

Auto-land calls `land(spec_id, project_dir=workspace_root,
gitops=target_gitops, harness_root=target_harness_root)`. `project_dir` remains
the orchestration workspace used for canonical spec and lifecycle operations;
`harness_root` is used only for PR-state discovery and branchful or branchless
delivery-worktree cleanup. It defaults to `project_dir`, preserving existing
single-repository and direct callers. An explicit `state_dir` continues to
override the PR-state scan only. The target resolved from the spec and the
supplied target GitOps instance continue to own all Git operations. The
target-child `echelon delivery land` adapter passes its resolved harness root.

This matches the existing explicit `echelon delivery land` contract: the
wrapper project locates the spec and declared target, while the supplied
target GitOps instance owns mirror and branch operations.

No environment-variable inference will be added inside `land()`. Callers own
root resolution and pass the result explicitly, keeping the lander usable and
deterministic in tests and non-CLI integrations.

### Review And Re-entry Ownership

Phase 3 keeps the same three owners. `ReviewLoopController.base_dir` is the
target harness root for build-specific review state; the coordinator passes the
already-resolved canonical spec directory through this backwards-compatible
final parameter:

```python
class ReviewLoopController:
    def __init__(
        self,
        gitops: Any,
        config: HarnessConfig,
        spec_id: str,
        strategy_id: str,
        base_dir: str = ".",
        build_id: str = "",
        spec_dir: str | Path | None = None,
    ) -> None: ...
```

The review provider runs from the live target delivery worktree and receives
both its absolute `worktree` and the canonical absolute `spec_dir`. Review seen
state and the skill status file remain under
`<target-harness>/runs/<build-id>/state/`; they are not written to the
orchestration workspace or a shared harness-root file. A missing delivery
worktree is a controlled review failure, never a reason to run an implementation
agent from the harness root. Worktree validation is deferred until blocking
comments require source analysis, so an approved PR with no comments can still
merge after its delivery worktree has already been removed. A timeout, nonzero
skill exit, malformed/missing status, or status other than
`review_fix_queued` fails the review cycle without marking comments seen,
resolving threads, or requesting another review.

Ralph preserves a converged delivery worktree even when convergence happens
before the final outer iteration so Phase 2, Phase 3, and landing can consume
it. The review skill treats that worktree as source context only and never
checks out, switches, or stashes its branch. It writes review artifacts to the
explicit canonical `spec_dir`. Phase 1 re-entry reads sorted
`review-fix-*.md` files directly from that directory; it does not run Git
commands against the target harness root.

### Single-Target Boundary

This auto-land path is supported only when the canonical spec declares exactly
one implementation target, matching `resolve_land_repo()`'s existing contract.
Once correct spec discovery exposes a multi-target spec to `run_skill`, it must
not let independent target workers race to mark the shared spec `landed`.
Instead, auto-land is skipped with an explicit warning that aggregate
multi-target landing is unsupported. Delivery convergence remains recorded;
no target branch or lifecycle status is mutated by that skipped auto-land.

Detection happens after canonical spec resolution and only after convergence
when auto-merge would otherwise run:

```text
targets = read_targets(spec_dir)
if len(targets) > 1:
    skip land()
```

Each independently dispatched target worker emits exactly one warning (the
orchestrator's existing `[target]` prefix identifies its source):

```text
auto-land skipped for spec <spec-id>: aggregate multi-target landing is unsupported (<count> targets)
```

The worker still returns its converged delivery result. Suppressing duplicate
warnings at the parent orchestrator would require a new aggregate result
protocol and is outside this fix.

## Spec Discovery And Diagnostics

`land()` continues to call `find_spec_dir(spec_id, wrapper_project_dir)` and
continues to respect its repository-boundary rule.

When branchless landing is evaluated, diagnostics will separate these cases:

1. `spec_dir is None`: report that the spec directory was not found from the
   supplied orchestration root and include that root in the message. The
   problem text is:

   ```text
   spec directory for <spec-id> was not found from orchestration root <path>
   ```
2. The spec directory exists but frontmatter has no `status`: retain the
   explicit `spec status is (missing), not ready_to_land or landed` message.
3. The status exists but is not landable: report the actual status as today.

This preserves existing lifecycle validation while preventing a path lookup
failure from masquerading as malformed spec metadata.

The new diagnostic is intentionally limited to the branchless completion path
that produced the Prosaic failure. This change does not tighten legacy
branchful landing when no spec directory exists; changing that compatibility
behavior requires separate lifecycle analysis.

## Data Flow

For a target-side polyrepo continuation:

1. The CLI resolves the orchestration workspace and target harness root.
2. The CLI constructs target-scoped GitOps from the target harness root.
3. The CLI calls `run_skill.run(base_dir=target_harness_root,
   orchestration_root=workspace_root)`.
4. Build and verification continue to use target harness state and target
   worktrees.
5. After convergence, auto-land calls `land()` with the workspace root, target
   harness root, and target-scoped GitOps instance.
6. `land()` finds the workspace spec, reads `ready_to_land`, resolves its
   declared target, and performs the existing readiness and landing flow.

For a multi-target spec, step 5 is replaced by the explicit unsupported
warning described above. No target worker calls `land()`.

## Error Handling

- A nonexistent explicit orchestration root is not silently replaced by
  `base_dir`; `run()` fails before coordinator construction.
- A valid explicit orchestration root with no matching spec fails before build
  work with the same spec-directory/search-root facts used by the branchless
  diagnostic.
- A found spec without status remains a lifecycle-data error.
- A non-landable status remains a normal blocked landing.
- Target mirror or branch failures remain GitOps errors and are not converted
  into spec-discovery errors.
- Auto-land continues returning `False` on controlled landing failure so the
  delivery summary remains truthful.
- Multi-target auto-land is skipped explicitly rather than raising
  `land requires exactly one target repo for normal specs` inside each target
  worker.
- CLI entry points render `RunContextError` without a Python traceback and exit
  1; library entry points receive the exception unchanged.

## Tests

### Run Skill

- A single-repository run without `orchestration_root` passes the resolved
  `base_dir` as both `land(project_dir=...)` and `land(harness_root=...)`.
- A polyrepo-style run with distinct roots passes `orchestration_root` to
  both `StrategyCoordinator` and `land()` while constructing coordinator state
  under `base_dir`.
- Explicit coordinator orchestration context controls canonical spec/tasks and
  persisted workspace state with both absent and conflicting environment roots.
- Interrupted and blocked resumes refresh canonical orchestration paths and
  target-task IDs without resetting iteration or token progress.
- The initial run and every resume/continue re-entry path forward the resolved
  orchestration root.
- `resume_skill.resume` forwards an explicit orchestration root when supplied
  and preserves its legacy default when omitted.
- An explicit nonexistent orchestration root fails before coordinator start.
- An explicit valid root without the selected spec fails before coordinator
  start and reports both selector and searched root.
- `_resolve_run_roots()` returns identical roots for a single-repository call
  and distinct normalized roots for a polyrepo call.

### Landing Diagnostics

- Branchless landing with no discoverable spec reports `spec directory not
  found` and the searched root; it does not report a missing status.
- Branchless landing with a discoverable spec lacking `status` reports the
  existing missing-status lifecycle error.
- Branchless landing with `ready_to_land` continues into normal provenance and
  ancestry checks.
- A legacy branchful landing without a discoverable spec retains its existing
  behavior.

### Polyrepo Regression

- Build a temporary workspace shaped like the Prosaic case:
  `workspace/specs/911-*`, `workspace/runs/targets/prosaic`, and a separate
  target repository.
- Converge a mocked target delivery with auto-merge enabled.
- Assert auto-land receives the workspace root, resolves the spec as
  `ready_to_land`, and never emits the `(missing)` status diagnostic.
- Assert coordinator and state paths remain rooted under
  `workspace/runs/targets/prosaic`, proving the fix does not redirect target
  harness state into the orchestration root.
- Put an existing PR and registered worktree under
  `workspace/runs/targets/prosaic/runs/build-*`; assert real `land()` uses
  `merge_pr`, never direct merge, and destroys that worktree after both
  branchful and branchless success.
- Assert a two-target canonical spec does not call `land()` from either target
  worker and that each modeled worker emits the exact aggregate-landing
  unsupported warning once.
- CLI context failures exit 1 without a traceback; direct library calls raise
  `RunContextError`.
- A three-root Phase 3 run passes the target harness and canonical spec roots
  separately, executes the review provider in the target worktree, stores
  review status under the build-specific harness state, and injects canonical
  review-fix content into Phase 1 without Git reads from the harness root.
- Missing review worktrees fail without invoking the provider, and an early
  converged Ralph iteration preserves its registered delivery worktree.

## Live Validation

Automated tests are the acceptance gate for auto-land propagation. The
existing Prosaic workspace cannot safely serve as the first full landing test:
`resolve_land_repo()` selects `sources/prosaic`, whose `package.json` and
`package-lock.json` are dirty. Normal landing operates on that checkout and
must block rather than overwrite or silently stash those changes.

After automated tests pass and the installed CLI is refreshed, perform a
non-mutating Python smoke check using the installed Echelon virtual
environment—not a delivery or land command. The snippet imports and calls
`_resolve_run_roots()`, then passes the returned workspace root to
`find_spec_dir()` and `read_frontmatter()` with these exact inputs:

```text
base_dir = <workspace>/runs/targets/prosaic
orchestration_root = <workspace>
spec selector = 911
```

The smoke check succeeds only when it resolves
`specs/911-new-prosaic-distribution-feature`, reads `ready_to_land`, leaves the
target checkout HEAD and diff byte-for-byte unchanged. It does not claim to
exercise landing diagnostics; the automated branchless-landing tests own the
`(missing)` versus spec-directory-not-found assertions.

Full live landing is a separate, explicitly authorized validation step after
the target checkout is clean. Resolving the existing changes is a user-owned
prerequisite, not part of this fix. The user may preserve them by committing
them or by creating a named stash; Echelon will not choose or perform either
operation implicitly. Before landing, require `git status --porcelain` to be
empty and record:

- the configured target default branch and its remote-tracking commit;
- the verified delivery branch and commit;
- harness mirror default-branch commit;
- orchestration spec status and orchestration repository commit;
- orchestration repository `git status --porcelain` output and binary staged
  and unstaged diffs;
- registered harness worktrees;
- target checkout HEAD;
- target repository `git status --porcelain` output, which must be empty;
- either the preservation commit hash or the named stash reference used for
  the prior dirty changes.

Full landing succeeds only when the configured remote default branch contains
the verified commit, the canonical orchestration spec advances to `landed`,
and the preservation evidence remains valid: a preservation commit is an
ancestor of the landed default branch, or a named stash still resolves to the
same object. A fetch failure caused by the stale legacy `iter-4` worktree is
reported as an independent live-test blocker, not as a regression in root
propagation or diagnostics. Neither stale worktree cleanup nor dirty-checkout
resolution is performed by this fix.

After landing, the target repository must still have empty
`git status --porcelain` output. The orchestration repository may be dirty
because lifecycle persistence is intentionally uncommitted; its post-land
binary diff must equal its captured pre-land diff plus only the expected
`specs/911-new-prosaic-distribution-feature/spec.md` status transition. No
other orchestration path may change during live validation.

`_finish_landing()` retains its current lifecycle persistence semantics:
`write_status()` updates the canonical orchestration `spec.md` frontmatter and
human-readable status to `landed`, but does not commit or push the orchestration
repository. For this fix, “advances to landed” means that the canonical file is
updated on disk and `read_frontmatter()` returns `landed`. Automatic commit or
publication of that lifecycle mutation requires a separate design.

## Documentation

Add a concise changelog entry stating that target-side polyrepo auto-land now
discovers canonical specs from the orchestration workspace rather than the
target harness directory, and that missing-spec discovery is reported
separately from missing lifecycle status. README changes are unnecessary
because command syntax and supported user workflow do not change.
