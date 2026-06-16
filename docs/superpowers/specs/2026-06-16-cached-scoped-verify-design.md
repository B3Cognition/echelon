# Cached and Scoped Verify Design

## Problem

Harness banzai runs spend too much time and provider budget repeating full
`verify-spec` after small build slices. Recent NavigationalPortal runs also show
that repeated full audits amplify unstable LLM-owned row inventories: one run can
report 172, 189, or 232 fulfillment rows depending on how the agents restated
the checklist. The harness must reduce unnecessary full audits without hiding
real fulfillment blockers.

## Goals

- Make banzai runs cheap enough to keep building through many task slices.
- Keep semi mode conservative for user-supervised runs.
- Make every fulfillment refresh decision visible in logs and state.
- Prevent dirty verify-owned artifacts from confusing the next build slice.
- Establish the path to true scoped verify-spec without making row drift worse.

## Non-Goals

- Do not implement true scoped requirement judgment in the first slice.
- Do not let LLM agents invent or remove canonical fulfillment rows.
- Do not weaken land-time fulfillment checks.
- Do not hand-edit `fulfillment-report.md` or `fulfillment-gaps.md` from build
  slices.

## Recommended Behavior

### Stage 1: Deterministic Cache and Deferral

Ralph should treat fulfillment refresh as an explicit policy decision:

- `semi`: conservative. Run full verify-spec after successful task slices unless
  the existing full report cache is valid for the current commit and spec-input
  hash.
- `banzai`: aggressive. Defer full verify-spec until convergence/milestone
  boundaries, while still running normal project verification and applying
  Python-owned task progress from `completed_task_ids`.
- `convergence_only`: keep the existing behavior: defer until all canonical
  tasks are complete.
- `every_slice`: always attempt refresh, but still use the existing full-report
  cache before invoking the provider.

The refresh result should be structured and recorded as one of:

- `cached`: current `fulfillment-report.md` metadata matches HEAD, spec inputs,
  and audit row set.
- `full`: provider-backed full verify-spec was invoked.
- `deferred`: policy says this build slice does not need full verify-spec yet.
- `failed`: full verify-spec was attempted and failed.

### Stage 2: Dirty Verify Artifact Containment

After a full verify-spec refresh, Ralph should keep verify-owned artifacts from
leaking confusing dirty state into later build prompts.

If `fulfillment-report.md` / `fulfillment-gaps.md` are modified by a full
refresh, they should be handled in one deterministic way:

- If the build slice is committed, include those generated verify artifacts in
  the harness commit with the source/task changes that caused them.
- If the build is checkpointed before commit, salvage them with the rest of the
  dirty worktree.
- If a later build slice starts with dirty verify-owned artifacts that were not
  produced by the current slice, the prompt context must label them as inherited
  verify artifacts, not user code changes.

This removes the current ambiguity where COMMANDER sees dirty fulfillment files
and must infer whether it is allowed to touch them.

### Stage 3: Python-Owned Canonical Requirement Inventory

True scoped verify-spec requires a stable requirement universe first. Python
should extract and persist the canonical inventory from `spec.md`, `plan.md`,
`coverage-map.md`, and task metadata before any LLM agent runs.

The persisted inventory becomes the only allowed row set for:

- `requirement-audit.md`
- `implementation-map.md`
- `fulfillment-report.md`
- `fulfillment-gaps.md`

LLM agents may fill evidence, confidence, notes, and status for existing IDs.
They may not create, rename, or drop requirement rows. Any candidate new row is
reported as `unmapped_candidate`, not silently added to the fulfillment table.

### Stage 4: True Scoped Verify

After Stage 3, scoped verify can rejudge only impacted IDs:

- task IDs reported in `completed_task_ids`
- requirements mapped from those task IDs
- dependencies declared in task metadata
- runtime-threshold rows affected by changed files
- any row whose cited evidence file changed since the last full verify

The scoped report should preserve the last full report's unaffected rows, stamp
metadata with `verify_scope=scoped`, and include `base_full_verify_commit`.
Before land, Ralph must require a current full verify report or run one.

## Data Flow

1. Build slice writes `.harness-build-status.json` with `completed_task_ids`.
2. Ralph applies task progress deterministically to `tasks.md`.
3. Project verification runs.
4. Ralph evaluates fulfillment refresh policy:
   - cache hit: skip provider and mark refresh `cached`
   - banzai non-boundary: mark refresh `deferred`
   - boundary/conservative: invoke full verify-spec
5. Ralph applies the fulfillment gate:
   - cached/full report with blocking statuses remains a verification failure
   - deferred refresh reports a controlled failure only at convergence boundary
   - land still blocks stale or unresolved full fulfillment reports

## Logging and State

Each outer/inner loop should record:

- `fulfillment_refresh.status`
- `fulfillment_refresh.reason`
- `fulfillment_refresh.scope`
- `fulfillment_refresh.cache_key` when available
- `fulfillment_refresh.report_path` when available

The user-facing output should include a one-line decision such as:

```text
fulfillment refresh: deferred (banzai slice; full verify required before convergence)
fulfillment refresh: cached (HEAD/spec inputs unchanged)
fulfillment refresh: full (semi mode after task slice)
```

## Error Handling

- Provider session limits during full verify-spec should remain checkpointed and
  recoverable with the existing `provider_session_limit` path.
- Missing verify-spec skill remains a hard refresh failure.
- A full verify report whose row set does not match the latest audit remains a
  hard failure.
- A scoped report is never sufficient for land unless a current full report
  also exists.

## Testing

Stage 1 tests should cover:

- banzai defers fulfillment refresh for incomplete task progress.
- semi attempts full refresh and uses cache before provider invocation.
- refresh decision is written to state and appears in user-facing output.
- deferred refresh does not allow convergence when full fulfillment is required.

Stage 2 tests should cover:

- generated fulfillment artifacts are included in normal harness commits.
- salvage commits include dirty verify artifacts but still exclude
  `.harness-build-status.json`.
- inherited dirty verify artifacts are labeled as inherited context.

Stage 3 tests should cover:

- canonical inventory extraction is stable for the same spec inputs.
- LLM-produced extra/missing rows fail validation.
- report row order follows the Python-owned inventory.

Stage 4 tests should cover:

- scoped verify chooses impacted rows from completed task IDs and changed files.
- scoped reports preserve unaffected rows.
- land rejects scoped-only verification.

## Rollout

Implement in order:

1. Stage 1: policy-aware cached/deferred full verify.
2. Stage 2: verify-artifact containment.
3. Stage 3: canonical inventory.
4. Stage 4: true scoped verify.

This order gives immediate token savings while keeping release safety tied to
full verify-spec until row-set determinism is strong enough for scoped judgment.
