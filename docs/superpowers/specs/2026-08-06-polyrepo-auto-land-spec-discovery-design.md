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
- Give Phase 1 verification and end-to-end delivery convergence distinct,
  durable meanings so Phase 3 cannot leave a failed delivery recorded as
  converged.
- Represent Phase 2 visual validation and crash recovery explicitly rather
  than treating them as implicit extensions of Phase 1.
- Let a safely scoped review provider produce canonical review outputs through
  validated build-scoped staging without granting it direct canonical writes.
- Preserve current behavior for single-repository delivery runs.
- Add regression coverage for the observed Prosaic failure path.

## Non-Goals

- Cleaning the stale `harness/911/default/iter-4` worktree.
- Resolving or discarding the dirty Prosaic authoring checkout.
- Changing fulfillment, branch-selection, or merge semantics outside the
  delivery-state clarification defined below.
- Making `find_spec_dir()` cross Git boundaries.
- Changing PR-tool discovery or degraded no-PR behavior.
- Implementing aggregate auto-land for specs with multiple implementation
  targets. Normal `land()` currently requires exactly one declared target;
  multi-target landing needs orchestration after every target converges and is
  a separate design.
- Designing a provider-neutral capability compiler for review triage. This
  change supports the review-triage profile on Claude only; Prosaic/provider
  capability negotiation is a follow-up design.

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
skill exit, malformed/missing output manifest, or manifest status other than
`review_fix_queued` or `no_blocking_comments` fails the review cycle without
marking comments seen, resolving threads, or requesting another review.

Ralph preserves a verified delivery worktree even when verification happens
before the final outer iteration so Phase 2, Phase 3, and landing can consume
it. The review skill treats that worktree as source context only and never
checks out, switches, or stashes its branch. It writes proposed review outputs
to build-scoped staging; the controller validates and publishes them to the
explicit canonical `spec_dir`. Phase 1 re-entry reads only the published,
sorted `review-fix-*.md` files from that directory; it does not run Git commands
against the target harness root.

### Delivery State Semantics

`converged` is the terminal end-to-end delivery status. Phase controllers do
not return it. New durable delivery states have these meanings:

| Status | Owner | Meaning |
| --- | --- | --- |
| `running` | coordinator / Phase 1 | Implementation or review-fix work is executing. |
| `verified` | coordinator boundary | Phase 1 passed required non-visual verification; enabled downstream phases may remain. |
| `validating` | coordinator / Phase 2 | Visual validation is executing against the verified worktree. |
| `reviewing` | coordinator / Phase 3 | The verified and, when enabled, visually validated implementation is undergoing PR review or merge. |
| `finalizing` | coordinator | All enabled execution phases passed; single-target provenance/lifecycle writes or target-local multi-target completion are being persisted. |
| `blocked` | coordinator | A recoverable phase failure occurred; `blocked_phase` is exactly `implementation`, `visual`, `review`, or `finalization`. |
| `converged` | coordinator | Every enabled delivery phase completed successfully. This state is terminal. |
| `interrupted` | coordinator | Execution stopped externally and may resume through the phase recorded in `interrupted_phase`. |
| `failed` | coordinator | An irrecoverable invariant or persisted-state corruption was detected. This state is terminal. |
| `cancelled_by_coordinator` | coordinator | The parent coordinator intentionally cancelled this strategy. This state is terminal. |

The enabled-phase graph determines the next state. Skipped phases do not get a
synthetic state:

```text
Phase 2 off, Phase 3 off: running -> verified -> finalizing -> converged
Phase 2 on,  Phase 3 off: running -> verified -> validating -> finalizing -> converged
Phase 2 off, Phase 3 on:  running -> verified -> reviewing -> finalizing -> converged
Phase 2 on,  Phase 3 on:  running -> verified -> validating -> reviewing -> finalizing -> converged
```

At run creation the coordinator persists an immutable `enabled_phases` list.
Phase 1 is always present. Phase 2 is included only when visual tests are
configured and Phase 1 uses the sandbox path that exposes its worktree to
`VisualRalphController`; the existing LLM-managed Phase 1 path records Phase 2
as skipped. Phase 3 is included only when review-loop configuration is enabled
and a PR host is configured. Continuation uses this persisted list even if the
ambient config later changes. Starting a new delivery is required to adopt a
different phase plan. If Phase 3 is enabled but Phase 1 produces no PR URL, the
coordinator blocks Phase 3 with `termination_reason: missing_pr_url`; it does
not silently treat review as complete.

The state machine admits these transitions:

```text
running    -> verified | blocked | interrupted | failed | cancelled_by_coordinator
verified   -> validating | reviewing | finalizing | blocked
validating -> running | reviewing | finalizing | blocked | interrupted | failed | cancelled_by_coordinator
reviewing  -> running | finalizing | blocked | interrupted | failed | cancelled_by_coordinator
finalizing -> converged | blocked
blocked    -> running     when blocked_phase == implementation
blocked    -> validating  when blocked_phase == visual
blocked    -> reviewing   when blocked_phase == review
blocked    -> finalizing  when blocked_phase == finalization
interrupted -> running | validating | reviewing | finalizing
               according to interrupted_phase
```

`validating -> running` occurs only when Phase 2 applied a source fix. Every
such fix invalidates the earlier Phase 1 evidence, so Phase 1 must verify the
new commit before visual validation resumes. A visual pass that made no
unverified source change proceeds directly to Phase 3 or convergence.

Phase and delivery results use separate types and vocabularies:

```text
ImplementationResult: verified | blocked | interrupted | failed | cancelled
VisualResult:          passed | fix_applied | blocked
ReviewResult:          completed | review_fix_queued | blocked
DeliveryResult:        converged | blocked | interrupted | failed | cancelled
```

`ReviewResult(completed)` means the configured Phase 3 approval, merge, and
thread-resolution criteria all succeeded. `no_blocking_comments` is only a
triage-manifest status inside Phase 3 and is not itself proof that Phase 3
completed.

The existing `LoopResult` is replaced at its boundaries rather than extended
with both phase-local and delivery-wide statuses. `RalphController`,
`VisualRalphController`, and `ReviewLoopController` return their phase-specific
types. `StrategyCoordinator` is the only component that constructs a
`DeliveryResult` and persists delivery status. This prevents a value such as
`verified` or `passed` from being mistaken for overall completion.

`RalphController` returns `ImplementationResult(verified)` after final
implementation verification. It does not persist `converged` or advance the
canonical spec to `ready_to_land`. The coordinator records `verified`, chooses
the next enabled phase, and records `converged` only after the last enabled
phase succeeds.

Phase 2 runtime/setup failure, exhausted visual attempts, or missing verified
worktree persists `blocked_phase: visual`. Phase 3 timeout, missing worktree,
provider failure, invalid output manifest, exhausted review loop, or failed
merge persists `blocked_phase: review`. Phase 1 retains
`blocked_phase: implementation`. Provenance or lifecycle persistence failure
uses `blocked_phase: finalization`. Each block also persists a stable
`termination_reason`, the last completed phase, active commit, strategy, build
id, and any active PR URL before returning. `failed` is reserved for an
irrecoverable invariant or state-corruption error; ordinary phase exhaustion,
missing prerequisites, provider failures, and Git/remote failures are
recoverable `blocked` outcomes.

### Restart And Continue Rules

Every nonterminal state is a durable checkpoint. `echelon delivery continue`
uses the persisted state and never guesses a phase from files alone:

- `running`: use the existing Phase 1 resume path.
- `verified`: verify that the recorded commit and registered worktree still
  exist, then enter the first enabled incomplete downstream phase. Do not rerun
  Phase 1 merely because the process stopped at this boundary.
- `validating`: discard incomplete Phase 2 runtime/container state and retry
  visual validation from its first check against the recorded verified commit.
- `reviewing`: reuse the persisted PR URL, seen-comment IDs, canonical spec
  directory, and registered worktree, then retry the current review/merge
  cycle. Remote polling and merge checks must remain idempotent.
- `finalizing`: verify any already-written provenance and lifecycle values,
  reject conflicting values, and perform only the incomplete finalization
  write before recording convergence.
- `blocked`: transition only to the state selected by `blocked_phase` in the
  transition table above.
- `interrupted`: transition to the state selected by `interrupted_phase` and
  apply that state's restart rule.
- `converged`: report the completed delivery and perform no phase work.

If a checkpoint prerequisite is missing or differs from the recorded commit,
continuation persists `blocked` for that same phase with a precise reason. It
does not fall back to another root, silently create a worktree, or restart
Phase 1. When Phase 3 returns `review_fix_queued`, the coordinator transitions
to `running`, executes only the newly verified task IDs, and requires a fresh
Phase 1 `verified` result. When Phase 2 returns `fix_applied`, the same
re-verification rule applies.

There is no `converged -> blocked` transition. Existing persisted `converged`
states are completed legacy deliveries and are never retroactively reopened.

The delivery state schema version increments once for these fields and states.
On the first continuation of a legacy nonterminal record without
`enabled_phases`, the coordinator snapshots the current configuration into the
new immutable phase list and persists it before executing work. A legacy
`blocked` record without `blocked_phase` maps to `implementation`; the harness
cannot safely infer that it had entered a newer review phase. Legacy
`interrupted` records map to their recorded implementation resume path. Legacy
`failed`, `cancelled_by_coordinator`, and `converged` records remain terminal.
There is no compatibility alias for the internal `LoopResult`: all in-repo
callers move to the phase-specific or delivery result type in the same change.

### Convergence, Lifecycle, And Landing Boundary

Delivery convergence and landing are separate outcomes:

1. The last enabled delivery phase succeeds.
2. The coordinator persists `finalizing`. For a single-target spec, it
   idempotently records the verified
   commit, then advances the canonical lifecycle to `ready_to_land`.
3. Only after both writes succeed does it persist delivery `converged`. A crash
   between these writes leaves a nonterminal checkpoint; continuation verifies
   matching existing data and repeats only the incomplete write.
4. If auto-land is enabled, it runs as a post-convergence action. Successful
   landing advances lifecycle state to `landed`; failed landing leaves delivery
   state `converged` and lifecycle state `ready_to_land`.

The command result reports delivery and landing independently. A failed
auto-land is therefore not represented by reopening delivery state. It returns
a non-successful landing outcome with the next step `echelon delivery land
<spec-id>`, while `echelon delivery continue` remains a no-op for the already
converged delivery.

For a spec with multiple implementation targets, no target worker may mutate
the shared lifecycle state. Each worker may persist its target-local
`converged` result, but the canonical spec remains unchanged and auto-land is
skipped with the aggregate-landing warning. A future parent-level aggregate
coordinator must prove that every declared target converged before advancing
`ready_to_land`; that protocol is outside this change. This explicit exception
removes the race between independent target workers and the single-target
lifecycle rule above.

### Safe Review Provider Scope

This change deliberately implements review-triage permissions for Claude only.
The provider request carries the named intent:

```text
execution_profile: review_triage_v1
```

This name is a dispatch seam, not a claim that permissions are already
provider-neutral. `AICodingCliProvider` rejects the profile before subprocess
launch unless the selected backend is Claude. The controlled error identifies
the configured provider and says that `review_triage_v1` currently requires
Claude. There is no fallback to an unscoped invocation, Codex `--add-dir`, or
unsafe host execution. A generic Prosaic capability model is deferred.

`ReviewLoopController` already fetched and filtered the blocking comments. It
serializes that normalized list into the resolved review prompt, including
comment IDs, reviewer, body, path, line, and timestamp. The review skill uses
only this supplied list; it no longer runs `gh`, `glab`, or any other network
command. The provider therefore needs neither Bash nor network access.

The provider executes with the delivery worktree as its working directory.
Before invocation, the controller resolves the canonical `spec_dir` and the
build-specific review status file. It creates a unique attempt directory under
`<target-harness>/runs/<build-id>/state/review-staging/`, then, while holding
the canonical review-artifact lock described below, computes the first unused
numeric suffix and a bounded set of possible artifact names for the current
comment batch. It passes request metadata with:

```text
execution_profile: review_triage_v1
tool_read_roots:
  - <delivery-worktree>
  - <canonical-spec-dir>
tool_write_paths:
  - <attempt-dir>/tasks-append.md
  - <attempt-dir>/review-fix-<next>...<next+comment-count-1>.md
  - <target-harness>/runs/<build-id>/state/<strategy>-review-status.json
```

The possible review-fix range is bounded by the number of input comments;
there cannot be more diagnosed groups than comments. The provider can read the
canonical spec but cannot write it. No orchestration workspace root, canonical
spec directory, target harness root, or staging directory is granted wholesale.

The Claude backend compiles `review_triage_v1` into a dedicated hard-coded
profile:

- use Claude `--bare`, load no user, project, or local settings, and load no
  MCP servers;
- disable slash commands and ambient plugins/hooks;
- expose only `Read`, `Write`, `Edit`, and `Agent`;
- apply exact absolute `Read(...)`, `Write(...)`, and `Edit(...)` allow rules
  from the metadata above;
- explicitly load the debugger, sentinel, and spec-guard agent definitions
  supplied by the harness through Claude's `--agents` input;
- restrict each supplied diagnostic agent to `Read` and restrict commander
  `Agent(...)` calls to those three exact agent names;
- deny Bash, web/network tools, background agents, and every permission-bypass
  flag.

The existing generic file-scope path cannot be reused unchanged because its
`--safe-mode` setting disables custom agents and its `--tools Read,Write,Edit`
list omits `Agent`. The new profile owns its complete Claude argument list so
later changes to generic prompt scoping cannot accidentally broaden or disable
review triage. The implementation must include a CLI-level test proving the
constructed command contains the three explicit agents and no Bash or unsafe
permission flag.

### Review Artifact Allocation And Proof

The status file is a proposal manifest, not proof by itself. The controller acquires an
exclusive lock at `<canonical-spec-dir>/.echelon-review.lock` before choosing
artifact numbers and holds it through provider completion and output
validation and canonical publication. Lock contention produces a recoverable
review block; it never chooses another suffix concurrently. Stale-lock handling
uses the same PID and process-liveness rules as `StateStore`.

Under the lock, the controller scans only names matching
`review-fix-<positive-integer>.md`, chooses `next = max(existing, default=0) +
1`, records the pre-invocation existence and digest of canonical `tasks.md`,
and confirms that every candidate from `next` through `next + comment_count -
1` is absent. It also parses the canonical `T-<n>` task rows, allocates the
next `comment_count * 3` task numbers, and supplies both bounded ranges in the
prompt. Each diagnosed group consumes the next artifact number and exactly
three task numbers; skipped groups leave only an unused tail, never an internal
gap. It creates a fresh attempt directory and never reuses one from a prior
call. Any collision found before launch is recalculated under the same lock;
any unexpected canonical change at validation or publication time blocks the
cycle rather than overwriting it.

When tasks are produced, the provider must write this schema to the exact
build-specific status path:

```json
{
  "status": "review_fix_queued",
  "groups": 2,
  "artifacts": ["review-fix-7.md", "review-fix-8.md"],
  "tasks": [
    {"task_id": "T-143", "review_task_id": "RF7-T1", "artifact": "review-fix-7.md"},
    {"task_id": "T-144", "review_task_id": "RF7-T2", "artifact": "review-fix-7.md"},
    {"task_id": "T-145", "review_task_id": "RF7-T3", "artifact": "review-fix-7.md"},
    {"task_id": "T-146", "review_task_id": "RF8-T1", "artifact": "review-fix-8.md"},
    {"task_id": "T-147", "review_task_id": "RF8-T2", "artifact": "review-fix-8.md"},
    {"task_id": "T-148", "review_task_id": "RF8-T3", "artifact": "review-fix-8.md"}
  ],
  "tasks_append": "tasks-append.md"
}
```

`status` is `review_fix_queued` exactly when `groups > 0`. Success then requires
all of the following:

- `groups`, artifact count, and the distinct numeric suffixes agree;
- every artifact is a nonempty regular file in the fresh attempt directory and
  allocated candidate set;
- each artifact maps to exactly three task entries; canonical `task_id` values
  and `review_task_id` labels are unique, consume contiguous prefixes of their
  allocated ranges, and agree with the artifact suffix;
- every task entry appears as one canonical task row in `tasks-append.md`, and
  every row in that file corresponds to exactly one manifest entry;
- `tasks-append.md` is a nonempty regular file containing only those new task
  rows and their required detail lines, not a replacement copy of canonical
  `tasks.md`; and
- the status file is a regular file with the expected schema and no unknown
  output paths.

For `groups == 0`, `status` is `no_blocking_comments`, `artifacts` and
`tasks` must be empty, `tasks_append` must be absent, and the attempt
directory must contain no review output. The review loop may then continue
polling or merge; it does not re-enter Phase 1.

After staged validation succeeds for `groups > 0`, the controller writes a
build-scoped publication journal containing the canonical pre-state digests,
allocated names, staged digests, and both task identifier forms. While still holding the lock, it
publishes each artifact with a temp-file-and-rename in the canonical spec
directory, then atomically replaces `tasks.md` with its exact prior bytes plus
the validated append payload. It validates the canonical digests and task IDs
before marking the journal complete and returning `review_fix_queued`. Phase 1
cannot observe queued work until the journal is complete.

If the process stops during publication, continuation acquires the same lock,
loads the journal, accepts already-published files only when their digests
match, and completes the remaining writes. A conflicting canonical digest
blocks review without overwriting user data. Invalid staged output changes no
canonical file and is retained in its attempt directory for diagnosis; a retry
uses a new attempt ID. The lock is always released. Provider exit code zero
without a valid manifest, valid staged evidence, and a completed publication
journal is failure.

### Single-Target Boundary

This auto-land path is supported only when the canonical spec declares exactly
one implementation target, matching `resolve_land_repo()`'s existing contract.
Once correct spec discovery exposes a multi-target spec to `run_skill`, it must
not let independent target workers race to mark the shared spec `landed`.
Instead, auto-land is skipped with an explicit warning that aggregate
multi-target landing is unsupported. Delivery convergence remains recorded;
no target branch or lifecycle status is mutated by that skipped auto-land.

Detection happens after canonical spec resolution during finalization, and is
checked again before post-convergence auto-land would otherwise run:

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
4. Phase 1, enabled visual validation, and enabled review use target harness
   state and the registered target worktree. The coordinator checkpoints each
   phase using the delivery state machine above.
5. For a single target, the coordinator records verified provenance, advances
   the canonical spec to `ready_to_land`, and then records `converged`.
6. As a separate post-convergence action, auto-land calls `land()` with the
   workspace root, target harness root, and target-scoped GitOps instance.
7. `land()` finds the workspace spec, reads `ready_to_land`, resolves its
   declared target, and performs the existing readiness and landing flow.

For a multi-target spec, step 5 records only target-local convergence without
changing canonical lifecycle state, and step 6 is replaced by the explicit
unsupported warning described above. No target worker calls `land()`.

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
- Phase 3 failures persist `blocked` with `blocked_phase: review`; they never
  leave the durable overall status at `converged` or require a fresh delivery
  run for recovery.
- Phase 2 failures persist `blocked` with `blocked_phase: visual`; visual fixes
  re-enter Phase 1 before their evidence can be accepted.
- A successful provider exit without a valid output manifest and matching
  artifact/task evidence is a blocked Phase 3 result.
- Selecting `review_triage_v1` with any backend other than Claude fails closed
  before provider launch and persists a recoverable review block.
- Auto-land failure after convergence does not reopen the delivery. It leaves
  the canonical spec `ready_to_land` and reports landing failure separately.
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

### Delivery State

- Phase 1 returns `ImplementationResult(verified)`; only the coordinator
  persists the `verified` delivery checkpoint.
- Each combination of enabled/disabled visual and review phases follows the
  four explicit normal paths in the state graph.
- `enabled_phases` is snapshotted once; changing ambient visual/review config
  before continuation does not alter the persisted phase plan.
- The coordinator persists `validating` before Phase 2, `reviewing` before
  Phase 3, and `finalizing` before provenance/lifecycle writes; it persists
  `converged` only after the last enabled phase and both single-target writes
  succeed.
- `VisualResult(fix_applied)` and `ReviewResult(review_fix_queued)` both
  transition to `running` and require a new Phase 1 verification before their
  respective phase is retried.
- Every Phase 2 failure persists `blocked_phase: visual`; `delivery continue`
  retries Phase 2 from the recorded verified commit when prerequisites match.
- Every Phase 3 failure path persists `blocked`, `blocked_phase: review`, and a
  recoverable reason; `delivery continue` retries Phase 3 without Phase 1 when
  no review-fix tasks exist.
- An enabled review phase without a Phase 1 PR URL blocks with
  `missing_pr_url`; it is never treated as a skipped or successful review.
- Restart tests cover `verified`, `validating`, `reviewing`, and `finalizing`,
  including a missing or mismatched recorded worktree/commit that blocks the
  same phase without falling back to Phase 1.
- Single-target convergence writes `ready_to_land` before `converged`; a crash
  between the idempotent writes resumes only the incomplete write.
- Auto-land failure leaves delivery `converged` and lifecycle
  `ready_to_land`, reports a separate landing failure, and makes `delivery
  continue` a no-op.
- Multi-target workers never write canonical lifecycle state even when their
  target-local delivery converges.
- Legacy persisted `converged` states remain terminal and readable.
- Legacy nonterminal state migration snapshots `enabled_phases` once, maps an
  unqualified block to `implementation`, and never reinterprets a terminal
  legacy state.

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
- The controller embeds its already-fetched normalized comments in the review
  prompt; the skill never invokes `gh`, `glab`, Bash, or a network tool.
- The provider request selects `review_triage_v1`, grants the delivery worktree
  and canonical spec as read roots, plus only staged `tasks-append.md`, the
  bounded staged review-fix candidates, and the build-specific status file as
  write outputs. It grants no canonical write path.
- Claude command construction uses `--bare`, explicit exact-file rules, and
  exactly the debugger, sentinel, and spec-guard agent definitions. It contains
  no Bash, ambient MCP, background-agent, or permission-bypass capability.
- Codex and every non-Claude backend reject `review_triage_v1` before launching
  a subprocess; no provider silently drops or broadens the profile.
- Concurrent artifact-allocation tests prove the canonical lock prevents two
  review cycles from choosing the same suffix and that stale locks follow
  `StateStore` PID-liveness behavior.
- A zero-group `no_blocking_comments` manifest changes no canonical artifact.
  A queued manifest is accepted only when every staged artifact, append payload,
  and task ID matches the manifest and allocated range.
- Publication-journal crash tests stop after each canonical write, then prove
  continuation completes matching partial publication without duplicating
  tasks or overwriting conflicting files.
- Provider success with a missing artifact, unexpected path, colliding suffix,
  duplicate/missing task ID, replacement-style task content, or malformed
  manifest changes no canonical file, produces a recoverable review block, and
  leaves comments unseen.
- Missing review worktrees fail without invoking the provider, persist a
  recoverable review block, and an early verified Ralph iteration preserves
  its registered delivery worktree.

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
