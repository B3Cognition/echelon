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
creates the selected L3 prerequisite, freezes a deterministic exhaustive plan,
generates bounded domain and source-composition evidence slices, independently
verifies every slice, and creates an L4 target root only when the exact planned
closure is accepted.

L4 is deliberately granular. It does not ask one model call to exhaustively
rewrite a domain. A deterministic plan divides each selected domain into
bounded evidence slices derived from the immutable source partition, L0
inventory and evidence, L2 behavioral depth, and L3 audit authority. Accepted
slices are immediately reusable checkpoints. One malformed or semantically
insufficient slice can consume at most two targeted producer repairs and can
never cause accepted siblings to be regenerated.

Protocol 2.8 can start from a closed L3 authority or from an L3 terminal state
whose only unresolved class is `requires_deeper_evidence`. When the selected
L3 prerequisite does not yet exist, `deepen --to L4` visibly creates or reuses
it first. After L4 evidence completes for a deeper-evidence blocker, the
controller automatically and visibly creates or reuses an immutable
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
- Provide a no-write/no-dispatch `--shadow` preview before costly L4 execution.
- Accept L3 parents that are complete or blocked solely by
  `requires_deeper_evidence` in the selected scope.
- Freeze one deterministic, complete slice plan per selected domain and one
  source-composition plan per selected source.
- Ensure every in-scope source record and every required behavioral aspect is
  assigned to the frozen plan exactly and explainably.
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
- a closed selection, parent, policy, executor, and budget authority set.

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

For the requested selection, the command resolves the strongest exact L3
authority compatible with the snapshot, partition, lower artifact policies,
and selection. If no eligible L3 authority exists, it creates or reuses a
selected L3 child using the existing protocol-2.5 path. The command displays
the prerequisite run ID and waits for its terminal authority before creating
the L4 child.

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
  -> selected L3 prerequisite (created or reused when needed)
  -> protocol-2.8 L4 child
  -> protocol-2.8 L4 closure successor (only for deeper-evidence findings)
```

Each arrow is an independently authenticated immutable run. The convenience
orchestration does not merge their event ledgers or state.

`--shadow` performs no writes, pointer changes, checkpoint staging, or provider
dispatch. With an eligible selected L3 authority it builds the exact plan and
reports target/entry counts, immediately realizable versus deferred source
entries, compatible checkpoint counts, required producer/verifier calls, worst
case bounded calls under retry policy, and conservative minimum/maximum token
and active-time reservations. If L3 is missing, shadow reports the exact
prerequisite request and stops; it never creates that prerequisite implicitly.

## Run authority

### `RunManifestV7`

`RunManifestV7` closes the following authority:

- run and creation identity;
- composite source snapshot and partition manifest IDs;
- workspace partition catalog reference;
- inherited artifact-policy catalog reference;
- protocol-2.8 exhaustive-policy catalog reference;
- executor-contract catalog reference;
- parent-authority bundle reference;
- exact selected L3 authority reference;
- exact accepted L4 evidence-root reference for `l4-closure-successor`;
- parent lineage and input run identity;
- explicit `SelectionScopeV1`;
- `run_mode`, `requested_goals`, and target layer;
- exactly one `ExhaustiveRequestV1` or `L4ClosureRequestV1` identity;
- initial run budget policy; and
- immutable L4 attempt policy.

The manifest does not contain mutable progress, discovered slices, provider
results, checkpoint cache locations, or closure-successor state.
Closed-schema validation requires exhaustive mode to pin the exhaustive request
and no accepted L4 parent root. Closure-successor mode must pin the closure
request and complete L4 evidence-run root and must not pin an exhaustive
request. The two modes cannot be represented ambiguously.

### `ParentAuthorityBundleV3`

`ParentAuthorityBundleV3` embeds or references, without rewriting:

- the exact source snapshot and partition authority;
- accepted L0/L1/L2 authority for the selected scope;
- the selected L3 audit epoch, overlays, closure receipts, source roots, and
  terminal root state;
- selected unresolved deeper-evidence finding keys, if any;
- the input run manifest and terminal-event hashes; and
- any staged checkpoint provenance required to make the L4 child
  self-contained.

The bundle validates that every selected L3 artifact refers to the same lower
authority and snapshot. It rejects a mixture of roots from incompatible L3
epochs or source lineages.

### `ExhaustiveRequestV1`

The request identity includes:

- selected source and domain keys and whether the request is `--all`;
- selected L3 authority hash;
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

### `ExhaustivePlanV1`

The run plan contains one `DomainExhaustivePlanV1` per selected domain, one
`SourceExhaustivePlanV1` per selected source, and deterministic run-root work.
Both target plans share the closed `ExhaustiveTargetPlanV1` contract. The plan
is canonical, sorted, bounded, and content-addressed. Its identity is a
manifest authority.

Each domain plan binds:

- domain scope and partition ID;
- exact L0 inventory and evidence hashes;
- exact L2 domain-depth artifact and context hashes;
- exact selected L3 audit/closure authority;
- applicable deeper-evidence finding IDs;
- the complete ordered `SlicePlanEntryV1` set; and
- a coverage ledger proving assignment of every required subject, source
  record, category, and finding.

Each source plan binds:

- source scope, partition ID, and selection-relative coverage mode;
- exact selected domain-plan hashes;
- source-level L0 inventory/evidence and L2 overview authority;
- the selected L3 source audit target, epoch, overlays, and closure authority;
- source-level deeper-evidence finding IDs;
- source records not owned by any selected domain;
- source composition, cross-domain boundary, configuration/security,
  operations/lifecycle, and negative-space slices; and
- a coverage ledger for every required source-level subject, record, category,
  and finding.

For explicit domain selection, the source plan is selection-relative and may
reference only those domains plus authenticated source-level authority. For a
whole-source or `--all` request, it covers the complete source composition.

The planner must reject rather than activate if the plan exceeds policy bounds,
cannot assign an in-scope record, repeats an assignment that must be unique, or
cannot prove exact closure.

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

Sorted subjects are assigned to category slices using immutable policy bounds:
maximum subjects, source records, context bytes, and conservative tokens per
slice. Oversized subject groups split deterministically by stable identity; no
semantic model judgment controls the split.

Every domain-owned in-scope source record must appear in at least one domain
slice's evidence coverage assignment. Every selected source record not owned by
a selected domain must appear in its source plan. Every behavioral
subject/category pair required by policy must appear exactly once as a primary
assignment. Secondary evidence references may repeat, but the plan
distinguishes primary coverage from supporting evidence. Every selected
`requires_deeper_evidence` finding must be assigned to at least one same-scope
slice and has one primary resolving slice.

### `SlicePlanEntryV1` and `SliceSpecV1`

Each frozen plan entry contains:

- stable plan-entry ID;
- target kind, exact domain-or-source scope, and category;
- primary subject IDs;
- supporting subject IDs;
- primary source-record IDs;
- permitted supporting source-record IDs;
- required lower artifact-key IDs and planned target-root key IDs;
- assigned deeper-evidence finding IDs;
- context-object hashes;
- evidence-object hashes;
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
execution order, budgets, and provider observations. Unchanged semantic inputs
therefore produce the same work identities across children. A changed domain
root changes only dependent realized source-composition slices and roots, not
the frozen coverage plan.

## L4 artifact graph

The graph is strictly additive:

```text
authenticated L0-L3 authority
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
- normalized behavioral claims;
- source evidence anchors for every claim;
- boundary, failure, and negative-space observations required by category;
- L3 finding IDs addressed and the new evidence supplied;
- explicit unknown or unresolved observations; and
- a bounded rendered explanation derived from the structured payload.

Every claim must cite authenticated evidence permitted by the slice context.
The controller rejects unknown paths, hashes, subjects, findings, or evidence
anchors before semantic verification. A slice with unresolved observations may
be durably captured and verified as REPAIR evidence, but cannot receive an
acceptance receipt.

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
- coverage-ledger hash;
- addressed deeper-evidence finding IDs; and
- root state `complete`.

The root constructor requires exactly one realized and accepted slice for every
entry in the frozen target plan, with no extras. Subset completion, a PASS
count, or a percentage can never create a root. An
`L4SourceCompositionRootV1` applies the same rule to its source plan and also
binds the selected domain-root hashes.

### `L4SourceRootV1` and `L4RunRootV1`

A source root binds its source-composition root and every selected domain root
for that source and records:

- selected domain keys;
- intentionally unselected domain keys;
- whether the source has full domain coverage under `--all`; and
- the inherited L3 source authority.

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
3. creates or reuses the selected L3 prerequisite;
4. validates its terminal eligibility;
5. builds and validates the parent-authority bundle;
6. builds policy and executor catalogs;
7. constructs the deterministic exhaustive plan;
8. computes conservative minimum initial reservation; and
9. rejects unsafe or unaffordable activation without writing a run.

The run manifest and all referenced catalogs/objects are committed before the
active-run pointer changes.

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
normalized repair input for the next dispatch, when one remains. It never
creates semantic authority or receives a nested contract retry.

### Phase 3: independent verification

Every valid candidate requires a verifier dispatch. A verifier PASS is parsed,
deterministically checked, certified, and accepted. A REPAIR result creates the
normalized repair packet for the same slice.

Verifier result-contract failure has one fixed retry and does not consume a
producer repair. If that retry also fails, the slice blocks on verifier
contract failure without regenerating a valid candidate. Verifier semantic
REPAIR consumes one producer attempt when another is available.

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
If it remains open, status distinguishes completed L4 evidence from blocked L3
finding closure and reports exact unresolved finding classes. The new closure
receipt composes with the inherited L3 finding; it never rewrites or relabels
the original protocol-2.5 object.

## Budget authority

Protocol 2.8 uses the existing independent run token and provider-active-time
ceilings exposed as `--token-limit` and `--active-ms-limit`.

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

## Controller, events, and durable state

The protocol-2.8 controller remains the sole writer to its event chain,
candidate/verification ledgers, certification/acceptance ledgers, budget
ledger, checkpoint ledger, root ledger, and state projection. Provider agents
write only their staged result files.

The closed protocol-2.8 event allowlist covers:

- manifest, catalog, parent bundle, plan, and activation commitment;
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

## Checkpoint adoption and incremental behavior

Protocol 2.8 defines `CheckpointManifestV2` and
`CheckpointSelectionBundleV2`. V2 embeds the unchanged V1 checkpoint authority
for L0-L3 and adds only the protocol-2.8 plan-entry realization, L4 candidate,
verification, accepted-slice, target/root, and semantic-closure kinds. Existing
protocol-2.6 consumers continue to read V1 and ignore V2; protocol 2.8 can read
both. The workspace discovery cache records the checkpoint schema and never
rewrites V1 exports.

Protocol 2.8 checkpoint eligibility requires exact equality of:

- source snapshot content for the slice scope;
- partition and exact domain-or-source target scope;
- lower L0-L3 dependency hashes;
- exhaustive plan and slice identities;
- artifact and exhaustive policy hashes;
- producer/verifier executor contracts;
- candidate, verification, certification, and acceptance receipts; and
- object bytes.

Selection expansion adopts already accepted slices and generates only newly
selected work. A source change invalidates only slices whose assigned primary
or supporting source records, lower artifacts, or L3 authority changed. A
policy or verifier change branches affected L4 identities without rewriting
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

`echelon re status` reads the manifest first and renders `RE V2 — PROTOCOL 2.8`.
The heading never contains a hard-coded older protocol.

Human status reports:

- run, input, L3 prerequisite, L4 child, and linked protocol-2.8
  closure-successor IDs;
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

- `L4 SELECTED SCOPE COMPLETE`;
- `L4 ALL-SCOPE EVIDENCE COMPLETE — SYNTHESIS REQUIRED`;
- `L4 EVIDENCE COMPLETE — L3 CLOSURE BLOCKED`; and
- `L4 BLOCKED — REQUESTED EVIDENCE INCOMPLETE`.

The banner is the final prominent output, not an earlier buried line. A
completed selected run states which domains remain intentionally unselected.
An all-scope run states that protocol-2.9 synthesis is still required. No
protocol-2.8 state or banner says `full quality`, `published complete`, or
equivalent.

The linked inherited-finding closure state has precedence over scope wording.
An all-scope L4 root with an open protocol-2.8 closure successor ends with
`L4 EVIDENCE COMPLETE — L3 CLOSURE BLOCKED`, never the synthesis-required
banner. Synthesis becomes the next action only after the linked selected L3
findings have complete native or protocol-2.8 composed closure authority.

## Failure taxonomy and next actions

Pre-activation failures create no L4 run:

- invalid or dirty source authority;
- unsupported input protocol or lineage;
- ambiguous/unknown selection;
- unavailable or ineligible L3 prerequisite;
- mixed/non-deeper L3 blocker classes;
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
- linked inherited L3-finding closure remains open.

Status maps each reason to one command or external action. Resource pauses show
the exact `echelon re continue` authorization command. Fixed-attempt failures
do not suggest adding tokens. Dirty or changed sources require commit, stash, or
revert and a new snapshot; they never suggest silently including dirty files.

## Security and evidence boundary

- Source access remains inside the immutable declared snapshot.
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
independent authorization; if it pauses, the visible chain stops and prints
the exact L3 continuation command before any L4 run exists. An operator who
needs custom L3 limits may create that prerequisite explicitly. No
`hard_`-prefixed public setting is introduced.

`--shadow` follows the existing RE v2 shadow convention and is valid for L4
without resource flags. Combining shadow with token/time authorization is
rejected because shadow cannot spend or append authority.

`echelon re continue` recognizes active schema-7 runs, appends only permitted
resource authorization, recovers authority, and resumes pending work. Repeating
continue on a complete run is zero-call and prints the complete banner.

The active-run pointer may advance through prerequisite, L4, and closure
children, but status invoked with any explicit run ID remains authoritative for
that run. The orchestrated command's final banner names the final state across
the linked chain so the user does not need to inspect nested `state.json`
files.

## Implementation boundaries and reuse

New protocol code lives under `src/harness/re_v2/protocol_28/` with focused
modules for closed models, parent authority, policy, planning, graph
realization, context, execution, verification, artifacts, budget integration,
checkpoint V2, controller, recovery, lifecycle, materialization, and status.
The CLI adds only manifest-first routing, selection/prerequisite orchestration,
and operator option plumbing.

Protocol 2.8 reuses:

- canonical JSON, content digests, object stores, durable files, locks, event
  chains, typed ledgers, and execution captures from the shared kernel;
- immutable source snapshot, partition, inventory, and evidence authority;
- L1/L2 artifact and certification authority by reference;
- L3 epoch/finding/closure authority by embedding `ParentAuthorityBundleV2` in
  `ParentAuthorityBundleV3`;
- protocol-2.6 checkpoint discovery semantics through versioned V2 decoding;
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

- Closed-field round trips for every schema-7 value.
- Canonical digest and order independence where sets are semantic.
- Rejection of extra fields, wrong versions, invalid IDs, duplicate subjects,
  duplicate source records, and cross-scope dependencies.
- Request identity excludes budgets and includes every semantic authority.
- Slice identity is stable across run IDs and execution order.

### Selection and prerequisites

- `--all`, source, and domain selector matrix.
- Unknown, duplicate, ambiguous, and conflicting selectors.
- Zero-domain sources with and without source-composition work.
- Direct L3 complete parent.
- L3 parent blocked only by selected deeper-evidence findings.
- Rejection of mixed or unsupported L3 blockers.
- Automatic creation/reuse of missing selected L3.
- Synthesis input resolves to underlying analysis authority without consuming
  synthesized artifacts.
- Shadow is side-effect free, reports missing L3 without creating it, and emits
  exact plan/checkpoint/call counts once L3 is eligible.

### Planning and coverage

- Every domain and source fixed category is planned.
- Every in-scope domain-owned and source-level record is assigned exactly at
  the correct scope.
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

- Crash/process-death fixtures at every producer and verifier durable boundary.
- Durable raw capture prevents duplicate calls.
- Accepted receipts survive projection/materialization loss.
- Root and automatic closure-successor linking are idempotent.
- Byte-identical event and projection replay.

### Adoption and incremental reuse

- Full zero-call sibling adoption.
- Reconstruction after origin runs and cache are removed.
- Selection expansion generates only new slices.
- One source-record change regenerates only dependent slices and roots.
- Policy/verifier changes branch L4 only.
- Poisoned checkpoints are rejected/quarantined without weakening parent
  authority.

### L3 handoff

- Completed deeper evidence creates or reuses one closure successor.
- Successor consumes exact L4 evidence and cannot start a new audit epoch.
- Closed findings produce closure receipts.
- Missing, mismatched, or incomplete finding-to-evidence authority produces the
  closure-blocked integrity banner without relabeling accepted L4 evidence as
  failed.
- Identical completed handoff performs zero calls.

### Status, compatibility, and repository gates

- Dynamic protocol header is `2.8` in text and JSON.
- Every terminal state ends with the correct prominent banner.
- Selected versus all scope and synthesis-required truth are explicit.
- Protocol 2.2 through 2.7 routing and canonical authorities remain compatible.
- V1 never imports or dispatches protocol 2.8.
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
   regenerated.
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
2. `deepen --to L4 --shadow` previews exact work and bounded cost without
   mutation or dispatch.
3. Missing selected L3 authority is automatically and visibly created/reused.
4. Only closed or deeper-evidence-only L3 authority reaches L4 activation.
5. Every selected domain and source has one immutable deterministic exhaustive
   target plan.
6. Every planned slice is independently generated, verified, and accepted or
   truthfully terminal-failed under fixed limits.
7. No L4 root exists without exact complete plan closure.
8. Accepted siblings survive budgets, retries, crashes, and successor runs.
9. Identical completed requests and reconstructed siblings perform zero calls.
10. Deeper-evidence completion automatically and visibly routes through an
   immutable protocol-2.8 closure successor over the inherited L3 epoch.
11. Status distinguishes L4 evidence completion, inherited-finding closure,
    synthesis, and full quality.
12. Protocol 2.8 never publishes or claims full workspace quality.
13. Protocol-2.2-through-2.7 and v1 compatibility gates pass.
14. The synthetic, installed-provider, and selected OptaSearch pilots pass with
    clean source repositories.
15. The full repository suite passes.

## Follow-on order

1. Protocol 2.9/schema 8 consumes all-scope, L4-complete authority with complete
   native-or-L4 semantic closure, incrementally reuses unaffected protocol-2.7
   synthesis artifacts, publishes through the existing recoverable
   transaction, and owns the full-quality claim.
2. EGR-170 adapts atomic lower-artifact repair to stable L0-through-L4 and
   synthesis interfaces.
3. Default-engine cutover requires completed L4-aware synthesis, atomic repair,
   and retained production evidence showing bounded cost and truthful quality.
