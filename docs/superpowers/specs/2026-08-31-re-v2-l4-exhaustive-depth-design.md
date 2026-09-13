# RE v2 L4 Selective Exhaustive Depth Design

**Status:** Draft for final user review; implementation not started
**Issue:** EGR-169, final selective-deepening increment
**Protocol:** 2.8
**Run manifest schema:** 7
**Follows:** protocols 2.2 through 2.7
**Precedes:** protocol 2.9 L4-aware synthesis and EGR-170 atomic repair

## Summary

Protocol 2.8 adds explicitly selected L4 exhaustive analysis to RE v2 without
changing the identity or meaning of any protocol-2.2-through-2.7 authority. An
operator selects domains with `--source` and optional `--domain`, or explicitly
requests the complete workspace with `--all`. The controller authenticates or
creates the selected L3 prerequisite under a durable orchestration intent,
freezes a deterministic exhaustive plan, stages a complete byte-range evidence
view of the selected immutable source snapshot, generates bounded domain and
source-composition evidence slices, independently verifies every slice, and
creates an L4 target root only when the exact planned source-and-semantic closure
is accepted.

L4 is deliberately granular. It does not ask one model call to exhaustively
rewrite a domain. A deterministic plan divides each selected domain into
bounded evidence slices derived from the immutable source partition, L0
inventory and evidence, L2 behavioral depth, and L3 audit authority. Accepted
slices are immediately reusable checkpoints. One malformed or semantically
insufficient slice can consume at most two targeted producer repairs and can
never cause accepted siblings to be regenerated.

Protocol 2.8 can start from a closed L3 authority or from an L3 terminal state
whose only unresolved class is `requires_deeper_evidence`. When the selected
L3 prerequisite does not yet exist, `deepen --to L4` first commits an immutable
`DeepenOrchestrationIntentV1`, then visibly creates or reuses L3. If L3 pauses or
the process exits, the intent survives and `echelon re continue` resumes the
same chain rather than losing the pending L4 request. After L4 evidence
completes for a deeper-evidence blocker, the controller automatically and
visibly creates or reuses an immutable
protocol-2.8 closure successor over the frozen L3 findings and accepted L4
evidence. Other L3 blocker classes do not permit L4 execution.

An L4 run never publishes workspace `re/` output and never claims full
workspace quality. Protocol 2.9 will add a separate L4-aware synthesis child.
Only an all-scope, L4-complete authority whose inherited L3 findings are closed
either natively or by an `L4SemanticClosureRootV1`, followed by successful
protocol-2.9 synthesis, may make the future full-quality publication claim.

## Problem

RE v2 currently provides:

- immutable L0 inventory and evidence;
- reusable L1 compact baselines;
- selected L2 behavioral depth;
- frozen L3 semantic audit epochs and bounded closure;
- cross-run checkpoint adoption; and
- deferred protocol-2.7 workspace synthesis.

The remaining EGR-169 gap is exhaustive depth for explicitly critical domains.
Treating L4 as another workspace-wide profile would recreate the failure mode
that motivated RE v2: large prompts, repeated whole-domain repair, mutable
coverage, and enormous token spend when only a small portion is missing or
malformed. Treating L4 as a single unverified model artifact would be cheaper
but could not support a high-confidence or future full-quality claim.

L3 also intentionally leaves `requires_deeper_evidence` unresolved. Without
L4, that class is a truthful but permanent terminal debt. L4 must supply the
missing evidence without mutating the frozen L3 epoch, then return that evidence
to a new immutable closure successor.

Finally, the current successful OptaSearch lineage contains L2 and synthesis
authority but no L3 semantic audit. Requiring operators to manually discover
and run each prerequisite would make the layered model operationally brittle.
The L4 command therefore owns visible prerequisite orchestration while keeping
each run independently immutable.

## Goals

- Register L4 as protocol 2.8 and manifest schema 7.
- Keep L4 explicitly selective; `--all` is the only all-workspace request.
- Automatically create or reuse missing selected-scope L3 prerequisites.
- Persist the pending L4 request before prerequisite execution so the complete
  chain remains resumable after an L3 pause, crash, or process exit.
- Provide a no-write/no-dispatch `--shadow` preview before costly L4 execution.
- Accept L3 parents that are complete or blocked solely by
  `requires_deeper_evidence` in the selected scope.
- Freeze one deterministic, complete slice plan per selected domain and one
  source-composition plan per selected source.
- Ensure every in-scope source record, every eligible source byte/range, and
  every required behavioral aspect is assigned to the frozen plan exactly and
  explainably; pre-existing L0 omissions can never count as L4 coverage.
- Generate bounded evidence slices independently.
- Require an independent semantic verifier PASS for every accepted slice.
- Permit at most two targeted producer repairs after initial generation.
- Stop early after two identical non-improving verifier outcomes.
- Reserve budget for both generation and verification before generation.
- Export accepted slices and roots as adoptable certified checkpoints.
- Recover every controller, producer, and verifier crash boundary without
  duplicating a durably captured provider call.
- Automatically and visibly route completed deeper evidence into an immutable
  protocol-2.8 closure successor over the inherited L3 epoch.
- Render truthful, prominent progress and terminal banners.
- Preserve exact protocol-2.2-through-2.7 and v1 behavior.

## Non-goals

- Workspace synthesis or publication.
- A full-workspace-quality claim.
- Mutating protocol 2.7 to consume L4 authority.
- Automatically starting protocol-2.9 synthesis.
- Atomic repair of L0, L1, L2, or L3 artifacts.
- Resolving `requires_human_decision`, lower-artifact defects, or changed-source
  blockers through L4.
- Model-led discovery that can add slices after activation.
- Open-ended repair, adaptive attempt caps, or attempts unlocked by budget
  increases.
- Making RE v2 the default engine.
- Parallel provider execution in the first protocol-2.8 release.

## Approved decisions

1. L4 is explicitly selective; full selection requires `--all`.
2. A terminal L3 parent blocked only by `requires_deeper_evidence` is eligible.
3. L4 never publishes or independently claims full workspace quality.
4. Work is a deterministic slice DAG, not one monolithic domain artifact.
5. Every slice requires independent semantic verification.
6. Each slice permits one initial producer attempt and at most two repairs.
7. L3-finding closure handoff after completed deeper evidence is automatic and
   visible through a versioned protocol-2.8 successor.
8. Missing selected-scope L3 is automatically created or reused before L4.
9. Protocol 2.9 is a separate L4-aware synthesis increment; protocol 2.7 stays
   frozen.
10. L4 exhaustive evidence closes every eligible selected snapshot byte/range;
    L0 evidence omissions are supporting debt, never L4 coverage.
11. Automatic L3 prerequisite work is governed by a durable resumable
    orchestration intent committed before L3 starts.
12. Reusable slice identity binds target-local L3 projections, not a global
    selection-bound audit epoch.
13. Shadow reports exact realized reuse and bounded conditional intervals for
    deferred dependencies rather than impossible exact forecasts.
14. L4 checkpoints use a separate V2 projection; V1 origins and bytes remain
    unchanged and recognized V2 origins are not V1 corruption.
15. Partial synthesis inputs follow an explicit selected/unselected eligibility
    matrix and can never be promoted to complete authority.
16. Zero-call closure mismatch is reported as integrity failure, not semantic
    finding failure.
17. Exhaustive and closure-successor manifests have disjoint closed field sets;
    closure mode contains no provider or budget authority.

## Versioning and compatibility

Protocol 2.8 uses `RunManifestV7` with:

- `schema_version: 7`;
- `engine: re-v2`;
- `engine_protocol_version: "2.8"`;
- `run_mode: "exhaustive-depth"` with
  `requested_goals: ["selective-exhaustive-depth"]`, or
  `run_mode: "l4-closure-successor"` with
  `requested_goals: ["l4-evidence-closure"]`;
- `target_layer: "L4"`; and
- the following closed mode-dependent field matrix.

| Authority | `exhaustive-depth` | `l4-closure-successor` |
|---|---|---|
| `selection` and source/partition authority | required | required, exactly equal to the evidence run |
| lineage | one `ParentLineageV1` analysis parent | one `L4ClosureLineageV1` binding the L3 and L4 inputs |
| workspace-partition and inherited artifact-policy catalogs | required | forbidden; authenticated through the closure parent/evidence root |
| `ParentAuthorityBundleV3` | required | forbidden |
| `L4ClosureParentBundleV1` | forbidden | required |
| `ExhaustiveRequestV1` | required | forbidden |
| `L4ClosureRequestV1` | forbidden | required |
| exhaustive plan and policy catalogs | required | forbidden; inherited through the pinned L4 run root |
| provider executor catalog and attempt policy | required | forbidden |
| initial token/active-time budget policy | required | forbidden |
| accepted `L4RunRootV1` | forbidden at creation | required |
| deterministic closure-policy authority | forbidden | required |

Absent means the field is not present in the closed schema, not `null` and not a
zero-valued placeholder. Closure-successor mode therefore has no provider,
attempt, reservation, or resource-authorization surface to misinterpret.
In code, `RunManifestV7` is the public discriminated union of
`ExhaustiveRunManifestV7` and `L4ClosureRunManifestV7`; the manifest-first loader
selects the concrete closed decoder from `run_mode`. This avoids an optional
mega-schema whose invalid field combinations could survive construction.

Protocol dispatch remains manifest-first. A schema-7 run always routes to the
protocol-2.8 loader, status renderer, controller, recovery policy, and
materializer. Earlier manifests never import protocol-2.8 code through their
runtime dispatch. Shared kernel primitives may be reused, but existing protocol
authorities and their canonical bytes are not rewritten.

Protocol 2.8 adds new L4 policy and executor entries rather than changing
earlier catalogs. The implementation must record and test the exact repository
baseline for protocol-2.2-through-2.7 compatibility. Any unavoidable shared
fix requires its own versioned interface and explicit compatibility proof.

Protocol 2.9 will use a later manifest schema. It may adopt protocol-2.7
synthesis artifacts when their exact dependencies remain current, but that is
outside this design.

## Operator request and prerequisite orchestration

The user-facing request is:

```text
echelon re deepen --to L4 (--all | --source <id> [--domain <id> ...])
                  [--from-run <run-id>]
                  [--token-limit <n>]
                  [--active-ms-limit <n>]
                  [--shadow]
```

Selection rules remain the existing deepening rules:

- `--all` cannot be combined with `--source` or `--domain`;
- explicit selection requires at least one `--source`;
- domain selectors require exactly one source and resolve to stable domain
  keys before any child activation;
- duplicate, ambiguous, and unknown selectors fail before child creation; and
- sources with zero domains remain valid. Their source-composition plan, rather
  than their domain count, determines whether provider work is required.

`--from-run` may name a compatible L2, L3, checkpoint-adoption, or synthesis
lineage. If it names synthesis, the CLI authenticates its accepted source
outcomes and follows them to their analysis authority. Synthesized Markdown or
workspace artifacts never become L4 source evidence.

Synthesis lineage is resolved per selected source under this closed matrix:

| Synthesis outcome | Selected by this request | L4 prerequisite behavior |
|---|---:|---|
| complete | yes | traverse to and authenticate the exact lower analysis authority |
| partial | no | retain as unselected lineage debt; it does not contaminate selected scope |
| partial because L3 is `next_epoch_required` | yes | stop before L4 and require the explicit next L3 audit epoch named by status |
| partial for any other reason | yes | reject as an unsupported/incomplete analysis parent |

An `--all` request therefore rejects any partial synthesis source. The
controller never converts a protocol-2.7 partial acceptance into complete L4
input, and it never silently falls back from a selected partial L3 result to an
older L2 result. A new L3 prerequisite is automatic only when selected L3
authority is absent; an existing but ineligible L3 authority remains a visible
blocker so audit-epoch intent is not guessed.

### `DeepenOrchestrationIntentV1`

Every non-shadow L4 request commits an immutable orchestration intent before it
starts or activates a prerequisite. The intent is stored below
`runs/.re-v2-orchestrations/<orchestration-request-id>/` with an append-only,
content-free orchestration event chain and a rebuildable projection. The hidden
namespace is durable run history, is excluded from RE run/checkpoint-origin
enumeration, and is not disposable `.echelon/re-v2/checkpoints/` cache state. It
is not an RE analysis run and does not merge child ledgers.

The intent binds:

- input run manifest and authenticated terminal-event hashes;
- source snapshot, partition, and resolved `SelectionScopeV1`;
- the semantic L4 request, exhaustive policy, and executor authorities;
- initial L4 token and active-time authorization;
- the required L3 prerequisite request identity; and
- the ordered state machine `awaiting_l3 -> awaiting_l4 -> awaiting_closure -> complete`.

The orchestration request identity excludes resource authorization but includes
all semantic fields. Repeating the same command reuses the intent; larger L4
authorization is appended as an intent event and is applied when the L4 child
exists. Events bind created/reused child run IDs and their manifest/terminal
hashes. At most one child may satisfy each transition. A source-authority change
blocks the intent and requires a new request rather than retargeting it.

For the requested selection, the command resolves the strongest exact L3
authority compatible with the snapshot, partition, lower artifact policies,
and selection. If no selected L3 authority exists, it creates or reuses a
selected L3 child using the existing protocol-2.5 path. If selected L3 authority
exists but is terminal-ineligible, orchestration blocks instead of bypassing it
through older lower authority. The command displays the prerequisite run ID and
waits for its terminal authority before creating the L4 child. If L3 pauses, the
orchestration intent remains `awaiting_l3`.
Continuing that L3 run, by active pointer or explicit run ID, also resumes its
unique open intent after L3 reaches terminal authority. A process crash at any
transition is recovered from the intent events and authenticated child state.

Eligible L3 terminal states are:

- complete for every selected audit target; or
- blocked with a frozen epoch where every unresolved selected finding has class
  `requires_deeper_evidence`.

An unselected blocker does not contaminate a strictly selected L4 request.
`--all` requires eligibility across the complete source/domain selection.
`requires_human_decision`, lower-artifact mutation requirements, an unfinished
audit target, deferred next-epoch observations, changed source authority, or a
mixed blocker set stops orchestration before L4 activation. Status must name
the blocking class and exact safe next action.

The visible lineage is:

```text
input run
  -> durable orchestration intent
     -> selected L3 prerequisite (created or reused when needed)
     -> protocol-2.8 L4 child
     -> protocol-2.8 L4 closure successor (only for deeper-evidence findings)
```

Each child arrow names an independently authenticated immutable run. The intent
records links and transition state only; it does not merge child event ledgers,
usage, or analysis state.

`--shadow` performs no writes, pointer changes, checkpoint staging, or provider
dispatch. With an eligible selected L3 authority it builds the exact plan and
reports target/entry counts, immediately realizable versus deferred source
entries, and exact compatibility for checkpoints whose dependencies are already
realized. For source-composition entries that depend on not-yet-known domain-root
hashes, it reports conditional checkpoint candidates rather than calling them
compatible. Required calls and conservative token/active-time reservations are
reported as a minimum/maximum interval: the minimum assumes every conditional
candidate later authenticates, and the maximum assumes none does and includes
all fixed retries. Counts become exact when all dependency roots are known. If
L3 is missing, shadow reports the exact prerequisite request and stops; it never
creates an intent or prerequisite implicitly.

## Run authority

### `RunManifestV7`

`RunManifestV7` closes the following authority:

- run and creation identity;
- composite source snapshot and partition manifest IDs;
- mode-specific closed lineage and input-run identities;
- explicit `SelectionScopeV1`;
- `run_mode`, `requested_goals`, and target layer;
- exactly one request identity; and
- exactly the mode-specific authorities in the versioning matrix above.

Exhaustive mode additionally pins `ParentAuthorityBundleV3`, the target-local L3
projection catalog, snapshot-evidence catalog, exhaustive plan/policy and
executor catalogs, initial budget policy, and immutable attempt policy. Closure
mode instead pins `L4ClosureParentBundleV1`, `L4ClosureRequestV1`, the complete
L4 run root, and the deterministic closure policy. It contains none of the
exhaustive-mode provider or budget fields.

The manifest does not contain mutable progress, discovered slices, provider
results, checkpoint cache locations, or closure-successor state.
Closed-schema validation applies the mode matrix before resolving any referenced
object. The two modes cannot be represented ambiguously.

### `ParentAuthorityBundleV3`

`ParentAuthorityBundleV3` embeds or references, without rewriting:

- the exact source snapshot and partition authority;
- accepted L0/L1/L2 authority for the selected scope;
- the selected L3 audit epoch, overlays, closure receipts, source roots, and
  terminal root state;
- one `L3TargetAuthorityProjectionV1` per selected domain and source target;
- selected unresolved deeper-evidence finding keys, if any;
- the input run manifest and terminal-event hashes; and
- any staged checkpoint provenance required to make the L4 child
  self-contained.

The bundle validates that every selected L3 artifact refers to the same lower
authority and snapshot. It rejects a mixture of roots from incompatible L3
epochs or source lineages.

`L3TargetAuthorityProjectionV1` is a deterministic, selection-independent view
of one L3 audit target. It binds the audit target, its candidate authority,
applicable findings, resolution overlays, closure receipts/state, relevant L2
roots, and audit/executor policies. The bundle proves that each projection is a
member of the exact selected epoch, but the projection identity excludes the
epoch's global `selection_id`, unrelated targets, run IDs, and terminal-event
hashes. Domain and source slice identities bind these projections rather than
the whole selection-bound epoch. Selection expansion can therefore reuse an
unchanged target only when its complete target-local authority is byte-identical.

### `L4ClosureParentBundleV1`

Closure-successor mode uses a different zero-provider parent bundle containing
the exact blocked L3 manifest/terminal event and frozen epoch, the complete L4
evidence-run manifest/terminal event and `L4RunRootV1`, assigned target-local
projections, accepted slices and verifier receipts, and all immutable object
bytes needed to reconstruct closure. It must be self-contained and must match
the selection and source authority in the closure manifest. It cannot contain
checkpoint provenance, provider executors, attempt policy, or budget authority.
`L4ClosureLineageV1` names those same two direct inputs and their manifest and
terminal-event hashes; it has no invented single-parent ancestry.

### `ExhaustiveRequestV1`

The request identity includes:

- selected source and domain keys and whether the request is `--all`;
- exact selected L3 parent authority and target-projection catalog hashes;
- exhaustive-policy catalog hash;
- executor-contract catalog hash;
- producer and verifier authority hashes; and
- source snapshot and partition hashes.

Budgets are not semantic inputs and do not change the request identity.
Repeating an identical request returns the existing eligible child. A terminal
complete child performs zero new calls. A blocked child is continued only when
new resource authorization is appended or when its status explicitly allows a
new immutable successor.

### `L4ClosureRequestV1`

The closure-successor request identity includes:

- blocked L3 parent manifest and terminal-event hashes;
- frozen L3 epoch and exact unresolved deeper-evidence finding IDs;
- complete protocol-2.8 L4 evidence-run root;
- exact accepted L4 target roots and slice-verification receipts assigned to
  those findings;
- deterministic L4 closure policy authority; and
- source snapshot, partition, and selection hashes.

It is a new protocol-2.8 authority. It does not reuse or reinterpret a
protocol-2.5 human-guidance object, `RunManifestV4`, or closure receipt. This is
required because frozen protocol 2.5 cannot authenticate L4 dependencies.

## Deterministic exhaustive planning

### Why planning is deterministic

A model-led planner could discover new work indefinitely and would make both
cost and completion claims depend on execution order. Protocol 2.8 therefore
freezes its complete work set before provider execution. Providers populate and
verify planned evidence; they never add, remove, merge, or split slices.

### Complete snapshot evidence authority

L4 does not treat an L0 evidence-pack selection as complete source evidence.
L0 evidence excerpts and depth-debt descriptors remain authenticated supporting
context, but an omitted L0 file or range never satisfies an L4 coverage entry.

Before L4 activation, a pinned snapshot reader reopens every selected in-scope
`FileRecordV1`, verifies its mode, content hash, byte count, and text status
against the immutable clean Git snapshot, and creates a
`SnapshotEvidenceCatalogV1`. For every eligible UTF-8 regular file, the catalog
contains ordered `SnapshotEvidenceShardV1` values that:

- cover the exact half-open raw byte interval `[0, byte_count)` with no gaps or
  overlaps;
- bind source ID, normalized path, file content hash, byte offsets, line/column
  metadata, raw shard hash, and exact raw bytes;
- split deterministically at the largest UTF-8 boundary at or below the policy
  byte cap, preferring a preceding LF boundary when one exists; and
- are individually content-addressed and independently scope-checkable.

For explicit domain selection, the primary coverage set is the selected
domain-owned records plus source-level records not owned by any domain. A file
owned by an intentionally unselected domain may be staged only as supporting
evidence when the selected partition already names it as a supporting path; its
shards are marked supporting and do not contribute to selected-scope exhaustive
closure. `--all` assigns every source record to exactly one primary domain or
source-level coverage set. This prevents a selective run from quietly claiming
unselected domain bytes while still allowing authenticated boundary context.

Empty files receive an explicit zero-byte coverage receipt. Non-regular or
non-text records receive a closed `NonTextEvidenceDispositionV1`. The policy may
classify a record as a proven non-behavioral asset from immutable path/mode/type
rules, in which case its metadata disposition is exhaustive coverage. A
potentially behavioral record whose contents cannot be represented safely is an
`unsupported_behavioral_content` pre-activation blocker; it can never be
silently labelled not applicable or full coverage.

The run-global catalog is selection-bound, but it contains one
`TargetSnapshotEvidenceProjectionV1` per domain and source-level target. A
target projection binds only that target's primary records/shards,
selection-authorized supporting shards, local partition/content IDs, and exact
membership proofs into the composite snapshot. Its identity excludes unrelated
sources/domains and the global selection ID. Domain slice identities bind the
target projection and shard hashes, not the run-global catalog hash. Source
composition binds its source-level projection plus its selected domain roots.
This preserves local invalidation and selection-expansion reuse without
weakening proof that every shard belongs to the exact composite snapshot.

All catalog, shard, empty-file, and non-text-disposition bytes are written to a
private staged run store before manifest publication. Activation occurs only
after the catalog proves exact file and byte-range closure and every referenced
object is durable. The child is therefore self-contained after activation even
if an origin run, checkpoint cache, or source checkout later disappears or
changes. A failure while staging leaves no visible run or active pointer.

The initial exhaustive policy caps raw shard payload at 64 KiB. Slice context
packing uses actual canonical bytes and may place fewer than the nominal record
or subject limit in a slice. An oversized file is split into more shards; it is
not rejected merely because one whole file exceeds a context limit.

### `ExhaustivePlanV1`

The run plan contains one `DomainExhaustivePlanV1` per selected domain, one
`SourceExhaustivePlanV1` per selected source, and deterministic run-root work.
Both target plans share the closed `ExhaustiveTargetPlanV1` contract. The plan
is canonical, sorted, bounded, and content-addressed. Its identity is a
manifest authority.

Each domain plan binds:

- domain scope and partition ID;
- exact L0 inventory and evidence hashes;
- exact target-local L3 authority and target snapshot-evidence projection
  hashes;
- exact L2 domain-depth artifact and context hashes;
- applicable deeper-evidence finding IDs;
- the complete ordered `SlicePlanEntryV1` set; and
- a coverage ledger proving assignment of every required subject, source
  record, category, and finding.

Each source plan binds:

- source scope, partition ID, and selection-relative coverage mode;
- exact selected domain-plan hashes;
- source-level L0 inventory/evidence and L2 overview authority;
- the target-local L3 source authority projection;
- exact source-level target snapshot-evidence projection hash;
- source-level deeper-evidence finding IDs;
- source records not owned by any selected domain;
- source composition, cross-domain boundary, configuration/security,
  operations/lifecycle, and negative-space slices; and
- a coverage ledger for every required source-level subject, record, category,
  byte range, non-text disposition, and finding.

For explicit domain selection, the source plan is selection-relative and may
reference only those domains plus authenticated source-level authority. For a
whole-source or `--all` request, it covers the complete source composition.

The planner must reject rather than activate if the plan exceeds policy bounds,
cannot assign an in-scope record or evidence shard, repeats an assignment that
must be unique, encounters unsupported behavioral content, or cannot prove exact
file/byte and semantic closure.

### Required categories

Every selected domain plans these fixed exhaustive categories:

- public surfaces and callable operations;
- state, data models, transformations, and invariants;
- boundaries, integrations, protocols, and dependency behavior;
- failure modes, retries, recovery, and degraded behavior;
- configuration, feature controls, security, and permissions;
- observability, operational behavior, and lifecycle; and
- negative space: absent behavior, unsupported cases, and explicit unknowns.

A category may be substantively inapplicable, but it is never silently omitted.
Its slice must produce evidence-backed `not-applicable` observations that the
independent verifier checks.

A category with literally no subjects, records, findings, or evidence shards
receives a controller-created `CategoryVacancyReceiptV1` instead of a provider
slice. The receipt proves the empty inputs from the frozen coverage ledger. This
is distinct from semantic inapplicability, which still requires an analyst and
verifier. It makes a truly empty source plan provider-free without silently
omitting any required category.

Every selected source separately plans source composition, cross-domain
boundaries, source-level configuration/security, operations/lifecycle, and
negative space. This source plan is what can satisfy a source-scoped L3
`requires_deeper_evidence` finding; a domain slice may never pretend to resolve
a source-scoped finding.

### Subject and source-record assignment

The planner derives required subjects from stable lower authority:

- L2 behavioral surfaces and unknown/depth-debt subjects;
- L3 finding subject references;
- L0 partition file records, symbols, evidence anchors, and source facts; and
- integration and source-boundary references already authenticated by L2/L3.

The exhaustive policy contains a closed subject-kind/category applicability
table, evidence-anchor-to-shard mapping rule, uncited-shard discovery rule, and
canonical bin-packing algorithm. It does not ask a model to decide which
categories apply. Stable subjects are ordered by UTF-8 identity; target,
category, subject, shard, and record tuples are then packed greedily in that
order until the next tuple would exceed any count, canonical-byte, or token
bound. The same inputs and policy must produce byte-identical plan entries on
every implementation.

Sorted subjects are assigned to category slices using immutable policy bounds:
maximum subjects, source records, context bytes, and conservative tokens per
slice. Oversized subject groups split deterministically by stable identity; no
semantic model judgment controls the split.

Every domain-owned in-scope source record and every one of its evidence shards
must have exactly one primary coverage assignment in its domain plan. Every
selected source record not owned by a selected domain, and every one of its
shards or non-text dispositions, must have exactly one primary assignment in
its source plan. Shards may repeat as supporting evidence for semantic subjects,
but primary byte-range coverage may not repeat. The policy assigns otherwise
uncited shards to the target's negative-space/source-discovery work so code
omitted by lower layers is still read by both producer and verifier. Every
behavioral subject/category pair required by policy must appear exactly once as
a primary assignment. Every selected `requires_deeper_evidence` finding must be
assigned to at least one same-scope slice and has one primary resolving slice.

Findings covered by authenticated residual-debt acceptance are not mandatory
L4 closure assignments. They remain unresolved in the L3 projections, and the
exact acceptance remains in every L4 context; L4 cannot turn partial input into
clean input. Unaccepted deeper-evidence findings retain their closure obligation.

Each mandatory finding gets a dedicated bounded evaluation slice with its
declared evidence and subjects as supporting authority. Discovery slices retain
exactly-once primary byte coverage. Generated target indexes are not semantic
evidence mappings: their findings conservatively require the target evidence.
If the complete finding context cannot fit, preparation fails before provider
dispatch with an actionable bounded-context diagnostic. It must not assign the
finding to the first arbitrary byte bin, split away required evidence, or retry
an impossible immutable context. A larger cross-slice synthesis strategy is
separate work, not an implicit increase to context or token limits.

### `SlicePlanEntryV1` and `SliceSpecV1`

Each frozen plan entry contains:

- stable plan-entry ID;
- target kind, exact domain-or-source scope, and category;
- primary subject IDs;
- supporting subject IDs;
- primary source-record IDs;
- permitted supporting source-record IDs;
- primary snapshot-evidence shard or non-text-disposition IDs;
- permitted supporting snapshot-evidence shard IDs and exact byte ranges;
- required lower artifact-key IDs and planned target-root key IDs;
- assigned deeper-evidence finding IDs;
- context-object hashes;
- complete snapshot-evidence object hashes plus inherited supporting-evidence
  hashes;
- producer and verifier contract hashes; and
- canonical size and resource estimates.

`SliceSpecV1` is the realized execution specification. It binds one plan entry
to the exact accepted dependency artifact hashes and output artifact key. A
domain entry whose lower dependencies already exist can be realized
immediately. A source-composition entry that depends on planned domain roots is
realized only after those roots are accepted. This is deterministic deferred
instantiation, not model-led planning: every entry, coverage assignment, and
required dependency key is frozen before activation.

The plan-entry and realized-slice identities exclude run ID, timestamps,
execution order, budgets, provider observations, the global L3 selection ID, and
unrelated L3 targets. They include the exact target-local L3 projection and
snapshot-evidence dependencies. Unchanged target-local semantic inputs therefore
produce the same work identities across children, including selection expansion.
A changed domain root changes only dependent realized source-composition slices
and roots, not the frozen coverage plan.

## L4 artifact graph

The graph is strictly additive:

```text
authenticated L0-L3 authority
  -> complete snapshot-evidence catalog, target projections, and shards
  -> target-local L3 authority projections
  -> exhaustive plan
  -> slice context
  -> evidence slice candidate
  -> independent verification
  -> accepted slice receipt
  -> L4 target roots
  -> L4 source root
  -> L4 run root
  -> protocol-2.8 L4 closure successor (when required)
```

### `ExhaustivePolicyV1`

The closed policy freezes:

- required category set;
- subject/source-record assignment rules;
- snapshot-evidence shard construction, non-text disposition, exact byte-range
  closure, and uncited-shard discovery rules;
- slice context and output byte limits;
- conservative input/output reservation parameters;
- initial generation plus two producer repairs;
- two-identical-outcome early-stop rule;
- producer contract retry limit, fixed at zero because malformed producer
  output consumes one of the three total producer attempts;
- verifier contract retry limit, fixed at one because a malformed verifier
  result must not force regeneration of a valid candidate;
- producer and verifier identities; and
- accepted normalized diagnostic classes.

The initial policy uses these exact planning/output bounds:

- 64 KiB raw snapshot-evidence payload per shard;
- 16 primary and 32 supporting subjects per slice;
- 64 primary and 128 supporting source records per slice;
- 128 KiB canonical context;
- 64 KiB canonical candidate output;
- 96 KiB rendered Markdown;
- 131,072 conservative input tokens;
- 512 plan entries per target; and
- 16,384 plan entries per run.

Inputs split deterministically before a bound is exceeded. A single subject or
record set that cannot fit by itself is an explicit partition/policy blocker,
not permission to truncate context. Later tuning creates a new exhaustive
policy identity and branches only dependent L4 authority.

The first release uses exactly three producer dispatches per slice at most.
Malformed producer output counts against that total. Each valid candidate may
receive one verifier dispatch plus one verifier contract-repair dispatch. The
attempt caps are semantic policy, not resource budgets, and cannot be raised by
CLI authorization. The absolute pathological bound is therefore nine provider
dispatches per slice: three producer calls and two verifier calls for each of
three valid candidates. Ordinary PASS is two calls, and plateau detection can
stop semantic repair after the second producer/verifier cycle.

### `ExhaustiveEvidenceSliceV1`

The producer output is closed structured data containing:

- slice and target identity;
- category and covered primary subjects;
- covered primary source records;
- covered primary snapshot-evidence shards/ranges and non-text dispositions;
- normalized behavioral claims;
- source evidence anchors for every claim;
- boundary, failure, and negative-space observations required by category;
- L3 finding IDs addressed and the new evidence supplied;
- explicit unknown or unresolved observations; and
- a bounded rendered explanation derived from the structured payload.

Every claim must cite authenticated evidence permitted by the slice context.
The controller rejects unknown paths, hashes, subjects, findings, evidence
anchors, shard IDs, or byte ranges before semantic verification. It also rejects
a candidate that does not acknowledge every primary shard/range assigned to the
slice. A slice with unresolved observations may be durably captured and verified
as REPAIR evidence, but cannot receive an acceptance receipt.

### `ExhaustiveVerificationV1`

Verification is a separate provider dispatch with a fresh context and a
distinct Prosaic verifier role. It receives:

- the immutable slice spec;
- the exact candidate hash and structured payload;
- the permitted authenticated source evidence;
- relevant lower claims and L3 findings; and
- the verifier contract and response schema.

It does not receive producer reasoning, raw provider telemetry, prior repair
conversation, controller state, or untrusted prose outside the candidate.

Independent means a distinct execution capture, verifier executor authority,
fresh provider context, and no continuation of the producer session. Provider
routing may resolve both roles to the same provider/model; requiring a second
vendor is not part of the semantic contract.

The verifier returns `PASS` or `REPAIR` plus normalized diagnostics. It checks:

- exact planned subject and source-record coverage;
- exact primary shard/range coverage and treatment of uncited lower-layer code;
- evidence grounding and scope;
- behavioral completeness for the category;
- contradictions with lower accepted authority;
- unsupported claims;
- failure, boundary, and negative-space completeness; and
- whether assigned deeper-evidence findings are actually supported.

Provider verdicts remain evidence. The deterministic controller validates the
verifier result contract and creates the certification and acceptance receipts.

### Diagnostics and repair packets

Diagnostics have stable IDs derived from candidate, verifier policy, class,
subject, and evidence references. Allowed classes are closed and include:

- missing planned coverage;
- unsupported claim;
- contradictory claim;
- invalid or insufficient evidence;
- incomplete boundary behavior;
- incomplete failure/recovery behavior;
- incomplete negative space;
- unresolved assigned L3 finding; and
- malformed result contract.

A repair packet contains the frozen slice spec, rejected candidate hash,
normalized diagnostics, accepted evidence boundary, and attempt number. It does
not include free-form hidden guidance or broaden scope. Repair candidates
supersede only prior candidates for the same slice.

### `AcceptedExhaustiveSliceV1`

The accepted authority binds:

- slice spec and candidate hashes;
- producer execution capture;
- verifier result and execution capture;
- deterministic certification receipt;
- acceptance receipt;
- attempt history summary; and
- addressed L3 finding IDs.

The complete candidate, verifier output, receipts, context, and required source
objects are staged in the child before acceptance so checkpoint export is
self-contained.

### `L4TargetRootV1` and `L4DomainRootV1`

`L4TargetRootV1` is the shared closed root envelope for domain and source
targets. A domain root contains:

- domain plan hash;
- exact accepted-slice hashes;
- exact verifier and acceptance receipt hashes;
- inherited L3 authority hash;
- target-local L3 and target snapshot-evidence projection hashes;
- coverage-ledger hash, including exact file/byte-range closure;
- addressed deeper-evidence finding IDs; and
- root state `complete`.

The root constructor requires exactly one realized and accepted slice for every
entry in the frozen target plan, with no extras. Subset completion, a PASS
count, a percentage, an L0 selected-file count, or an L0 depth-debt summary can
never create a root. The coverage ledger must also prove that every in-scope
record has either complete primary shard coverage, an empty-file receipt, or a
permitted non-text disposition, with no `unsupported_behavioral_content`. An
`L4SourceCompositionRootV1` applies the same rule to its source plan and also
binds the selected domain-root hashes.

### `L4SourceRootV1` and `L4RunRootV1`

A source root binds its source-composition root and every selected domain root
for that source and records:

- selected domain keys;
- intentionally unselected domain keys;
- whether the source has full domain coverage under `--all`; and
- the inherited target-local L3 source projection.

For a source with zero partition domains, `--all` still creates and executes
the source-composition plan when it contains source-level subjects, records, or
L3 findings. It is provider-free only when that exact plan has no authorial
slices. Zero domains must never be confused with zero source behavior.

The run root binds all selected source roots, exact selection, request, plan,
policy, and parent authority. It records `selected-scope` or `all-scope`; it
does not contain `full-quality`, `published`, or synthesis state.

### `L4FindingClosureReceiptV1` and closure root

Every deeper-evidence finding has one primary resolving slice and may have
supporting slices. The primary slice verifier must explicitly assess whether
the frozen finding is supported by the new evidence. For source-scoped or
cross-domain findings, the required source-composition slice and its verifier
receipt are also mandatory dependencies. A slice cannot PASS while its assigned
finding remains unsupported.

The closure successor performs no provider dispatch. For each finding, the
deterministic controller validates the complete primary/supporting assignment,
accepted candidate receipts, independent verifier PASS receipts, target roots,
and any required source-composition root, then creates an
`L4FindingClosureReceiptV1`. Missing or mismatched authority blocks as an
integrity failure; it is never converted into a semantic PASS.

After every inherited selected deeper-evidence finding has a receipt,
`L4SemanticClosureRootV1` binds the exact inherited L3 epoch, L4 evidence-run
root, closure receipts, and source-composition roots. These are protocol-2.8 L4
authorities; the original L3 epoch and protocol-2.5 receipts remain unchanged.
The separate successor exists to preserve an explicit immutable state
transition and visible lineage, not to pay for a redundant third model opinion
after producer plus independent verifier.

## Producer and verifier execution

Protocol 2.8 adds two neutral Prosaic roles:

- `echelon.re-exhaustive-analyst`; and
- `echelon.re-exhaustive-verifier`.

Both follow the established dispatcher/protocol split and ALWAYS/NEVER paired
invariants. Their frontmatter remains provider-neutral. Existing provider
resolution maps model tier and effort through Prosaic and the shared
`SquadCliProvider`; protocol 2.8 adds no provider adapter.

The analyst receives only one slice context and writes exactly one structured
candidate. The verifier receives only one candidate and its frozen evidence
boundary and writes exactly one structured verdict. Neither writes controller
state, ledgers, receipts, roots, status, or completeness claims.

Controller-owned result parsing enforces the trailing result contract. Missing,
duplicate, malformed, or extra result fields are contract failures. Raw source
content, provider reasoning, prompts, candidate prose, and diagnostics do not
enter ordinary terminal output or content-bearing telemetry.

## Execution lifecycle

### Phase 0: pre-activation

Before creating an L4 run, the CLI:

1. resolves and authenticates the input lineage;
2. resolves selection to stable keys;
3. commits or reuses `DeepenOrchestrationIntentV1`;
4. creates, reuses, or resumes the selected L3 prerequisite;
5. validates its terminal eligibility;
6. builds target-local L3 projections and the parent-authority bundle;
7. reads every selected file through the pinned snapshot reader and privately
   stages the complete snapshot-evidence catalog/shards;
8. builds policy and executor catalogs;
9. constructs the deterministic exhaustive plan and proves file/byte closure;
10. computes conservative minimum initial reservation; and
11. rejects unsafe or unaffordable activation without publishing an L4 run.

The run manifest and all referenced catalogs/objects, including complete source
shards, are committed before the active-run pointer changes. Failed private
staging is removed; only the durable orchestration intent and its content-free
failure event remain visible.

### Phase 1: checkpoint reconstruction and adoption

Protocol 2.8 layers checkpoint schema V2 over the frozen protocol-2.6 V1
system, adding L4 plan, slice, verification, accepted-slice, and root kinds.
Discovery cache remains disposable. Direct-parent exact authority outranks
sibling checkpoints; compatible checkpoints fill only missing exact
identities.

Every adopted checkpoint is copied into the child and its receipts are
revalidated before activation or dispatch. A child must remain continuable and
re-exportable after its origin runs and discovery cache disappear.

### Phase 2: slice generation

The ready queue contains only dependency-complete missing slices. Before a
producer call, the controller reserves the conservative producer cost plus the
minimum verifier cost. If that pair cannot be afforded, the run pauses without
dispatch.

Provider output is durably captured before parsing. A valid candidate is stored
content-addressably and appended to the candidate ledger. Invalid producer
output consumes the current one-of-three producer dispatches and becomes the
normalized repair input for the next dispatch, when one remains. The controller
records a stable, content-free contract failure code and includes all prior
codes for that slice in the next producer context, including after controller
restart. `addressed_finding_ids` is exactly the assigned finding set;
`unresolved_finding_ids` is the subset examined but not resolved, so unresolved
findings occur in both arrays. Invalid output never creates semantic authority
or receives a nested contract retry.

Provider timeouts and execution failures are distinct durable capture outcomes,
not malformed candidate contracts. They consume the same bounded attempts, but
are not injected as content-repair instructions. A timed-out file cannot become
accepted authority even if its JSON is valid. Exhausted attempts report the last
provider failure type, including after capture recovery.

### Phase 3: independent verification

Every valid candidate requires a verifier dispatch. A verifier PASS is parsed,
deterministically checked, certified, and accepted. A REPAIR result creates the
normalized repair packet for the same slice.

Verifier result-contract failure has one fixed retry and does not consume a
producer repair. If that retry also fails, the slice blocks on verifier
contract failure without regenerating a valid candidate. Verifier semantic
REPAIR consumes one producer attempt when another is available.
Recovery consumes an already captured second verifier attempt without reserving
or executing it again.

### Phase 4: bounded repair and plateau

One initial producer attempt plus two repairs are allowed. The controller
compares normalized verifier diagnostic ID sets. Two consecutive attempts with
the same nonempty diagnostic set terminate the slice early as
`non_improving_verification`, even if a nominal third attempt remains.

Accepted siblings are never reopened. Repair scope cannot change the plan,
slice identity, evidence boundary, or assigned findings. A terminal failed
slice blocks root creation and remains eligible only for adoption of its
accepted siblings into a new policy/version successor; raising budget cannot
raise the attempt cap.

### Phase 5: root construction

When every planned slice is accepted, deterministic constructors create the
domain-target, source-composition, source, and run roots in dependency order.
Roots require no provider dispatch. Materialization occurs only after the
corresponding root is durable.

### Phase 6: automatic L3-finding closure handoff

If the selected L3 parent contained deeper-evidence findings, completed L4
roots trigger creation or reuse of an immutable schema-7
`l4-closure-successor`. Its request authority binds:

- the blocked L3 parent manifest and terminal event;
- frozen epoch and unresolved finding IDs;
- exact L4 target roots and accepted-slice/verifier evidence hashes; and
- the protocol-2.8 run root.

The successor deterministically validates the assigned accepted slice,
independent verifier, target-root, and source-composition authority and creates
the versioned protocol-2.8 closure receipts/root. It cannot discover a new
audit epoch, create new findings, or mutate L4. Identical authority resolves to
the same successor and always performs zero provider calls.

Closure-successor mode has no provider-ready work, makes no reservation, and
records zero provider usage. It neither needs nor accepts resource
authorization; an integrity blocker requires corrected/versioned authority, not
more tokens.

If closure succeeds, protocol-2.8 status reports the linked closed authority.
If deterministic closure cannot authenticate its inputs, status distinguishes
completed L4 evidence from closure-integrity failure and reports exact missing
or mismatched authority IDs. It does not report a semantic finding as open: an
assigned finding could not have reached an accepted slice/root without verifier
PASS. The new closure receipt composes with the inherited L3 finding; it never
rewrites or relabels the original protocol-2.5 object.

## Budget authority

Protocol-2.8 `exhaustive-depth` mode uses the existing independent run token and
provider-active-time ceilings exposed as `--token-limit` and
`--active-ms-limit`. Closure-successor mode has no budget field or resource
authorization surface.

Before each producer dispatch, the scheduler must retain enough authorized
capacity for the paired verifier reservation. This prevents accepted spend on
an artifact that the same run can no longer verify. Repairs repeat the paired
reservation check.

Charges distinguish:

- producer versus verifier work;
- known versus unknown reported usage;
- conservative reservation versus trusted observation;
- generated versus adopted work; and
- historical rejected attempts versus terminal failed slices.

An operator may append authorization to increase token or active-time ceilings.
Authorization does not alter selection, plan, policy, attempt limits, plateau
rules, executor contracts, or work identity. Untrusted provider usage follows
the existing conservative-reservation policy and is not transformed into a
fabricated observation or a fatal over-reservation breach.

Dispatches reserve five minutes per started 128 KiB of frozen context, bounded
to five through fifteen minutes; verifier sizing includes the candidate output
allowance. The entire producer/verifier pair must fit the already authorized
run-wide budget before dispatch. This does not increase that budget or attempts.

The shared CLI deadline leaves up to five seconds inside the existing dispatch
active-time reservation for shutdown and boundary checks (10% for reservations
below 50 seconds). Observed duration is never clamped to the reservation. A genuine
reservation breach remains blocking and is reported separately from an exhausted
run budget; increasing the run ceiling cannot repair that breach.

## Controller, events, and durable state

The protocol-2.8 controller remains the sole writer to its event chain,
candidate/verification ledgers, certification/acceptance ledgers, budget
ledger, checkpoint ledger, root ledger, and state projection. Provider agents
write only their staged result files.

The orchestration coordinator is separately the sole writer to one intent event
chain. Its closed events are intent commitment; L3/L4/closure child
created-or-reused; child paused, terminal-eligible, or terminal-ineligible;
transition advanced; authorization appended; source changed; and orchestration
complete/blocked. They contain only IDs, hashes, states, reason classes, and
resource ceilings. Child analysis and provider usage stay in child authority.

The closed protocol-2.8 event allowlist covers:

- manifest, snapshot-evidence catalog, target-projection catalog, parent bundle,
  plan, exact coverage proof, and activation commitment;
- checkpoint discovery, rejection/quarantine, staging, and adoption;
- slice realization from a frozen plan entry;
- producer reservation, lease, start, durable capture, candidate acceptance or
  rejection, and abandonment;
- verifier reservation, lease, start, durable capture, PASS/REPAIR result,
  contract retry, and abandonment;
- certification, acceptance, repair packet, plateau, and terminal slice
  failure;
- target/source/run root acceptance;
- resource authorization and blocking;
- materialization completion;
- closure-successor creation/reuse, link, closure receipt, and closure root;
  and
- terminal run completion or blocker.

Events carry only canonical IDs, reason classes, counts, provider/model routing
metadata, timing, and usage. They never carry source excerpts, prompts,
candidate content, verifier prose, or repair text.

The projection exposes authoritative lifecycle states:

- `planned`;
- `active`;
- `resource_blocked`;
- `execution_blocked`;
- `evidence_complete`;
- `closure_integrity_blocked`; and
- `complete`.

`evidence_complete` means the exact L4 evidence-run root exists. `complete`
means either no inherited deeper-evidence findings existed or the linked
protocol-2.8 semantic closure root exists. Projection loss is repaired from
events and ledgers and cannot reopen accepted work.

## Recovery

Recovery is authority-first and idempotent. It authenticates the manifest,
catalogs, parent bundle, plan, event chain, ledgers, object store, execution
captures, receipts, accepted checkpoints, roots, and any linked protocol-2.8
closure successor before projecting state.

Before an L4 manifest exists, orchestration recovery authenticates the immutable
intent and its event chain, then compares the linked L3 child against
`awaiting_l3`. A terminal eligible L3 advances exactly once to L4 staging; a
resource-blocked L3 stays linked and resumable; an ineligible terminal L3 closes
the intent as blocked with its exact next action. Equivalent rules apply at the
L4 and closure transitions. A child is never inferred from the mutable active
pointer alone.

For both producer and verifier dispatches, recovery handles:

- reservation durable, provider not started;
- lease durable, child not started;
- provider active with live owner;
- dead owner before durable result;
- durable raw result before parse;
- parsed candidate/verdict before object write;
- object durable before ledger append;
- certification durable before acceptance;
- acceptance durable before checkpoint export;
- root durable before materialization; and
- L4 completion durable before protocol-2.8 closure-successor link.

A live owner is never duplicated. A dead indeterminate provider execution is
resolved through the existing bounded abandonment/retry contract. A durable
raw result is parsed before any replacement call. A durable accepted artifact
is never regenerated because a projection or cache is missing.

Plan reconstruction must reproduce the manifest-pinned plan byte-for-byte; a
difference is corruption, not a reason to replan. Materialized Markdown and
status projections are rebuildable and never execution authority.

Snapshot evidence is never reconstructed from a changed or missing source after
activation. Recovery uses the run-local staged shard objects and verifies the
catalog's exact byte closure. Missing shard bytes are corruption, not permission
to reread an unpinned working tree or downgrade completeness.

## Checkpoint adoption and incremental behavior

Protocol 2.8 defines `CheckpointManifestV2` and
`CheckpointSelectionBundleV2`. V1 remains the only checkpoint manifest for
L0-L3; V2 contains only protocol-2.8 snapshot-evidence, target-projection,
plan-entry realization, L4 candidate, verification, accepted-slice, target/root,
and semantic-closure kinds. A protocol-2.8 selection bundle can reference
authenticated V1 and V2 manifests without wrapping or rewriting V1 bytes.

Workspace projections are physically versioned:

```text
.echelon/re-v2/checkpoints/index-v1.json
.echelon/re-v2/checkpoints/manifests/          # unchanged V1 projection
.echelon/re-v2/checkpoints/index-v2.json
.echelon/re-v2/checkpoints/index-v2.lock
.echelon/re-v2/checkpoints/manifests-v2/       # L4-only V2 projection
.echelon/re-v2/checkpoints/quarantine-v2.json
```

Protocol 2.8 never writes the V1 index, manifest directory, or quarantine file.
One narrow shared origin-discovery fix reads only the manifest schema/protocol
pair before invoking a version-specific reconstructor: the V1 reconstructor
silently skips recognized schema-7 origins, while the V2 reconstructor consumes
only schema-7 origins. A recognized newer schema is not V1 corruption and is
never added to V1 quarantine. Tests freeze V1 selection/index bytes for the same
2.2-through-2.7 origin set with and without adjacent 2.8 runs. Unknown or
malformed manifests remain rejected by the owning versioned reconstructor.

Protocol 2.8 checkpoint eligibility requires exact equality of:

- source snapshot content for the slice scope;
- partition and exact domain-or-source target scope;
- lower L0-L2 dependency hashes and exact target-local L3 projection;
- target snapshot-evidence projection and shard hashes;
- exact target plan-entry and realized-slice identities, not the unrelated
  run-global plan hash;
- artifact and exhaustive policy hashes;
- producer/verifier executor contracts;
- candidate, verification, certification, and acceptance receipts; and
- object bytes.

Selection expansion adopts already accepted slices and generates only newly
selected work. Global selection, request, epoch, or `ExhaustivePlanV1` identity
differences do not invalidate a slice when its target plan entry, target-local
L3 projection, snapshot shards, policy, executor, and realized dependencies are
identical. A source change invalidates only slices whose assigned primary or
supporting shards/records, lower artifacts, or target-local L3 authority changed.
A policy or verifier change branches affected L4 identities without rewriting
lower layers.

Malformed or incomplete checkpoints are rejected. Authenticated but
incompatible checkpoints are ignored with a content-free shadow explanation.
Cryptographically inconsistent entries are quarantined from future discovery.
No checkpoint can downgrade or replace stronger direct-parent authority.

## Materialization

Protocol 2.8 materializes only below:

```text
runs/<run-id>/re/l4/
```

The compatibility view includes:

- snapshot-evidence catalog and content-free exact-range coverage summaries;
- the frozen exhaustive plan and coverage ledger;
- accepted structured and rendered evidence slices;
- independent verification summaries;
- per-domain exhaustive roots;
- per-source composition and aggregate roots;
- the run root; and
- linked protocol-2.8 closure-successor receipts, root, and reference when
  present.

Materialization is deterministic, manifest-last, and rebuildable from durable
authority. It does not modify workspace `re/`, protocol-2.7 synthesis output,
source repositories, or lower run directories.

## Status and terminal banners

For a schema-7 run, `echelon re status` reads the manifest first and renders
`RE V2 — PROTOCOL 2.8`. The heading never contains a hard-coded older protocol.
While an L3 prerequisite is active, the header remains its true protocol and a
separate `pending L4 orchestration` line shows the intent; the header never
pretends the L3 child itself is protocol 2.8.

When the active run is a prerequisite or child named by an open orchestration
intent, default status authenticates that unique intent and renders the chain's
operator state. Explicit run status remains scoped to the named immutable run
and includes a link to, but never substitutes, its intent. A disposable reverse
index may accelerate lookup; authority comes from the intent event chain and
child hashes, not the index or active pointer.

Human status reports:

- orchestration intent ID/state and input, L3 prerequisite, L4 child, and linked
  protocol-2.8 closure-successor run IDs;
- selected source/domain count and `selected-scope` versus `all-scope`;
- planned, adopted, generated, verified, repaired, accepted, failed, and pending
  slice counts;
- per-source and per-domain plan/acceptance progress;
- producer and verifier dispatch/usage totals;
- charged, authorized, and trusted-observed resources;
- avoided dispatch and reservation totals;
- historical rejected attempts separately from terminal failed slices;
- inherited L3-finding closure state and protocol-2.8 closure-root state;
- post-L4 synthesis/publication state as `not run`; and
- one exact next safe action.

Machine-readable JSON carries the same facts with stable reason codes.

Terminal banners are:

- `L4 PENDING — L3 PREREQUISITE RESOURCE BLOCKED` for a resumable open intent;
- `L4 NOT STARTED — L3 PREREQUISITE INELIGIBLE` for a terminal blocked intent;
- `L4 NOT STARTED — PRE-ACTIVATION BLOCKED` for snapshot, plan, policy, or
  minimum-reservation failure after intent commitment;
- `L4 SELECTED SCOPE COMPLETE`;
- `L4 ALL-SCOPE EVIDENCE COMPLETE — SYNTHESIS REQUIRED`;
- `L4 EVIDENCE COMPLETE — CLOSURE INTEGRITY BLOCKED`; and
- `L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE`.

The banner is the final prominent output, not an earlier buried line. A
completed selected run states which domains remain intentionally unselected.
An all-scope run states that protocol-2.9 synthesis is still required. No
protocol-2.8 state or banner says `full quality`, `published complete`, or
equivalent.

The linked inherited-finding closure state has precedence over scope wording.
An all-scope L4 root with an open protocol-2.8 closure successor ends with
`L4 EVIDENCE COMPLETE — CLOSURE INTEGRITY BLOCKED`, never the
synthesis-required banner. This state reports missing or mismatched authority
IDs and a reconstruction/versioning action; it does not relabel a frozen finding
as semantically unresolved or recommend more model repair. Synthesis becomes the
next action only after the linked selected L3 findings have complete native or
protocol-2.8 composed closure authority.

## Failure taxonomy and next actions

Pre-activation failures create no L4 run:

- invalid or dirty source authority;
- unsupported input protocol or lineage;
- ambiguous/unknown selection;
- unavailable or ineligible L3 prerequisite;
- mixed/non-deeper L3 blocker classes;
- incomplete snapshot byte coverage or unsupported behavioral content;
- invalid or oversized deterministic plan;
- invalid policy/executor catalog; and
- unaffordable minimum initial producer-plus-verifier reservation.

Post-activation blockers retain durable accepted work:

- token or active-time authorization exhausted;
- provider unavailable or indeterminate;
- producer result-contract attempts exhausted;
- verifier result-contract attempts exhausted;
- semantic repair attempts exhausted;
- non-improving verification plateau;
- checkpoint corruption;
- root closure mismatch; and
- closure-successor authority is missing, mismatched, or corrupt.

Status maps each reason to one command or external action. Resource pauses show
the exact `echelon re continue` authorization command. Fixed-attempt failures
do not suggest adding tokens. Dirty or changed sources require commit, stash, or
revert and a new snapshot; they never suggest silently including dirty files.

## Security and evidence boundary

- Source access remains inside the immutable declared snapshot.
- Pre-activation snapshot reads are hash/size/mode verified and all required
  source bytes are staged before publication; post-activation execution reads
  only the staged immutable shards.
- Context construction resolves only manifest-authenticated objects.
- Paths are normalized, scope-checked, and never accepted from provider output
  as new authority.
- Symlinks and traversal outside the candidate workspace remain forbidden.
- Producer and verifier tools are the minimum required read-only set.
- Prompts, source excerpts, model reasoning, candidate prose, and verifier
  diagnostics are excluded from content-bearing telemetry and ordinary terminal
  output.
- Durable objects may contain source-derived evidence under the run directory;
  status and telemetry expose only IDs, counts, classes, providers, models,
  durations, and usage.
- The verifier cannot accept its own malformed response; deterministic
  certification remains controller-owned.

## CLI and lifecycle behavior

The Typer and legacy-compatible parsers both register `L4`. Help text lists all
registered layers truthfully. L3-only semantic flags remain invalid for L4,
and `--token-limit`/`--active-ms-limit` authorize only the protocol-2.8 child.
An automatically created L3 prerequisite retains protocol-2.5 defaults and
independent authorization; if it pauses, the visible chain reports both the
exact L3 continuation command and that the durable L4 intent remains pending.
After continuation closes L3, the CLI automatically advances the same intent to
L4. An operator who needs custom L3 limits may create that prerequisite
explicitly. No
`hard_`-prefixed public setting is introduced.

`--shadow` follows the existing RE v2 shadow convention and is valid for L4
without resource flags. Combining shadow with token/time authorization is
rejected because shadow cannot spend or append authority.

`echelon re continue` recognizes active or explicitly named schema-7 runs,
appends only permitted exhaustive-mode resource authorization, recovers
authority, and resumes pending work. When it continues a schema-5 L3 run linked
to exactly one open orchestration intent, it advances that intent automatically
after L3 terminates. Ambiguous multiple intents are an integrity blocker rather
than an arbitrary choice. Closure-successor mode rejects resource flags.
Repeating continue on a complete run or intent is zero-call and prints the
complete banner.

The active-run pointer may advance through prerequisite, L4, and closure
children, but status invoked with any explicit run ID remains authoritative for
that run. The orchestrated command's final banner names the final state across
the linked chain so the user does not need to inspect nested `state.json`
files.

## Implementation boundaries and reuse

New protocol code lives under `src/harness/re_v2/protocol_28/` with focused
modules for closed models, orchestration intent/recovery, parent and target-local
L3 authority, snapshot-evidence staging, policy, planning, graph realization,
context, execution, verification, artifacts, budget integration, checkpoint V2,
controller, recovery, lifecycle, materialization, and status. The CLI adds only
manifest-first routing, intent/selection/prerequisite orchestration, and operator
option plumbing.

Protocol 2.8 reuses:

- canonical JSON, content digests, object stores, durable files, locks, event
  chains, typed ledgers, and execution captures from the shared kernel;
- immutable source snapshot, partition, inventory, and evidence authority;
- L1/L2 artifact and certification authority by reference;
- L3 epoch/finding/closure authority by embedding `ParentAuthorityBundleV2` in
  `ParentAuthorityBundleV3`;
- protocol-2.6 checkpoint ranking/adoption semantics through separate V1 and V2
  projections and a version-aware origin prefilter;
- Prosaic metadata loading and the shared `SquadCliProvider` path;
- existing conservative budget accounting and authorization events; and
- existing terminal-banner and active-run-pointer infrastructure through
  protocol-aware adapters.

When a shared primitive lacks the required aggregate or versioned behavior,
protocol 2.8 adds a new adapter/module and selects it only for schema 7. It does
not silently change frozen execution identities in protocol directories 2.2
through 2.7.

Rejected alternatives are:

- one monolithic domain call, because one defect would repeat the full domain;
- adaptive model-led planning, because scope/cost/replay would not be frozen;
- producer self-certification, because schema validity is not semantic quality;
- another whole-domain post-L4 repair loop, because it recreates the original
  cost failure;
- mutating protocol 2.5 to accept L4 evidence, because its manifest and closure
  identities are frozen;
- mutating protocol 2.7 for L4 synthesis, because it would invalidate existing
  synthesis replay; and
- automatic synthesis, because analysis completion is not publication
  authorization.

## Testing strategy

### Schema and identity

- Closed-field round trips for both concrete schema-7 manifest variants and
  every referenced value; union dispatch is `run_mode`-first.
- Canonical digest and order independence where sets are semantic.
- Rejection of extra fields, wrong versions, invalid IDs, duplicate subjects,
  duplicate source records, and cross-scope dependencies.
- Exhaustive and closure mode field matrices reject every forbidden/missing
  policy, executor, budget, attempt, request, and parent combination.
- Request identity excludes budgets and includes every semantic authority.
- Slice identity is stable across run IDs, execution order, and unrelated/global
  L3 selection expansion.

### Selection and prerequisites

- `--all`, source, and domain selector matrix.
- Unknown, duplicate, ambiguous, and conflicting selectors.
- Zero-domain sources with and without source-composition work.
- Direct L3 complete parent.
- L3 parent blocked only by selected deeper-evidence findings.
- Rejection of mixed or unsupported L3 blockers.
- Automatic creation/reuse of missing selected L3.
- L3 resource pause, process exit, explicit continuation, and automatic
  advancement of the same durable intent into L4.
- Crash/idempotency fixtures before and after every orchestration transition.
- Synthesis input resolves to underlying analysis authority without consuming
  synthesized artifacts.
- Complete/partial, selected/unselected, `next_epoch_required`, and `--all`
  synthesis-parent matrix.
- Shadow is side-effect free, reports missing L3 without creating it, emits
  exact counts for realized work, and bounded conditional intervals for deferred
  source-composition checkpoints and calls.

### Planning and coverage

- Every domain and source fixed category is planned.
- Every in-scope domain-owned and source-level record is assigned exactly at
  the correct scope.
- Every eligible UTF-8 source byte is covered exactly once as primary evidence;
  empty and non-text records have exact permitted dispositions.
- L0 omitted files/ranges are re-read from the pinned snapshot and cannot count
  as L4 coverage until their complete L4 shards are staged.
- Unsupported potentially behavioral content blocks before activation.
- Every required subject/category pair has one primary assignment.
- Every selected deeper-evidence finding has one same-scope primary resolving
  slice.
- Deterministic size splitting and stable plan bytes.
- Rejection of gaps, illegal duplicates, oversized unsplittable inputs, and
  plan mutation after activation.
- Complete root requires exact plan equality, not percentage or count.

### Producer, verifier, and repair

- Candidate schema and evidence-boundary validation.
- Verifier fresh-context and exact-candidate binding.
- PASS acceptance only after deterministic certification.
- REPAIR diagnostics are normalized and slice-scoped.
- Initial plus two producer repairs, never a fourth attempt.
- Two identical non-improving outcomes stop early.
- Verifier contract retries do not consume semantic producer repairs.
- Accepted siblings never reopen.

### Budget and scheduling

- Producer dispatch requires retained verifier reservation.
- Known, unknown, reserved, charged, and trusted-observed usage remain distinct.
- Raising token/time authorization resumes pending work.
- Raising authorization cannot change attempt limits or work identities.
- Adoption records avoided dispatches and reservations without fabricated
  provider usage.

### Recovery

- Crash during snapshot-evidence staging publishes no L4 manifest or pointer;
  retry reuses the intent and rebuilds a byte-identical private stage.
- After activation, continuation succeeds from run-local shards with the source
  checkout and origin runs unavailable; missing shards fail as corruption.
- Crash/process-death fixtures at every producer and verifier durable boundary.
- Durable raw capture prevents duplicate calls.
- Accepted receipts survive projection/materialization loss.
- Root and automatic closure-successor linking are idempotent.
- Byte-identical event and projection replay.

### Adoption and incremental reuse

- Full zero-call sibling adoption.
- Reconstruction after origin runs and cache are removed.
- Selection expansion generates only new slices.
- Selection expansion across a different global L3 epoch/selection identity
  and run-global snapshot-evidence catalog adopts byte-identical target-local L3
  and snapshot-evidence projections and slices.
- One source-record change regenerates only dependent slices and roots.
- Policy/verifier changes branch L4 only.
- Poisoned checkpoints are rejected/quarantined without weakening parent
  authority.

### L3 handoff

- Completed deeper evidence creates or reuses one closure successor.
- Successor consumes exact L4 evidence and cannot start a new audit epoch.
- Closed findings produce closure receipts.
- Missing, mismatched, or incomplete finding-to-evidence authority produces the
  closure-integrity banner with authority IDs and without relabeling accepted L4
  evidence as failed or a finding as semantically open.
- Identical completed handoff performs zero calls.

### Status, compatibility, and repository gates

- Dynamic protocol header is `2.8` in text and JSON.
- Every terminal state ends with the correct prominent banner.
- Selected versus all scope and synthesis-required truth are explicit.
- Protocol 2.2 through 2.7 routing and canonical authorities remain compatible.
- V1 never imports or dispatches protocol 2.8.
- V1 cache reconstruction produces byte-identical V1 selection/index authority
  with adjacent schema-7 runs and never quarantines recognized V2 origins.
- V2 cache/index writes cannot modify V1 cache files.
- Focused protocol matrix, compatibility matrix, installation dry run, and full
  repository `pytest` suite pass.

## Rollout and real-workspace proof

1. Run the complete deterministic and compatibility gates.
2. Install Echelon from the implementation checkout.
3. Use a clean synthetic Git fixture to prove selected-domain and `--all`
   completion, including a manufactured deeper-evidence L3 blocker.
4. Run an installed-provider pilot that proves producer/verifier result
   contracts, bounded repair, interruption recovery, and zero-call replay.
5. On the clean OptaSearch workspace, deepen one representative critical domain
   and prove that all compatible L0-L3 authority is adopted rather than
   regenerated, while every L0-omitted selected file/range is supplied by new
   complete snapshot-evidence shards.
6. Remove or hide checkpoint origins/cache and prove self-contained replay.
7. Record provider/model/effort, generated/adopted/verified/repaired counts,
   avoided dispatches/reservations, trusted and conservative usage, active time,
   event/root hashes, and source-cleanliness evidence without exposing source
   content.

Full OptaSearch `--all` is not a protocol-2.8 release gate. It is deferred until
protocol 2.9 can synthesize and publish the resulting authority. This avoids
spending for an all-scope result that the installed system cannot yet expose as
the intended full-quality outcome.

## Success criteria

Protocol 2.8 is complete when:

1. `deepen --to L4` supports explicit source/domain selection and `--all`.
2. `deepen --to L4 --shadow` previews the exact frozen work set, exact realized
   reuse, and bounded conditional reuse/cost intervals without mutation or
   dispatch.
3. A durable orchestration intent preserves the pending L4 request across L3
   pauses, crashes, process exits, and explicit continuation.
4. Missing selected L3 authority is automatically and visibly created/reused.
5. Only closed or deeper-evidence-only L3 authority reaches L4 activation, and
   synthesis partial-parent handling follows the closed eligibility matrix.
6. Every eligible selected source byte is present in a run-local authenticated
   shard or an exact permitted disposition before activation; L0 omissions do
   not count as L4 coverage.
7. Every selected domain and source has one immutable deterministic exhaustive
   target plan.
8. Every planned slice is independently generated, verified, and accepted or
   truthfully terminal-failed under fixed limits.
9. No L4 root exists without exact plan, file/byte-range, and semantic closure.
10. Accepted siblings survive budgets, retries, crashes, selection expansion,
    and successor runs through target-local authority identity.
11. Identical completed requests and reconstructed siblings perform zero calls.
12. Deeper-evidence completion automatically and visibly routes through an
   immutable protocol-2.8 closure successor over the inherited L3 epoch.
13. Status distinguishes L4 evidence completion, closure integrity,
    synthesis, and full quality.
14. Protocol 2.8 never publishes or claims full workspace quality.
15. Protocol-2.2-through-2.7 and V1 compatibility gates pass, including
    byte-identical V1 cache behavior beside schema-7 origins.
16. The synthetic, installed-provider, and selected OptaSearch pilots pass with
    clean source repositories.
17. The full repository suite passes.

## Follow-on order

1. Protocol 2.9/schema 8 consumes all-scope, L4-complete authority with complete
   native-or-L4 semantic closure, incrementally reuses unaffected protocol-2.7
   synthesis artifacts, publishes through the existing recoverable
   transaction, and owns the full-quality claim.
2. EGR-170 adapts atomic lower-artifact repair to stable L0-through-L4 and
   synthesis interfaces.
3. Default-engine cutover requires completed L4-aware synthesis, atomic repair,
   and retained production evidence showing bounded cost and truthful quality.
