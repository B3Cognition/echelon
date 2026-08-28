# RE v2 Adoptable Certified Checkpoints Design

**Date:** 2026-08-28  
**Status:** Implemented
**Owner:** EGR-166  
**Depends on:** EGR-164 and EGR-165  
**Precedes:** EGR-168 workspace synthesis and EGR-169 L4 exhaustive depth

## Summary

RE v2 already has immutable artifacts, typed certification and acceptance
receipts, object-backed ledgers, dependency graphs, and self-contained direct
parent adoption. It still strands accepted work when the producing run is
paused, blocked, partial, unpublished, or simply not the selected direct
parent.

Protocol 2.6 adds automatic workspace-local discovery and adoption of certified
artifact checkpoints. Every durably accepted artifact is immediately eligible.
A new run selects only exact-compatible, dependency-closed authority, copies
the selected closure into its own staged run, and records adoption before any
provider dispatch for that work item. The origin run need not terminalize and
need not survive after child creation.

The workspace checkpoint index is a disposable projection. Run manifests,
hash-chained events, typed ledger records, and immutable object bytes remain the
only authority.

## Problem

The current lineage path solves one narrower case: a deepening child can import
the complete accepted closure of its explicit completed parent. It does not
solve these cases:

- one source or domain is accepted before a sibling source blocks;
- a run pauses after useful artifacts are accepted;
- two sibling runs analyze the same pinned source and one has reusable work;
- an unpublished accepted domain needs to seed a later run;
- a non-parent run contains the strongest certified artifact for an exact key;
- an interrupted child must finish importing already-selected checkpoint
  authority without consulting the origin.

Repeating those provider calls wastes tokens and makes partial certified work
operationally valueless.

## Goals

1. Make every durably accepted L0 through L3 artifact discoverable as a
   workspace-local checkpoint.
2. Adopt exact-compatible checkpoints automatically without a CLI opt-in.
3. Adopt only a complete authenticated dependency subgraph.
4. Preserve explicit direct-parent precedence.
5. Select deterministically when sibling runs accepted different valid
   artifacts for the same artifact key.
6. Make the child self-contained before it becomes active.
7. Recover idempotently from every copy, ledger, and event boundary.
8. Keep provider selection and execution entirely in the existing Prosaic and
   shared provider paths for work that is not adopted.
9. Report origins, rejection reasons, quarantines, avoided dispatches, and
   avoided conservative reservations truthfully.
10. Preserve byte-compatible continuation of protocols 2.2 through 2.5.

## Non-goals

- No remote or cross-workspace checkpoint exchange.
- No mutable checkpoint database as authority.
- No adoption across different source snapshots, partitions, scopes, policies,
  producers, executors, verifier implementations, audit epochs, or finding
  authority.
- No synthesis, publication, L4 exhaustive analysis, or atomic repair.
- No provider adapter, alternate LLM path, model override, or prompt change.
- No automatic upgrade of an existing protocol-2.2 through protocol-2.5 run.
- No garbage collection of authoritative run objects. Disposable index and
  reconstructed manifest projections may be replaced atomically.
- No newest-run-wins or filesystem-order selection.

## Approved decisions

- Discovery is workspace-wide across sibling runs, not restricted to the
  direct-parent lineage.
- Exact-compatible checkpoints are adopted automatically.
- Eligibility begins immediately after durable artifact acceptance; origin
  terminal state is irrelevant.
- The index is artifact-granular, while adoption is dependency-closed.
- Competing valid candidates use deterministic quality-first selection with an
  artifact-hash tie break.
- The workspace index is a reconstructable cache, never independent authority.

## Versioning and compatibility

Checkpoint-aware runs use **protocol 2.6** and **run schema 5**. Existing event
schemas, manifest schemas, authority bytes, and recovery behavior for protocols
2.2, 2.3, 2.4, and 2.5 remain frozen.

`RunManifestV5` represents target layers L1, L2, and L3. It composes the
existing layer-specific catalogs and authorities rather than redefining their
contents. Its new checkpoint-selection input is additive. Execution delegates
to the existing layer graph, certification, materialization, provider,
controller, and recovery building blocks.

New baseline and deepening runs use protocol 2.6 after cutover. An older run
continues with its recorded protocol and cannot discover checkpoints that were
not part of its immutable creation authority.

## Authority model

### Existing authority remains canonical

The following existing values remain authoritative:

- immutable run manifest and input catalogs;
- source snapshot and workspace partition manifests;
- `WorkItemV2` and `ArtifactKeyV2`;
- candidate assessment, certification, and artifact acceptance receipts;
- semantic certification and closure authority for L3;
- hash-chained events and typed ledger records;
- immutable object bytes.

Checkpoint models reference and package those values. They do not replace or
reinterpret them.

### `CheckpointManifestV1`

One reconstructable manifest describes one accepted artifact:

- `schema_version`;
- origin run ID and run-manifest hash;
- origin engine protocol and run schema;
- origin acceptance event hash and ledger-record hash;
- exact work-item bytes and identity;
- exact artifact key and artifact hash;
- certification receipt identity and bytes;
- optional certified candidate-assessment identity and bytes;
- artifact-acceptance receipt identity and bytes;
- `AdoptedArtifactAuthorityV1` provenance;
- accepted-artifact dependencies as exact artifact-key/hash pairs;
- non-artifact immutable dependency hashes;
- producer, executor, verifier, policy, source-snapshot, partition, scope,
  layer, and audit-epoch compatibility identities already carried by the work
  item and receipts;
- deterministic checkpoint rank and rank-policy hash.

Its identity is the canonical content digest. The manifest file is a projection
that can be regenerated from the origin ledger and objects. A projection is
usable only when reconstruction produces the same identity.

### Dependency closure

For a candidate artifact, accepted-artifact dependencies are resolved by exact
artifact hash to their accepted artifact keys. Other dependency hashes must be
present as immutable objects in the origin closure.

A candidate is selectable only when:

- its own authority validates;
- every accepted-artifact dependency has a selected compatible checkpoint or
  exact direct-parent authority;
- every non-artifact dependency byte is available and hash-valid;
- the resulting graph is acyclic; and
- the complete closure matches the target graph's expected work items.

An accepted domain artifact can therefore be reused independently. A source
root or other downstream artifact cannot be assembled from incompatible or
missing fragments.

### `CheckpointSelectionBundleV1`

Creation freezes one canonical bundle containing:

- target source-snapshot and partition identities;
- target layer and selection identity;
- target graph identity;
- selected checkpoint-manifest identities;
- exact adopted-artifact authorities in dependency order;
- origin manifest/event/ledger prefix hashes;
- copied receipt and work-item identities;
- copied immutable object inventory;
- rank vectors and deterministic selection reasons;
- rejected and quarantined candidate identities with controlled reason codes.

The bundle is stored in the immutable run inputs and referenced by
`RunManifestV5`. The target run never reselects checkpoints after publication.

## Eligibility

An artifact becomes eligible when all of these boundaries are durable:

1. the candidate assessment, when provider-backed, is recorded;
2. an accepted certification receipt is recorded;
3. an artifact acceptance receipt is recorded;
4. the matching acceptance event is present; and
5. every referenced object verifies by content hash.

The origin may be active, paused, blocked, failed for an unrelated work item,
or complete. In-flight candidates, certifications without acceptance, torn
ledger/event prefixes, and rejected artifacts are ineligible.

L3 artifacts additionally require exact audit epoch, frozen finding authority,
semantic round, and semantic dependency identities. Findings and epochs are
never remapped between sibling runs. Protocol-2.5 successor adoption remains
the normal path for semantic closure; workspace checkpoints can reuse L3 only
when those identities are already exact.

## Workspace discovery cache

The disposable cache lives below:

```text
.echelon/re-v2/checkpoints/
  index-v1.json
  index-v1.lock
  manifests/
    <checkpoint-manifest-id>.json
  quarantine-v1.json
```

These paths are ignored and excluded from source snapshots. Writes use the
existing atomic-write and lock patterns.

Reconstruction enumerates safe `runs/re-*` directories, validates supported
manifests, and performs stable reads of event and ledger chains. A concurrent
append causes a bounded rescan of that origin. If stability cannot be obtained,
the origin is skipped for the current creation; target generation remains
available.

Deleting the cache loses no authority. A malformed cache entry is ignored and
reconstructed. Quarantine is diagnostic projection state, not a destructive
mutation of the origin.

## Compatibility and selection

### Exact compatibility

The expected current graph work item is the compatibility key. A checkpoint
must reproduce the exact work-item and artifact-key identities, including:

- source snapshot and partition;
- source/domain scope and content identity;
- target layer and artifact kind;
- dependency hashes;
- layer policy;
- producer family and executor contract;
- verifier ID, version, and implementation digest;
- response schema and agent authorities where applicable; and
- L3 audit epoch and frozen semantic authority where applicable.

Matching a filename, source ID, domain label, or profile name is insufficient.

### Precedence

Selection order is:

1. exact direct-parent authority;
2. exact workspace checkpoint candidates;
3. normal deterministic or provider generation.

Direct-parent authority wins even when a sibling candidate has a stronger rank,
because choosing the parent is an explicit lineage decision.

### Deterministic rank

Only existing certified data may contribute to ranking. Each artifact policy
registers a deterministic rank extractor and rank-policy hash.

- Rejected or incomplete candidates are never ranked.
- Compact baselines rank by policy-declared established required surfaces and
  applicable coverage counts. Unknown counts participate only when the frozen
  artifact policy explicitly defines their ordering; honest uncertainty is not
  penalized implicitly.
- Deterministic structural artifacts have equal pass quality unless their
  existing assessment exposes a stronger policy-defined vector.
- L3 semantic artifacts have equal pass quality unless their existing semantic
  certification exposes a comparable policy-defined vector.
- Equal rank selects the lexicographically smallest artifact hash.

Selection first applies those rules per exact artifact key. If independently
ranked winners from different origins form a smaller closure than an
authenticated origin-coherent alternative, the larger dependency-closed set
wins. Equal-size closures retain the per-key ranked result. A lower-ranked
dependency selected only to unlock the larger exact closure is reported as
`checkpoint_dependency_closure`; this bounded fallback evaluates one candidate
closure per origin and does not search arbitrary combinations.

Timestamps, run IDs, directory order, and discovery order never affect the
winner. All valid alternatives and the selection reason remain visible in
status telemetry.

## Creation and adoption flow

1. Perform the existing clean-Git source preflight.
2. Capture or validate the pinned workspace source snapshot and partition.
3. Build the requested L1, L2, or L3 graph using existing policies.
4. Validate explicit direct-parent authority, when present.
5. Rebuild or query the workspace checkpoint cache.
6. Filter candidates by exact expected graph work items.
7. Validate origin authority and compute deterministic ranks.
8. Select the maximal dependency-closed checkpoint set after parent authority.
9. Build `CheckpointSelectionBundleV1`.
10. Copy every selected receipt, work item, capture, artifact, and transitive
    object into a staged child directory.
11. Verify the staged child is self-contained and the selection bundle identity
    is exact.
12. Publish `RunManifestV5` and its immutable inputs atomically.
13. Append `run_created`.
14. Import parent authority through the existing parent path.
15. Import checkpoint authority in dependency order through the shared typed
    ledger-copy primitives.
16. Append one checkpoint-adoption event per imported artifact.
17. Plan remaining graph work normally.

The run is not made active until step 12 has a complete staged authority copy.
Origin deletion after that point cannot affect recovery.

## Events and ledger import

Protocol 2.6 adds `checkpoint_artifact_adopted`. Its canonical payload contains:

- checkpoint-selection bundle identity;
- checkpoint-manifest identity;
- adopted-artifact authority;
- origin run ID;
- current work-item ID; and
- deterministic selection-reason code.

The event must precede any lease or dispatch for its work item. Duplicate
artifact keys, receipt identities, or work items are rejected. It is invalid
while a provider dispatch is active.

Ledger import reuses the existing typed certification, candidate-assessment,
artifact-acceptance, and object-store functions. Shared lower-level copy helpers
are extracted from protocol-2.4 parent adoption so parent and checkpoint paths
do not diverge.

Adoption consumes zero provider tokens and zero provider active time. It does
not increment generation, retry, or semantic-round counters.

## Recovery

Creation and import are idempotent at these fault seams:

- cache rebuilt;
- selection frozen;
- each authority/object copied;
- manifest and input catalogs published;
- `run_created` appended;
- each typed ledger receipt imported;
- each checkpoint-adoption event appended; and
- first remaining work item planned.

Recovery reads only the target manifest, selection bundle, copied objects,
target ledger, and target events. It validates any existing prefix and appends
only missing ledger records or events. A conflicting prefix is an authority
error and blocks the child.

If discovery rejects every candidate before the bundle is frozen, the work item
remains normal generation work. If an artifact selected into a frozen bundle
cannot be imported from the already copied child authority, the child blocks;
it never silently replaces frozen adoption with a provider call.

## Failure and quarantine policy

Controlled discovery outcomes include:

- `checkpoint_incompatible`;
- `checkpoint_dependency_missing`;
- `checkpoint_origin_unstable`;
- `checkpoint_manifest_invalid`;
- `checkpoint_receipt_invalid`;
- `checkpoint_object_missing`;
- `checkpoint_object_hash_mismatch`;
- `checkpoint_authority_conflict`;
- `checkpoint_rank_invalid`; and
- `checkpoint_cycle_detected`.

Incompatibility is an ordinary miss. Invalid authority is quarantined for the
current cache generation and excluded from selection. Other valid candidates
may still win. If none remain, the target work item is generated normally.

Post-freeze conflicts or missing copied authority are child integrity failures,
not generation fallbacks.

## Status and telemetry

Human and JSON status include:

- checkpoint cache generation and reconstruction status;
- discovered, compatible, selected, adopted, rejected, and quarantined counts;
- counts and copied bytes by source, domain, layer, and artifact kind;
- origin run IDs and checkpoint-manifest identities for adopted artifacts;
- direct-parent versus workspace-checkpoint precedence;
- deterministic selection reason and rank-policy identity;
- avoided provider dispatch count;
- avoided token and active-time reservations, explicitly labeled as avoided
  reservations rather than observed usage;
- zero-dispatch completion/reuse; and
- controlled rejection/quarantine reason counts.

The normal final banner states how much authority was adopted and how much work
was generated. It does not call partial artifacts complete and does not claim
synthesis, publication, L4, or atomic repair.

No separate checkpoint maintenance command is required initially. Missing or
corrupt cache state is rebuilt automatically. `echelon re status --json`
provides the inspection surface.

## Security and integrity

- Paths discovered from run IDs are validated and confined below the workspace
  `runs/` directory.
- Symlinked run authority, objects, cache manifests, and traversal paths are
  rejected.
- Stable chain reads prevent importing a torn active-run prefix.
- Every copied byte is verified by content hash before selection and after
  staging.
- The target clean-source preflight remains mandatory for fully adopted runs.
- Raw provider output and raw guidance are not copied into workspace telemetry.
- The cache cannot authorize adoption without successful origin reconstruction.

## Testing strategy

### Canonical unit tests

- strict model schemas, identities, ordering, and round trips;
- compatibility across every identity dimension;
- rank extraction and artifact-hash tie breaks;
- dependency closure and cycle rejection;
- cache reconstruction, atomic replacement, and malformed cache recovery;
- safe path and symlink rejection;
- direct-parent precedence;
- L3 audit-epoch non-remapping; and
- status/telemetry schemas.

### Controller and recovery tests

- fully adopted zero-dispatch run;
- partially adopted graph followed by normal provider generation;
- domain adoption from an origin blocked on another domain;
- adoption from active, paused, blocked, failed-unrelated, and completed origins;
- origin deletion after staged child publication;
- concurrent origin append and bounded stable-read rescan;
- competing valid candidates with different ranks and equal-rank hash ties;
- corrupt candidate quarantine with valid sibling fallback;
- no valid checkpoint generation fallback;
- post-freeze authority conflict blocks without provider dispatch;
- crash recovery at every creation/import boundary;
- copied child recovery without cache or origin; and
- exact no-call continuation after terminalization.

### Compatibility tests

- protocols 2.2 through 2.5 continue byte-identically;
- existing direct-parent adoption events and bundles remain exact;
- v1 engine routing is unchanged;
- provider selection continues through Prosaic metadata and existing adapters;
- source snapshots exclude checkpoint cache paths; and
- dirty source repositories fail before discovery or creation.

### Real Codex pilot

Use a clean Git workspace and the normal Codex provider through Prosaic:

1. create an origin run that accepts at least one domain artifact and then
   pauses or blocks on an independent sibling;
2. create a sibling protocol-2.6 run for the same exact snapshot and scope;
3. prove automatic adoption of the accepted domain and its dependency closure;
4. prove zero provider calls for adopted work and normal calls only for missing
   work;
5. delete or hide the disposable checkpoint cache and origin after child
   creation, then prove child continuation remains valid;
6. repeat the exact terminal request and prove zero additional events and
   dispatches; and
7. prove both workspace and source Git repositories remain clean.

## Rollout

1. Add canonical checkpoint models and cache reconstruction without changing
   creation routing.
2. Add deterministic compatibility, ranking, and dependency-closed selection.
3. Add schema-5 inputs and staged self-contained authority copying.
4. Add protocol-2.6 events, ledger import, recovery, status, and telemetry.
5. Route new opt-in v2 baseline and L2/L3 deepening runs to protocol 2.6.
6. Run compatibility, fault-injection, and real Codex gates.
7. Mark EGR-166 fixed only after the real sibling-run pilot demonstrates
   automatic adoption and zero-call savings.

## Implementation evidence

Protocol 2.6 is implemented for new L1, L2, and L3 runs. The offline
compatibility sweep passed 861 tests with 3 expected skips before the live
pilot; the final focused gate passed 106 tests with 1 expected live skip. The
complete locked-environment repository gate passed 10,776 tests with 13 skips
and 1 intentional deselection.

The clean installed Codex pilot used source snapshot
`sha256:7a4cd7a63f3fa58f3add53262ff84f99dc5035d8e6e33d12f8428815798c1cf1`.
Origin runs `re-20260828-084826-825013` and
`re-20260828-085101-370246` exposed a real selection defect: schema-5 origins
were initially not reconstructable, and independent tie-breaking later mixed
origins into an 11-of-14 closure. After correcting both boundaries, sibling
`re-20260828-090755-380569` completed in 4.14 seconds with 14 adopted
checkpoints, 0 generated artifacts, 0 charged tokens, and 0 charged active
milliseconds. Its status reports 14 avoided dispatches and a conservative
786,432-token avoided reservation.

All prior origins and the disposable cache were then moved aside. Continuing
the terminal child took 2.58 seconds and left the event-chain SHA-256 unchanged
at `90173e69ebd3f9f19d813092a25c8a2e782f019a54de5562ab34517cd351764b`.
With only that self-contained adopted child available, sibling
`re-20260828-090831-459009` rebuilt the cache and again completed with 14
adopted, 0 generated, and no provider charge in 4.16 seconds. The declared
source Git repository remained clean throughout.

Default-engine cutover remains outside this design.

## Success criteria

EGR-166 is complete when:

1. an artifact accepted in a nonterminal origin run is immediately eligible;
2. a sibling run automatically adopts exact-compatible authority;
3. adoption is artifact-granular and dependency-closed;
4. direct-parent authority takes precedence;
5. conflicts resolve by deterministic certified rank and artifact hash;
6. the workspace cache is disposable and reconstructable;
7. the child is self-contained before activation;
8. recovery never requires the origin after child publication;
9. corrupt or incompatible checkpoints never become authority;
10. adopted work incurs no provider dispatch, retry, or semantic budget charge;
11. status and telemetry explain every selection and rejection;
12. protocols 2.2 through 2.5 remain compatible;
13. the real Codex sibling-run pilot passes with clean Git; and
14. no synthesis, L4, atomic repair, or provider-specific execution path is
    introduced.

## Follow-on order

After EGR-166:

1. EGR-168 consumes accepted complete or explicit-partial source-root sets for
   one deferred workspace synthesis operation.
2. EGR-169 registers selected exhaustive L4 work over accepted L3 authority.
3. EGR-170 adapts atomic repair to the stable L0-through-L4 artifact graph.
