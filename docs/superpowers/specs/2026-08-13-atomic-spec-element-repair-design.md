# Atomic Specification Element Repair Design

## Status

Safety and certification invariants were approved on 2026-08-13 after
architecture review. Implementation is deferred pending the RE execution-kernel,
layering, convergence, and synthesis redesign tracked by EGR-164 through
EGR-169. Before implementation planning, the RE adapter's state, routing,
full-gate, budget, and publication integration must be revised against those
interfaces. Execution remains explicitly opt-in. The intended first release
covers only `spec.md` repair in reverse engineering (RE) and normal Phase A
specification authoring, plus the required controller-certified synchronization
of Phase A's companion `requirements-overview.md` after repair convergence.

## Problem

Echelon persists specifications, quality reports, controller state, and journal
entries, but its repair dispatches are still too coarse. A failing source-domain
specification or Phase A quality review can send an agent back through most of
the artifact instead of assigning one independently verifiable correction. A
reasoning model can then consume its entire output or context allowance before
returning a complete `echelon_result`. The artifact may contain useful edits,
but the missing result prevents ordinary workflow routing and a subsequent
continuation asks the model to reason broadly again.

The durable artifact is therefore preserved while the durable *execution unit*
is not. Repeated `finish_reason=length`, missing-result, or no-progress outcomes
can strand a run on the same whole-specification task.

## Goals

- Represent specification repair as durable, element-centered work.
- Group all current findings for the same FR, NFR, scenario, or acceptance
  block into one repair unit.
- Use the same repair mechanics for RE and normal Phase A while preserving each
  workflow's existing gates and terminal policies.
- Let controller-certified artifact evidence determine the outcome of a repair
  dispatch, including when the provider omits a usable completion payload.
- Prevent unverified edits from reaching the canonical artifact.
- Detect and reject out-of-scope candidate edits without overwriting concurrent
  canonical changes.
- Resume safely after process interruption without rediscovering completed
  work.
- Bound attempts, repeated findings, queue generations, and total workflow
  repair cost.
- Introduce the behavior additively behind an explicit opt-in.

## Non-Goals

- Repairing `plan.md`, `tasks.md`, Lexicon artifacts, delivery artifacts, or
  source code in the first release.
- Replacing WHAT, RE specification creation, Understanding, WHY2, semantic
  review, publication, or existing workflow controllers.
- Preserving or resuming a model's hidden reasoning.
- Allowing a model-authored result to override controller-owned quality gates or
  routing.
- Automatically migrating an in-flight legacy run into atomic repair.
- Making qualitative findings atomic when no scoped controller verifier can
  certify them.

## Decisions

### Shared mechanics, workflow-owned policy

A shared `SpecRepairEngine` owns queue mechanics. RE and Phase A provide
adapters that translate their gate findings into a common schema and map the
engine's neutral terminal outcome into workflow-specific routing.

The shared engine owns:

- element-centered grouping;
- stable queue ordering;
- durable queue state;
- pre-dispatch baselines;
- bounded repair prompts;
- mutation-scope checks;
- isolated candidate creation and compare-and-swap promotion;
- gate rechecks supplied by the workflow adapter;
- attempt, no-progress, and generation accounting;
- controller-certified repair receipts.

The workflow adapter owns:

- finding classification and eligibility;
- the authoritative verifier;
- evidence and human-decision routes;
- per-unit and outer repair budgets;
- exhaustion policy;
- final full-gate routing;
- publication and completion.

The existing in-memory `RepairLoop` remains unchanged. It is useful for bounded
work inside one live process, but it is not a durable queue and cannot provide
the recovery semantics required here.

### Element-centered repair

One unit represents one affected specification element, not one finding. If
`FR-006` has an invalid citation, an ambiguous outcome, and an unscoped
universal claim, those findings form one `FR-006` unit. This avoids separate
calls repeatedly rewriting the same content.

The supported first-release element kinds are:

- functional requirement;
- non-functional requirement;
- identified acceptance criterion;
- scenario or user-story block, including unnumbered acceptance criteria nested
  beneath it;
- an explicitly linked small group of the above when one finding cannot be
  repaired independently.

Adapters parse their existing specification syntax into stable element IDs and
byte spans. A finding without a unique supported element anchor is not eligible
for atomic repair and follows the legacy aggregate route. Duplicate IDs,
ambiguous spans, or a link to an unparseable element also make the finding
ineligible.

The unit identity is stable for a workflow, artifact, and ordered element-ID
set. Finding contents have a separate fingerprint so changed findings do not
create a fresh unit and evade its attempt budget.

#### In-place and structural element slots

Each unit declares one of two mutation modes:

- `in_place` authorizes replacement of the existing element body while
  preserving its ID and peer boundary;
- `structural_split` authorizes replacement of one element slot with the
  original element plus a bounded number of new peer requirements or identified
  acceptance criteria.

For `structural_split`, the controller reserves the exact new IDs before
dispatch. The original ID must remain, the candidate may use only a prefix of
the reserved IDs, and no existing ID outside the authorized linked group may be
renamed or removed. The adapter validates uniqueness, ordering, cross-references,
and the resulting peer boundaries before promotion. The repair request receives
the reserved ID set and cannot invent IDs outside it.

Any reserved IDs actually used become part of the original unit's durable
lineage. A later finding anchored to the original or a generated child ID reopens
that same unit history rather than receiving a fresh attempt budget.

A repair that requires global renumbering, deletion of the original ID, or an
unbounded reorganization is not eligible for first-release atomic repair and
uses the legacy aggregate route. This permits the existing Phase A requirement
to split compound behavior into separately identified requirements while
keeping the mutation surface deterministic.

### Controller-certified repair node

Atomic repair is a dedicated controller operation. It does not reuse the result
contract of a full authoring phase.

For RE:

```text
re-extract-2-specify
  -> target gate fails
  -> re-extract-2-repair-element
  -> queue resolves or exhausts
  -> existing target/source gates and routing
```

For normal Phase A:

```text
phase1-what
  -> Understanding + WHY2
  -> eligible spec-repair findings
  -> phase1-repair-element
  -> queue resolves or exhausts
  -> Understanding + WHY2 and existing routing
```

The nodes reuse the artifact-owning roles, RE-SPECIFIER and CARTOGRAPHER, with a
narrow controller-rendered request. Their allowed state updates are empty. The
model may edit only the authorized candidate `spec.md` elements and has no
routing authority.

`phase1-repair-element` is a new `controller_spec_repair` workflow node type,
not a normal `agent` node. Its executor internally invokes the provider, builds
a controller-owned result from candidate certification, and submits that result
through the existing `PreparedPhaseResult`, routing-snapshot/CAS, completion
outbox, and journal transaction. Provider output never bypasses Phase A's
existing state revision or routing transaction. Controller-owned `spec_repair`
updates travel as transaction state updates, not as agent `state_updates`.

The Phase A graph routes one unit per node execution. A pending queue transitions
back to `phase1-repair-element`; a drained generation transitions to
`phase1-understanding`; exhaustion transitions to the existing blocked policy.
RE adds the dedicated phase ID to its controller phase and prompt registries but
keeps the queue and certification inside the existing RE controller protocol.

If a provider returns a valid completion payload, it is retained as diagnostic
metadata. The controller still derives the node outcome from artifact scope and
the adapter's verifier. If a provider returns `length`, times out, exits
nonzero, or omits a result, the same certification runs after the provider is
known to have stopped. A missing model result is never passed off as a valid
model result: the controller records its own repair receipt and completes the
repair node through the controller protocol.

Atomic execution requires a provider capability that enforces the candidate's
read/write boundary and terminates the complete provider process tree before
certification. OpenAI-compatible exact tool scopes and an equivalently confined
Claude invocation can advertise this capability. A backend that merely runs in
the project working directory without enforcing the supplied paths cannot.
`atomic` mode fails closed with `spec_repair_provider_scope_unsupported` when the
capability is absent; it never silently downgrades to legacy. `shadow` mode does
not require the capability because it performs no provider call or mutation.

Full creation and review nodes retain their existing result contracts because
they may return required evidence-resolution, human-input, and routing state.

### Normalized controller diagnostics

The shared engine does not parse human-readable gate messages to discover
element IDs. Each adapter supplies normalized controller diagnostics:

```yaml
finding_id: finding-...
rule_id: unscoped_universal_claim
route: spec_repair
severity: high
element_refs: [NFR-001]
evidence_refs: [src/module.py:10-24]
verifier_id: re-semantic-preflight/unscoped-universal-claim
message: "Bounded diagnostic text for the repair prompt"
```

`finding_id`, `rule_id`, `route`, `severity`, `element_refs`, and `verifier_id`
are controller-owned fields. RE gate producers or their deterministic adapter
must add structured element references to currently aggregate
`ReSpecQualityFailure` and `SemanticPreflightFinding` data. Phase A derives
references from the certified Understanding report's exact requirement IDs.
Human-readable prose is prompt context only and is never an identity or routing
source.

Document-global findings such as missing required sections, minimum-count
deficits, or a missing Behavior Coverage table remain legacy findings unless a
later design introduces a supported document-level element and scoped verifier.

## Eligibility

The engine accepts only findings classified as `spec_repair` and bound to a
supported element. Findings classified as `evidence_resolution` or
`human_decision` always use their existing routes.

The first release also requires a scoped controller verifier. RE deep-spec and
semantic-preflight findings qualify when the existing controller gate can
re-evaluate the target element. Phase A certified Understanding findings
qualify when the report identifies the affected FR, NFR, scenario, or AC and
the relevant metric can be recomputed. A SAGE-only qualitative finding without
a deterministic scoped check remains on the legacy route. It may become
eligible in a later version if a controller-owned scoped verifier is defined.

This restriction keeps “resolved” meaningful: an edit is resolved only when an
authoritative check proves the finding is absent.

When finding classes are mixed, routing is deterministic:

1. unresolved `evidence_resolution` or `human_decision` findings take their
   existing route before any automatic edit;
2. otherwise, eligible atomic units run and the complete quality chain reruns;
3. remaining unsupported or qualitative `spec_repair` findings take the legacy
   aggregate route within the workflow's remaining outer budget.

The queue never marks an excluded finding resolved merely because eligible
neighbors were repaired.

## Durable State

Each run snapshots its repair mode at creation. Runs without this snapshot are
legacy runs even if workspace configuration later changes.

The common state lives under `spec_repair` in the workflow's authoritative
controller state and is written only through the existing controller/state
transaction mechanism. For Phase A this is the squad `state.json`. RE has an
outer lifecycle state and an inner controller state; `runs/<run-id>/re/state.json`
is authoritative for the repair queue, while the outer `runs/<run-id>/state.json`
may mirror only the snapshotted mode and status summary.

```yaml
spec_repair:
  schema_version: 1
  mode: atomic
  workflow: re
  generation: 1
  source_report:
    path: quality/targets/api/001.json
    sha256: "..."
  artifact:
    path: sources/api/specs/001/spec.md
    sha256: "..."
  active_unit_id: repair-...
  outer_round: 1
  atomic_dispatches: 3
  units:
    repair-...:
      element_kind: functional_requirement
      element_ids: [FR-006]
      finding_fingerprint: "..."
      finding_refs: [finding-1, finding-2]
      mutation_mode: structural_split
      reserved_ids: [FR-010, FR-011]
      status: active
      attempts: 1
      no_progress_count: 0
      baseline_path: .control/spec-repair/repair-.../1/spec.before.md
      candidate_path: .control/spec-repair/repair-.../1/candidate/spec.md
      baseline_sha256: "..."
      promotion: null
      last_receipt: {...}
```

Quality-report bodies remain separate controller-owned artifacts. State stores
paths, hashes, stable finding references, and the minimum prompt data needed to
resume; it does not duplicate entire reports or model transcripts.

Phase A registers a controller-authored `spec_repair_receipt` type in
`runtime/workflow/journal-entry-types.yaml`. Its idempotency key is the ordered
tuple `(workflow, generation, unit_id, attempt)`, and it is appended through the
existing completion transaction. RE emits the same receipt payload to its
controller telemetry and retains the routing fields in inner state. State keeps
the current receipt and queue status required for routing. No hidden reasoning
is stored.

The `.control/spec-repair/**` tree is controller-private. RE repair snapshots,
publication, source coverage, artifact discovery, and cleanup rules must treat
it as control-plane data rather than source output.

## Queue Construction and Ordering

After the existing full gate fails, the adapter:

1. Classifies every finding.
2. Excludes non-atomic findings and preserves their existing route.
3. Resolves eligible findings to unique elements.
4. Groups findings by element or explicit linked group.
5. Selects `in_place` or `structural_split` mutation mode and reserves any new
   IDs deterministically.
6. Computes unit and finding fingerprints.
7. Persists the complete generation before selecting work or consuming its one
   outer repair round.

Units are ordered deterministically by severity, artifact position, element
kind, and element ID. Only one unit is active at a time. Later parallelism is
outside the first-release scope because all units mutate the same file.

An unresolved evidence or human-decision route takes precedence over automatic
repair. Mixed runs do not silently repair around a decision the workflow says
must be made first.

## Repair Prompt Contract

The repair request contains only the context needed for the active unit:

- artifact path and fingerprint;
- controller-owned candidate path and expected canonical preimage fingerprint;
- element kind, IDs, exact current text, and limited neighboring context;
- all grouped findings and their rule identifiers;
- required source/evidence excerpts or references;
- immutable governance and formatting constraints;
- the explicit allowed-element set;
- mutation mode and any controller-reserved new IDs;
- a statement that the controller validates and routes the outcome.

The prompt does not ask the model to re-review the full specification, run the
entire workflow, or declare downstream readiness. The provider may use tools to
read the candidate and permitted evidence, but file-write scope is restricted to
the candidate `spec.md`. Atomic nodes override the artifact-owning role's normal
high-effort default with a bounded repair profile: low reasoning effort when the
provider supports it, an adapter-supplied per-dispatch output/token ceiling, and
a repair-specific timeout. Unsupported effort controls do not weaken the hard
token and timeout ceilings.

## Candidate Guard and Compare-and-Swap Promotion

Before dispatch, the controller:

1. Acquires the existing run lock.
2. Reads the canonical `spec.md`, writes and fsyncs a private full-file baseline,
   and creates an identical controller-owned candidate under the run-control
   area.
3. Persists the active unit, baseline and candidate paths, canonical preimage
   hash, and incomplete `last_dispatch` marker.
4. Starts the provider with enforced write access only to the candidate.

The parser replaces authorized baseline and candidate element slots with
canonical placeholders and compares the remaining document bytes. This permits
the targeted slot to change length while requiring all unauthorized content to
remain byte-identical. An `in_place` candidate must retain its ID and unique
parseable boundary. A `structural_split` candidate must satisfy its original-ID,
reserved-ID, ordering, and reference-integrity contract.

After dispatch, or during recovery of an incomplete atomic dispatch, the
controller first ensures no provider process can still write the candidate. It
then classifies the candidate:

- unauthorized content changed;
- artifact is unreadable, truncated, or structurally ambiguous;
- no bytes changed;
- only authorized elements changed.

For the first two cases, the controller records `invalid_scope` and discards or
retains the private candidate for diagnostics. The canonical artifact is
untouched; no baseline restoration is performed. A valid targeted candidate
remains certifiable even when the provider result is incomplete.

The adapter runs its scoped verifier against the candidate path, never against
an unpromoted canonical file. A unit becomes `resolved` only after that verifier
passes and promotion succeeds. Promotion uses a recoverable compare-and-swap
protocol:

1. Persist `promotion_pending` with the expected canonical preimage hash,
   candidate hash, receipt identity, and candidate path.
2. Re-read the canonical artifact. If its hash differs from the expected
   preimage, do not overwrite it; record `artifact_changed_concurrently` and
   block the atomic node for operator-safe recovery.
3. Atomically replace and fsync the canonical artifact from the candidate.
4. Commit the controller receipt, queue transition, and completed-dispatch
   marker through the workflow's state transaction.

On restart, the controller reconciles `promotion_pending` by hash. A canonical
hash equal to the candidate hash means promotion already occurred and only the
state transaction remains. A hash equal to the preimage permits promotion to be
retried. Any third hash is a concurrent-change conflict and is never overwritten.

## Certification and Receipts

Every dispatch produces a controller-owned receipt:

```yaml
unit_id: repair-...
generation: 1
attempt: 2
provider_outcome: length
canonical_preimage_sha256: "..."
candidate_sha256: "..."
scope_valid: true
gate_outcome: resolved
remaining_finding_ids: []
```

`provider_outcome` is diagnostic. `gate_outcome` controls the repair queue and
is one of:

- `resolved`: the scoped verifier proves the unit's findings are absent;
- `remaining`: the artifact is valid but one or more scoped findings remain;
- `invalid_scope`: the private candidate violated its authorized mutation scope
  and was rejected;
- `no_progress`: artifact and finding fingerprints are unchanged;
- `artifact_changed_concurrently`: the canonical compare-and-swap precondition
  failed and no promotion occurred;
- `exhausted`: no further dispatch is allowed for the unit.

`invalid_scope` rejects the private candidate; it does not restore or modify the
canonical artifact.

Every provider dispatch consumes an attempt, including `length`, timeout,
nonzero exit, missing result, invalid scope, and no change. Changed findings
show progress but do not reset attempts. A resolved unit is not redispatched
unless a later full gate proves that it regressed.

## Full-Gate Convergence

After the current queue generation has no pending units, Phase A first performs
the companion synchronization below, then each workflow reruns its complete
existing quality chain. This catches cross-element regressions and findings
outside scoped verifiers.

Phase A uses one bounded `phase1-sync-requirements-overview` controller operation
because WHAT owns both `requirements-overview.md` and `spec.md`. CARTOGRAPHER
receives the promoted canonical specification and the existing overview, writes
only a private whole-overview candidate, and runs with the same confined
provider, incomplete-result certification, and compare-and-swap promotion
protocol. This is a companion-artifact synchronization, not a second element
repair queue and not another outer repair round.

The controller verifies the overview template, rejects references to unknown
requirement IDs, and records the canonical spec SHA used to produce the promoted
overview. Failure to synchronize or promote blocks Phase A with
`requirements_overview_sync_failed`; Phase A never advances with an overview
known to predate the repaired specification. Existing downstream review remains
authoritative for semantic contradictions in the overview.

If the full gate produces newly eligible findings, the adapter may create
another generation within the existing outer workflow ceiling. If the full
report fingerprint and artifact fingerprint match the preceding generation,
the engine terminates rather than rebuilding an identical queue. Reopened
element IDs retain their history so a regression cannot obtain a fresh
unbounded budget.

The shared engine returns a neutral exhausted result. Current policy is:

- RE records explicit partial-quality debt and continues according to its
  existing source-level policy;
- normal Phase A remains blocked because its specification-quality gate is
  mandatory.

These policies belong to adapters and may change independently later.

## Budgets and Circuit Breakers

Each adapter supplies a per-unit attempt limit, a per-generation atomic dispatch
limit, per-dispatch token and timeout limits, and the existing outer
repair/iteration ceiling. Creating and executing one non-empty atomic queue
generation consumes exactly one existing outer repair round. Individual element
dispatches consume their unit, generation, token, and time budgets but do not
individually increment the outer RE repair counter or Phase A iteration.

A complete-gate rerun that creates another non-empty generation consumes the
next outer repair round. Shadow queue derivation and a generation that is routed
away before any automatic edit do not consume an outer round. Atomic budgeting
therefore preserves the meaning of existing RE domain-repair passes and Phase A
WHAT/WHY2 iterations while still bounding the number and cost of element calls.

The first unchanged candidate/finding result records `no_progress` and permits
one narrower retry when the unit and generation budgets allow it. A second
consecutive identical result exhausts the unit. Any scoped candidate change or
changed finding fingerprint resets only `no_progress_count`; it never resets
the unit's total attempts. Repeated provider failures therefore cannot consume
an entire generation without durable change.

Queue generation count, reopened-unit count, provider outcome, token usage,
candidate rejection, promotion conflicts, and termination reason are observable
in status and telemetry.

## Configuration and Compatibility

The feature is disabled by default:

```yaml
harness:
  spec_repair:
    re: legacy       # legacy | shadow | atomic
    phase_a: legacy  # legacy | shadow | atomic
```

Implementation adds a validated `SpecRepairConfig` to `HarnessConfig`; unknown
or misspelled modes fail configuration loading instead of being silently
ignored. Run creation snapshots the selected mode into the authoritative
workflow state before any repair can be scheduled. RE lifecycle initialization
copies the RE mode into its inner controller state, which remains authoritative
for continuation.

- `legacy` preserves current behavior.
- `shadow` derives and records the proposed queue and telemetry but makes no
  repair provider call, artifact mutation, or routing change.
- `atomic` executes the controller-certified queue.

There is no automatic migration for existing runs. A new run snapshots the
configured mode. A legacy run remains legacy on continuation; an atomic run
continues atomic even if workspace defaults later change. An explicit future
migration command would require its own design.

Creation prompts, creation result contracts, evidence routing, human gates,
publication, and final quality gates remain unchanged. Turning the feature off
for new runs does not rewrite any existing artifact or state.

## Implementation Boundaries

The shared implementation should remain provider-independent and small:

- a specification-element parser and mutation guard;
- repair-unit and receipt schemas;
- a durable queue engine over an injected state transaction interface;
- an injected provider-dispatch callback;
- an injected scoped-verifier callback;
- an isolated-candidate store and recoverable compare-and-swap promoter;
- RE and Phase A adapters;
- a Phase A `controller_spec_repair` executor and overview synchronizer;
- narrow prompt rendering for RE-SPECIFIER and CARTOGRAPHER.

Provider adapters continue to report raw exit, timeout, token, and finish-reason
metadata. They do not decide whether an artifact repair succeeded. They also
advertise whether they can enforce the atomic candidate boundary; this is a
capability declaration, not a success verdict.

The Prosaic agent files own invariant repair behavior. Runtime workflow nodes
own context assembly, allowed outputs, and controller state contracts. The
shared Python engine owns persistence, certification, and routing outcomes.

## Verification Strategy

### Shared unit tests

- Stable parsing for RE and Phase A element syntax.
- Multiple findings grouped into one FR, NFR, AC, or scenario unit.
- Explicitly linked element groups.
- Structural split slots retain the original ID and accept only
  controller-reserved new IDs.
- Global renumbering, unreserved IDs, and deletion of the original ID are
  rejected or classified legacy.
- Ambiguous, duplicate, missing, and unsupported anchors rejected.
- Normalized diagnostics use structured element references rather than parsing
  IDs from diagnostic prose.
- Stable unit identity with an independently changing finding fingerprint.
- Deterministic queue ordering.
- Attempt and outer-budget accounting.
- Identical artifact/finding no-progress detection.
- Identical full-gate generation termination.

### Candidate, promotion, and recovery tests

- Authorized element-only edits accepted.
- Adjacent or unrelated candidate edits rejected while the canonical file stays
  byte-identical.
- Deleted IDs, duplicate IDs, malformed Markdown, and truncated candidates are
  rejected without canonical mutation.
- Baseline and active dispatch persisted before provider execution.
- Restart between provider return and certification resumes the same unit.
- Restart after certification does not duplicate a receipt or redispatch.
- Recovery refuses to inspect while a provider writer may still be active.
- Promotion is retried safely when canonical still equals the preimage.
- Recovery recognizes an already-promoted candidate by hash.
- A concurrent canonical change fails compare-and-swap and is never overwritten.
- `.control/spec-repair/**` never appears as RE source output or a non-target
  repair mutation.

### Provider-outcome tests

- `finish_reason=length` after a passing targeted edit resolves the unit.
- `length` without an edit records no progress.
- Missing `echelon_result` after a valid edit is controller-certified.
- Timeout and nonzero exit follow the same candidate checks after process
  termination.
- A valid model result cannot override a failing scoped verifier.
- An invalid model result cannot invalidate a passing scoped verifier.
- Atomic mode fails closed for a provider without enforced candidate scope.
- Atomic prompts apply their repair-specific effort, token, and timeout bounds.

### Workflow integration tests

- Legacy mode reproduces existing RE and Phase A routing.
- Shadow mode changes neither artifact nor route.
- In-flight states without the schema remain legacy.
- Evidence-resolution and human-decision findings bypass atomic repair.
- Unsupported SAGE-only qualitative findings retain legacy routing.
- Queue drain reruns the complete existing quality chain.
- Phase A queue drain synchronizes and validates `requirements-overview.md`
  before rerunning the complete quality chain.
- RE exhaustion records partial-quality debt and advances per RE policy.
- Phase A exhaustion remains blocked.
- One queue generation consumes one outer repair round regardless of its number
  of successful element dispatches.
- A newly generated queue consumes the next outer round.
- `last_dispatch.post_dispatch_complete` and journal effects are committed once
  for controller-certified incomplete provider responses.

### Live acceptance

Use a retained failing RE workspace with an OpenAI-compatible reasoning model
to demonstrate that:

- a domain is repaired one element at a time;
- continuation does not rediscover resolved units;
- a `length` response with a valid saved repair advances;
- repeated no-progress stops automatically;
- the final existing RE gate remains authoritative.

Run a representative Phase A specification in shadow mode before enabling
atomic mode and compare proposed units, final gate results, routes, and artifact
diffs with the legacy workflow.

## Rollout

1. Add shared schemas, parser, mutation guard, durable queue, and shadow
   adapters with both modes defaulting to `legacy`.
2. Exercise shadow mode in focused RE and Phase A tests and retained runs.
3. Enable `atomic` explicitly for selected RE runs.
4. Review telemetry for candidate rejection, promotion conflicts, no-progress,
   queue regeneration, token use, and final-gate equivalence.
5. Enable `atomic` explicitly for selected Phase A runs.
6. Consider default changes or additional artifact types only through a later
   design backed by rollout evidence.

## Acceptance Criteria

The design is successfully implemented when:

- both workflows can opt into the same durable element-centered repair engine;
- the model never owns routing for an atomic repair node;
- a passing persisted repair can survive `finish_reason=length` or a missing
  result;
- unrelated candidate edits are deterministically rejected without touching the
  canonical artifact;
- promotion never overwrites a concurrently changed canonical artifact;
- structural splits can introduce only controller-reserved requirement or AC
  IDs;
- continuation resumes the exact active or next unit;
- no-progress and exhaustion terminate without a manual retry loop;
- RE and Phase A preserve their different exhaustion policies;
- legacy is the default and existing in-flight runs behave exactly as before;
- complete existing quality gates still decide whether either workflow may
  advance.
