# Source Topology Foundation

**Status:** Implemented

**Date:** 2026-08-04

## Goal

Create one trustworthy, provider-neutral source-topology capability for Echelon.
Reverse engineering (RE), delivery verification, artifact graphs, and a future
Graph Analyst must consume the same deterministic CodeGraph and PerlGraph
contracts instead of parsing workflow-specific JSON independently.

The topology foundation must answer file- and symbol-level questions, preserve
provenance and freshness, and remain useful when one provider or language is
unsupported. The Graph Analyst itself is a separate follow-up project.

## Decisions

- Topology is a first-class Echelon domain, not an RE-only feature.
- `source:<source-id>` is the only canonical source identity.
- CodeGraph and PerlGraph retain provider-specific raw artifacts behind one
  normalized Python interface.
- Full symbol graphs are queried through topology providers and are not copied
  into every spec or workspace artifact graph.
- CodeGraph emits every discovered symbol. Echelon removes the current
  10,000-symbol cap and the `--max-symbols` bridge option.
- Run-local delivery topology is not canonical before its spec lands.
- A landed, exact-match delivery snapshot may be promoted to canonical
  topology without claiming that semantic RE prose is current.
- Semantic RE and source topology have independent freshness receipts.

## Ownership And Storage

Topology has three lifecycle surfaces:

```text
RE run:        runs/<re-run>/re/sources/<id>/*graph*.json
Delivery run:  runs/<delivery-run>/.../verify/*graph*.json
Canonical:     re/topology/
```

Canonical topology is durable published workspace state:

```text
re/topology/
  index.json
  sources/<source-id>/
    receipt.json
    codegraph-analysis.json
    codegraph-summary.json
    perlgraph-analysis.json
    perlgraph-summary.json
```

`re/topology/index.json` is the authority for topology discovery. It lists each
configured source, its current source fingerprint, publication generation,
provider receipts, and artifact hashes. RE context artifacts under
`re/sources/<id>/` remain semantic RE. Existing CodeGraph files there migrate
to the topology registry rather than remaining a second authority.

Topology publication uses the existing RE staging, path-safety, lock, journal,
and atomic-replacement patterns. A failed topology transaction leaves the
previous valid generation untouched.

## Source Identity

The workspace graph already owns:

```text
source:<source-id>
```

This identity is reused by spec graphs, workspace graphs, published RE, and
topology results. The recently introduced `re-source:<source-id>` identity is
removed before it becomes a public contract.

Spec graphs may include a `SourceRoot` node only when its ID and path match the
canonical workspace configuration. Workspace composition merges that node into
the workspace-owned `SourceRoot` and fails on conflicting properties. A spec
that used published RE connects directly to the canonical source:

```text
spec:<spec-id> USES_SOURCE source:<source-id>
source:<source-id> DESCRIBED_BY artifact:<...>
source:<source-id> HAS_DECISION decision:<...>
```

RE publication generation, semantic fingerprint, topology fingerprint, and
artifact paths are receipts or properties. They never create alternate source
identities.

## Provider Artifact Contracts

Both providers keep their native semantic detail, but their analysis artifacts
must provide enough identity and completeness data for exact normalization.

Every emitted symbol receives a deterministic `symbol_key` derived from:

```text
source-relative file path
qualified name
symbol kind
signature, or an empty value
```

The source ID scopes the key when exposed through Echelon. The source
fingerprint is excluded so a symbol retains identity across ordinary source
revisions. Duplicate canonical symbol locators make the provider artifact
invalid; Echelon does not use line numbers as unstable identity fallbacks.

Every relationship names `source_key` and `target_key`. Display names alone are
not valid endpoints. This repairs the current CodeGraph ambiguity where the
same qualified name can occur in multiple files. Provider relationships whose
target cannot be resolved remain diagnostic evidence and are excluded from
default traversal; Echelon does not invent a code symbol.

Each provider artifact reports:

- artifact schema version and tool version;
- generation timestamp and analyzed repository path;
- supported languages and provider capabilities;
- source, symbol, and relationship counts;
- emitted counts and `complete: true|false`;
- degraded, unsupported, parse-failure, or dynamic-language diagnostics;
- provider-native confidence and provenance when available.

### CodeGraph Completeness

The bridge no longer accepts or applies `--max-symbols`. It writes every symbol
returned by the CodeGraph index and every relationship whose endpoints are in
that emitted symbol set. The existing output-size warning may remain, but it
does not alter output.

Timeouts and process resource limits are execution failures, not reasons to
silently publish a partial projection. A future bounded projection must use a
different explicit artifact role and cannot satisfy canonical topology audit.

### PerlGraph Capability

PerlGraph publishes the same receipt shape even for repositories without Perl.
`unsupported` and `empty` are valid provider states. PerlGraph retains its
relationship confidence, provenance, dynamic-pattern, and parse-diagnostic
data. These fields are not flattened into false CodeGraph parity.

## Normalized Topology Model

The Python topology layer exposes immutable, deterministic records:

- `TopologySource`
- `TopologyFile`
- `TopologySymbol`
- `TopologyRelationship`
- `TopologyReceipt`
- bounded query and traversal result records

The normalized relationship vocabulary is:

```text
CONTAINS     DECLARES      IMPORTS       REQUIRES
CALLS        EXTENDS       IMPLEMENTS    USES_ROLE
TESTS        REFERENCES    INSTANTIATES  DECORATES
OTHER
```

Each provider has an explicit mapping from its native kinds. Normalized edges
retain `provider`, `provider_kind`, confidence, provenance, and source range
when available. `OTHER` remains inspectable but is excluded from default
impact traversal.

The provider interface supplies:

```text
receipt(source)
search(source, query, types, limit)
explain(source, node)
neighbors(source, node, direction, relations, limit)
impact(source, node, max_depth, relations)
```

Results are canonically ordered, bounded, and include the exact topology
generation, source fingerprint, provider receipt hash, traversal paths, and
truncation state. Consumers never parse provider JSON directly.

## CLI

Topology is exposed at the top level because both RE and delivery use it:

```text
echelon topology audit [--source <id>] [--json]
echelon topology list-sources [--json]
echelon topology search <query> [--source <id>] [--type <type>] [--json]
echelon topology explain <node> [--source <id>] [--json]
echelon topology neighbors <node> [--source <id>] [--json]
echelon topology impact <node> [--source <id>] [--max-depth <n>] [--json]
```

Read commands do not generate or publish topology. They consume canonical
published topology and preserve audit exit behavior:

- `0`: current and complete;
- `1`: usable but degraded, incomplete, or stale;
- `2`: unavailable, malformed, ambiguous, or unsafe.

An ambiguous node selector is an error that lists bounded candidate IDs. Search
across all sources remains deterministic and includes source identity in every
result.

## Audit And Freshness

Topology audit validates:

- registry and receipt schemas;
- safe canonical artifact paths and exact artifact hashes;
- source ID membership in canonical workspace configuration;
- provider artifact schema and endpoint referential integrity;
- symbol-key uniqueness and relationship deduplication;
- reported counts against artifact contents;
- provider capability and completeness claims;
- published source fingerprint against the current configured source;
- receipt hashes and generation consistency.

Source fingerprinting reuses `harness.re_fingerprint`; no second fingerprint
algorithm is introduced. A stale topology may be inspected as historical data,
but code-level results are explicitly non-current and cannot be presented as
current impact evidence.

Semantic RE freshness remains separate. Architecture, component, contract, and
decision prose can be stale while topology is current, and vice versa.

## RE Production

RE extraction calls the shared topology producers. A validated RE publication
may atomically publish both semantic RE and topology for refreshed sources.
Both receipts use the same analyzed source fingerprint at that point, but they
remain independently auditable afterward.

Add a targeted reconciliation command:

```text
echelon re refresh --source <source-id>
```

It selects only that changed source, refreshes dependent workspace synthesis,
and publishes through the normal validated transaction. The command itself is
explicit publication intent. It must not inherit the current behavior where an
existing publication turns every reusable source into a refresh.

## Delivery Production And Landing

Delivery verification continues to generate run-local CodeGraph and PerlGraph
evidence from the feature worktree. The evidence receipt additionally records
the target source ID, analyzed commit, source fingerprint, provider versions,
artifact hashes, and completeness.

Run-local topology is never canonical while the spec is unlanded. After a
successful land operation, Echelon may promote the verified snapshot only when:

1. the spec status is `landed`;
2. the delivery target maps unambiguously to a configured source ID;
3. the verified commit equals the landed default-branch commit;
4. the recomputed source fingerprint equals the evidence fingerprint;
5. at least one provider is usable and every promoted provider artifact passes
   topology validation.

Providers are promoted independently. An unsupported PerlGraph receipt may be
published alongside healthy CodeGraph topology, and one unavailable provider
does not suppress another provider's valid current snapshot.

Promotion is a topology-only atomic transaction. It does not rewrite or mark
semantic RE prose current. Promotion failure happens after the source merge and
must not turn a successful landing into a failed landing. Echelon reports the
topology as stale or unavailable and gives a deterministic recovery command.

After landing, Echelon audits the affected source and reports:

```text
topology: current | stale | unavailable
semantic RE: current | stale | unavailable
next: echelon re refresh --source <source-id>
```

Automatic LLM-driven RE refresh is deliberately excluded from landing. It can
be slow or require human input, while landing must remain bounded and
recoverable.

## Artifact Graph Integration

Artifact graphs remain compact. They contain canonical source nodes, explicit
spec/source relationships, semantic RE artifacts, decisions, and lightweight
topology receipt artifacts. They do not copy every file, symbol, or call edge.

Requirement, task, verification, or decision links to files and symbols are
added only when canonical evidence names exact topology identities. Inferred
joins produced by future question answering stay in query results and do not
mutate persisted graphs.

## Failure Handling

- Missing provider runtime produces an unavailable provider receipt.
- Unsupported language produces a valid unsupported receipt.
- Provider timeout, malformed JSON, duplicate symbol identity, a traversable
  relationship with an unresolved endpoint, count mismatch, or hash mismatch
  fails that provider.
- A source can remain queryable through one healthy provider when another is
  unsupported or unavailable.
- Stale topology never silently falls back to run-local or cache artifacts.
- Promotion and refresh use explicit source IDs and validated paths; no
  recursive discovery outside configured sources is allowed.
- Absolute host paths from provider artifacts are not exposed as canonical
  node identity or CLI output paths.

## Testing

1. CodeGraph emits more than 10,000 symbols without truncation and reports
   complete counts.
2. Duplicate qualified names in different files receive distinct symbol keys
   and relationships resolve to exact endpoints.
3. Duplicate canonical locators fail validation.
4. CodeGraph and PerlGraph fixtures map every supported relationship kind.
5. Unsupported and empty PerlGraph states remain valid and capability-aware.
6. Registry publication, rollback, hash validation, and stale fingerprint
   detection follow existing RE transaction behavior.
7. Spec and workspace graphs use one `source:<id>` node and reject conflicts
   with workspace configuration.
8. CLI operations are deterministic, bounded, audit-aware, and provider-neutral.
9. Unlanded delivery evidence cannot be promoted.
10. Landed promotion requires exact commit and fingerprint matches.
11. Promotion failure does not reverse a successful landing.
12. Targeted RE refresh selects one source instead of refreshing every reused
    source.
13. OptaSearch exercises multi-source scale, duplicate qualified names,
    unsupported PerlGraph sources, stale topology, and post-land reconciliation.
14. Existing spec graph, workspace graph, RE publication, and delivery evidence
    suites remain green.

## Out Of Scope

- The Graph Analyst agent or natural-language answer synthesis.
- Persisting every code symbol in spec or workspace artifact graphs.
- Semantic similarity edges inferred by an LLM.
- Publishing topology from unfinished delivery branches.
- Automatically running full semantic RE during landing.
- A graph database; provider artifacts and bounded in-process indexes remain
  sufficient until measured scale proves otherwise.
