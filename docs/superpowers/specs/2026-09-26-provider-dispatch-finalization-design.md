# Provider Dispatch Finalization Design

**Date:** 2026-09-26  
**Status:** Proposed — revised after architecture review
**Scope:** Command-driven Phase A provider dispatches in newly initialized,
current-version runs across greenfield, brownfield, and self-analysis modes

## Intent

Every in-scope Phase A provider dispatch must pass through one controller-owned
finalization boundary before its verdict, journal entries, state updates, or
routing can be accepted. The compiled assignment contract is both the source of
the provider's write permissions and the post-dispatch publication authority.

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
10. A provider cannot write a product artifact outside the exact mutable paths
    resolved from its compiled assignment contract. Providers that cannot
    enforce that exclusive scope fail closed for `publish` assignments.
11. Accepted nested results remain transient until the existing spec step seals
    and applies their journal, cost, state, and publication effects.
12. CHIEF writes only its run-local draft. Publication of
    `.echelon/constitution.md` remains a controller-owned effect in the existing
    spec-step publication plan.
13. Managed discovery keeps its existing private-directory inspection and
    controller-publication protocol. It is an explicitly stronger, out-of-scope
    dispatch boundary rather than a bypass of this one.

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
ArtifactRoot = Literal["active_spec", "squad", "proposal"]
ReadRoot = Literal["active_spec", "project", "squad", "context", "runtime", "staging"]

@dataclass(frozen=True)
class ProviderArtifactRule:
    root: ArtifactRoot
    path: str
    kind: Literal["file", "directory"]
    requirement: Literal["required", "optional"]

@dataclass(frozen=True)
class ProviderReadRule:
    root: ReadRoot
    path: str
    kind: Literal["file", "directory"]

@dataclass(frozen=True)
class ProviderArtifactContract:
    mode: ArtifactMode
    artifacts: tuple[ProviderArtifactRule, ...]
    read_inputs: tuple[ProviderReadRule, ...] = ()
    allow_shadow_recovery: bool = False
```

The workflow graph gains an `artifact_contract` field on each provider-backed
phase and nested provider assignment. Example:

```yaml
artifact_contract:
  mode: publish
  allow_shadow_recovery: true
  artifacts:
    - root: active_spec
      path: spec.md
      kind: file
      requirement: required
    - root: active_spec
      path: requirements-overview.md
      kind: file
      requirement: required
  read_inputs:
    - root: active_spec
      path: assumptions.md
      kind: file
```

Rules:

- roots are symbolic controller capabilities, never provider-supplied paths;
- `active_spec` resolves to the active spec directory;
- `squad` resolves to `${SQUAD_DIR}` and is permitted only for the exact
  `constitution.draft.md` CHIEF target;
- `proposal` resolves to the controller's `kb-proposals` directory and is
  permitted only for the exact dispatch-specific SAGE proposal filename;
- paths are exact normalized relative paths beneath their resolved root;
- directories represent the complete owned subtree and replace filename
  wildcards such as `adr/ADR-*.md`;
- `required` means a successful artifact-producing outcome must claim and
  publish the path during this dispatch;
- `optional` means the path may be omitted, but if it is claimed or changed it
  must be valid and current;
- `publish` grants mutable access only to paths listed by `artifacts`;
- `result_only` permits no artifact claims and is used for judgments and other
  structured-result calls;
- `read_only` permits no artifact claims and also retains the dispatch's
  existing input-manifest mutation guard;
- `read_inputs` contributes read permissions but never write permissions; and
- controller and provider-adapter operational paths may be adapter-internal,
  but cannot overlap product, spec, run-output, state, journal, or source paths.

For a directory rule, the provider claims individual members. The finalizer
normalizes those claims to a sorted leaf-member manifest. A required directory
needs at least one valid current-dispatch member unless its assignment-specific
semantic validator requires a stronger minimum. Merely touching the directory
inode is not publication. Unchanged retained children are recorded separately
as inputs and never count as current output.

The contract compiler produces a permission projection before execution:

```text
read roots = compiled read_inputs + controller-required immutable context
write paths = exact compiled artifact targets
exclusive write scope = true
atomic replacement = temporary siblings of exact write targets only
```

Parallel assignments may not own overlapping files, directories, or
ancestor/descendant targets. Compilation rejects overlap. An adapter that
cannot enforce the projection cannot run a `publish` assignment; prompt-only
write instructions are not a supported containment mechanism.

Verdict-dependent artifact requirements are not a second expression language.
Each assignment supplies one controller-owned outcome classifier with three
results:

- `published`: enforce all required and claimed optional artifacts;
- `domain_blocked`: preserve the assignment's `BLOCKED` or `STOP_AND_ASK`
  policy outcome, require no missing-output recovery, and still reject any
  unauthorized mutation or invalid claimed optional output; or
- `invalid`: reject the provider result before any acceptance.

The classifier consumes only the validated structured result. Artifact-aware
semantic validators run afterward over the exact accepted receipt. This keeps
legitimate evidence-blocked SAGE and ASSESS2 outcomes distinct from provider or
publication failure.

`outputs` remains descriptive prompt metadata during this cutover. Runtime
safety never parses filenames from it. Once all prompt builders consume the
typed contract, redundant filename-only `outputs` entries may be removed in a
separate cleanup.

Graph compilation fails when:

- an active `agent` phase lacks an artifact contract;
- a nested staged, conditional, or real pre-dispatch agent lacks one;
- a runtime-only provider call lacks a registered typed assignment descriptor;
- a deterministic or commander-internal phase declares a provider contract;
- a root is unsupported for that assignment, a path is absolute, traverses
  upward, duplicates or overlaps another mutable rule, or has an unsupported
  kind or requirement;
- parallel assignments have overlapping mutable targets;
- `result_only` or `read_only` contains artifact rules.

Documentary pre-dispatch entries without an agent remain non-dispatch metadata
and need no contract.

### Assignment Inventory

The implementation adds the contract beside each graph assignment instead of
inferring it from `outputs`. This inventory is normative for coverage:

| Assignment family | Contract mode and roots | Execution rule |
|---|---|---|
| Ordinary SCOUT, SYNTHESIZER, MODELER, TRACKER, WHY1, CARTOGRAPHER, WHY2, INVESTIGATOR, lexicon derivation, ASSESS, DECIDE, ARCHITECT, SENTINEL, PLAN, and experimental quality phases | `publish`; exact `active_spec` files/subtrees from that assignment | One occurrence when selected; mode/greenfield skips are manifest entries, not missing receipts |
| CHIEF constitution authoring | `publish`; required `squad:constitution.draft.md` | Canonical constitution promotion is a later controller publication effect |
| Conditional specialists | `publish`; exact `active_spec` report files | One selected or skipped manifest entry per eligible specialist; optional spike files remain optional rules |
| Consensus WHY3 review | `publish`; required `active_spec:issues.md` and `active_spec:quality-gates.md` for `published` outcomes | Initial and final revalidation are distinct occurrence variants |
| Consensus ASSESS2 | `publish`; required `active_spec:implementability-report.md` for `published` outcomes | `REJECTED` with a report is published; legitimate evidence `BLOCKED` may be artifact-free |
| Consensus PLAN2 | `publish`; exact mutable planning outputs (`tasks.md`, `critical-path.md`, `risk-matrix.md`, and `dependencies.md`) | Dispatch, deferred, and sealed-result reuse are distinct manifest statuses |
| SAGE work assessment | `result_only` | A distinct runtime assignment descriptor; never reuse the WHY3 publish contract |
| SAGE decision proposal | `publish`; exact dispatch-specific `proposal` target | Separate occurrence from the decision judgment |
| Direct Commander judgment and provider-backed human-resolution calls | `result_only` | A registered runtime descriptor is required for every call site |
| Provider result repair | `result_only` | A subordinate attempt under the original occurrence with no product write paths |
| Managed discovery producers/reviewers | Existing stronger private-directory protocol | Explicitly excluded and guarded as `changed intentionally`, not passed to this finalizer |

The concrete YAML contract is authoritative for exact filenames. A structural
test compares all active graph and registered runtime descriptors with this
inventory so adding a provider call without choosing a contract mode fails.

## Single Dispatch and Finalization Boundary

A shared `ProviderDispatchFinalizer` is used by both `squad_executors.py` and
the Phase A controller's direct Commander judgment calls. Callers provide:

- phase ID;
- assignment ID and unique occurrence ID, including nested agent, mode, and
  revalidation purpose;
- current state revision;
- the compiled artifact contract;
- the controller-resolved root registry;
- result schema contract;
- prompt and prompt-metadata identities;
- the controller-owned outcome classifier; and
- an optional versioned semantic validator.

The service owns this sequence:

```text
compile exact assignment contract
  -> derive and enforce exclusive provider read/write scope
  -> capture required and optional pre-dispatch snapshots
  -> execute provider
  -> detach and validate result/schema/state ownership
  -> discard any provider-forged receipt fields
  -> classify published, domain-blocked, or invalid outcome
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
- phase ID, exact assignment ID, and unique occurrence ID;
- source state revision;
- canonical contract digest;
- prompt and prompt-metadata digests;
- outcome classification;
- each accepted root/path, kind, content digest, and pre/post filesystem
  identity digest;
- evidence kind (`created`, `replaced`, or `shadow_promoted`);
- the normalized directory member manifest where applicable;
- semantic validator identity/version and result digest; and
- a digest of the validated provider result manifest and subordinate result
  repair attempt chain.

The finalizer rejects:

- missing required paths for a `published` outcome;
- required paths omitted from `output_files` for a `published` outcome;
- claims outside the contract;
- optional paths changed without a matching claim;
- claimed paths without current-dispatch filesystem evidence;
- any provider mutation outside the compiled exclusive write projection;
- stale files, symlinks, special files, unsafe directories, and traversal;
- non-empty artifact claims for `result_only` or `read_only`; and
- a semantic validator that consumes a different receipt or artifact set.

An identical-content rewrite succeeds when inode or timestamp identity changed
during the dispatch. A digest match alone is neither success nor failure.

Provider adapters receive the compiled permission projection, not filenames
parsed from prompts or `outputs`. The finalizer verifies that the adapter
accepted an exclusive scope before dispatch. Tests exercise Claude, Codex, and
every other provider adapter that claims this capability, including exact
target writes, allowed sibling-temp atomic replacement, arbitrary sibling
denial, source/control-plane denial, traversal denial, and symlink denial.

### Provider Result Repair

A structured-result repair is a subordinate provider attempt, not a new
artifact-producing assignment. It always receives a `result_only` projection
with zero write paths and immutable access to the original raw response and
schema instructions. It cannot inherit the original publish scope. The parent
receipt records the ordered original/repair attempt identities and binds the
accepted repaired manifest. A repair write attempt fails the entire occurrence.

## Shadow Recovery

Shadow recovery remains a materialization path inside the shared finalizer,
not an executor-specific exception.

When `allow_shadow_recovery` is true, the finalizer captures canonical and
shadow baselines before execution. It may copy only a contract-listed shadow
artifact that changed during this dispatch. After copying, it proves the
canonical target and includes the canonical target in the receipt. A stale
pre-existing shadow artifact cannot satisfy the contract.

## Executor Cutover and Durable Acceptance

The cutover covers every command-driven Phase A provider family:

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

Each top-level phase execution owns one in-memory `PhaseExecutionAccumulator`.
Every successful nested finalization appends:

- its occurrence and receipt;
- detached journal entries;
- cost/token deltas;
- validated state updates;
- controller publication requests, such as CHIEF draft promotion; and
- the working-state projection needed by later children in the same phase.

Nested executors read the accumulator's projected state but do not persist
accepted child journal, cost, state, or canonical publication effects. The
accumulator is returned on successful, blocked, deferred, and early-return
paths. The controller either seals the complete accumulator into the existing
spec step or accepts none of its result effects. Existing pre-dispatch attempt
bookkeeping may remain durable only when it contains no accepted provider
result, artifact, journal, cost, or route state.

CHIEF draft promotion is represented in the existing spec-step publication
plan. The provider receipt authenticates `squad:constitution.draft.md`; the
controller effect validates that receipt and atomically promotes the draft to
`.echelon/constitution.md`. A crash cannot leave a canonical constitution
ahead of its sealed step.

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

Managed discovery is not routed through this service. Its producers and
reviewers keep `run_inspection_turn`, private temporary directories,
assignment-bound prompt/reply receipts, replay, and controller-owned
publication. The bypass guard classifies those call sites as the named
`managed_discovery` stronger boundary; no other unfinalized provider call is
allowed.

## Spec-Step Binding

Publication proof is a prerequisite to sealing a route, not a new replayable
filesystem effect. Providers have physically written the active run-local
artifacts by this point, but no journal, state, cost, routing, or canonical
publication effect has accepted those writes yet.

Before dispatch, the controller builds a phase execution manifest from the
compiled graph plus registered runtime assignment variants. Every entry has:

- stable assignment ID and unique occurrence ID;
- contract digest;
- selected condition or controller purpose;
- status: `executed`, `skipped`, `deferred`, or `reused`;
- a bounded skip/defer reason when not executed; and
- for reuse, the prior sealed step and receipt identity being reused.

Repeated WHY3 review and revalidation calls have distinct occurrences.
Conditional specialists remain present as selected or skipped. Deferred PLAN2
is not treated as a missing receipt. Runtime-only SAGE assessment, proposal,
Commander judgment, and human-resolution variants have explicit descriptors
and therefore appear in the same manifest.

The controller copies the complete manifest, all harness-owned receipts, and
the accumulator's deferred effect identities into `SpecStepIntent.provenance`
when it calls `prepare_spec_step`. The intent validator remains graph-independent:
it authenticates the closed manifest schema and digest, contract digests,
receipt-to-executed-occurrence correspondence, reuse references, ordering, and
uniqueness. Every `executed` occurrence has exactly one accepted receipt; no
`skipped` or `deferred` occurrence has one. The existing canonical intent
digest seals this provenance together with the prepared-result and routing
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
provider result whose receipt set does not exactly match its sealed execution
manifest cannot be used to prepare or begin a step.

Nested receipts are accumulated rather than stored only on the final child
result. They are sealed in deterministic manifest order, never thread-completion
order. Revalidation never replaces an earlier occurrence or receipt.

## Failure and Recovery

Publication failure returns an `ExecutorBlockedResult` before the failed
dispatch's journal entries, cost, state updates, canonical publication, or
routing decision are accepted. An earlier child receipt and projected effect
remain in the phase accumulator on blocked and early-return paths so the
controller can either seal the complete accepted prefix or reject the phase
without partially persisting it. Executor code cannot silently discard that
prefix.

Fault injection covers crashes after child finalization, after accumulation,
before step preparation, after step preparation, and during the existing
effect loop. Before sealing there are no durable accepted child effects. After
sealing, normal spec-step recovery replays the complete authenticated plan.
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

Resetting an old workspace is not sufficient to install the current workflow
definition. A supported run is newly initialized after the current bundle has
been installed or the workspace has been explicitly refreshed. Historical run
state is never migrated.

## Test Strategy

Tests are added in RED/GREEN order for:

1. graph compilation of publish, result-only, read-only, nested, and runtime
   assignment contracts;
2. rejection of missing and malformed current workflow contracts;
3. missing first-generation required output;
4. stale required output with an empty manifest;
5. successful provider exit after a failed write;
6. a false output claim;
7. identical valid rewrite;
8. partial multi-file publication;
9. optional omission, optional claimed publication, optional unclaimed
   mutation, and directory member manifests that reject empty or
   metadata-only publication;
10. undeclared output claims;
11. file/directory mismatch, symlink, traversal, and special-file rejection;
12. fresh shadow recovery and stale shadow rejection;
13. assignment-derived exclusive write scopes, overlapping parallel-owner
    rejection, atomic sibling replacement, arbitrary sibling/source/control
    denial, traversal/symlink denial, and equivalent behavior across supported
    provider adapters;
14. parallel dispatch isolation and retry isolation, including a provider that
    attempts to write another assignment's output;
15. provider result repair with a zero-write `result_only` projection and an
    attempted repair-time mutation;
16. published, `BLOCKED`, `STOP_AND_ASK`, and invalid-provider outcomes,
    including ASSESS2 rejection and missing-evidence SAGE behavior;
17. ordinary, pre-dispatch, staged, revalidation, conditional, result-only,
    and Commander call-site coverage;
18. no journal, cost, state, or canonical constitution acceptance before the
    outer spec step is sealed;
19. fault injection after nested finalization, before accumulation, before
    sealing, and after sealing, including early-return preservation;
20. deterministic manifest ordering and sealing of repeated, skipped,
    deferred, reused, and executed occurrences in spec-step provenance;
21. rejection of missing, forged, duplicate, contract-mismatched, or
    occurrence-mismatched receipts during step preparation;
22. a structural guard proving no in-scope command-driven Phase A provider
    call bypasses the shared dispatch service while explicitly accepting only
    the named managed-discovery stronger boundary; and
23. CHIEF draft authentication and crash-safe controller promotion through the
    existing publication effect.

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

1. every in-scope Phase A provider assignment has one explicit typed contract;
2. every in-scope command-driven Phase A provider invocation uses the shared
   dispatch finalizer, and managed discovery is the only named stronger
   boundary;
3. each compiled contract is the sole source of both exclusive provider write
   permissions and post-dispatch artifact validation;
4. every required artifact for a published outcome has current-dispatch
   evidence before any result is accepted, while legitimate domain-blocked
   outcomes preserve their classification;
5. provider result repair has no product write capability and is bound into the
   parent attempt receipt;
6. all accepted provider receipts match one closed execution manifest and are
   harness-owned and sealed into the existing spec-step intent;
7. nested journal, cost, state, and canonical publication effects remain
   transient until that spec step is sealed;
8. CHIEF canonical publication is controller-owned and crash-recoverable
   through the existing publication effect;
9. the manual mandatory-output map and phase-specific publication branches are
   deleted;
10. no second durable authority, marker, outbox, or recovery loop exists;
11. parallel ownership, provider sandbox, retry isolation, blocked outcomes,
    directory semantics, result repair, and crash-boundary regressions pass;
    and
12. focused and repository unit verification are green and recorded.
