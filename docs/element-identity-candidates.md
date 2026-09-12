# Inactive identity candidate checks

`IdentityStore.check_discovery_candidate` checks an explicit captured artifact
bundle against one registry read transaction. It returns immutable `diagnostics`
and `references`; it does not allocate, revise, publish, assess evidence, or grant
semantic approval. No producer, publication owner, graph, or memory consumer is
connected to this API. No canonical files are opened by the checker.

`IdentityStore.check_identity_candidate` exposes the same read-only algorithm
through the broader `IdentityEditScope`. It adds definition preflight for the six
U/A/FR/NFR/AC/T families and explicit ISS occurrence preflight without weakening
the discovery policy. The two exact
scope types select fixed internal policies; callers cannot override role,
lifecycle-family, caption, or nesting rules.

The general wrapper also accepts explicit supplemental associations:
`projection_sources: Sequence[LexiconProjectionSource]` and
`evidence_inventories: Sequence[EvidenceInventoryContext]`. A projection
descriptor names its captured projection, authoritative requirements source, and
optional captured glossary. An inventory descriptor names its captured JSON
inventory and the exact seed locators validation must cover. These descriptors
are structural controller assertions only, not durable binding receipts,
semantic approval, or a publication-success signal.

Callers provide `CandidateArtifact(path, role, before_text, after_text)` entries.
Paths use canonical relative POSIX syntax. Text is exact UTF-8 encodable source
without NUL; `None` denotes an absent image and the empty string denotes an empty
file. At least one image per artifact and one artifact per request are required.
An absent image contributes an empty typed fact set without invoking its adapter;
a present empty string is still parsed and may be invalid, as it is for native
Lexicon. Creating or removing a whole Lexicon file also requires explicit
unowned-text permission for its `ARTIFACT`/`TITLE` content outside declarations.
All caller sequences, descriptors, and inventory seed sequences are copied into
tuples and validated before the transaction.
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
| `lexicon_projection` | Unsupported | Explicitly associated derived declarations; never authoritative definitions | Projection references with the projection path/hash/span |
| `glossary` | Unsupported | Empty typed fact set with exact content hash | None; labels and URLs are opaque text |
| `evidence_inventory` | Unsupported | Empty typed fact set with exact content hash | None; source IDs and locators are opaque text |
| `investigation`, `evidence`, `references` | References only | References only | Adapter-recognized local references |
| `issues` | Unsupported | Explicit report occurrences; never authoritative definitions | Issue-body references with the original report path/hash/span |
| Unrecognized roles | Unsupported | Unsupported | None interpreted by the checker |

Roles are never inferred from filenames. Unsupported roles produce
`unsupported_role`. ISS may be an existing exact reference target. Its report
occurrences are not definitions; explicit ISS lifecycle effects are supported
only by the general wrapper with report context. Native `lexicon` is
authoritative; `lexicon_projection` is not a second
definition source. Naming duplicate authoritative definitions in two supported
artifacts never makes the duplicate legal.

## Supplemental associations

Roles are still never inferred from filenames. Every captured
`lexicon_projection` requires exactly one `LexiconProjectionSource`; every
captured `evidence_inventory` requires exactly one `EvidenceInventoryContext`.
Descriptor primary paths cannot repeat. Every named path must use canonical
relative POSIX syntax and must be present in the captured bundle with the
declared role. A present projection image requires the corresponding source
image. A declared glossary may be absent in either image, in which case
validation receives `None`; a present empty glossary remains the exact empty
string. An undeclared glossary is never discovered by filename or opened from
disk.

Each present projection image runs the shared complete SPEC Lexicon validator on
the exact captured projection, source, and optional glossary text. Every finding
is returned as `invalid_lexicon_projection` with its original code, message,
line, span, and image; parser diagnostics remain independent. The managed
FR/NFR/AC projection labels must also exactly equal the typed declarations from
the named requirements source image, otherwise
`projection_authority_mismatch` is returned. This does not add ERROR or other
families to the registry. Multiple projections may explicitly name the same
source. Native Lexicon and Markdown declarations remain independently
authoritative and still conflict when duplicated.

Each present inventory image runs the shared inventory validator with the exact
snapshotted seed locators. Structural, frontier, and required-seed failures are
returned as `invalid_evidence_inventory`. A present empty JSON document is
invalid; an absent image is not parsed. Missing or mismatched associations are
blocking diagnostics (`projection_binding_missing`, `inventory_binding_missing`,
or `supplemental_binding_mismatch`) and never imply empty required-seed coverage.

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

Discovery lifecycle changes are limited to U/A. General lifecycle changes cover
U/A/FR/NFR/AC/T/ISS. Every change must name a scoped, validated declaration or
issue occurrence present in the bundle. The shared lifecycle planner runs once
for the complete mixed-family batch on the same connection. A rejected
batch yields `lifecycle_rejected` and prevents dependent projection and reference
assessment; no partial projection is used.

U/A captions retain the reviewed discovery rule in both wrappers: changing a
caption requires a new identity through an explicit transition. FR/NFR/AC wording
and canonical task titles are rendered source, not registry subjects. They may
change only when an explicit scoped revision preserves the immutable stored
subject and supplies exact new adapter content. Structural acceptance says
nothing about semantic continuity; existing requirements, task, and Lexicon
quality validators remain separate.

## Explicit issue reports

The general wrapper accepts `issue_reports: Sequence[IssueReportContext] = ()`.
The immutable descriptor is exported from `harness.element_identity_issue_candidate`
and contains `path`, `before_report_id`, `after_report_id`, `before_occurrences=()`,
and `after_occurrences=()`. Both occurrence tuples use the existing exact
`IssueOccurrence` type. Descriptor and nested sequences are snapshotted and
scalar-validated before the single query-only transaction. Invalid types,
paths, report-ID scalars and duplicate context paths raise `IdentityStoreError`.
Empty and duplicate occurrence tuples are interpreted by candidate relationship
checks, not by the binding API's nonempty write-batch policy.

Each `issues` artifact requires explicit report context. A present report needs
a nonblank report ID; an absent report needs `None` and no occurrences. A present
report with zero typed declarations can have a report ID and an empty tuple.
Missing context produces `issue_report_context_missing`; a missing/wrong-role
target or disagreement with image presence produces `issue_report_mismatch`.
These are blocking diagnostics, never implicit unbound review approval.

Every typed occurrence maps one-to-one by display ID to an explicit descriptor.
Report ID, SHA-256 of the complete original report, rendered caption/title and
body must match exactly. The issue body is the typed declaration content after
the first heading-line newline: it excludes the heading, preserves subsequent
CRLF/Unicode/whitespace and the adapter-owned Resolution Guidance companion,
and excludes report footers. Missing, extra or mismatched mappings and duplicate
display or durable IDs within a report produce `issue_occurrence_mismatch`.
The same durable issue may appear independently in different explicit reports.
Occurrences never enter authoritative definition or numeric-ordinal maps.

Before occurrences require exact retained binding payloads authenticated through
the existing connection-owned binding reader and receipt validator. Every field
must match; a fingerprint alone is insufficient. Missing exact provenance yields
`unrecorded_issue_occurrence`. Damaged retained records, receipts or targets raise
the existing integrity exception. A retained body interpretation that includes
text outside the current typed block boundary rejects explicitly; it is never
rewritten or re-fingerprinted. Historic local display labels may map to durable
ISS IDs only through these exact retained records.

Every managed after label must equal its canonical durable `issue_id`, including
an existing identity's preserved legacy spelling. Reports cannot restart ISS
numbering or reuse an old local label for a different canonical issue;
`issue_display_identity_mismatch` blocks such mappings. New after occurrences
must match the exact current/projected active revision, immutable subject/title
and body, or receive `issue_revision_mismatch`.

There is one historical exception: the complete after text, report ID and full
occurrence tuple may equal the authenticated before image exactly. Those
retained active-revision occurrences can remain visible after the current head
advances or becomes terminal. Canonical after-label rules still apply. Changed
bytes or attribution cannot use this exception to issue fresh stale evidence.
Active proposed creations, revisions and transition successors independently
require a matching projected-revision after occurrence (`issue_occurrence_missing`),
even when an old report remains unchanged elsewhere. Retirement and supersession
require explicit canonical element scope and a validated retained before
occurrence. A scoped occurrence can disappear, or exact history can stay visible.

Report omission does not retire an active issue or close a review obligation.
The checker does not interpret PASS/FAIL, resolved/unresolved, or banzai
eligibility. Original occurrences, source claims and fingerprint resolution
history remain unchanged. `issue_identity.issue_fingerprint` and
`matching_issue_resolution` retain their original behavior: meaningful evidence
or repair-obligation changes cannot inherit an unrelated resolution, while
presentation/status changes retain their existing fingerprint treatment.
Revision-bound reference claims are an independent provenance check. A later
managed quality gate must reconcile outstanding issues explicitly against the
existing resolution ledger; this structural API cannot certify resolution.

The role adapter's grammar remains unchanged. It recognizes digit-led ISS
spellings, including supported legacy composites. A digit-free legacy heading
such as `ISS-legacy` with an explicit occurrence rejects because there is no typed
declaration to bind. With an empty occurrence tuple it remains unowned report
text, subject to artifact/unowned permissions; a zero-diagnostic result does not
prove report completeness. Managed producers and historical migration must
reconcile unsupported source spellings explicitly before claiming complete
managed coverage.

## Exact edit scope

`DiscoveryEditScope(writable_paths, element_ids, unowned_text_paths=())` separates
artifact permission, declaration permission, and permission to edit surrounding
source. Every writable path must be in the captured bundle, and unowned-text
paths must be writable. Every changed artifact must be writable; every introduced,
removed, or edited declaration and every lifecycle-affected identity must be in
element scope. Read-only dependencies belong in the bundle, too.

`IdentityEditScope` has the same three fields but accepts U/A/FR/NFR/AC/T/ISS labels.
Nested requirement declarations must have source intervals that are disjoint or
properly contained; crossing, identical, malformed, and out-of-bounds intervals
are rejected. Discovery retains its original non-overlap rule.

Derived projection declarations retain their real spans in this scope check.
Changing a block requires the projection artifact path and its exact element ID;
permission for the source does not authorize the projection. Header, source-hash,
glossary, inventory, and other text outside managed spans requires unowned-text
permission. A projection may be introduced or removed without a second lifecycle
event when its authoritative source identity is otherwise preserved, created, or
retired correctly.

Issue report scope uses full rendered occurrence blocks with their canonical
IDs mapped from the explicit descriptors and their original spans/text intact.
A historical display alias never grants permission for a different canonical
issue. Multiple reports remain independently artifact-scoped. Report headings,
footers and layout outside issue blocks require unowned-text permission;
Resolution Guidance inside the typed block belongs to that issue. Creating or
removing an empty report also requires writable and unowned-text permission,
because image presence is distinct from an empty image.

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
general wrapper, canonical task `req`/`depends` fields and native or derived
Lexicon `DEPENDS` clauses reach dependency validation through their real
adapters. Their
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
A changed source hash, including changed projection wording for the same
authoritative revision, receives no carried-over claims. Projection claims retain
the projection's path, hash, and span rather than the associated source's
provenance. Null claims never certify current content. No claims are inserted,
copied, or rebound. Reference states are returned separately from structural
diagnostics and cannot certify a semantic gate. Diagnostics are deduplicated only
when identical and sorted by path, ID, code, and detail; reference states follow
path and source-span order.

## Publication boundary

Zero diagnostics means only that these explicit supported checks found no defect
in the supplied snapshot. The checker cannot prove that all required artifacts
were supplied or that preimages are canonical. A later publication owner must
authenticate the captured set and preimages, bind staged bytes and effects to
durable intent/CAS, and decide required evidence gates. A detached check cannot
authorize publication after concurrent registry or source changes.

Qualified and interval reference resolution, historical reconciliation/import
tools, canonical and staged authentication, semantic
review of changed derived wording, durable publication intents/receipts and CAS,
managed report producer/resolution-gate integration, graph/memory consumers,
bounded repair, combined provider
simulation, and explicit rollout remain follow-on work. The general checker stays
inactive and cannot authenticate completeness or authorize publication.
