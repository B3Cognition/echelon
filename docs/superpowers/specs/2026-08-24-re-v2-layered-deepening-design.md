# RE v2 Layered Deepening Design

**Date:** 2026-08-24  
**Finding:** EGR-169, with the lineal checkpoint-adoption subset of EGR-166  
**Status:** Approved in chat; awaiting review of this written specification

## Summary

RE v2 currently produces a proven immutable L0 inventory and L1 compact
baseline through protocol 2.3. This design adds opt-in L2 deepening without
reopening a terminal run, regenerating accepted lower layers, or introducing a
second provider path.

The layer chain is strict and additive:

```text
L0 inventory
  -> L1 compact baseline
    -> L2 behavioral depth
      -> L3 semantic audit
        -> L4 exhaustive depth
```

Every higher-layer artifact references certified lower-layer hashes from the
same immutable source snapshot. A completed run remains terminal. Deepening
creates a self-contained child run that adopts the parent's certified authority
and schedules only work missing from the requested scope.

The first release implements L2 only. It defines the prerequisite-planning rule
for later L3 and L4 releases: requesting a higher registered layer schedules
each missing intermediate layer in order and certifies each independently.
Protocol 2.4 rejects an unregistered L3 or L4 target rather than pretending the
layer exists.

All model-backed work continues through neutral Prosaic prose and Echelon's
existing shared coding-provider path. This design adds no provider adapter,
adapter ID, model mapping, API transport, credential handling, or
provider-specific RE branch.

## Context

The retained OptaSearch RE campaign showed why detail cannot remain a
workspace-wide profile:

- raising a global ceiling also permitted more repeated semantic work;
- accepted source work was repeatedly revisited;
- workspace synthesis ran before source outcomes stabilized;
- a high-detail profile applied expensive effort across the workspace instead
  of only where it was needed; and
- completed lower-detail work was not a reusable prerequisite for later depth.

EGR-164 introduced the pinned execution kernel. EGR-165 populated reusable L0
and L1 identities. Protocol 2.3 then moved the L1 authorial dispatch to the
normal Prosaic and `SquadCliProvider` path and proved it with a real Codex run.
That run accepted all required artifacts, continued idempotently, retained
provider telemetry, and left the source Git repository untouched.

L2 must preserve those properties. It is not permission to rebuild provider
execution or to fold semantic audit, synthesis, exhaustive RE, or atomic repair
into one increment.

## Goals

- Layer L2 work over exact certified L0 and L1 authorities.
- Keep completed parent runs immutable and terminal.
- Make a child run self-contained while preserving exact parent provenance.
- Let operators deepen the whole baseline or explicit source/domain scopes.
- Schedule only missing work and perform zero provider calls for already
  accepted or unrelated artifacts.
- Give every requested scope a truthful, visible completion state.
- Preserve independent resource and attempt limits.
- Keep every LLM dependency in Prosaic frontmatter and the existing shared
  provider path.
- Preserve protocol 2.0 through 2.3 reads, continuation, canonical bytes, and
  execution behavior.
- Establish the prerequisite rule later L3 and L4 producers must follow.

## Non-goals

- Semantic validation, audit epochs, or semantic repair; EGR-167 owns them.
- Workspace synthesis or publication below workspace `re/`; EGR-168 owns them.
- Implementing L3 or L4 producers in protocol 2.4.
- Arbitrary goal names or user-authored layer definitions.
- Whole-domain or atomic artifact repair; EGR-170 owns repair.
- Adopting arbitrary uncertified output, rendered Markdown, mutable staging, or
  workspace publication as authority.
- Discovering checkpoints from unrelated run lineages.
- Deepening dirty source repositories or a source commit different from the
  selected parent snapshot.
- A new provider adapter, API path, output-envelope protocol, model selector,
  or provider-specific fallback.
- Making RE v2 the default engine.

## Decisions

### 1. Fixed layers, not arbitrary goals

The public target is a closed layer ID. Protocol 2.4 registers only `L2`.
Future protocols may register `L3` and `L4` without changing the meaning of
L2.

```text
echelon re deepen --to L2 ...
```

The CLI does not accept a free-form `--goal`. Artifact policy, dependencies,
producer protocol, verifier, and completion rules are all closed for each
registered layer.

### 2. Child runs preserve terminal semantics

Deepening never appends to a completed run. It creates a child whose manifest
pins:

- direct parent run ID;
- parent manifest hash;
- parent terminal event hash;
- source snapshot and partition identities;
- requested target layer;
- normalized selected scope;
- existing artifact-policy catalog hash;
- producer/executor/verifier authority hashes; and
- run-wide resource ceilings.

The child adopts the direct parent's exact accepted root. The direct parent and
every adopted artifact's source run remain explicit. No artifact is treated as
locally produced merely because its bytes were copied into the child object
store.

### 3. Adoption copies authority, not generated content

The child is self-contained. Adoption verifies source bytes and then stores
them through the existing content-addressed object store. This is not
regeneration: the adopted artifact hash remains identical.

The child stores one immutable `ParentAuthorityBundleV1`, referenced from its
schema-3 manifest. It contains parent/run provenance once, plus a sorted mapping
from each adopted artifact key to its existing acceptance closure:

```yaml
schema_version: 1
direct_parent_run_id: <safe run id>
source_manifest_hash: sha256:...
source_event_chain_hash: sha256:...
source_terminal_event_hash: sha256:...
source_ledger_chain_hash: sha256:...
lineage_root_run_id: <safe run id>
ancestor_bundle_hashes: [sha256:...]
artifacts:
  - artifact_key_id: sha256:...
    artifact_hash: sha256:...
    dependency_hashes: [sha256:...]
    certification_receipt_id: sha256:...
    candidate_assessment_id: sha256:... | null
    artifact_acceptance_receipt_id: sha256:...
    source_run_id: <safe run id>
    source_ledger_entry_hash: sha256:...
```

The bundle, source manifest bytes, authenticated event-chain bytes through the
terminal envelope, and authenticated ledger-chain bytes through the terminal
source entry are stored once as verified content-addressed objects. For every
adopted output, the adopter copies the schema-aware object closure and replays
the parent's existing canonical `CertificationReceiptV2`, optional
`CandidateAssessmentReceiptV1`, and `ArtifactAcceptanceReceiptV2` payloads into
the child through the typed durable-ledger facade, in their required order. It
does not define a second accepted-artifact or certification receipt type.

When the direct parent is schema 3, `ancestor_bundle_hashes` contains its exact
transitive parent-authority bundle closure and every referenced chain object.
The adopter verifies that closure while checking the manifest parent links and
copies it without flattening or rewriting ancestor provenance.

The child ledger record hashes are naturally new because the child has its own
hash chain; the nested receipt identities and artifact hashes remain exact. A
protocol-2.4 `artifact_adopted` event points to the bundle and imported receipt
IDs so status can distinguish adoption from local generation without granting
the event a parallel acceptance authority. Copying the authenticated parent
chain bytes lets the child revalidate provenance even after the parent run
directory is removed; a lone terminal envelope or ledger line is insufficient
authority.

Rendered projections, status JSON, candidate staging, and provider-authored
verdicts are never adoptable authority.

### 4. Scope controls scheduling, not lineage truth

The child imports the direct parent's complete accepted root and its transitive
certification/adoption closure. The requested scope controls which missing L2
artifacts enter the ready queue and which outputs determine completion.

Previously accepted L2 artifacts are therefore carried forward
deterministically. This lets later child runs accumulate selective depth without
scanning unrelated runs or repeating prior domains.

An artifact outside the requested scope can be adopted but is reported as
`not_requested`; it cannot make the requested scope look more complete.

### 5. L2 is a delta over L1

L2 deepens the existing authorial families rather than replacing them:

- domain `domain-baseline` at layer L2 adds supported detail for contracts,
  flows, integrations, state invariants, failure paths, and edge behavior;
- source `source-overview` at layer L2 adds supported cross-domain boundaries,
  interactions, flow topology, and failure propagation; and
- deterministic L2 source roots bind the selected domain set, accepted domain
  depth, source depth, lower-layer roots, and coverage state.

The layer is part of every artifact key, so an L2 `domain-baseline` is distinct
from its L1 prerequisite. Materialization composes the layers; it never
overwrites the L1 artifact.

L2 claims must not copy an L1 claim byte-for-byte with the same evidence merely
to fill space. A deeper claim may refine an L1 claim when it adds precision,
additional authorized evidence, or a materially deeper behavioral statement.
Deterministic certification rejects exact duplicate claims. Semantic conflict
judgment remains deferred to L3.

## Protocol and compatibility boundary

Protocol 2.4 uses run-manifest schema 3 because parent lineage, selected scope,
and target layer are new immutable semantic inputs. Protocol 2.0 and 2.1 retain
schema 1; protocols 2.2 and 2.3 retain schema 2.

Schema dispatch remains exact:

| Manifest schema | Protocols | Meaning |
|---|---|---|
| 1 | 2.0, 2.1 | pinned deterministic kernel variants |
| 2 | 2.2, 2.3 | L0/L1 layered baseline |
| 3 | 2.4 | lineal adoption and selective L2 deepening |

No schema-2 field becomes optional or changes interpretation. Schema-3 types
may reuse schema-2 artifact keys and canonical objects when their serialized
contract is unchanged. New schema-3 lineage and selection values use new
closed types rather than optional fields on schema-2 manifests.

The following remain byte-for-byte stable for protocols 2.0 through 2.3:

- manifests and stored input objects;
- artifact and work identities;
- event and ledger envelopes;
- candidate inventories and commit records;
- certification receipts;
- materialized L0/L1 projections; and
- the pinned Prosaic agent bytes already stored by a run.

Protocol 2.4 reuses adapter-contract version 1, its existing implementation
digest, adapter ID, executor path, and provider delegation unchanged. The L2
executor entry differs only in controller-owned producer policy, pinned
Prosaic-agent hash, response-schema hash, and verifier authority. Protocol 2.3
continues through its existing context path. There is no provider-adapter fork
or adapter version bump.

### Frozen protocol-2.3 authority rule

L2 must not edit a source module whose bytes contribute to an installed
protocol-2.3 executor, renderer, calculator, normalizer, verifier, partitioner,
or ownership digest. Schema-3 behavior lives in focused protocol-2.4 modules
and plugs into the existing generic storage, Prosaic/provider, authority,
candidate, accounting, event-envelope, ledger-envelope, and status-routing
seams.

Shared canonical value modules may gain schema-3 types or strictly additive L2
branches only when protocol-2.0-through-2.3 canonical fixtures prove that every
old input has identical bytes, validation outcome, identity, and behavior. L2
must not copy the execution kernel into a second controller. Protocol 2.4 uses
a thin `Protocol24Controller` subclass because the frozen protocol-2.2
controller directly invokes an L1-only parser before verifier dispatch. The
subclass inherits the run loop, recovery, provider invocation, accounting,
capture, retry, ledger, and terminal behavior unchanged and overrides only the
provider-candidate parsing/certification transaction. The protocol-2.2
controller source and installed digests remain byte-for-byte stable.

### Mandatory execution-seam proof

The current `Protocol22Controller`, `Protocol22RunContext`, recovery functions,
and some execution helpers intentionally require exact schema-2 types. They are
not declared reusable merely because their algorithms look relevant.

Before implementing L2 producers, the first implementation slice must prove in
tests that a minimal schema-3 work item can pass through the existing shared
provider executor and durable candidate-capture path while using:

- the configured `SquadCliProvider` and `AICodingCliProvider`;
- existing executor-contract and installed-authority validation;
- existing reservation and usage normalization;
- existing capture, inventory, and commit stores;
- `EventStore` and `DurableLedger`; and
- no copied run-loop, provider invocation, recovery, or execution code from
  `Protocol22Controller`, protocol-2.2 recovery, or protocol-2.2 execution.

A thin protocol-2.4 orchestration state machine may own only new lineage,
adoption, selected-scope, L2 parsing/certification, and L2 transition rules. It
may not duplicate the run loop, provider invocation, usage accounting,
candidate durability, recovery, or at-most-once dispatch mechanics. The narrow
subclass is not a controller fork: every method except provider-candidate
parsing/certification is inherited from the frozen controller.

## Public CLI

### Command

```text
echelon re deepen --to L2 \
  (--all | --source <source-id> [--source <source-id> ...]) \
  [--domain <domain-id> ...] \
  [--from-run <run-id>] \
  [--token-limit <positive-limit>] \
  [--active-ms-limit <positive-ms>]
```

Rules:

- `--to` is required and may occur once.
- Protocol 2.4 accepts only `L2`; `L3` and `L4` report `layer not registered`.
- Exactly one selection form is required: `--all` or one or more `--source`.
- `--all` is mutually exclusive with `--source` and `--domain`.
- `--domain` is valid only with exactly one selected source.
- A source without `--domain` expands to every domain owned by that source in
  the authenticated parent partition.
- Source IDs are exact `WorkspacePartitionCatalogV1` source IDs. Domain CLI
  values are exact `presentation_domain_id` values resolved within the selected
  source to their immutable `domain_key`; neither form accepts globs.
- Repeated source/domain values are rejected instead of silently deduplicated.
- `--from-run` is optional. Without it, Echelon uses the current run resolved by
  the existing `.current-re` mechanism and requires that authority to be a
  compatible completed parent or an idempotently matching child.
- The selected parent must expose certified prerequisites for the requested
  scope and the exact current snapshot.
- V1-only flags and `--engine` are invalid for `deepen`.

Examples:

```bash
echelon re deepen --to L2 --all
echelon re deepen --to L2 \
  --source pressbox-search \
  --source optapulse-platform
echelon re deepen --to L2 \
  --source pressbox-search \
  --domain search-api
echelon re deepen --to L2 --all \
  --from-run re-20260823-222511-413200
```

### Idempotent command resolution

The semantic request identity is derived from lineage-root authority, snapshot,
normalized selection, target layer, and the existing artifact-policy catalog
identity. The direct parent is recorded provenance but does not make an
otherwise identical request new. Token/time ceilings are operational
authorization and do not affect identity.

Without `--from-run`, resolution starts from the run selected by the existing
`.current-re` resolver; it does not introduce a second "deepest run" registry.
Under one workspace deepening-creation lock, the resolver inspects immutable
schema-3 manifests in that active lineage for the semantic request identity.
This scan is only for creation idempotency; accepted-artifact reuse still comes
exclusively from the selected direct parent's authenticated root.

The creation lock uses the repository's existing no-follow regular-file and
`flock` pattern. It is a scoped serialization point for child allocation and
active-pointer publication, not a new lock service or run-state authority.

When the same request already exists:

- a complete child returns its status and performs zero dispatches;
- a paused compatible child is selected and remains continuable through
  `echelon re continue`;
- a currently running child is reported rather than duplicated; and
- a terminal failed or explicitly partial child is reported with an explicit
  instruction; Echelon does not silently create a duplicate attempt.

Increasing a resource ceiling appends authorization to the existing child. It
never creates a new semantic run identity.

## Source and parent preflight

Preflight completes before a child directory, manifest, event, or active
pointer is created.

The adopter verifies:

1. the run ID resolves below the workspace run root without symlink traversal;
2. the parent manifest schema/protocol pair is supported;
3. the parent event chain is complete and has exactly one `run_completed`
   terminal event; failed and explicitly partial parents are not eligible in
   this increment;
4. the terminal event hash equals the value selected for the child manifest;
5. schema-3 parent links form a cycle-free chain to one schema-2 L0/L1 lineage
   root, with every stored parent manifest and terminal hash matching;
6. source snapshot, component, partition, and ownership identities agree;
7. every required artifact is accepted by a controller-owned ledger entry and
   valid certification receipt;
8. every key, dependency, receipt, and artifact object matches its content
   hash;
9. the dependency closure contains no missing, conflicting, or cyclic entry;
10. the workspace's declared source repositories are clean; and
11. their commits equal the commits authenticated by the parent snapshot.

A dirty source stops with commit/stash/revert guidance. A changed clean source
stops with guidance to create a new L0/L1 baseline. `--from-run` selects an
authority; it is not permission to deepen stale code.

Preflight reuses the clean-Git composite snapshot/workspace-manifest validators
and the authenticated `WorkspacePartitionCatalogV1` descriptors. It does not
add another repository walker, source catalog, domain-discovery pass, or dirty
tree interpretation.

Files are opened with the existing no-follow and stable-stat patterns. Any
change observed between validation and copy aborts child creation. Adoption
never reads source evidence from the live checkout; provider work reads only
the copied immutable snapshot and adopted objects.

## Child creation and active pointer

Child creation extends the established protocol-2.2 input-publication path; it
does not introduce a whole-run staging directory or rename lifecycle.

1. allocate the ID with the existing RE v2 run-ID allocator;
2. create the standard `ReV2Paths` layout;
3. publish adopted blobs through `ObjectStore`;
4. publish the workspace-partition, artifact-policy, executor-contract, and
   parent-authority input references with the same new-file, fsync, no-follow,
   and fault-hook helpers used by `create_protocol_22_run_store`;
5. link the immutable schema-3 manifest last;
6. append `run_created` and adoption events through `EventStore` with the
   protocol-2.4 `EventProtocol`;
7. import the accepted receipt closure through the typed durable ledger and
   derive the initial projection; and
8. activate it last with the existing active-pointer publisher.

The implementation should extract a schema-neutral manifest-last publication
helper from `create_protocol_22_run_store`, or add a thin schema-3 factory over
the same primitives. It must retain the existing incomplete-store detection and
fault-injection behavior. A crash before the manifest link leaves an incomplete
discoverable store that creation recovery can validate and remove/restart under
the creation lock. A crash after the manifest link but before active-pointer
publication leaves a discoverable recoverable run and does not displace the
prior active run. Recovery is idempotent and never repeats an imported receipt.

The child manifest references `ParentAuthorityBundleV1`; its identity commits
the sorted adopted-artifact map and parent chain objects. Input loading and
projection replay recompute that identity before planning or provider dispatch.

## Artifact policy and dependency graph

Protocol 2.4 does not add a layer catalog. The existing artifact-policy catalog,
executor-contract catalog, workspace-partition catalog, and graph templates are
the closed authority; layer selection is not inferred from filenames or prose.

Schema-3 extends the current canonical planning vocabulary additively:

- `ArtifactScope` remains the scope identity;
- `ArtifactKeyV2`, `WorkTemplateV2`, `WorkItemV2`, and
  `instantiate_work_item_v2` remain the identity shapes and binding rule;
- their closed layer/goal validation gains protocol-2.4 L2 values while fixtures
  prove every schema-2 value retains identical bytes and identity;
- a protocol-2.4 graph builder constructs selected L2 templates from
  `WorkspacePartitionCatalogV1`, policy entries, and executor entries; and
- `PlanningAuthorityV2`, `PlanningBudgetV2`, `PlanDecisionV2`, and the existing
  delta-planning algorithm remain the planner contracts.

`Protocol22Graph` itself remains closed to schema-2 inventory/baseline. The
protocol-2.4 graph is a focused wrapper over the same template and planning
primitives, not a copied planner. The artifact-policy catalog version used by
schema 3 adds the exact L2 slots; it replaces the proposed layer catalog rather
than duplicating it.

The graph retains imported L0/L1 `WorkTemplateV2` and `WorkItemV2` values
exactly, including their original `inventory` or `baseline` goal IDs. It adds
only selected L2 templates under the closed `selective-deepening` goal. The
protocol-2.4 graph therefore permits this authenticated mixed-goal prerequisite
closure; it never rekeys adopted work as L2 merely to satisfy a homogeneous-goal
assumption.

### Registered L2 work

For each selected domain:

```text
adopted L0 domain inventory
  + adopted L0 domain evidence pack
  + adopted L1 domain context/depth debt
  + adopted L1 domain baseline
    -> deterministic L2 targeted evidence pack
      -> deterministic L2 domain context bundle
        -> provider-authored L2 domain-baseline delta
          -> deterministic L2 domain certification/debt projection
```

For each selected source:

```text
adopted L1 source overview/root
  + accepted selected L2 domain projections
    -> deterministic L2 source context bundle
      -> provider-authored L2 source-overview delta
        -> deterministic L2 selected-source root
```

An L2 source overview is selection-relative. If only a subset of the source's
domains is requested, the root records that subset and cannot claim full-source
L2 coverage. A later child may adopt it and add other domains; the prior root
remains valid for its exact dependency set.

### Future prerequisite planning

The planner computes a closed chain from the highest registered target to L0.
For each selected scope it:

1. adopts matching certified prerequisites;
2. schedules missing prerequisites in ascending layer order;
3. schedules a layer only after its required lower layer is certified; and
4. determines completion only from outputs required by the requested target.

When L3 or L4 is registered later, `--to L3` or `--to L4` therefore fills any
missing intermediate layer automatically. Protocol 2.4 does not create
placeholder L3/L4 work or claim those layers are available.

## L2 content contract

L2 reuses the strict claim/evidence authorial envelope from L1. It does not add
a new provider result envelope. The layer-specific policy changes the required
depth, evidence selection, allowed size, and minimum utility.

### Domain depth

The L2 domain policy focuses the existing surfaces on:

- externally observable and internal contracts;
- normal and alternative control flows;
- integration boundaries and protocol interactions;
- state transitions and data invariants;
- failure propagation, recovery, and retry behavior;
- input, boundary, concurrency, and lifecycle edge behavior;
- tests that establish or fail to establish those behaviors; and
- operational constraints visible in the bounded evidence.

Every factual statement carries one or more authorized evidence references.
When bounded evidence is insufficient, the artifact records an honest unknown;
it never turns missing evidence into an affirmative absence.

### Source depth

The L2 source policy focuses on:

- cross-domain calls and data flows;
- shared contracts and integration boundaries;
- orchestration and lifecycle ordering;
- failure propagation across selected domains;
- selected-domain coverage; and
- unresolved cross-domain questions.

The source producer cannot cite an unselected domain's private evidence. It may
cite adopted L1 source evidence and controller-produced projections for the
selected L2 domains.

### Evidence selection

L2 evidence selection is deterministic. It uses L0 inventory, L1 claims,
unknowns, depth debt, declared entry points, explicit dependency edges, and
policy classifiers to select targeted source excerpts from the immutable
snapshot. The model does not choose its own read set or inspect the live source.

The initial L2 limits are:

| Surface | Maximum |
|---|---:|
| Domain context bundle | 160 KiB / 163,840 conservative input tokens |
| Source context bundle | 128 KiB / 131,072 conservative input tokens |
| Domain canonical authorial JSON | 64 KiB |
| Source canonical authorial JSON | 64 KiB |
| Rendered Markdown per artifact | 128 KiB |
| Retained provider stdout | existing terminal 128 KiB cap |
| Billable reservation per dispatch | existing 262,144-token cap |

Selection stops at the bound and records exact omission/debt descriptors. It
does not exceed the bound or trigger an unplanned extra model call.

## Prosaic and provider execution

Add one neutral Prosaic role:

```text
prosaic/subagents/echelon.re-deepener.md
```

Its frontmatter owns model tier, effort, tools, color, and neutral execution
metadata. The intended initial policy is `model_tier: strong`, `effort: high`,
and write-only candidate authority. `ProsaicPromptLoader.load_subagent` and
`canonical_prosaic_agent_bytes` supply the exact artifact bytes and interpreted
metadata pinned into the child object store, following the existing
`_prepare_re_v22_creation` pattern.
The existing internal candidate filename remains `baseline.json`; L2 changes
the pinned layer policy and Prosaic instructions, not the provider result or
candidate-capture protocol.

The RE controller delegates through the existing chain:

```text
ProsaicPromptLoader
  -> pinned ProsaicCommandArtifact
    -> existing shared CLI executor contract
      -> SquadCliProvider
        -> configured AICodingCliProvider
```

Codex, Claude, Copilot, and OpenCode therefore use the same L2 code path. The
provider layer remains responsible for model selection, effort mapping,
credentials, subprocess transport, usage observations, timeouts, and the
strict `echelon_result` envelope.

RE must not:

- inspect the provider name and choose L2 behavior;
- translate Prosaic model/effort metadata itself;
- invoke a provider CLI or HTTP endpoint directly;
- add an L2 provider adapter or provider-specific response parser;
- enable result repair in the provider adapter;
- grant source-discovery tools to the authoring agent; or
- infer success from process exit alone.

The protocol-2.4 installed-authority registry is an additive registration over
`InstalledAuthorityRegistry` and the existing executor-catalog resolver. It
registers the new agent and L2 verifier/policy authorities while retaining the
existing compact response-schema bytes, request renderer, shared CLI adapter,
reservation calculator, usage normalizer, and execution path. If implementation
requires a different provider response envelope, this L2 design is violated. It
does not fork registry or executor resolution.

The controller still captures provider output durably before parsing and
accepts an artifact only through deterministic certification.

## Attempts, resources, and no-repair policy

L2 deliberately does not recreate the v1 repair loop. Each provider-authored
L2 work item permits:

- one initial provider attempt;
- at most one shared retry;
- at most one result-contract retry within the shared attempt budget;
- at most one artifact-contract retry within the shared attempt budget;
- zero semantic-repair rounds; and
- zero whole-domain repair rounds.

The absolute maximum is two external provider dispatches per work item. The
second dispatch has exactly one recorded retry reason; result-contract,
artifact-contract, and shared-retry allowances cannot combine into a third
dispatch. The exact counters remain separate, and one attempt cannot be
relabeled to bypass another exhausted limit.

Run-wide token and provider-active-time ceilings remain independent operational
authorization. Schema 3 reuses `BudgetPolicyV2`, `BudgetDecisionV2`,
`evaluate_budget_v22`, and the existing budget/dispatch event counters; it adds
no second budget model. The schema-3 `selective-deepening` validator requires
the already-representable literal attempt tuple `(2, 2, 0, 1, 1, 1)`. Raising
either ceiling appends the existing
`budget_authorized` event and resumes the same semantic child identity. It does
not increase provider, generation, result-contract, artifact-contract, or
future semantic-round limits.

Unknown or untrusted provider usage follows the existing conservative
reservation-charging rule and remains visible in status. L2 does not add a
provider-specific token estimator.

## Certification and completion

Provider output is authorial input only. Deterministic certification verifies:

- the exact response schema and canonical normalization;
- artifact kind, L2 layer, selected scope, and partition identity;
- exact dependency hashes and adopted lower-layer closure;
- claim/evidence structure and evidence authorization;
- evidence path and line-range validity against the immutable snapshot;
- required surfaces and honest unknown encoding;
- byte, count, and minimum-utility bounds;
- no exact claim/evidence duplication from L1; and
- candidate inventory, commit, and result-contract integrity.

Certification does not claim semantic truth. Accepted L2 remains
`semantic_status: unaudited` until L3.

A child is complete only when every output required by the normalized requested
scope has an accepted certification. Unselected domains are not failures.
Status always distinguishes:

- `not_requested`;
- `adopted`;
- `planned`;
- `running`;
- `accepted`;
- `paused_resource`; and
- `blocked_incomplete`.

An accepted sibling remains accepted when another requested domain fails.
Independent ready work continues. If any requested output remains unresolved,
the child is paused or blocked; it is never reported complete.

Partial finalization is available only through an explicit operator action
supported by the lifecycle. Protocol 2.4 never automatically converts
exhaustion into a partial terminal result.

## Status and final banner

`echelon re status` and `--json` keep the current protocol router. The generic
`render_v2_status` dispatch gains a protocol-2.4 renderer which follows
`protocol_22_status_document` and `_render_human`; no second status command,
pointer resolver, or status cache is introduced. The document adds:

- protocol and manifest schema;
- direct parent and lineage root run IDs;
- parent manifest and terminal-event hashes;
- source snapshot identity;
- target layer and normalized requested scope;
- adopted artifact/imported-receipt counts by layer;
- planned, accepted, unresolved, and failed requested outputs;
- per-source and per-domain layer states;
- intentionally unselected domain counts;
- source L2 selected-domain coverage;
- provider/model observations and trusted/untrusted usage;
- attempt and resource usage/remaining authorization; and
- the exact next action when paused or blocked.

Human output ends with one prominent terminal banner:

```text
L2 SELECTED SCOPE COMPLETE
L2 PAUSED - CONTINUABLE
L2 BLOCKED - REQUESTED OUTPUTS INCOMPLETE
```

The complete banner states that the selected L2 scope is complete, not that the
workspace has full RE quality. It explicitly reports semantic audit, workspace
synthesis, and exhaustive depth as not run.

For a domain-only request, status may truthfully show:

```text
requested scope: complete
source L2 coverage: intentionally scoped (1/12 domains)
failed requested outputs: 0
```

## Recovery and failure isolation

Adoption and execution use `EventStore` with a protocol-2.4 `EventProtocol`,
`DurableLedger` with a protocol-2.4 typed facade extending the protocol-2.2
receipt decoder, and the existing candidate-capture and projection-replay
primitives. The event envelope, ledger envelope, locking, canonical framing,
idempotent append, and at-most-once dispatch machinery remain shared.

Recovery handles these boundaries idempotently:

1. adoption object copied but no parent-authority bundle committed;
2. parent-authority bundle committed but no imported ledger/event entry;
3. adoption event appended but projection not checkpointed;
4. dispatch leased but not started;
5. dispatch started with no durable observation;
6. provider result captured but candidate inventory incomplete;
7. candidate committed but not certified;
8. certification recorded but artifact not accepted;
9. all requested artifacts accepted but terminal event absent; and
10. terminal event durable but active pointer stale.

The existing at-most-once external-dispatch rule remains. A started dispatch is
never reissued under the same dispatch ID. Indeterminate external execution
uses the existing recovery classification and cannot be disguised as an
authorial or semantic repair.

A failure in one requested domain blocks only its dependency closure. Source
L2 work whose selected dependencies are incomplete remains pending or blocked;
unrelated domains continue. Accepted lower and sibling artifacts are retained
for a later child lineage.

## Materialization and publication boundary

Protocol 2.4 extends `materialize_accepted_l1`, `materialized_path_for`, and the
existing exact-root/projection specifications with L2 cases. It keeps the same
materialization lock, altered-projection quarantine, atomic publication, and
byte-exact rebuild rules. This is an additive layer-aware materializer, not a
new framework.

It materializes immutable run-local L2 JSON, Markdown, and exact-root
projections below the child run. It does not write workspace `re/` or trigger
workspace synthesis.

Materialized L2 is rebuildable from accepted objects and receipts. Deleting a
projection and rebuilding it must produce byte-identical output. The
parent-authority bundle and object-store authorities are not projections and are
never rebuilt from Markdown.

EGR-168 will later synthesize an accepted source-root set. Its design must
consume exact L0/L1/L2 roots and must not make L2 depend on synthesis.

## Telemetry

Existing protocol 2.3 event and usage observations remain the model. L2 adds
layer and adoption dimensions without provider-specific fields:

- parent and lineage run IDs;
- requested target layer;
- source/domain selected scope;
- adopted artifact and byte counts by layer;
- adoption validation duration;
- initial versus shared-retry dispatches;
- result- and artifact-contract retry reasons;
- provider-observed active duration;
- trusted, untrusted, or unavailable token usage;
- reservation charged for unknown/untrusted usage;
- accepted artifacts by layer and scope; and
- zero-dispatch reuse counts.

Telemetry must distinguish deterministic adoption/planning from model-backed
authoring. It must be possible to answer how much L2 reused, how much it
generated, and why any requested output remains incomplete.

## Rejected parallel machinery

The following alternatives are explicitly rejected because Echelon already has
the required authority or durability mechanism:

- a layer catalog beside the artifact-policy and executor catalogs;
- a selector/source index beside `WorkspacePartitionCatalogV1`;
- a new provider adapter, model mapper, result envelope, or usage estimator;
- a second accepted-artifact/adoption receipt hierarchy beside the typed ledger;
- a whole-run staging/rename publisher beside manifest-last run-store creation;
- a second active-run resolver or status cache beside `.current-re` and replay;
- a new planner or budget engine beside the V2 planning and accounting
  contracts; and
- a new materialization framework beside accepted-object projection replay.

The only new semantic authorities are the schema-3 manifest values, the
parent-authority bundle, L2 artifact-policy entries, and the protocol-2.4 event
additions required to report adoption and selected scope. The provider-facing
result envelope and accepted compact claim/evidence artifact schema remain the
L1 contracts; L2 depth comes from layer identity, dependency selection, and
policy, not a second authorial format.

## Verification strategy

### Compatibility

- Pin protocol 2.0 through 2.3 canonical fixtures and identity digests.
- Continue existing protocol 2.3 fixtures using pinned Prosaic bytes.
- Prove schema dispatch rejects invalid schema/protocol pairs.
- Prove no L2 change alters L0/L1 materialization bytes.

### CLI and creation

- Test all valid selector forms and every mutual-exclusion error.
- Reject absent selection, duplicate IDs, unknown IDs, and domain selectors
  spanning multiple sources.
- Reject dirty, changed, incompatible, nonterminal, or uncertified parents
  before visible run creation.
- Prove active-pointer-last and manifest-last behavior under fault injection.
- Prove repeated semantic requests resolve to the existing child.

### Adoption

- Verify the parent-authority bundle, manifest, terminal event, copied
  event-chain prefix, copied ledger-chain prefix, imported receipts, key,
  artifact, dependency, and root hashes independently.
- Reject projections and provider verdicts as adoption authority.
- Reject symlink substitution, path escape, mutation during read, conflicting
  receipts, missing objects, and cyclic dependencies.
- Delete the parent after successful adoption and prove the child can replay
  and materialize from its self-contained proof objects.
- Prove adopted artifact hashes remain identical to the parent's hashes.

### Planning and completion

- Prove only selected missing L2 work enters the queue.
- Prove unrelated and already accepted work causes zero provider dispatches.
- Prove future registered target planning orders missing layers without
  skipping; protocol 2.4 rejects unregistered L3/L4.
- Prove partial source selection cannot claim full-source coverage.
- Prove requested failures block completion while accepted siblings survive.
- Prove explicit partial finalization is the only partial terminal path.

### Prosaic/provider boundary

- Make the mandatory execution-seam proof the first implementation gate.
- Fail that gate if protocol 2.4 copies protocol-2.2 controller, recovery, or
  execution code instead of composing the shared provider/capture substrate.
- Assert `echelon.re-deepener` is installed through normal Prosaic migration.
- Assert inspected frontmatter is pinned and passed unchanged to
  `SquadCliProvider`.
- Exercise Codex, Claude, Copilot, and OpenCode configuration through the
  existing shared-provider harness.
- Add a static regression that no provider adapter ID, provider-specific model
  mapping, direct CLI invocation, or HTTP transport is added by L2.
- Reject missing/malformed `echelon_result`, extra state updates, extra
  candidate files, and invalid authorial JSON through existing contracts.

### Budget and recovery

- Prove per-item attempt dimensions cannot exceed their literal limits.
- Prove token/time authorization does not change semantic identity or attempt
  limits.
- Prove unknown provider usage charges the reservation and remains visible.
- Crash after every adoption, dispatch, capture, certification, acceptance, and
  terminal boundary; continuation must converge without duplicate provider
  execution.

### Installed real-workspace pilot

After focused and complete repository tests pass:

1. install Echelon from the implementation branch;
2. migrate a disposable clean real workspace through normal Prosaic tooling;
3. run L0/L1 with the configured Codex provider if no compatible baseline is
   already available;
4. deepen one real source/domain to L2;
5. inspect events, ledger, parent-authority bundle, candidates, status, and
   telemetry;
6. repeat the same command and prove zero provider dispatches;
7. deepen a second scope and prove the first L2 artifact is adopted, not
   regenerated; and
8. confirm every source repository remains clean and unchanged.

The release gate is the focused RE v2 matrix plus the complete repository
suite. A real pilot is evidence, not a substitute for deterministic tests.

## Implementation boundaries

Production changes should remain within these responsibilities:

- a first, disposable execution-seam proof which must pass before L2 feature
  implementation proceeds;
- CLI parsing/routing for `re deepen`;
- schema-3 manifest and selection/lineage values;
- deterministic parent resolver and adopter;
- additive artifact-policy and shared planning-primitive extensions;
- L2 deterministic evidence/context/root producers;
- L2 authorial normalization and deterministic certification;
- the neutral Prosaic deepener role;
- status/materialization/telemetry extensions; and
- compatibility, recovery, and live-pilot tests.

Existing components remain authoritative:

| Responsibility | Required existing component |
|---|---|
| Prosaic loading and metadata | `ProsaicPromptLoader`, `ProsaicCommandArtifact` |
| Provider selection and execution | `SquadCliProvider`, `AICodingCliProvider` implementations |
| Result envelope | `EchelonResultContract` |
| Source authority | clean-Git composite snapshot and pinned snapshot reader |
| Object authority | existing `ObjectStore` |
| Immutable input publication | `ReV2Paths` and the manifest-last `create_protocol_22_run_store` primitives |
| Parent resolution and activation | `resolve_current_re_run`, `_new_re_v2_run_id`, `_activate_re_v2_run` |
| Selection authority | `WorkspacePartitionCatalogV1` source/domain descriptors |
| Planning identities | `ArtifactScope`, `ArtifactKeyV2`, `WorkTemplateV2`, `WorkItemV2` |
| Delta planning | `PlanningAuthorityV2`, `PlanningBudgetV2`, `PlanDecisionV2`, `plan_next_v22` algorithm |
| Policy and execution authority | artifact-policy and executor-contract catalogs |
| Events and replay | `EventStore`, `EventProtocol`, and the existing projection model |
| Ledger | `DurableLedger` plus existing certification/assessment/acceptance receipts |
| Candidate durability | existing staging, inventory, commit, and recovery stores |
| Accounting | `BudgetPolicyV2`, `evaluate_budget_v22`, reservation and normalized usage types |
| Acceptance | controller-owned certifier and ledger |
| Materialization | existing exact projection specs, locking, quarantine, and rebuild path |
| Status routing | `render_v2_status` and the protocol-2.2 status-document/render pattern |

If implementation appears to require replacing one of those components, work
stops and the design is revisited. L2 is an extension of the proven kernel, not
a second RE system.

## Completion criteria

The L2 increment is complete only when:

1. the execution-seam proof demonstrates reuse without a forked controller,
   recovery engine, provider path, or candidate store;
2. protocol 2.4 creates schema-3 child runs without changing old protocols;
3. lower-layer adoption is self-contained, hash-verified, and replayable;
4. the CLI supports the approved explicit selectors and idempotent resolution;
5. L2 schedules only missing work over exact L0/L1 dependencies;
6. all authorial calls use the neutral Prosaic deepener through the existing
   shared provider path;
7. no new provider adapter or provider-specific branch exists;
8. attempts are bounded and no semantic/whole-domain repair loop exists;
9. requested-scope completion and partial source coverage are reported
   truthfully;
10. crash recovery performs no duplicate external dispatch;
11. repeated and unrelated deepening produce zero unnecessary provider calls;
12. the installed real-workspace pilot preserves clean source Git and records
    usable telemetry; and
13. compatibility, focused RE v2, and complete repository gates pass.

Passing these criteria establishes selective L2 depth. It does not establish
semantic audit, workspace synthesis, exhaustive L4 coverage, atomic repair,
full RE quality, or default-engine readiness.
