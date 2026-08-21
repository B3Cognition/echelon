# RE v2 Layered Baseline Design

**Date:** 2026-08-21  
**Finding:** EGR-165  
**Status:** Approved design; implementation pending

## Purpose

EGR-165 turns the pinned RE v2 execution kernel into a useful layered system.
It adds a bounded, publishable L1 compact baseline above deterministic L0
inventory without introducing the expensive semantic-audit, repair, or
workspace-synthesis loops that remain assigned to later findings.

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
- a deterministic, immutable source/domain partition input;
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

Protocol 2.2 continues to require the protocol 2.1 clean-Git composite source
snapshot. Before writing the run manifest, Echelon also runs the existing
deterministic domain-discovery rules against each source inside that snapshot.
It writes one canonical partition document containing every source ID, source
path, domain ID, domain root, file count, line count, partition algorithm
version, and source snapshot ID. The content hash of this document is the
`partition_manifest_id`.

The partition document is an immutable run input rather than provider output.
This allows the complete artifact graph to be constructed and pinned before
any provider dispatch. The L0 domain-partition artifact materializes and
certifies that exact input; it does not discover a second partition.

## Scoped Artifact Identity

Protocol 2.2 introduces an explicit scope value:

```text
ArtifactScope = {
  source_id,
  domain_id | null
}
```

`domain_id` is null for source-scoped artifacts and required for domain-scoped
artifacts. The enclosing partition manifest binds a domain ID to its immutable
root and inventory.

The protocol 2.2 artifact key is:

```text
ArtifactKey = {
  identity_schema_version,
  source_snapshot_id,
  partition_manifest_id,
  scope,
  artifact_kind,
  layer,
  producer_protocol_version,
  layer_policy_hash,
  dependency_hashes
}
```

The same scope is part of `WorkTemplate` identity. Logical-output uniqueness is
the tuple `(scope, artifact_kind, layer)`, so two domains may produce the same
artifact kind without collision.

`identity_schema_version` lets model decoding and canonical serialization
preserve the exact legacy representation of protocol 2.0/2.1 receipts while
using explicit scope for protocol 2.2. Legacy records gain no inferred fields
and therefore retain their existing identities and hash-chain validity.

`layer_policy_hash` is derived from the artifact kind, layer, and pinned
content-policy version. It changes only when required artifact content changes.
Provider, model, token ceiling, time ceiling, and attempt authorization are
execution controls and are deliberately absent from artifact identity.

## Pinned Policy and Executor Catalogs

Protocol 2.2 replaces the single implicit layer-version assumption with a
canonical artifact-policy catalog. Each graph template resolves exactly one
catalog entry by layer and artifact kind. The catalog pins:

- content-policy version;
- artifact schema version;
- maximum candidate size;
- required content sections;
- evidence and ownership rules; and
- producer protocol and result-contract versions.

The initial L1 policy is `compact-v1`. It is the only L1 content policy exposed
by EGR-165. Custom depth, source selection, and domain selection are deferred to
EGR-169.

The manifest also pins executor contracts by producer family:

- deterministic in-process execution for L0 inventory, L0 partition
  materialization, and L1 source-root assembly; and
- the configured CLI or API provider adapter for L1 source and domain
  baselines.

Executor validation occurs before dispatch and again at lease execution. A
provider or model change that satisfies the same pinned producer/result
contract does not invalidate accepted artifacts.

## Production Artifact Graph

For every declared source, the graph contains:

```text
L0 source-inventory -------------------+--> L1 source-overview --------+
L0 domain-partition -------------------+                               |
                                      +--> L1 domain-baseline A -------+
                                      +--> L1 domain-baseline B -------+--> L1 source-baseline-root
                                      +--> ... -------------------------+
```

The source inventory and domain partition are source-scoped. Each domain
baseline is scoped to one exact source/domain pair. The source overview is
source-scoped and describes only bounded source-wide structure from L0 inputs;
it does not duplicate domain specifications or perform workspace synthesis.

`source-baseline-root` is generated in process after the source overview and
every selected domain baseline is accepted. Its canonical JSON records the
source scope, partition identity, policy hash, exact overview hash, and sorted
domain-ID-to-artifact-hash map. It contains no generated prose.

A changed L1 policy produces different L1 keys and source roots while leaving
the L0 keys unchanged. A changed source snapshot or partition invalidates the
affected dependency closure. Later EGR-166 work may adopt independently
certified matching receipts into a new run; EGR-165 itself performs no
cross-run lookup.

## L1 Baseline Content Contract

The new neutral `echelon.re-baseliner` agent produces one candidate per
dispatch. It follows the dispatcher/protocol split: the controller supplies the
exact context pack and scope, while the agent file owns invariant production
and result-contract rules.

The agent may read only:

- the immutable snapshot path;
- the owned source or domain root;
- canonical L0 dependency objects;
- the pinned `compact-v1` policy; and
- explicitly supplied controller metadata.

It may write only its candidate directory. It never writes controller state,
the ledger, events, materialized output, workspace synthesis, or sibling
artifacts.

Each candidate is a canonical tree containing:

- `baseline.json`, the machine-readable contract; and
- `baseline.md`, the bounded human-readable view.

Both files identify the same artifact kind, layer, source/domain scope,
snapshot, partition, policy, and dependencies. Domain baselines cover bounded
responsibilities, entry points, core behavior and failure paths, state/data,
external contracts, tests, operational constraints, and explicit unknowns.
Source overviews cover source purpose, runtime shape, domain catalog, major
entry points, and intra-source boundaries without restating domain detail.

Every factual claim that requires source evidence carries a normalized
snapshot-relative `path:line` reference. The result contract echoes scope,
dependency hashes, produced files, and evidence references. Provider-authored
verdicts are evidence only; acceptance authority remains with the controller.

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
- artifact schema and agreement between JSON and Markdown;
- required compact-baseline sections and maximum output size;
- canonical, in-bounds evidence references;
- existence of every cited path and line in the immutable snapshot;
- source/domain ownership of every cited path;
- absence of sibling-source or sibling-domain evidence; and
- controller-computed evidence and inventory coverage metadata.

Candidate-declared coverage is never authoritative. The certifier computes the
accepted coverage record from the pinned inventory and validated evidence set.
That record describes observed evidence coverage; it does not claim semantic
completeness.

The certifier does not judge whether prose correctly interprets behavior. Every
accepted L1 artifact therefore records:

```text
semantic_status: unaudited
```

EGR-167 may later add a separately keyed semantic-audit overlay and promote the
audited outcome without regenerating unchanged L1 bytes.

## Materialization

Artifact objects and receipts remain authoritative. After acceptance, the
controller atomically materializes the verified object by artifact hash:

```text
runs/<run-id>/v2/materialized/L1/
  sources/<source-id>/
    overview/<artifact-hash>/
    domains/<domain-id>/<artifact-hash>/
    root/<artifact-hash>.json
```

Materialized paths are immutable projections, not authority. Recovery verifies
their contents against the object store. A missing projection is rebuilt; an
altered or unsafe projection is rejected and replaced through the same atomic
materialization path. Unexpected symlinks, traversal, special files, and
content/hash mismatches fail closed.

EGR-165 writes nothing below workspace `re/`. Workspace synthesis, tracked
publication, and a canonical workspace generation remain EGR-168 concerns.

## Status and Terminal Semantics

Human and JSON status report:

- accepted and required L0/L1 counts;
- per-source accepted and required domain counts;
- deterministic evidence/inventory coverage;
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
- the pinned partition document;
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
   leaves L0 keys unchanged.
4. Partition generation and graph reconstruction are deterministic across
   input ordering and process restart.
5. Each domain baseline depends on the exact accepted L0 hashes for its source,
   and each source root depends on the exact overview and domain hashes.
6. Provider/model and resource-limit changes do not alter artifact identity.
7. The baseliner result contract rejects missing files, wrong scope, wrong
   dependencies, and extraneous writes.
8. Certification rejects path traversal, symlinks, special files, out-of-scope
   evidence, nonexistent lines, oversize output, and JSON/Markdown disagreement.
9. A malformed result receives at most one contract retry; certification
   rejection does not enter a repair loop.
10. Crash/restart at candidate persistence, certification, ledger append, and
    materialization boundaries produces the same replayed plan and accepted
    roots without duplicate provider execution.
11. Status and final banners distinguish L1 completion from semantic audit,
    synthesis, selective depth, and full-quality completion.
12. A clean multi-source fixture completes with independently accepted domain
    artifacts and exact source roots while writing nothing below workspace
    `re/`.
13. The established v1-isolation suite proves that v1 dispatch, continuation,
    publication, and status remain unchanged.

## Completion Criteria

EGR-165 is complete only when a live protocol 2.2 fixture run produces
controller-certified L1 source and domain artifacts, exact source roots,
recoverable run-local materialization, and an unambiguous compact-baseline
banner; changing only the L1 content policy must demonstrably reuse the same L0
identity within the layered model.

EGR-165 completion does not make RE v2 the default and does not satisfy the
full-quality cutover condition. EGR-166 through EGR-170 remain required.
