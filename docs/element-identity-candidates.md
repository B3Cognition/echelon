# Inactive identity candidate checks

`IdentityStore.check_discovery_candidate` checks an explicit captured artifact
bundle against one registry read transaction. It returns immutable `diagnostics`
and `references`; it does not allocate, revise, publish, assess evidence, or grant
semantic approval. No producer, publication owner, graph, or memory consumer is
connected to this API. No canonical files are opened by the checker.

`IdentityStore.check_identity_candidate` exposes the same read-only algorithm
through the broader `IdentityEditScope`. It adds definition preflight for the six
U/A/FR/NFR/AC/T families without weakening the discovery policy. The two exact
scope types select fixed internal policies; callers cannot override role,
lifecycle-family, caption, or nesting rules.

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

| Explicit controller role | Discovery wrapper | General wrapper definitions | References |
| --- | --- | --- | --- |
| `unknowns` | U definitions | U definitions | Adapter-recognized local references |
| `assumptions` | A definitions | A definitions | Adapter-recognized local references |
| `requirements` | Unsupported | FR/NFR/AC definitions | Adapter-recognized local references |
| `tasks` | Unsupported | T definitions | Canonical `req`/`depends` plus other adapter-recognized references |
| `lexicon` | Unsupported | Native FR/NFR/AC definitions | Native `DEPENDS` plus other adapter-recognized references |
| `investigation`, `evidence`, `references` | References only | References only | Adapter-recognized local references |
| `issues`, `lexicon_projection`, unrecognized roles | Unsupported | Unsupported | None interpreted by the checker |

Roles are never inferred from filenames. Unsupported roles produce
`unsupported_role`. ISS may be an existing exact reference target, but issue
occurrences are not definitions and ISS lifecycle effects are outside both scope
policies. Native `lexicon` is authoritative; `lexicon_projection` is not a second
definition source. Naming duplicate authoritative definitions in two supported
artifacts never makes the duplicate legal.

The existing [artifact grammar](element-identity-artifacts.md) is unchanged;
malformed syntax, qualified references, wrong-role declarations, and other parser
diagnostics remain blocking and identify their before/after image. Duplicate
definitions across files and numeric-padding aliases are rejected. Intervals
produce `unsupported_reference_range`, with no endpoint expansion or implied
coverage of the interval. References never create entities.

Definitions require a matching assessed baseline head, exact declaration content,
and validated namespace and identity bindings. A rendered caption is distinct
from the immutable registry subject: baseline authentication compares exact source
content, and heading preservation compares the before and after U/A captions.
The existing lifecycle planner separately preserves the registry subject.
Imported-but-unassessed content cannot be adopted through this checker as a
history import. New definitions require an exact reserved creation or a reserved
transition successor, with exact projected content; their captions need not equal
their registry subjects. Active content edits require matching lifecycle
revisions; changing the U/A caption requires a new identity through an explicit
replacement, split, or merge.
Retirement and supersession preserve exact prior content. Unchanged terminal
declarations are retained history; scoped removal does not retire them again.

Discovery lifecycle changes are limited to U/A. General lifecycle changes are
limited to U/A/FR/NFR/AC/T. Every change must name a scoped declaration present in
the bundle. The shared lifecycle planner runs on the same connection. A rejected
batch yields `lifecycle_rejected` and prevents dependent projection and reference
assessment; no partial projection is used.

U/A captions retain the reviewed discovery rule in both wrappers: changing a
caption requires a new identity through an explicit transition. FR/NFR/AC wording
and canonical task titles are rendered source, not registry subjects. They may
change only when an explicit scoped revision preserves the immutable stored
subject and supplies exact new adapter content. Structural acceptance says
nothing about semantic continuity; existing requirements, task, and Lexicon
quality validators remain separate.

## Exact edit scope

`DiscoveryEditScope(writable_paths, element_ids, unowned_text_paths=())` separates
artifact permission, declaration permission, and permission to edit surrounding
source. Every writable path must be in the captured bundle, and unowned-text
paths must be writable. Every changed artifact must be writable; every introduced,
removed, or edited declaration and every lifecycle-affected identity must be in
element scope. Read-only dependencies belong in the bundle, too.

`IdentityEditScope` has the same three fields but accepts U/A/FR/NFR/AC/T labels.
Nested requirement declarations must have source intervals that are disjoint or
properly contained; crossing, identical, malformed, and out-of-bounds intervals
are rejected. Discovery retains its original non-overlap rule.

Unless unowned-text permission is explicit, text outside authorized declaration
spans must remain exactly equal, including Unicode, CRLF, comments, and order.
The comparison replaces surviving authorized declarations with collision-free
NUL-delimited exact-ID markers and removes authorized introduced/deleted spans
only on the side where they occur. For nested requirements, masking covers only
the outermost authorized span and skips authorized descendants already contained
by it. Every declaration's old and new full content is still compared
independently. Consequently, editing a nested AC changes the stored full content
of its FR ancestor and requires explicit scope and revision for both. Parent scope
does not authorize changed descendants; child scope does not silently revise its
ancestor. An unchanged child under an explicitly revised parent remains exact.
This is source-span ownership, not line-based diff permission. Unowned-text
permission does not permit editing unscoped definitions or bypass lifecycle
checks. Changes to a reference-only artifact require both writable and
unowned-text permission.

## Reference states, not evidence verdicts

References resolve by exact same-spec labels against validated current/projected
heads. Generic and evidence references may target terminal history. In the
general wrapper, canonical task `req`/`depends` fields and native Lexicon
`DEPENDS` clauses reach dependency validation through their real adapters. Their
exact target must be active: imported-but-unassessed, retired, and superseded
targets produce `inactive_dependency`. Proposed active creations and revisions in
the same lifecycle batch may resolve. Missing exact targets remain
`reference_identity_mismatch`. Intervals remain explicitly unsupported and are
never expanded into dependency endpoints.

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

Qualified and interval reference resolution, issue occurrence authorization,
derived Lexicon/source binding, JSON source-inventory checks, durable publication
and CAS, producer integration, graph/memory consumers, history tools, bounded
repair, combined provider simulation, and explicit rollout remain follow-on work.
