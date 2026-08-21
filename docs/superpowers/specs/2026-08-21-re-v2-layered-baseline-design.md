# RE v2 Layered Baseline Design

**Date:** 2026-08-21  
**Finding:** EGR-165  
**Status:** Revised after architecture review; implementation pending

## Purpose

EGR-165 turns the pinned RE v2 execution kernel into a useful layered system.
It adds a bounded, controller-certified run-local L1 compact baseline above
deterministic L0 inventory without introducing the expensive semantic-audit,
repair, or workspace-synthesis loops that remain assigned to later findings.

The completed increment must prove the architectural property that motivated
EGR-165: changing a higher-detail content policy adds or replaces only the
affected higher-layer artifact. It must not make accepted lower-layer bytes
stale merely because execution limits, provider choice, model choice, or a
different depth policy changed.

An accepted L1 result is useful on its own, but it is not a full-quality or
exhaustive reverse-engineering outcome. The operator-facing state is **L1
COMPACT BASELINE COMPLETE**, with semantic audit and workspace synthesis
explicitly reported as not run.

## Scope

This increment includes:

- protocol 2.2 scoped artifact and work-template identity;
- deterministic immutable workspace, source, and domain partition inputs;
- a production L0+L1 artifact dependency graph;
- a bounded `echelon.re-baseliner` agent contract;
- deterministic structural and source-evidence certification;
- controller-generated per-source baseline roots;
- immutable run-local L1 materialization;
- recovery, status, and final-banner support; and
- backward-compatible continuation of protocol 2.0 and 2.1 runs.

This increment excludes:

- cross-run or v1 artifact adoption, owned by EGR-166;
- semantic audit epochs and semantic repair, owned by EGR-167;
- workspace synthesis and workspace `re/` publication, owned by EGR-168;
- selective source/domain deepening, owned by EGR-169; and
- atomic element repair, owned by EGR-170.

## Architectural Choice

L1 uses a domain-first bounded DAG. Each provider dispatch owns exactly one
source or source-domain artifact. A deterministic controller step assembles an
accepted source root from exact accepted hashes.

This is preferred over a source-wide dispatch because failure and reuse remain
domain-local. It is preferred over a two-pass analyzer/specifier flow because
L1 is intentionally compact and must not reproduce v1's repeated whole-domain
generation cost before stable audit epochs exist.

## Immutable Protocol Boundary

New layered runs use engine protocol `2.2`. Existing protocol `2.0` and `2.1`
runs keep their current immutable manifests, identity schema, deterministic L0
graph, and continuation behavior. Echelon never migrates or reinterprets their
receipts in place.

Protocol 2.2 uses run-manifest schema 2 because it adds partition-input,
artifact-policy-catalog, and executor-contract-catalog authority. Protocol 2.0
and 2.1 retain run-manifest schema 1. Loading dispatches on the exact supported
schema/protocol pair; schema 1 canonical bytes are never decoded and re-emitted
as schema 2. The ledger record envelope remains version 1, while nested scoped
artifact keys carry `identity_schema_version: 2`.

Protocol 2.2 continues to require the protocol 2.1 clean-Git composite source
snapshot. Before writing the run manifest, Echelon also runs the existing
deterministic domain-discovery rules against each source inside that snapshot.
It writes a canonical workspace partition catalog containing every source ID,
source path, presentation domain ID, stable domain key, domain root, file count,
line count, partition algorithm version, and source snapshot ID. Its hash
remains a run-level recovery input; it is not copied into every artifact key.

The catalog also contains independently hashed descriptors:

- `source_content_id`: the selection-policy version and complete source-root-
  relative file path/mode/content-hash set; declared workspace location is not
  content identity;
- `source_partition_id`: the source ID, partitioner protocol, and sorted stable
  domain-key/root/owned-path descriptor set, excluding file content hashes;
- `domain_key`: a stable safe ID derived from source ID, canonical domain root,
  and ownership-policy version, independent of sequential presentation
  numbering and sibling insertion;
- `domain_content_id`: the ownership-policy version, domain-root-relative owned
  file set, and explicitly enumerated source-level supporting-artifact set; and
- `domain_partition_id`: the exact partitioner and ownership protocols, stable
  domain key, canonical root, and owned/supporting path sets, excluding file
  content hashes.

Changing a sibling source does not change these IDs. Changing one domain does
not change another domain's IDs unless a deliberately shared supporting
artifact in that domain's declared read set also changed.

The workspace catalog and its descriptors are immutable run inputs rather than
provider output. This allows the complete graph to be constructed and pinned
before any provider dispatch. L0 partition and inventory artifacts materialize
and certify those exact inputs; they do not discover a second partition.

Run creation creates the unique `v2/` directory with no-clobber semantics,
writes and fsyncs the canonical catalog under `v2/inputs/`, then publishes the
schema-2 manifest last using the existing no-clobber hard-link commit marker.
The manifest pins the catalog hash and relative path. The active-run pointer is
updated only after the manifest and directory metadata are durable. A store
without that final manifest remains explicitly incomplete. Recovery rejects a
missing, noncanonical, unsafe, or hash-mismatched catalog before replay or
provider dispatch.

## Scoped Artifact Identity

Protocol 2.2 introduces an explicit scope value:

```text
ArtifactScope = {
  source_id,
  domain_key | null,
  content_id | null
}
```

`domain_key` is null for source-scoped artifacts and required for domain-scoped
artifacts. The human-facing sequential `domain_id` remains pinned descriptor
metadata but is not artifact identity. `content_id` is null for a partition-only
artifact and otherwise the corresponding `source_content_id` or
`domain_content_id`, so content-aware keys are affected only by files inside the
artifact's declared read set.

The protocol 2.2 artifact key is:

```text
ArtifactKey = {
  identity_schema_version,
  scope,
  partition_id | null,
  artifact_kind,
  layer,
  producer_protocol_version,
  layer_policy_hash,
  dependency_hashes
}
```

`partition_id` is null when an artifact does not depend on partition shape,
`source_partition_id` for source-scoped partition-aware artifacts, and
`domain_partition_id` for domain-scoped artifacts. The workspace-wide snapshot
and partition-catalog IDs remain manifest/recovery authority, but are excluded
from independently reusable scoped artifact keys.

Content-only edits therefore change `content_id` without changing partition
identity. Added, removed, or reassigned paths change the relevant partition ID.
The artifact-policy catalog declares whether each artifact kind requires or
forbids content and partition IDs; graph/model validation rejects every other
combination, so nullability cannot bypass identity inputs.

The same scope is part of `WorkTemplate` identity. Logical-output uniqueness is
the tuple `(scope, artifact_kind, layer)`, so two domains may produce the same
artifact kind without collision and presentation-ID renumbering does not stale
unchanged domain artifacts.

`identity_schema_version` lets model decoding and canonical serialization
preserve the exact legacy representation of protocol 2.0/2.1 receipts while
using explicit scope for protocol 2.2. Legacy records gain no inferred fields
and therefore retain their existing identities and hash-chain validity.

`layer_policy_hash` is derived from the artifact kind, layer, and pinned
content-policy version. It changes only when required artifact content changes.
Extractor/producer protocol remains independently represented by
`producer_protocol_version`. Provider, model, token ceiling, time ceiling, and
attempt authorization are execution controls and are deliberately absent from
artifact identity.

## Pinned Policy and Executor Catalogs

Protocol 2.2 replaces the single implicit layer-version assumption with a
canonical artifact-policy catalog. Each graph template resolves exactly one
catalog entry by layer and artifact kind. The catalog pins:

- content-policy version;
- artifact schema version;
- maximum canonical JSON and rendered Markdown sizes;
- required content sections;
- evidence and ownership rules; and
- producer protocol and result-contract versions.

The initial L1 policy is `compact-v1`. It is the only L1 content policy exposed
by EGR-165. Custom depth, source selection, and domain selection are deferred to
EGR-169.

At run creation Echelon resolves the L1 provider through the normal workspace
configuration cascade, including `.echelon/config.yml` `llm.cli` and its
provider-specific settings. Protocol 2.2 does not add a separate hidden
provider selector. Resolution must succeed before the immutable manifest or
active-run pointer is written.

The manifest pins an executor-contract catalog by producer family:

- deterministic in-process execution for L0 source inventory, L0 source
  partition, L0 domain inventory, and L1 source-root assembly; and
- the configured CLI or API provider adapter for L1 source and domain
  baselines.

Each catalog entry contains the resolved provider/adapter ID, adapter contract
version, producer protocol, result-contract ID, execution mode, and a canonical
contract hash. Model choice and resource ceilings are recorded as execution
metadata but remain outside artifact identity. Recovery rebuilds the registry
from this catalog and rejects missing or changed adapters before dispatch.
Execution observations are checked against the registration for their exact
work item rather than against one run-wide provider name.

Executor validation occurs before dispatch and again at lease execution. A
provider or model change in a later run that satisfies the same pinned
producer/result contract does not change artifact keys; EGR-166 will define
when receipts produced by another run may be adopted.

## Production Artifact Graph

For every declared source, the graph contains:

```text
L0 source-inventory ------+--> L1 source-overview ---------------------+
L0 source-partition ------+                                             |
                                                                        |
L0 domain-inventory A --------> L1 domain-baseline A -------------------+
L0 domain-inventory B --------> L1 domain-baseline B -------------------+--> L1 source-baseline-root
... --------------------------------------------------------------------+
```

The source inventory is keyed only by `source_content_id`. The source partition
uses a null content ID and is keyed only by `source_partition_id`. Each domain
inventory is keyed independently by `domain_content_id` and
`domain_partition_id`, and materializes the exact owned/supporting file
inventory that the L1 producer may cite. A domain baseline depends only on its
exact accepted domain-inventory hash, so changes in an unrelated domain do not
invalidate it.

The source overview depends on source inventory and source partition. It
describes only bounded source-wide structure; it does not duplicate domain
specifications or perform workspace synthesis.

`source-baseline-root` is generated in process after the source overview and
every selected domain baseline is accepted. Its canonical JSON records the
source scope, partition identity, policy hash, exact overview hash, sorted
stable-domain-key-to-artifact-hash map, corresponding certification receipt
IDs, and the pinned presentation-ID map. It contains no generated prose.

A changed L1 policy produces different L1 keys and source roots while leaving
all L0 keys unchanged. A changed source file invalidates only L0/L1 artifacts
whose declared read set contains that file, followed by source overview/root as
required by their dependency hashes. A changed partition invalidates only its
source partition, affected domain inventories, and their downstream closure.
Later EGR-166 work may adopt independently certified matching receipts into a
new run; EGR-165 itself performs no cross-run lookup or object reuse.

## Creation and Goal Semantics

For protocol 2.2, `echelon re run --engine v2` requests the fixed `baseline`
goal by default. Its dependency closure contains all required L0 and L1 nodes
for every declared source and domain. `--goal inventory` remains available as
an explicit L0-only diagnostic; `--goal baseline` is the explicit form of the
default. No other goals, source filters, domain filters, or depth profiles are
accepted by EGR-165.

`--shadow` builds, validates, and explains the exact selected graph without
provider dispatch. It still resolves and validates the configured L1 adapter
when the selected goal is `baseline`, because a shadow run must not pin an
executor contract that cannot later be recovered. Continuation always uses the
immutable requested goal and rejects creation-only goal switches.

This fixed goal selector preserves an inexpensive deterministic diagnostic
without pre-empting EGR-169's selective deepening interface.

## L1 Baseline Content Contract

The new neutral `echelon.re-baseliner` agent produces one candidate per
dispatch. It follows the dispatcher/protocol split: the controller supplies the
exact context pack and scope, while the agent file owns invariant production
and result-contract rules.

The controller builds a scoped context bundle containing only:

- the immutable source or domain read-set view;
- canonical L0 dependency objects;
- the pinned `compact-v1` policy; and
- explicitly supplied controller metadata.

The agent contract instructs the provider to read that bundle and write only
its candidate directory. Providers that support an enforceable filesystem
sandbox receive the bundle as their read authority and the candidate directory
as their write authority. For providers without equivalent host isolation,
this remains a behavioral execution constraint; acceptance authority still
requires every factual claim and evidence reference to resolve inside the
pinned bundle. EGR-165 does not claim that an unrestricted third-party CLI was
technically prevented from inspecting other host paths.

The agent never writes controller state, the ledger, events, materialized
output, workspace synthesis, or sibling artifacts. The controller rejects any
candidate tree containing files outside the one-file result contract.

Each provider candidate contains exactly one canonical file:

- `baseline.json`, the machine-readable metadata and content contract.

The controller renders `baseline.md` deterministically from accepted JSON
during materialization. Markdown is therefore a derived projection, not a
second provider-authored artifact or certification input. This avoids duplicate
model output and an otherwise unverifiable narrative-equivalence contract.

`baseline.json` identifies artifact kind, layer, source/domain scope, stable
domain key, pinned presentation domain ID, content/partition IDs, policy, and
dependencies. Domain baselines cover bounded responsibilities, entry points,
core behavior and failure paths, state/data, external contracts, tests,
operational constraints, and explicit unknowns.
Source overviews cover source purpose, runtime shape, domain catalog, major
entry points, and intra-source boundaries without restating domain detail.

The `compact-v1` policy limits domain-baseline JSON to 32 KiB and source-
overview JSON to 48 KiB of canonical UTF-8. It limits derived Markdown to 96
KiB. Required content surfaces are represented as structured arrays; an empty
surface requires a bounded `absence_reason` rather than invented content.

Every factual claim that requires source evidence carries a normalized
bundle-relative `path:line` or `path:start-end` reference. The result contract
echoes scope, dependency hashes, produced files, and evidence references.
Provider-authored verdicts are evidence only; acceptance authority remains with
the controller.

## Execution and Budget Behavior

Each L1 work item allows one artifact-generation attempt and one retry only for
a malformed or missing result contract. EGR-165 introduces no content repair or
semantic repair loop. A structurally valid but rejected candidate pauses the
scoped item and reports normalized diagnostics.

Global token and active-time ceilings remain independent budget dimensions.
Raising them authorizes more execution but does not change work-item or
artifact identity. The controller remains single-dispatch in this increment;
independent domain nodes make bounded parallel execution possible later without
changing artifact contracts.

Accepted siblings are never discarded when another domain pauses. Continuing
the run replays authority and schedules only the unresolved dependency delta.

## Controller Certification

The L1 certifier is deterministic and controller-owned. It validates:

- exact scope, artifact kind, layer, policy, and dependency hashes;
- canonical JSON artifact schema;
- required compact-baseline sections and maximum output size;
- canonical, in-bounds evidence references;
- existence of every cited path and line in the immutable snapshot;
- source/domain ownership of every cited path;
- absence of sibling-source or sibling-domain evidence; and
- controller-computed referenced-file coverage and required-surface presence.

Candidate-declared coverage is never authoritative. The certifier computes the
accepted coverage record from the pinned inventory and validated evidence set.
It reports the literal referenced-file numerator/denominator and the presence
of required compact-baseline surfaces. It does not infer line coverage, behavior
coverage, or semantic completeness from citation count.

Protocol 2.2 certification uses an identity-schema-2 key containing the
artifact hash, full artifact-key identity, verifier ID/version, scoped content
ID, and nullable audit-epoch ID. The controller-authored receipt carries an
`assessment` object with referenced/inventory file counts, required-surface
presence, normalized diagnostics, and semantic status. Protocol 2.0/2.1
certification keys and receipts retain their existing canonical schema.

The certifier does not judge whether prose correctly interprets behavior. Every
accepted L1 certification therefore records:

```text
semantic_status: unaudited
```

EGR-167 may later add a separately keyed semantic-audit overlay and promote the
audited outcome without regenerating unchanged L1 bytes.

## Materialization

Artifact objects and receipts remain authoritative. After acceptance, the
controller atomically materializes the verified object by the filesystem-safe
hex suffix of its artifact hash:

```text
runs/<run-id>/v2/materialized/L1/
  sources/<source-id>/
    overview/<sha256-hex>/{baseline.json,baseline.md}
    domains/<domain-id>/<sha256-hex>/{baseline.json,baseline.md}
    root/<sha256-hex>.json
```

Materialized paths are immutable projections, not authority. Recovery verifies
their contents against the object store. A missing projection is rebuilt. An
altered or unsafe projection is atomically moved to a run-local quarantine path
without following links, the quarantine move is reported in status, and the
verified object is rematerialized through a no-clobber atomic publish.
Unexpected symlinks, traversal, special files, quarantine failure, and
content/hash mismatches fail closed before provider dispatch. Quarantined bytes
remain recoverable and are never treated as authority.

EGR-165 writes nothing below workspace `re/`. Workspace synthesis, tracked
publication, and a canonical workspace generation remain EGR-168 concerns.

## Status and Terminal Semantics

Human and JSON status report:

- accepted and required L0/L1 counts;
- per-source accepted and required domain counts;
- literal referenced-file coverage and required-surface presence;
- current or blocked scoped work-item identity;
- normalized rejection or budget reason;
- exact accepted source-root hash and materialized path;
- `semantic audit: not run`; and
- `workspace synthesis: not run`.

When all requested L0 and L1 nodes are accepted, the final banner is:

```text
L1 COMPACT BASELINE COMPLETE
```

It must also state that semantic audit, workspace synthesis, selective
deepening, and exhaustive RE were not performed. Neither status nor events may
label this outcome `full RE complete`, `full quality`, or an equivalent claim.

A rejected or budget-blocked domain leaves the run continuable. A source root
cannot be assembled until its overview and every required domain baseline are
accepted. Other sources may retain accepted roots independently.

## Recovery and Compatibility

Recovery selects the graph builder and identity decoder from the immutable
engine protocol. For protocol 2.2 it reconstructs the exact graph from:

- the validated composite source snapshot;
- the pinned workspace partition catalog and independently hashed source/domain
  descriptors;
- requested goals;
- the artifact-policy catalog; and
- executor contracts.

Recovery then validates and replays the event log, ledger, candidate state, and
materialized projection. A mismatch between reconstructed templates and pinned
inputs fails before provider execution.

Protocol 2.0 and 2.1 recovery continues to construct the legacy deterministic
L0 graph and accepts only legacy identity records. Protocol 2.2 accepts only
scoped identity records. No protocol reads another protocol's records as
current authority.

## Verification Strategy

Implementation follows test-driven development. The acceptance matrix covers:

1. Canonical protocol 2.0/2.1 serialization and identity remain byte-for-byte
   stable after protocol 2.2 support is added.
2. Protocol 2.2 rejects missing, unsafe, duplicate, or contradictory source and
   domain scopes.
3. Changing `compact-v1` to a different L1 policy changes L1 keys and roots but
   leaves every L0 key unchanged.
4. Changing one sibling source leaves all scoped keys for untouched sources
   unchanged; changing one domain leaves unrelated domain inventory and
   baseline keys unchanged.
5. Inserting a sibling domain may renumber presentation domain IDs but leaves
   stable keys and artifacts for unchanged domain roots unchanged.
6. A changed shared supporting artifact invalidates exactly the domain read sets
   that explicitly contain it.
7. A content-only edit changes the relevant content IDs while preserving
   partition IDs; path membership or ownership changes alter partition IDs.
8. Partition generation and graph reconstruction are deterministic across
   input ordering and process restart.
9. Each domain baseline depends only on its exact accepted domain-inventory
   hash, and each source root depends on the exact overview and domain hashes.
10. Provider/model and resource-limit changes do not alter artifact keys; no
   test claims cross-run adoption before EGR-166.
11. Run creation resolves and pins the configured L1 provider before manifest or
    active-pointer mutation; recovery rejects missing or incompatible adapters.
12. The default v2 goal plans the complete baseline closure, inventory-only
    remains deterministic, and shadow mode performs zero provider dispatches.
13. The baseliner result contract rejects a missing `baseline.json`, wrong
   scope, wrong dependencies, and extraneous candidate files.
14. Certification rejects noncanonical or oversize JSON, path traversal,
   symlinks, special files, out-of-scope evidence, and nonexistent lines.
15. Deterministic Markdown rendering is byte-stable, bounded, and derived only
   from accepted canonical JSON.
16. A malformed result receives at most one contract retry; certification
   rejection does not enter a repair loop.
17. Crash/restart at candidate persistence, certification, ledger append, and
   materialization boundaries produces the same replayed plan and accepted
   roots without duplicate provider execution.
18. Corrupt materialization is quarantined without following links and rebuilt
   from verified object authority before any provider dispatch.
19. Status and final banners distinguish L1 completion from semantic audit,
   synthesis, selective depth, and full-quality completion.
20. A clean multi-source fixture completes with independently accepted domain
   artifacts and exact source roots while writing nothing below workspace
   `re/`.
21. The established v1-isolation suite proves that v1 dispatch, continuation,
   publication, and status remain unchanged.

## Completion Criteria

EGR-165 is complete only when a live protocol 2.2 fixture run produces
controller-certified L1 source and domain artifacts, exact source roots,
recoverable run-local materialization, and an unambiguous compact-baseline
banner. Graph fixtures must prove that changing only the L1 content policy
preserves identical L0 keys and that sibling source/domain changes preserve
unaffected scoped keys. Operational adoption of those matching keys remains an
EGR-166 completion criterion.

EGR-165 completion does not make RE v2 the default and does not satisfy the
full-quality cutover condition. EGR-166 through EGR-170 remain required.
