# First-Class Reverse-Engineering Lifecycle Design

**Date:** 2026-07-16
**Status:** Approved
**Related finding:** EGR-149 tracks the mid-term shared lifecycle-control refactor.

## Problem

`echelon spec run` currently owns two distinct jobs:

1. Author a feature specification.
2. Plan, execute, repair, and publish workspace reverse engineering before
   feature discovery.

The second job is unusually expensive. A fresh brownfield spec run fingerprints
the workspace, materializes run-local RE state, and routes GOLDDIGGER before
SCOUT. Changed sources can trigger the complete RE extraction and validation
pipeline, including bounded repair loops and publication. Feature authoring is
therefore coupled to a workspace-understanding lifecycle that has a different
freshness policy, cost profile, failure model, and publication boundary.

Once a validated RE generation has been published, feature runs normally need
only its documents as read-only context. Re-extraction is useful only when an
operator knows or suspects that the source or extraction profile has changed.

## Decision

Make reverse engineering a first-class sibling lifecycle:

```text
echelon re run
echelon re continue
echelon re resume
```

The RE lifecycle owns freshness planning, extraction, repair, validation, and
automatic complete publication. The spec lifecycle never executes RE. By
default it snapshots the latest published RE generation as read-only context;
`echelon spec run --ignore-re` opts out.

Spec, RE, and delivery retain independent controllers and state stores. They
share the same user-facing run/continue/resume interaction model, but this
change does not introduce a generic lifecycle framework. EGR-149 tracks that
mid-term refactor after all three concrete lifecycles have stabilized.

## Goals

- Remove RE agent cost and RE failure modes from ordinary spec authoring.
- Give RE its own durable, resumable, operator-controlled lifecycle.
- Preserve the existing deterministic RE planner, controller, validation, lock,
  publication, and quality-debt behavior.
- Make the default `changed` policy a zero-agent no-op when the published
  generation is current.
- Automatically publish a structurally and semantically complete RE result.
- Keep partial or invalid output run-local until explicitly repaired or
  manually published under the existing override contract.
- Let spec runs consume one stable published RE generation by default.
- Keep spec, RE, and delivery current-run pointers independent.

## Non-Goals

- Do not redesign the RE extraction phases or agent protocols.
- Do not merge the spec, RE, and delivery controllers in this change.
- Do not make `spec run` determine whether published RE is fresh.
- Do not automatically publish partial RE output.
- Do not revive target-scoped RE policies. RE remains workspace-scoped.
- Do not add a new RE status command in this slice; the requested control
  surface is run/continue/resume.

## Public CLI Contract

### RE lifecycle

```text
echelon re run [--re-policy none|cached-only|changed|refresh-all]
               [--re-max-inner N] [--reset]

echelon re continue [--re-max-inner N]

echelon re resume "<answer>" [--re-max-inner N]
```

Policy behavior:

- `changed` is the default. It refreshes new or changed workspace sources and
  reuses current published sources. When the complete publication is current,
  the command exits successfully before provider creation or agent dispatch.
- `refresh-all` deliberately refreshes every available non-empty source and
  republishes workspace synthesis.
- `cached-only` performs no extraction. It succeeds only when usable published
  artifacts cover the declared workspace; otherwise it blocks with guidance to
  run policy `changed`.
- `none` remains accepted for compatibility as an explicit no-work policy.
- Retired `target-only` and `target-changed` values remain rejected with the
  existing workspace-scope explanation.

`--reset` abandons the active unfinished RE runtime state and builds a new plan
from the current workspace and published index. It does not delete or mutate the
published generation.

`--re-max-inner` may be supplied to all three lifecycle entry points. A genuine
budget increase preserves consumed counters and reactivates only unresolved
source-local quality debt that the larger bound makes eligible. Reusing the
same or a lower value is a no-op.

### Spec lifecycle

```text
echelon spec run <description> ... [--ignore-re]
```

Remove these options from `spec run`:

- `--re-policy`
- `--re-max-inner`

Remove `--re-max-inner` from `spec continue`. The root `echelon run`
compatibility alias follows the same contract as `echelon spec run`.

The legacy parser must continue recognizing the removed spellings solely to
reject them with a migration error that points to `echelon re run`. It must not
treat an obsolete option or its value as feature-description text.

## Runtime Ownership And Layout

RE run directories remain directly below `runs/` for compatibility with the
existing controller, lock, and manual publication helpers:

```text
runs/
  .current                 # active spec lifecycle only
  .current-re              # active RE lifecycle only
  .current-build-<spec-id> # delivery lifecycle only
  re-<timestamp>/
    state.json
    re/
      re-execution-plan.json
      re-source-index.json
      ... staged RE outputs ...
```

`runs/.current-re` contains a safe run ID, never a path. Resolution rejects
empty, path-like, symlink-escaping, missing, or non-RE run targets before state
mutation. Existing `runs/.gitignore` handling for `.current*` markers applies.

A completed marker may continue to point at the last RE run. `re run` inspects
its state: unfinished state resumes unless `--reset` is present; completed state
causes a new freshness plan. A no-change plan does not need to create a new run
directory.

## RE Run Flow

### Run

1. Validate workspace configuration, extension availability, tool policy, and
   the dedicated RE current marker.
2. If an unfinished RE run exists, apply any higher repair budget and resume it.
3. Otherwise discover the workspace, resolve the fingerprint profile, load the
   published index, and build the workspace-scoped execution plan.
4. If the plan requires no extraction or synthesis, print a current/no-work
   summary and exit zero without constructing an LLM provider.
5. For a work-bearing plan, create `runs/re-<timestamp>/`, write
   `runs/.current-re`, materialize the existing RE planning artifacts, and
   initialize controller state.
6. Execute `ReExtractionController` with the existing deterministic phase,
   quality, retry, and compaction-recovery contracts.
7. On complete validation, call the existing atomic publication boundary.
8. Verify the published index generation, persist publication facts in RE run
   state, mark the run done, and print a summary.

### Continue

`echelon re continue` resolves the active unfinished RE run and performs the
next no-input action. Examples include retrying a recoverable failed dispatch,
continuing from an interrupted phase, retrying an atomic publication after a
recoverable publication failure, or reactivating quality debt after an explicit
budget increase.

If the active run is waiting for a typed human answer, `continue` reports the
question and directs the operator to `re resume`. If there is no unfinished RE
run, it reports that there is nothing to continue and points to `re run`.

### Resume

`echelon re resume "<answer>"` is accepted only when RE state contains a typed,
unresolved human escalation. It records the answer through the same structured
decision primitives used by existing lifecycle controls, marks the escalation
resolved, injects the answer into the next applicable RE dispatch context, and
delegates to continuation.

Ordinary deterministic quality failures and exhausted budgets are not human
questions. `resume` rejects those states and gives the appropriate `continue`
or `continue --re-max-inner` command.

## Publication Contract

Complete extraction automatically publishes. Publication remains:

- single-writer locked,
- generation-checked,
- staged and atomic,
- validated against the durable registry schema,
- isolated from Git push behavior.

Automatic publication never uses `--allow-partial`. A partial result remains in
its RE run and returns a blocked or debt-bearing result. `echelon re publish`
remains available for recovery and the explicit manual partial override. Its
public semantics do not change.

A publication failure after successful extraction must not repeat extraction.
State records that extraction is complete and continuation retries only the
publication boundary when safe.

## Published RE Context In Spec Runs

At fresh spec-run initialization:

1. If `--ignore-re` is present, record an explicit ignored RE-context state and
   do nothing else.
2. Otherwise load and validate `re/index.json` without computing source
   fingerprints.
3. If no publication exists, record an absent RE-context state and continue
   normal spec authoring.
4. If a publication exists, resolve only paths registered by the canonical
   index and source manifests.
5. Copy the registered manifests and documents into a run-local read-only
   context snapshot and record the source generation and publication status.

The snapshot includes registered workspace documents, source manifests,
source overviews, source-owned specs, architecture map, and domain catalog when
present. It excludes source code, RE caches, staging directories, locks, and
unregistered files.

Agents receive a controller-owned `published_re_context` artifact map. SCOUT and
other consumers read that map directly. They no longer receive or mutate
`golddigger_*` queues or status fields. Because the documents are snapshotted,
a concurrent later `echelon re run` cannot silently change an in-progress spec
run or force it to restart.

Spec authoring deliberately does not compare published fingerprints with the
live workspace. An operator who knows the workspace changed runs
`echelon re run`; its default `changed` policy decides whether work is needed.

## Workflow And Prompt Changes

Remove RE execution from the Phase A graph:

- Remove `golddigger_mode1` from `phase1-discover.pre_dispatch`.
- Remove GOLDDIGGER Mode 2 queue processing from later Phase A pre-dispatch
  hooks.
- Remove `golddigger_requests`, `golddigger_completed_domains`,
  `golddigger_status`, `golddigger_mode`, and related execution-only state
  allowlists from spec phases.
- Update SCOUT, CARTOGRAPHER, and context-pack contracts to consume
  `published_re_context` when present and never request RE execution.
- Keep the GOLDDIGGER and standalone RE command/agent assets only where they are
  still part of an explicit RE or compatibility surface; they are not routed by
  `spec run`.

The RE extraction graph and phase contracts remain the invariant protocol for
explicit RE execution. The new coordinator is Python-owned and does not move
execution logic into thin command wrappers.

## State Contract

The RE lifecycle state records at least:

- run ID and run kind,
- status and current RE phase,
- requested and resolved RE policy,
- fingerprint profile and profile hash,
- execution-plan paths and source actions,
- `re_max_inner` and consumed repair counters,
- typed blocker or escalation metadata,
- extraction-complete status,
- publication-required status,
- expected and actual published generations,
- last dispatch sentinel and recovery details.

The spec lifecycle records a small independent context object:

```json
{
  "published_re_context": {
    "status": "attached",
    "generation": 7,
    "publication_status": "complete",
    "snapshot_root": "runs/<spec-run>/context/published-re",
    "artifacts": {}
  }
}
```

Allowed statuses are `attached`, `absent`, and `ignored`. This object contains
no refresh policy, source action, repair budget, or publication authority.

## Error Handling

- Invalid policy or budget fails before run creation.
- `cached-only` with missing/unusable workspace coverage blocks without agent
  dispatch and names the sources requiring `changed`.
- Lock contention leaves the current and published states unchanged.
- Invalid or unsafe current markers fail closed.
- Malformed canonical indexes prevent attachment to a spec run and produce a
  clear registry error; `--ignore-re` remains an explicit escape hatch.
- Agent or deterministic quality failure persists exact phase and blocker
  context for continuation.
- Partial extraction never auto-publishes.
- Publication failure preserves completed staged extraction for publication-only
  retry.
- `resume` without an unresolved typed question fails without changing state.
- An active spec run and active RE run may coexist because their markers and
  state stores are independent; the spec run reads its snapshot only.

## Components

Expected implementation boundaries:

- `src/echelon/cli_app.py`: typed RE run/continue/resume commands, spec
  `--ignore-re`, and removal of spec-owned RE options.
- `src/echelon/cli.py`: legacy parsing, migration errors, RE command dispatch,
  summaries, and current-marker resolution.
- New focused RE lifecycle coordinator/state helpers under `src/harness/` or
  `src/echelon/`; they compose existing RE primitives rather than duplicating
  extraction logic.
- `src/harness/re_planner.py`, `re_materializer.py`, `re_controller.py`,
  `re_publication.py`, and `re_registry.py`: reused, with narrowly scoped API
  changes where lifecycle composition requires them.
- `src/harness/squad.py` and `squad_executors.py`: remove RE execution ownership
  and attach the published-context snapshot.
- `extension/workflow/definition.yaml`, Phase A specs, and exploration agents:
  remove GOLDDIGGER routing and consume published context.
- README, RE overview/config docs, command tables, changelog, CLI version, and
  extension version.

## Verification

### CLI

- RE help exposes run/continue/resume and their typed options.
- Spec help exposes `--ignore-re` and omits RE policy/budget options.
- Removed spec options fail with the exact migration command.
- Root `echelon run` matches the spec-run option contract.
- Retired target-scoped RE policies remain rejected.

### RE lifecycle

- Default `changed` with a current complete publication makes zero provider
  calls and creates no unnecessary run.
- Work-bearing plans create and resolve only `runs/.current-re`.
- Active spec and delivery markers remain unchanged.
- Interrupted and retryable blocked runs continue at the correct RE phase.
- Higher repair budgets preserve consumed counters and reclaim only eligible
  debt.
- Human resume persists and injects a structured answer; resume without a
  question is rejected.
- Complete output publishes automatically and advances the generation.
- Partial output never publishes automatically.
- A publication-only retry does not rerun extraction.
- Unsafe or corrupt current markers and lock contention fail closed.

### Spec lifecycle

- Fresh spec initialization calls no RE planner, fingerprint, controller,
  GOLDDIGGER, or publication API.
- A valid publication produces a bounded run-local snapshot and artifact map.
- No publication proceeds with `published_re_context.status = absent`.
- `--ignore-re` produces `status = ignored` and reads no registered documents.
- A later RE publication does not change the spec run's snapshot.
- Phase A prompts contain no executable GOLDDIGGER Mode 1 or Mode 2 route.

### Regression

- Existing RE controller, quality-gate, cache, lock, and publication suites
  remain green.
- Existing spec run/continue/resume and delivery run/continue/resume behavior is
  unchanged outside the intentional CLI removal and context boundary.
- Extension dry-run and prompt/registry contract checks pass.

## Migration And Documentation

This is a deliberate CLI break with an actionable migration:

```text
before: echelon spec run "..." --re-policy changed --re-max-inner 10
after:  echelon re run --re-policy changed --re-max-inner 10
        echelon spec run "..."
```

Operators who do not want the last published generation for a feature use:

```text
echelon spec run "..." --ignore-re
```

Documentation must state clearly that `spec run` does not check RE freshness.
The explicit `re run` command is the only owner of freshness detection and
refresh work.
