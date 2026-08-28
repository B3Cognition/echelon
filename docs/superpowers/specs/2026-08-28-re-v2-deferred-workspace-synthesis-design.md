# RE v2 Deferred Workspace Synthesis Design

**Date:** 2026-08-28
**Status:** Approved design
**Owner:** EGR-168
**Depends on:** EGR-164 through EGR-167 and protocol 2.6 checkpoint adoption
**Precedes:** EGR-169 L4 exhaustive depth and EGR-170 atomic repair

## Summary

RE v1 can synthesize workspace artifacts before selected sources reach stable
terminal outcomes. Source repair then invalidates that synthesis and routes the
workspace through it again. The retained OptaSearch campaign dispatched
workspace synthesis 34 times, charged roughly 76.9 million known tokens, and
accepted a final synthesis that used roughly 2.9 million tokens.

Protocol 2.7 moves synthesis behind accepted source outcomes. The explicit
`echelon re synthesize --from-run <run-id>` command creates a self-contained
schema-6 child over one frozen set of accepted complete or explicitly accepted
partial source roots. It decomposes the existing public synthesis surface into
independently keyed artifacts, adopts exact reusable artifacts before dispatch,
generates only missing work through Echelon's existing Prosaic and provider
path, and publishes the completed closure atomically.

Synthesis completion and input quality are orthogonal. A workspace synthesis
over explicitly accepted partial sources succeeds when its required artifact
closure is accepted, while retaining a truthful partial-quality label and every
referenced debt manifest. It never claims full RE quality.

## Problem

The v1 synthesis target is operationally monolithic:

- source-owned and workspace-owned outputs are written in one broad target;
- one missing or invalid output can trigger another broad repair turn;
- source repair marks prior workspace synthesis stale;
- synthesis accounting shares the larger RE execution lifecycle;
- accepted outputs are mutable staged files rather than independently reusable
  certified artifacts; and
- a terminal partial source set is represented as a blocker or override rather
  than as explicit synthesis input authority.

Protocols 2.2 through 2.6 now provide the missing substrate: immutable source
and artifact identities, dependency graphs, typed receipts, independent
budgets, bounded semantic audit, self-contained children, cross-run checkpoint
adoption, hash-chained events, truthful status, and atomic publication
primitives. EGR-168 must compose those parts rather than revive the v1 loop.

## Goals

1. Run workspace synthesis only through an explicit child after every selected
   source has an accepted terminal outcome.
2. Admit partial source outcomes only through source-specific durable operator
   acceptance.
3. Freeze the exact accepted source roots, debt identities, synthesis policy,
   Prosaic execution authority, budget, and publication compare-and-swap base.
4. Preserve the existing consumer-facing `re/sources/...` and
   `re/workspace/...` paths.
5. Make source, domain, and workspace synthesis artifacts independently keyed,
   accepted, adoptable, recoverable, and materializable.
6. Reuse accepted source overviews instead of regenerating them.
7. Dispatch only missing dependency-ready work through the existing Prosaic and
   shared provider path.
8. Bound contract repair per artifact and synthesis resources independently of
   L0 through L4 resources.
9. Make synthesis completion, source input quality, and publication state
   separate truthful dimensions.
10. Publish a complete synthesis closure atomically without overwriting newer
    workspace authority.
11. Keep a child reconstructable and continuable after its parent, generating
    origins, and disposable checkpoint cache are unavailable.
12. Preserve protocol 2.2 through 2.6 continuation and v1 routing.

## Non-goals

- No L4 exhaustive-depth producer or claim.
- No lower-layer or semantic finding repair.
- No automatic synthesis tail step after baseline, deepening, or audit.
- No global v2 `--allow-partial` switch.
- No implicit acceptance of partial, blocked, missing, stale, or unauthenticated
  sources.
- No regeneration of accepted lower-layer source overviews.
- No provider adapter, direct API request, provider-specific prompt renderer,
  model map, credential branch, or provider-specific orchestration path.
- No cross-workspace or remote checkpoint exchange.
- No publication overwrite when the workspace generation changed after child
  creation.
- No default-engine cutover.

## Approved decisions

- Synthesis is an explicit self-contained child run.
- Partial acceptance is repeated and source-specific.
- Existing published paths remain the public compatibility contract.
- Public files are materialized from granular immutable synthesis artifacts.
- Synthesis completion and source completeness are orthogonal.
- Invalid synthesis candidates receive bounded artifact-local repair.
- The synthesis budget is independent of analysis and semantic budgets.
- A dependency-aware synthesis DAG is preferred over monolithic dispatch and
  shallow deterministic-only aggregation.
- Publication happens only after the required synthesis closure is accepted.
- Complete and explicitly partial publications are labelled distinctly.

## Versioning and compatibility

Checkpoint-aware synthesis children use **engine protocol 2.7** and **run
schema 6**. Protocol 2.7 consumes protocol-2.6 source and checkpoint authority
without changing the recorded bytes or behavior of protocols 2.2 through 2.6.

New implementation lives under `harness.re_v2.protocol_27`. It composes the
existing canonical encoding, object store, work item, candidate, receipt,
ledger, event, accounting, checkpoint reconstruction, adoption, Prosaic,
provider, materialization-safety, status, and publication building blocks.
Protocol 2.7 imports existing public helpers and adds protocol-2.7-scoped
composition around them; it does not edit protocol-2.2-through-2.6
implementation bodies. A capability that is not already reusable is added
under `protocol_27` rather than moved out of a frozen module. Frozen-protocol
canonical and continuation fixtures enforce this boundary.

Synthesis artifacts occupy a protocol-2.7 synthesis namespace. They are not
labelled L3 or L4, because workspace recomposition is not another analysis
depth. The existing L0-to-L4 chain remains strictly additive and semantically
unchanged.

The existing v1 command remains valid:

```text
echelon re synthesize [<run-id>] --allow-partial [--re-token-limit <n>]
```

The v2 route is selected only by the new child-run form and a v2 parent:

```text
echelon re synthesize --from-run <run-id> \
  [--accept-partial <source-id>]... \
  [--token-limit <positive-int>] \
  [--active-ms-limit <positive-int>]
```

`--from-run`, `--token-limit`, and `--active-ms-limit` reuse the existing
deepening CLI vocabulary. `--accept-partial` is repeatable, rejects duplicates,
and may identify only a selected source whose authenticated terminal outcome is
partial. Supplying it for a complete source, an unknown source, or a source
outside the frozen parent selection is an error. Omitting it for any partial
source is an error. A global `--allow-partial` remains v1-only.

## Run authority

### `RunManifestV6`

The immutable schema-6 manifest records:

- run ID, creation time, engine protocol, schema version, and goal;
- a deterministic synthesis-request identity over parent manifest, canonical
  selected source outcomes, accepted partial source IDs, synthesis resource
  policy, and both captured publication bases;
- direct parent run ID and authenticated parent manifest hash;
- protocol-2.6 execution and implementation snapshot authority;
- exact selected workspace/source/partition identities;
- exact accepted source-root records in canonical source-ID order;
- an accepted source-overview projection catalog binding each selected source's
  highest accepted layer, source-root authority, canonical materializer
  authority, exact Markdown content hash, and child object hash;
- per-source outcome: `complete` or `partial`;
- the debt-manifest object hash for every partial source and null for every
  complete source;
- the operator acceptance receipt identity for every partial source;
- the synthesis graph, artifact policy, response-schema, context-policy,
  producer, executor, verifier, and rank-policy identities;
- Prosaic role bytes and interpreted model tier, model, effort, and tools;
- the independent synthesis budget policy;
- the checkpoint selection snapshot and cache policy;
- the publication synthesis-policy hash; and
- the expected v2 published-index hash and compatibility-registry generation
  captured at child creation.

Manifest publication remains manifest-last and no-clobber. Every referenced
object, catalog, policy, response schema, context input, source authority, and
partial-acceptance receipt is staged and authenticated before the child becomes
active.

### Accepted source outcome

An accepted source outcome is not inferred from a banner, directory, or latest
run. For each selected source, the child resolves one authenticated accepted
source root from the explicit parent or protocol-2.6 checkpoint closure. The
source record binds:

- source ID and pinned source snapshot/content identity;
- exact accepted source-root artifact key and hash;
- dependency closure and acceptance authority;
- selected highest accepted analysis authority available in the parent;
- terminal outcome class;
- retained debt-manifest hash when partial; and
- operator acceptance receipt when partial.

Blocked, running, missing, stale, or dependency-incomplete sources are not
terminal inputs and make child creation fail before a run directory is
published.

Before child activation, the controller invokes the existing public
materializer for each source's selected highest accepted L1, L2, or L3
authority, validates the resulting overview projection against that authority,
and copies the exact Markdown bytes into the child's object store. A typed
`AcceptedSourceOverviewProjectionV1` binds source/layer/root, materializer
authority, content hash, and child object hash. Later synthesis and publication
read only these child-owned bytes; they neither read a mutable parent projection
nor reimplement a frozen layer renderer.

### `PartialSourceAcceptanceV1`

Each repeated `--accept-partial <source-id>` produces one immutable receipt
binding:

- schema version and source ID;
- parent run and manifest identity;
- source-root artifact key and hash;
- debt-manifest hash;
- canonical debt summary hash;
- the deterministic synthesis-request ID as accepting operation authority; and
- deterministic receipt identity.

The receipt records acceptance of the exact debt-bearing source outcome for
workspace synthesis. It does not change the source outcome, resolve debt, waive
future gates, or permit a full-quality claim. A changed source root or debt
manifest requires a new receipt.

## Synthesis artifact identity

Protocol 2.7 adds a synthesis-scoped canonical artifact key that reuses the
existing identity and hashing rules while representing three scope forms:

- `source`, with exactly one source ID;
- `workspace-domain`, with one deterministic workspace domain ID and its
  canonical participating source/domain set; and
- `workspace`, with no source or domain ID.

Every key includes:

- identity schema and synthesis namespace versions;
- scope and artifact kind;
- producer protocol and synthesis policy hash;
- response-schema and context-policy hashes;
- exact sorted artifact-dependency key/hash pairs;
- exact sorted non-artifact dependency hashes; and
- the partial-debt reference set that applies to the artifact.

Artifact keys do not include run IDs, origin IDs, provider attempt IDs, or
timestamps. Exact-compatible artifacts can therefore be adopted across sibling
runs. Different source roots, participating domains, debt manifests, policies,
producers, verifiers, response schemas, or dependency closures create different
keys.

## Artifact graph

### Deterministic inputs

The controller derives and stores, without model work:

- the accepted source authority catalog;
- terminal outcome and debt catalog;
- workspace topology catalog;
- deterministic workspace-domain membership;
- synthesis graph and work-template catalog;
- bounded evidence/context manifests;
- response schemas; and
- public materialization map.

Topology derives only from authenticated run objects and accepted artifacts.
The synthesizer never reads live source repositories. Source repositories remain
forbidden provider roots.

### Source-local nodes

For each accepted selected source:

1. The accepted highest-authority `source-overview` is adopted as a lower-layer
   dependency. Its existing layer materializer supplies the canonical Markdown
   projection copied to the public `overview.md` path. The candidate payload is
   neither copied directly nor regenerated.
2. `source-architecture` depends on that source's accepted overview, selected
   accepted domain artifacts, deterministic topology, and applicable debt.
3. `source-contracts` depends on the same source authority plus its accepted
   contract-bearing domain artifacts and debt.
4. `source-components` depends on the source inventory/topology, overview,
   selected accepted domain artifacts, and debt.

Changing one source invalidates only that source's generated synthesis nodes
before higher workspace dependencies are considered.

### Workspace-domain nodes

One `workspace-domain-summary` is required for every deterministic workspace
domain. Its key depends only on:

- the canonical participating source/domain identities;
- their accepted artifact roots;
- relevant source synthesis artifacts;
- deterministic topology; and
- participating debt references.

Changing an unrelated source does not invalidate that domain summary.

### Workspace nodes

The public workspace artifacts remain:

- `workspace-overview`;
- `workspace-relationships`; and
- `workspace-contracts`.

`workspace-overview` depends on the frozen accepted source set, source
overviews, source architecture/components, domain summaries, topology, and
workspace debt catalog. `workspace-relationships` depends on source
architecture/contracts, domain summaries, and topology.
`workspace-contracts` depends on source contracts and accepted relationships.

All three keys change when the frozen workspace authority set changes. This is
intentional: workspace-wide claims must be recomputed when a source is added,
removed, or replaced.

### Synthesis root

The controller creates one deterministic synthesis root only after every
required node has an accepted receipt. The root binds:

- all accepted source roots and terminal outcomes;
- every required synthesis artifact key and hash;
- every partial debt manifest and acceptance receipt;
- topology, graph, materialization, producer, verifier, and policy authority;
- input quality; and
- the publication synthesis-policy hash.

The root is controller generated and contains no inferred model claim.

### `PublicationDescriptorV1`

The controller creates one canonical publication descriptor after
materialization validates. It binds:

- the synthesis-root identity and hash;
- `input_quality`;
- every complete/partial source outcome;
- every debt-manifest and partial-acceptance receipt identity;
- the materialization-manifest identity;
- the exact staged compatibility-index hash and generation; and
- the run and synthesis-policy authority.

The descriptor hash is the accepted root supplied to the existing immutable
generation primitive. Complete/partial publication labels are therefore
authenticated data reachable through the published run, without changing the
frozen publication manifest or index schemas.

## Execution flow

1. Resolve the explicit parent and require either a stable protocol-2.6 source
   child or a terminal protocol-2.7 synthesis child whose embedded
   protocol-2.6 source authority is reconstructable.
2. Validate terminal source outcomes and exact repeated partial acceptances.
3. Capture the current compatibility-registry generation and v2
   published-index hash.
4. Stage every immutable authority object, input catalog, receipt, static graph
   node, work template, accepted overview projection, policy, and manifest,
   then publish the schema-6 manifest last. A concrete work item is instantiated
   only when every generated dependency has an accepted artifact hash; downstream
   artifact keys therefore never contain placeholders for not-yet-produced bytes.
5. Reconstruct the synthesis graph deterministically from the manifest.
6. Discover and select exact-compatible synthesis checkpoints with direct-parent
   precedence and protocol-2.6 deterministic dependency-closure behavior.
7. Copy and authenticate the selected closure into the child before recording
   adoption events.
8. Instantiate exact dependency-key/hash-bound work items and dispatch only
   dependency-ready missing work through the existing Prosaic/provider executor.
9. Validate, assess, certify, accept, and event each artifact independently.
10. Compute the synthesis root when the graph closes.
11. Materialize the immutable closure to run-local compatibility paths.
12. Attempt compatibility and v2 publication using both captured
    compare-and-swap bases.
13. Render machine-readable status and a prominent terminal banner.

Continuation reconstructs all state from the manifest, events, ledgers,
receipts, and objects. It never trusts mutable cache rows or materialized files.

## Prosaic and provider execution

Protocol 2.7 introduces one neutral `echelon.re-synthesizer` Prosaic role for
bounded synthesis artifact generation. The v1 `echelon.re-specifier` contract
remains unchanged. Frontmatter remains the authority for model tier, effort,
and tools. Prosaic rendering and Echelon's existing provider resolution
determine the concrete provider/model behavior.

The controller supplies exactly one synthesis work item, bounded context pack,
response schema, dependency manifest, and allowed artifact destination per
dispatch. Provider output returns the existing structured execution envelope;
the controller alone validates, stages, accepts, records, and materializes it.

The frozen protocol-2.2 baseline renderer accepts only `ContextBundleV1`, so it
cannot truthfully validate a synthesis context. Protocol 2.7 follows the
existing protocol-2.5 extension pattern: a synthesis-scoped deterministic
request renderer validates `SynthesisContextV1`, renders the neutral Prosaic
body plus canonical context/schema, and delegates the call to the same
`SquadCliProvider`. It reuses the shared result contract, provider factory,
frontmatter interpretation, reservation, normalized usage, capture, and
telemetry primitives. It adds no provider selection or provider-specific code.

No protocol-2.7 code calls a provider API directly, maps provider models,
constructs provider CLI arguments, or interprets provider-specific output.

## Context and claim safety

Context packs are derived only from authenticated child objects. They include
the minimum accepted lower and synthesis dependencies needed for one artifact,
plus applicable debt references. They exclude unrelated sources and domains,
live repositories, mutable workspace publication, and arbitrary sibling files.

Every response schema requires structured claim/evidence entries and explicit
input-quality/debt fields. Candidate validation fails when output:

- omits an applicable partial source or debt reference;
- claims complete/full quality over partial input;
- cites a source or artifact outside the context manifest;
- invents a participating source/domain;
- omits required consumer-facing sections; or
- violates its artifact-specific contract.

The controller-provided debt catalog remains authoritative even when model prose
fails to mention or attempts to downgrade it.

## Budget and bounded repair

Synthesis has an independent token and active-time pool recorded in the
schema-6 manifest. Analysis, semantic audit, and previous-run usage do not
consume or enlarge it. Provider dispatch uses the existing trusted usage or
conservative reservation accounting contract.

Each missing artifact permits:

- one initial generation attempt; and
- at most one result-contract/artifact-contract repair attempt.

There is no shared unbounded retry pool, broad workspace rewrite, or automatic
budget increase. A failed artifact cannot invalidate or charge accepted
siblings. Budget exhaustion prevents new dispatch but preserves every durable
candidate, receipt, accepted artifact, and adoption.

## Lifecycle and terminal semantics

Status exposes three independent dimensions:

```text
synthesis_status: in_progress | complete | incomplete
input_quality: complete | partial
publication_status: not_attempted | published_complete | published_partial | conflict
```

`synthesis_status: complete` means every required artifact and the synthesis
root are accepted for the exact frozen inputs. `input_quality: partial` means at
least one source was explicitly accepted with retained debt. These values are
not contradictory.

`synthesis_status: incomplete` is terminal for the current bounded attempt. It
records unresolved artifact keys, failure classes, retained checkpoints,
charged usage, and an exact continuation or successor command. It does not
discard successful work or call the entire source analysis blocked.

A terminal complete continuation performs no provider dispatch, creates no new
events, and leaves canonical ledgers byte-identical.

An illustrative partial terminal banner is:

```text
RE WORKSPACE SYNTHESIS — COMPLETE OVER ACCEPTED PARTIAL INPUTS
run: re-...
sources: 3 accepted (1 complete, 2 explicitly partial)
synthesis artifacts: 12/12 accepted (4 generated, 8 adopted)
provider charge: ...
retained source debt: pressbox-search, pressbox-search-soccer-api
publication: published partial
full-quality claim: unavailable
next step: deepen/repair the listed debt, then create a successor synthesis child
```

## Materialization

Materialization is a disposable projection of the accepted closure. It writes
only beneath the child run's RE directory until publication and preserves these
public paths:

```text
re/sources/<source-id>/overview.md
re/sources/<source-id>/architecture.md
re/sources/<source-id>/contracts.md
re/sources/<source-id>/components.md
re/workspace/overview.md
re/workspace/relationships.md
re/workspace/contracts.md
re/workspace/domains/<workspace-domain-id>.md
```

The accepted lower-layer overview is projected without an LLM rewrite. Every
generated file maps to exactly one accepted synthesis artifact. A deterministic
manifest records artifact keys, hashes, object paths, public paths, source
quality, and debt references. Path traversal, symlinks, hardlinks, type changes,
unexpected files, and hash mismatches fail closed.

Re-materialization after deletion must reproduce byte-identical files from the
self-contained child.

## Publication

Publication begins only after the synthesis closure and run-local
materialization validate. Protocol 2.7 acquires the existing workspace
`RePublishLock`, verifies both creation-time bases, and prepares the existing
rollback-capable `PublicationTransaction` for the compatibility files and
`re/index.json`. The transaction installs files first and the compatibility
index last, so that index always names a self-consistent physical projection.

The compatibility candidate is built before `PublicationDescriptorV1`: its
canonical index bytes determine the exact generation and index hash recorded by
the descriptor. The compatibility index does not refer back to the descriptor,
so the authority graph is acyclic. Its already-supported `quality` object
records the protocol-2.7 input-quality and debt summary; the registry reader
exposes that existing metadata without changing the index schema version.

While retaining the publication journal and lock, protocol 2.7 then calls the
existing v2 immutable generation and published-index compare-and-swap primitive
with `PublicationDescriptorV1` as the accepted root. The v2 index is the final
protocol-2.7 authority point. Only after both validated indexes name the same
descriptor/run does recovery mark publication terminal and remove rollback
state.

The compatibility rollback journal remains deliberately nonterminal after its
files are installed and until the v2 index plus protocol-2.7 publication receipt
are durable. A protocol-2.7 marker lets the existing interrupted-publication
entrypoint dispatch this journal to protocol-2.7 recovery. Recovery validates
both current indexes: it completes an already-installed matching pair, finishes
a still-valid v2 CAS, or rolls back only compatibility bytes owned by the
transaction. The legacy publication recovery path remains unchanged for
unmarked journals.

This composes existing publication building blocks without changing either
index schema. A crash between the two index writes leaves a valid compatibility
generation plus a durable journal and owned publication lock. Recovery either
completes the still-valid v2 CAS or rolls the compatibility transaction back
before releasing the lock. A v2 CAS conflict also rolls back the compatibility
transaction; it never leaves the child reported as published.

The generation manifest binds the accepted source roots, synthesis root, and
synthesis-policy hash. Publication status is:

- `published_complete` when all frozen sources are complete;
- `published_partial` when at least one source has an exact partial acceptance;
- `conflict` when either current publication base differs from its
  creation-time value; or
- `not_attempted` before a complete synthesis closure exists.

A conflict at either creation-time base never overwrites newer authority. The
synthesis child remains complete and self-contained. Status reads the current
published run ID and prints an exact successor command using that run as
`--from-run`, including the required source-specific partial acceptances.
Protocol 2.7 does not retry publication against a new compare-and-swap base and
does not silently refresh its frozen inputs.

Downstream consumers receive the existing registry paths plus explicit
complete/partial input quality and debt manifests. No consumer may infer full
quality merely from synthesis completion.

## Adoption and incremental recomposition

Synthesis checkpoint discovery follows protocol-2.6 workspace-local rules:

- direct-parent exact authority has precedence;
- other sibling candidates require exact key and policy compatibility;
- selection is deterministic and dependency-closed;
- the workspace cache is disposable;
- the child copies all selected objects and authority before activation; and
- adopted work incurs no provider attempt, retry, token, or active-time charge.

When one source changes, a successor recomputes that source's local nodes,
workspace-domain summaries in which it participates, and all workspace-wide
nodes. Unchanged source-local nodes and unrelated workspace-domain summaries
remain exactly adoptable. The status report distinguishes generated, adopted,
rejected, and dependency-pruned candidates and reports avoided dispatches and
conservative reservations.

## Recovery

Deterministic recovery tests cover crashes after each durable mutation:

- input object and manifest staging;
- partial-acceptance receipt staging;
- manifest publication;
- checkpoint object/receipt copy;
- adoption ledger and event writes;
- dispatch reservation and provider start;
- provider completion capture;
- candidate staging and assessment;
- certification and acceptance receipt writes;
- artifact-accepted event;
- synthesis-root creation;
- each materialized file and materialization manifest;
- compatibility candidate and rollback-journal staging;
- each compatibility backup/install plus compatibility-index replacement;
- v2 immutable generation creation and v2-index compare-and-swap;
- protocol-2.7 publication receipt; and
- rollback-journal finalization and cleanup.

Recovery either completes the pending idempotent step or resumes from the last
authenticated boundary. It never issues a duplicate provider call after a
durable provider result, double charges usage, accepts an unreceipted artifact,
or requires an origin after child activation.

## Status and telemetry

Machine-readable and human status report:

- parent, manifest, protocol, schema, and source authority;
- complete and explicitly partial source counts and IDs;
- debt-manifest and partial-acceptance receipt identities;
- required, generated, adopted, failed, and unresolved artifacts by scope;
- artifact origins and checkpoint rejection reasons;
- initial and repair attempts by artifact;
- trusted/unknown usage, reservations, token charge, and active time;
- avoided dispatch and conservative reservation estimates;
- synthesis status, input quality, and publication status;
- publication generation or conflict identity; and
- an exact next command.

No raw source content, prompts, provider responses, or unrestricted debt prose
enters telemetry.

## Test strategy

### Model and CLI tests

- Canonical schema-6 manifest and exact field rejection.
- Stable synthesis artifact, receipt, work item, graph, root, and acceptance
  identities.
- Repeated `--accept-partial` parsing, duplicate/unknown/complete-source
  rejection, and missing partial acceptance.
- Rejection of nonterminal, stale, malformed, unauthenticated, or
  dependency-incomplete source outcomes before child publication.
- Independent positive budget flags and immutable creation authority.
- Exact v1/v2 `re synthesize` routing isolation.

### Graph and adoption tests

- Required source, workspace-domain, workspace, and synthesis-root closure.
- One-source change invalidates only the expected source/domain/workspace nodes.
- Direct-parent precedence, sibling deterministic ranking, mixed-origin closure,
  corrupt/incompatible quarantine, and cache reconstruction.
- Adopted artifacts incur no dispatch or budget charge.
- Origin and cache removal still permit continuation and re-export.

### Execution and recovery tests

- Existing Prosaic/provider model and effort resolution for every synthesis
  work kind.
- Valid, malformed, missing, duplicate, and out-of-scope execution envelopes.
- Initial plus one contract-repair limit per artifact.
- Independent token/time exhaustion with retained sibling authority.
- Every recovery boundary listed above, including real child-process death where
  the provider lifecycle contract requires it.

### Materialization, status, and publication tests

- Existing public paths and byte-identical re-materialization.
- No live-source reads and no unsafe output filesystem objects.
- Orthogonal complete/partial/incomplete status and prominent banners.
- Complete and partial publication generation identity.
- Compare-and-swap conflict without overwrite.
- Downstream registry, spec, delivery, MemPalace, and publication consumers
  continue to resolve existing paths with explicit quality metadata.

### Compatibility tests

- Frozen protocol 2.2 through 2.6 canonical fixtures and implementation
  authorities remain byte-identical.
- Existing protocol continuations do not discover or infer protocol-2.7 state.
- v1 lifecycle, partial synthesis, publication, and CLI tests remain unchanged.
- Provider matrix covers Claude, Codex, Copilot, OpenCode, and compatible API
  execution through shared provider contracts; live credentials are optional.

### Real Codex pilot

A clean installed-workspace pilot must prove:

1. at least two accepted sources, with at least one complete source and one
   explicitly accepted partial source;
2. successful synthesis and partial publication;
3. independently generated and adopted artifact telemetry;
4. exact terminal continuation with no provider call and byte-identical events;
5. a sibling synthesis child adopting the complete closure with no provider
   call or charge;
6. successful cache reconstruction and continuation after generating origins
   and the disposable cache are hidden;
7. incremental recomposition after one source authority changes, preserving
   unrelated source and workspace-domain artifacts; and
8. clean source repositories throughout.

## Success criteria

EGR-168 is complete when:

1. synthesis cannot begin before every selected source has accepted terminal
   authority;
2. each partial source requires an exact source-specific acceptance receipt;
3. one schema-6 child freezes all source, debt, synthesis, execution, budget,
   and publication authority;
4. existing public synthesis paths remain available;
5. source, domain, and workspace artifacts are granular and dependency keyed;
6. accepted source overviews are reused without regeneration;
7. only missing work dispatches through the shared Prosaic/provider path;
8. repair and resources are independently bounded;
9. continuation and sibling adoption retain accepted work without duplicate
   calls or charges;
10. synthesis completion remains separate from source input quality;
11. complete and partial publications are labelled truthfully;
12. publication conflicts never overwrite newer generations;
13. the child remains self-contained after origins and cache removal;
14. focused, compatibility, full-suite, and real Codex pilot gates pass; and
15. L4, lower-layer atomic repair, provider-specific execution, and default
    cutover remain outside the implementation.

## Follow-on order

After EGR-168:

1. EGR-169 registers selected exhaustive L4 work over accepted L3 authority.
2. A successor synthesis child may consume the resulting higher accepted
   authority and reuse every unaffected synthesis node.
3. EGR-170 adapts atomic lower-artifact repair to the stable L0-through-L4 and
   synthesis interfaces.
4. Default-engine cutover requires the completed layered program and production
   evidence.
