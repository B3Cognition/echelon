# Inactive discovery candidate checks

`IdentityStore.check_discovery_candidate` checks an explicit captured artifact
bundle against one registry read transaction. It returns immutable `diagnostics`
and `references`; it does not allocate, revise, publish, assess evidence, or grant
semantic approval. No producer, publication owner, graph, or memory consumer is
connected to this API. No canonical files are opened by the checker.

Callers provide `CandidateArtifact(path, role, before_text, after_text)` entries.
Paths use canonical relative POSIX syntax. Text is exact UTF-8 encodable source
without NUL; `None` denotes an absent image and the empty string denotes an empty
file. At least one image per artifact and one artifact per request are required.
All caller sequences are copied into tuples and validated before the transaction.
Malformed requests raise `IdentityStoreError`; structural candidate defects are
returned as diagnostics. Nonempty lifecycle batches use existing strict request
validation. An empty batch proposes no lifecycle change.

Detectable damage to retained namespace counters, heads, identity bindings,
reservation records, or binding receipts also raises `IdentityStoreError`.
Relevant existing authority is validated before interpreting candidate defects,
on the same connection. Missing or unassessed baseline entities and mismatched
declaration content are candidate defects; a present but internally inconsistent
authority record is not repairable by editing the candidate. Malformed labels
inside otherwise valid source text are candidate diagnostics, not API errors.

## Supported artifacts

| Explicit controller role | Definitions | References |
| --- | --- | --- |
| `unknowns` | U declarations | Adapter-recognized local references |
| `assumptions` | A declarations | Adapter-recognized local references |
| `investigation`, `evidence`, `references` | None | Adapter-recognized local references |

Roles are never inferred from filenames. Other roles produce `unsupported_role`.
The existing [artifact grammar](element-identity-artifacts.md) is unchanged;
malformed syntax, qualified references, wrong-role declarations, and other parser
diagnostics remain blocking and identify their before/after image. Duplicate
definitions across files and numeric-padding aliases are rejected. Intervals
produce `unsupported_reference_range`, with no endpoint expansion or implied
coverage of the interval. References never create entities.

Definitions require a matching assessed baseline head, exact subject and content,
and validated namespace and identity bindings. Imported-but-unassessed content
cannot be adopted through this checker as a history import. New definitions
require an exact reserved creation or a reserved transition successor. Active
content edits require matching lifecycle revisions; changing the U/A caption
requires a new identity through an explicit replacement, split, or merge.
Retirement and supersession preserve exact prior content. Unchanged terminal
declarations are retained history; scoped removal does not retire them again.

Lifecycle changes are limited to U/A identities and must name scoped declarations
present in this bundle. The shared lifecycle planner runs on the same connection.
A rejected batch yields `lifecycle_rejected` and prevents dependent projection
and reference assessment; no partial projection is used.

## Exact edit scope

`DiscoveryEditScope(writable_paths, element_ids, unowned_text_paths=())` separates
artifact permission, declaration permission, and permission to edit surrounding
source. Every writable path must be in the captured bundle, and unowned-text
paths must be writable. Every changed artifact must be writable; every introduced,
removed, or edited declaration and every lifecycle-affected identity must be in
element scope. Read-only dependencies belong in the bundle, too.

Unless unowned-text permission is explicit, text outside authorized declaration
spans must remain exactly equal, including Unicode, CRLF, comments, and order.
The comparison replaces surviving authorized declarations with collision-free
NUL-delimited exact-ID markers and removes authorized introduced/deleted spans
only on the side where they occur. It rejects overlapping spans. This is source
span ownership, not line-based diff permission. Unowned-text permission does not
permit editing unscoped definitions or bypass lifecycle checks. Changes to a
reference-only artifact require both writable and unowned-text permission.

## Reference states, not evidence verdicts

References resolve by exact same-spec labels against validated current/projected
heads. Other families may be referenced when already materialized, but may not
be changed here. Generic and evidence references may target terminal history.
The checker rejects `requires`/`depends` targeting terminal heads defensively.
The current parser emits those dependency relations through task-role regions;
task and Lexicon candidate coverage is outside this discovery API. That branch
does not imply those artifact roles are supported here.

Retained claims are read and authenticated by the existing binding reader for the
exact source path and SHA-256 of UTF-8 bytes. An occurrence matches only a claim
whose anchor is exactly `span:<start>:<end>`, with the same target and relation.
Offsets are Python string offsets, not byte offsets. Other anchors are not
reinterpreted. Revision values retain deterministic operation/entry order.

| State | Meaning |
| --- | --- |
| `unassessed` | No matching non-null assessed revision |
| `current` | At least one matching non-null revision equals the active projected/current head |
| `historical` | Non-null assessed revisions exist, but none certifies that active head |

An unchanged evidence source may become historical when its target is revised.
A changed source hash receives no carried-over claims. Null claims never certify
current content. No claims are inserted, copied, or rebound. Reference states are
returned separately from structural diagnostics and cannot certify a semantic
gate. Diagnostics are deduplicated only when identical and sorted by path, ID,
code, and detail; reference states follow path and source-span order.

## Publication boundary

Zero diagnostics means only that these explicit supported checks found no defect
in the supplied snapshot. The checker cannot prove that all required artifacts
were supplied or that preimages are canonical. A later publication owner must
authenticate the captured set and preimages, bind staged bytes and effects to
durable intent/CAS, and decide required evidence gates. A detached check cannot
authorize publication after concurrent registry or source changes.

Requirements/tasks, issue occurrence authorization, derived Lexicon, JSON
evidence, producer integration, graph/memory consumers, history tools, bounded
repair, combined provider simulation, and explicit rollout remain follow-on work.
