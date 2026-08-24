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
- layer-policy catalog hash;
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

For every adopted artifact, the child retains a canonical proof containing:

```yaml
schema_version: 1
source_run_id: <safe run id>
source_manifest_hash: sha256:...
source_event_chain_hash: sha256:...
source_terminal_event_hash: sha256:...
source_ledger_chain_hash: sha256:...
source_ledger_entry_hash: sha256:...
source_certification_receipt_hash: sha256:...
artifact_key_hash: sha256:...
artifact_hash: sha256:...
dependency_hashes: [sha256:...]
```

The proof, source manifest bytes, authenticated event-chain bytes through the
terminal envelope, authenticated ledger-chain bytes through the source entry,
certification receipt, artifact-key bytes, and artifact bytes are copied as
verified content-addressed objects. The child ledger appends an
`artifact_adopted` entry referencing those hashes. Copying the authenticated
chain prefixes lets the child revalidate provenance even after the parent run
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
and plugs into the existing executor, producer, verifier, event, ledger, and
status registration seams.

Shared canonical value modules may gain schema-3 types or strictly additive L2
branches only when protocol-2.0-through-2.3 canonical fixtures prove that every
old input has identical bytes, validation outcome, identity, and behavior. L2
must not copy the execution kernel into a second controller. If the existing
registration seams cannot host L2 without changing a pinned protocol-2.3
authority, implementation stops and this design is revisited.

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
- Source and domain IDs are exact IDs from the parent partition, not globs.
- Repeated source/domain values are rejected instead of silently deduplicated.
- `--from-run` is optional. Without it, Echelon resolves the current deepest
  compatible completed run in the active lineage.
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
normalized selection, target layer, and layer-policy catalog. The direct parent
is recorded provenance but does not make an otherwise identical request new.
Token/time ceilings are operational authorization and do not affect identity.

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

Files are opened with the existing no-follow and stable-stat patterns. Any
change observed between validation and copy aborts child creation. Adoption
never reads source evidence from the live checkout; provider work reads only
the copied immutable snapshot and adopted objects.

## Child creation and active pointer

Child creation follows manifest-last durability:

1. create a unique staging directory below the run root;
2. write and fsync immutable input catalogs and verified adoption objects;
3. write and fsync the schema-3 manifest last;
4. atomically rename staging to the final run directory;
5. append `run_created` and adoption events through the normal hash-chained
   event store;
6. derive and verify the initial projection; and
7. update the workspace active pointer last.

Failure before the final rename leaves no visible run. Failure after the rename
but before active-pointer update leaves a discoverable recoverable run and does
not displace the prior active run. Recovery is idempotent and never repeats a
completed adoption copy.

The child manifest records an adoption-root hash over the sorted adoption-proof
hashes. Projection replay recomputes it. A mismatch fails closed before
planning or provider dispatch.

## Layer catalog and dependency graph

Protocol 2.4 stores one closed layer catalog. Layer selection is not inferred
from filenames or prose.

### Registered L2 work

For each selected domain:

```text
adopted L0 domain inventory
  + adopted L1 domain evidence pack
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
and write-only candidate authority. Prosaic inspection supplies the exact
artifact bytes and interpreted metadata pinned into the child object store.
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
authorization. Raising either ceiling appends a budget event and resumes the
same semantic child identity. It does not increase provider, generation,
result-contract, artifact-contract, or future semantic-round limits.

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

`echelon re status` and `--json` add:

- protocol and manifest schema;
- direct parent and lineage root run IDs;
- parent manifest and terminal-event hashes;
- source snapshot identity;
- target layer and normalized requested scope;
- adopted artifact/proof counts by layer;
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

Adoption and execution use the existing append-only event, candidate capture,
ledger, and projection-replay primitives.

Recovery handles these boundaries idempotently:

1. adoption object copied but no adoption proof committed;
2. adoption proof committed but no ledger/event entry;
3. adoption event appended but projection not checkpointed;
4. dispatch leased but not started;
5. dispatch started with no durable observation;
6. provider result captured but candidate inventory incomplete;
7. candidate committed but not certified;
8. certification recorded but artifact not accepted;
9. all requested artifacts accepted but terminal event absent; and
10. terminal event durable but active pointer/status cache stale.

The existing at-most-once external-dispatch rule remains. A started dispatch is
never reissued under the same dispatch ID. Indeterminate external execution
uses the existing recovery classification and cannot be disguised as an
authorial or semantic repair.

A failure in one requested domain blocks only its dependency closure. Source
L2 work whose selected dependencies are incomplete remains pending or blocked;
unrelated domains continue. Accepted lower and sibling artifacts are retained
for a later child lineage.

## Materialization and publication boundary

Protocol 2.4 materializes immutable run-local L2 JSON, Markdown, and exact-root
projections below the child run. It does not write workspace `re/` or trigger
workspace synthesis.

Materialized L2 is rebuildable from accepted objects and receipts. Deleting a
projection and rebuilding it must produce byte-identical output. Adoption
proofs and object-store authorities are not projections and are never rebuilt
from Markdown.

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

- Verify manifest, terminal event, copied event-chain prefix, copied ledger-chain
  prefix, receipt, key, artifact, dependency, and root hashes independently.
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
5. inspect events, ledger, adoption proofs, candidates, status, and telemetry;
6. repeat the same command and prove zero provider dispatches;
7. deepen a second scope and prove the first L2 artifact is adopted, not
   regenerated; and
8. confirm every source repository remains clean and unchanged.

The release gate is the focused RE v2 matrix plus the complete repository
suite. A real pilot is evidence, not a substitute for deterministic tests.

## Implementation boundaries

Production changes should remain within these responsibilities:

- CLI parsing/routing for `re deepen`;
- schema-3 manifest and selection/lineage values;
- deterministic parent resolver and adopter;
- layer-aware policy/graph extensions;
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
| Events and replay | existing hash-chained event store/projection model |
| Candidate durability | existing staging, inventory, commit, and recovery stores |
| Accounting | existing reservation and normalized usage types |
| Acceptance | controller-owned certifier and ledger |
| Status routing | existing protocol-selected status surface |

If implementation appears to require replacing one of those components, work
stops and the design is revisited. L2 is an extension of the proven kernel, not
a second RE system.

## Completion criteria

The L2 increment is complete only when:

1. protocol 2.4 creates schema-3 child runs without changing old protocols;
2. lower-layer adoption is self-contained, hash-verified, and replayable;
3. the CLI supports the approved explicit selectors and idempotent resolution;
4. L2 schedules only missing work over exact L0/L1 dependencies;
5. all authorial calls use the neutral Prosaic deepener through the existing
   shared provider path;
6. no new provider adapter or provider-specific branch exists;
7. attempts are bounded and no semantic/whole-domain repair loop exists;
8. requested-scope completion and partial source coverage are reported
   truthfully;
9. crash recovery performs no duplicate external dispatch;
10. repeated and unrelated deepening produce zero unnecessary provider calls;
11. the installed real-workspace pilot preserves clean source Git and records
    usable telemetry; and
12. compatibility, focused RE v2, and complete repository gates pass.

Passing these criteria establishes selective L2 depth. It does not establish
semantic audit, workspace synthesis, exhaustive L4 coverage, atomic repair,
full RE quality, or default-engine readiness.
