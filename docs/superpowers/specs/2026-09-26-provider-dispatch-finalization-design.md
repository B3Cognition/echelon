# Provider Dispatch Finalization Design

**Date:** 2026-09-26  
**Status:** Proposed  
**Scope:** Phase A provider-backed dispatches on current, greenfield runs

## Intent

Every Phase A provider dispatch must pass through one controller-owned
finalization boundary before its verdict, journal entries, state updates, or
routing can be accepted.

The boundary must prove the assignment's artifact contract, emit a
dispatch-bound receipt, and preserve that receipt in the existing sealed
spec-step intent. It must replace the manual mandatory-output map and the
WHY2, WHY3, and ASSESS2 publication branches without creating another state
machine, outbox, or recovery protocol.

This is a corrective refinement of the S5 spec-step kernel. It does not reopen
the S5 state model or introduce historical-run migration.

## Problem

The current containment patch correctly blocks the confirmed stale-output
failure on the highest-risk paths, but ownership remains split:

- `PhaseNode.outputs` is free-form prompt metadata, not a runtime contract;
- `_MANDATORY_PHASE_OUTPUTS` covers only selected ordinary phases;
- WHY2, WHY3, ASSESS2, PLAN2, and selected-issue revalidation have local
  publication rules;
- conditional specialists and several ordinary phases can bypass publication
  proof; and
- the harness-generated receipt is carried in the result but is not explicitly
  sealed into the durable spec-step provenance.

The code therefore contains one strong primitive without one authoritative
way to invoke it.

## Constraints

1. `pending_spec_step` remains the only durable authority for an incomplete
   Phase A step.
2. `SquadStateStore` remains the sole owner of atomic state writes and CAS.
3. The change must not add a publication marker to `state.json`, another
   outbox, or another recovery loop.
4. Provider claims remain untrusted. The harness creates the receipt.
5. Existing canonical files never satisfy a required output for a new
   dispatch.
6. Identical-content rewrites remain valid when filesystem identity proves a
   current write.
7. Commander decisions and routing policy remain unchanged.
8. Only current workflow definitions are supported. Missing or legacy
   contracts fail closed; there is no inference or migration adapter.
9. RE and Delivery retain their own controller contracts. This design changes
   Phase A only.

## Considered Approaches

### 1. Extend executor-local checks

Add more entries to `_MANDATORY_PHASE_OUTPUTS` and more special branches to
staged and conditional executors.

This is the smallest patch, but it preserves the exact ownership failure that
caused the regression. A new dispatch variant could still omit the check. This
approach is rejected.

### 2. Typed contracts and one shared finalizer

Compile an explicit artifact contract for every provider assignment, route all
Phase A provider calls through one dispatch/finalization service, and seal its
harness-owned receipts into the existing spec-step intent.

This removes the bypasses and manual maps while preserving S5 ownership. It is
the selected approach.

### 3. Controller-owned staging and atomic promotion

Force every provider to write into a dispatch-specific staging directory, then
atomically promote validated artifacts through a publication transaction.

This is the strongest end-state, but it changes provider permissions, prompt
paths, artifact roots, recovery, and every supported provider. Implementing it
inside this correction would create a second publication mechanism beside the
S5 step effect. It is deferred until there is evidence that the transitional
snapshot proof is insufficient.

## Typed Artifact Contract

`harness.provider_output_publication` owns immutable contract types:

```python
ArtifactMode = Literal["publish", "result_only", "read_only"]

@dataclass(frozen=True)
class ProviderArtifactRule:
    path: str
    kind: Literal["file", "directory"]
    requirement: Literal["required", "optional"]

@dataclass(frozen=True)
class ProviderArtifactContract:
    mode: ArtifactMode
    artifacts: tuple[ProviderArtifactRule, ...]
    allow_shadow_recovery: bool = False
```

The workflow graph gains an `artifact_contract` field on each provider-backed
phase and nested provider assignment. Example:

```yaml
artifact_contract:
  mode: publish
  allow_shadow_recovery: true
  artifacts:
    - path: spec.md
      kind: file
      requirement: required
    - path: requirements-overview.md
      kind: file
      requirement: required
```

Rules:

- paths are exact, normalized paths relative to the active spec directory;
- directories represent the complete owned subtree and replace filename
  wildcards such as `adr/ADR-*.md`;
- `required` means the current dispatch must claim and publish the path;
- `optional` means the path may be omitted, but if it is claimed or changed it
  must be valid and current;
- `publish` permits only paths listed by the contract;
- `result_only` permits no artifact claims and is used for judgments and other
  structured-result calls;
- `read_only` permits no artifact claims and also retains the dispatch's
  existing read-only sandbox or input-manifest mutation guard; and
- verdict-dependent requirements remain semantic validators applied after the
  shared publication proof. They are not encoded as a second expression
  language in the artifact contract.

`outputs` remains descriptive prompt metadata during this cutover. Runtime
safety never parses filenames from it. Once all prompt builders consume the
typed contract, redundant filename-only `outputs` entries may be removed in a
separate cleanup.

Graph compilation fails when:

- an active `agent` phase lacks an artifact contract;
- a nested staged, conditional, or real pre-dispatch agent lacks one;
- a deterministic or commander-internal phase declares a provider contract;
- a path is absolute, traverses upward, duplicates another rule, or has an
  unsupported kind or requirement; or
- `result_only` or `read_only` contains artifact rules.

Documentary pre-dispatch entries without an agent remain non-dispatch metadata
and need no contract.

## Single Dispatch and Finalization Boundary

A shared `ProviderDispatchFinalizer` is used by both `squad_executors.py` and
the Phase A controller's direct Commander judgment calls. Callers provide:

- phase ID;
- assignment ID, including nested agent and mode;
- current state revision;
- the compiled artifact contract;
- active spec root;
- result schema contract;
- prompt metadata; and
- an optional semantic validator.

The service owns this sequence:

```text
compile exact assignment contract
  -> capture required and optional pre-dispatch snapshots
  -> execute provider
  -> detach and validate result/schema/state ownership
  -> discard any provider-forged receipt fields
  -> recover changed shadow outputs when explicitly allowed
  -> validate output claims and current-dispatch filesystem evidence
  -> run assignment-specific semantic artifact validation
  -> return FinalizedProviderResult + harness receipt
```

No caller receives an accepted raw provider result. The accepted type is a
`FinalizedProviderResult`; journal, cost, state, staged aggregation, and route
code consume that type or its explicitly detached result.

The receipt contains at least:

- schema version;
- random dispatch ID generated before execution;
- phase ID and exact assignment ID;
- source state revision;
- canonical contract digest;
- each accepted path, kind, and content digest; and
- a digest of the validated provider result manifest.

The finalizer rejects:

- missing required paths;
- required paths omitted from `output_files`;
- claims outside the contract;
- optional paths changed without a matching claim;
- claimed paths without current-dispatch filesystem evidence;
- stale files, symlinks, special files, unsafe directories, and traversal;
- non-empty artifact claims for `result_only` or `read_only`; and
- a semantic validator that consumes a different receipt or artifact set.

An identical-content rewrite succeeds when inode or timestamp identity changed
during the dispatch. A digest match alone is neither success nor failure.

## Shadow Recovery

Shadow recovery remains a materialization path inside the shared finalizer,
not an executor-specific exception.

When `allow_shadow_recovery` is true, the finalizer captures canonical and
shadow baselines before execution. It may copy only a contract-listed shadow
artifact that changed during this dispatch. After copying, it proves the
canonical target and includes the canonical target in the receipt. A stale
pre-existing shadow artifact cannot satisfy the contract.

## Executor Cutover

The cutover covers every Phase A provider family:

- ordinary agent execution;
- actual pre-dispatch agents;
- staged Stage 1 and Stage 2 assignments;
- selected-issue and fresh-candidate revalidation;
- conditional specialists;
- result-only SAGE work assessment;
- provider repair/retry results returned to these callers; and
- direct Commander judgment and human-resolution calls.

Specialized executors continue to own sequencing and domain policy. They no
longer own publication proof.

Existing semantic checks remain after finalization, including evidence
inventory validation, coverage ownership, fixed-candidate fingerprints,
selected-issue envelopes, and read-only SAGE input-manifest checks. Where a
semantic check reasons about produced artifacts, it receives the exact
finalizer receipt rather than reopening an unrelated path set.

The following implementation structures are deleted after cutover:

- `_MANDATORY_PHASE_OUTPUTS`;
- `_SAGE_REVIEW_OUTPUTS` as a publication authority;
- executor-local selection of WHY2, WHY3, and ASSESS2 required filenames;
- direct `_exec_agent_with_contract` calls outside the shared dispatch service;
  and
- duplicate receipt stripping/insertion branches.

Domain-specific error classification is preserved. For example, a missing
ASSESS2 report remains `missing_consensus_prerequisite`, even though the common
finalizer detects it.

## Spec-Step Binding

Publication proof is a prerequisite to sealing a route, not a new replayable
filesystem effect. Providers have already written the active run-local
artifacts by this point.

The controller extracts the harness-owned receipts from the finalized phase
result and copies them into `SpecStepIntent.provenance` when it calls
`prepare_spec_step`. The intent validator authenticates their schema, contract
digests, assignment identities, and uniqueness. The existing canonical intent
digest then seals the receipts together with the prepared-result and routing
identities.

This gives recovery durable evidence of which provider dispatches were
accepted without adding:

- a new `SpecStepEffect` value;
- a new effect cursor;
- a new `state.json` marker;
- a provider-output outbox; or
- an independent retry/failure lifecycle.

The spec-step kernel does not re-run provider publication during recovery. It
verifies the already sealed intent and continues the existing effect plan. A
provider result without every receipt required by its compiled phase contract
cannot be used to prepare or begin a step.

Nested staged receipts are aggregated into the final phase result and sealed
in deterministic assignment order, never thread-completion order.

## Failure and Recovery

Publication failure returns an `ExecutorBlockedResult` before the failed
dispatch's journal entries, state updates, or routing decision are accepted.
The existing bounded phase-output recovery fields remain the user-visible
diagnostic surface during the cutover.

No new run-state migration is provided. A current run created from a workflow
definition without typed contracts is unsupported and must be reset. This is
consistent with the S5 current-runs-only policy.

If the process crashes after a provider writes an artifact but before a receipt
is sealed, the next dispatch treats that artifact as baseline. It cannot claim
the previous unsealed write as current evidence. The provider must publish it
again, or the run blocks with the existing recovery instruction. This is the
safe failure mode and avoids orphan-receipt recovery.

## Test Strategy

Tests are added in RED/GREEN order for:

1. graph compilation of publish, result-only, read-only, and nested contracts;
2. rejection of missing and malformed current workflow contracts;
3. missing first-generation required output;
4. stale required output with an empty manifest;
5. successful provider exit after a failed write;
6. a false output claim;
7. identical valid rewrite;
8. partial multi-file publication;
9. optional omission, optional claimed publication, and optional unclaimed
   mutation;
10. undeclared output claims;
11. file/directory mismatch, symlink, traversal, and special-file rejection;
12. fresh shadow recovery and stale shadow rejection;
13. ordinary, pre-dispatch, staged, revalidation, conditional, result-only,
    and Commander call-site coverage;
14. no journal, cost, or state acceptance before finalization;
15. deterministic ordering and sealing of nested receipts in spec-step
    provenance;
16. rejection of missing, forged, duplicate, or contract-mismatched receipts
    during step preparation; and
17. a structural guard proving no Phase A provider call bypasses the shared
    dispatch service.

Focused executor, phase-graph, prepared-result, and spec-step tests run after
each slice. The repository unit gate runs once after the whole cutover is
complete.

## Non-Goals

- Changing phase routing, prompts, verdicts, or Commander authority.
- Migrating historical runs or old deployed workflow definitions.
- Creating a generic workflow or publication framework for RE or Delivery.
- Replacing the descriptor-safe final Phase A publication transaction.
- Implementing provider-specific staging directories in this change.
- Treating deterministic downstream validation as dispatch provenance.

## Acceptance Criteria

The change is complete when:

1. every active Phase A provider assignment has one explicit typed contract;
2. every Phase A provider invocation uses the shared dispatch finalizer;
3. every required artifact has current-dispatch evidence before any result is
   accepted;
4. all accepted provider receipts are harness-owned and sealed into the
   existing spec-step intent;
5. the manual mandatory-output map and phase-specific publication branches are
   deleted;
6. no second durable authority, marker, outbox, or recovery loop exists;
7. the regression scenarios above pass; and
8. focused and repository unit verification are green and recorded.
