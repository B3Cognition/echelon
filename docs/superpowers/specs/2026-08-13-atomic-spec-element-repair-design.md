# Atomic Specification Element Repair Design

## Status

Approved for implementation planning on 2026-08-13. Execution is explicitly
opt-in. The first release covers only `spec.md` repair in reverse engineering
(RE) and normal Phase A specification authoring.

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
- Detect and restore out-of-scope edits.
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
model may edit only the authorized `spec.md` elements and has no routing
authority.

If a provider returns a valid completion payload, it is retained as diagnostic
metadata. The controller still derives the node outcome from artifact scope and
the adapter's verifier. If a provider returns `length`, times out, exits
nonzero, or omits a result, the same certification runs after the provider is
known to have stopped. A missing model result is never passed off as a valid
model result: the controller records its own repair receipt and completes the
repair node through the controller protocol.

Full creation and review nodes retain their existing result contracts because
they may return required evidence-resolution, human-input, and routing state.

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

## Durable State

Each run snapshots its repair mode at creation. Runs without this snapshot are
legacy runs even if workspace configuration later changes.

The common state lives under `spec_repair` in the workflow's existing
`state.json` and is written only through the existing controller/state
transaction mechanism:

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
  outer_dispatches: 3
  units:
    repair-...:
      element_kind: functional_requirement
      element_ids: [FR-006]
      finding_fingerprint: "..."
      finding_refs: [finding-1, finding-2]
      status: active
      attempts: 1
      no_progress_count: 0
      baseline_path: .control/spec-repair/repair-.../1/spec.before.md
      baseline_sha256: "..."
      last_receipt: {...}
```

Quality-report bodies remain separate controller-owned artifacts. State stores
paths, hashes, stable finding references, and the minimum prompt data needed to
resume; it does not duplicate entire reports or model transcripts.

Detailed receipts are appended to the existing controller journal or telemetry
stream. State retains the current receipt and queue status required for routing.
No hidden reasoning is stored.

## Queue Construction and Ordering

After the existing full gate fails, the adapter:

1. Classifies every finding.
2. Excludes non-atomic findings and preserves their existing route.
3. Resolves eligible findings to unique elements.
4. Groups findings by element or explicit linked group.
5. Computes unit and finding fingerprints.
6. Persists the complete generation before selecting work.

Units are ordered deterministically by severity, artifact position, element
kind, and element ID. Only one unit is active at a time. Later parallelism is
outside the first-release scope because all units mutate the same file.

An unresolved evidence or human-decision route takes precedence over automatic
repair. Mixed runs do not silently repair around a decision the workflow says
must be made first.

## Repair Prompt Contract

The repair request contains only the context needed for the active unit:

- artifact path and fingerprint;
- element kind, IDs, exact current text, and limited neighboring context;
- all grouped findings and their rule identifiers;
- required source/evidence excerpts or references;
- immutable governance and formatting constraints;
- the explicit allowed-element set;
- a statement that the controller validates and routes the outcome.

The prompt does not ask the model to re-review the full specification, run the
entire workflow, or declare downstream readiness. The provider may use tools to
read the artifact and permitted evidence, but file-write scope is restricted to
the target `spec.md`.

## Mutation Guard and Baseline Recovery

Before dispatch, the controller:

1. Acquires the existing run lock.
2. Writes and fsyncs a private full-file baseline under the run-control area.
3. Persists the active unit, baseline hash, and incomplete `last_dispatch`
   marker.
4. Starts the provider dispatch.

The parser replaces authorized baseline and post-dispatch element spans with
canonical placeholders and compares the remaining document bytes. This permits
the targeted element to change length while requiring all unauthorized content
to remain byte-identical. The postimage must retain unique parseable IDs and the
authorized group boundary.

After dispatch, or during recovery of an incomplete atomic dispatch, the
controller first ensures no provider process can still write the artifact. It
then classifies the postimage:

- unauthorized content changed;
- artifact is unreadable, truncated, or structurally ambiguous;
- no bytes changed;
- only authorized elements changed.

For the first two cases, the controller atomically restores and fsyncs the
baseline before recording `invalid_scope`. No other artifact is restored or
modified. A valid targeted change remains staged even when the provider result
is incomplete.

## Certification and Receipts

Every dispatch produces a controller-owned receipt:

```yaml
unit_id: repair-...
generation: 1
attempt: 2
provider_outcome: length
before_sha256: "..."
after_sha256: "..."
scope_valid: true
gate_outcome: resolved
remaining_finding_ids: []
```

`provider_outcome` is diagnostic. `gate_outcome` controls the repair queue and
is one of:

- `resolved`: the scoped verifier proves the unit's findings are absent;
- `remaining`: the artifact is valid but one or more scoped findings remain;
- `invalid_scope`: the postimage was rejected and the baseline restored;
- `no_progress`: artifact and finding fingerprints are unchanged;
- `exhausted`: no further dispatch is allowed for the unit.

Every provider dispatch consumes an attempt, including `length`, timeout,
nonzero exit, missing result, invalid scope, and no change. Changed findings
show progress but do not reset attempts. A resolved unit is not redispatched
unless a later full gate proves that it regressed.

## Full-Gate Convergence

After the current queue generation has no pending units, the workflow reruns
its complete existing quality chain. This catches cross-element regressions and
findings outside scoped verifiers.

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

Each adapter supplies both a per-unit attempt limit and the existing outer
repair/iteration ceiling. The per-unit limit cannot increase the outer ceiling;
every atomic provider dispatch also consumes outer capacity.

The engine stops a unit early when artifact and finding fingerprints are
identical after a dispatch. Repeated provider failures cannot consume all
remaining outer capacity on a unit that produces no durable change. A changed
artifact with changed findings remains repairable only within the same unit's
attempt limit.

Queue generation count, reopened-unit count, provider outcome, token usage,
restoration events, and termination reason are observable in status and
telemetry.

## Configuration and Compatibility

The feature is disabled by default:

```yaml
harness:
  spec_repair:
    re: legacy       # legacy | shadow | atomic
    phase_a: legacy  # legacy | shadow | atomic
```

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
- RE and Phase A adapters;
- narrow prompt rendering for RE-SPECIFIER and CARTOGRAPHER.

Provider adapters continue to report raw exit, timeout, token, and finish-reason
metadata. They do not decide whether an artifact repair succeeded.

The Prosaic agent files own invariant repair behavior. Runtime workflow nodes
own context assembly, allowed outputs, and controller state contracts. The
shared Python engine owns persistence, certification, and routing outcomes.

## Verification Strategy

### Shared unit tests

- Stable parsing for RE and Phase A element syntax.
- Multiple findings grouped into one FR, NFR, AC, or scenario unit.
- Explicitly linked element groups.
- Ambiguous, duplicate, missing, and unsupported anchors rejected.
- Stable unit identity with an independently changing finding fingerprint.
- Deterministic queue ordering.
- Attempt and outer-budget accounting.
- Identical artifact/finding no-progress detection.
- Identical full-gate generation termination.

### Mutation and recovery tests

- Authorized element-only edits accepted.
- Adjacent or unrelated edits rejected and baseline restored byte-for-byte.
- Deleted IDs, duplicate IDs, malformed Markdown, and truncated files restored.
- Baseline and active dispatch persisted before provider execution.
- Restart between provider return and certification resumes the same unit.
- Restart after certification does not duplicate a receipt or redispatch.
- Recovery refuses to inspect while a provider writer may still be active.

### Provider-outcome tests

- `finish_reason=length` after a passing targeted edit resolves the unit.
- `length` without an edit records no progress.
- Missing `echelon_result` after a valid edit is controller-certified.
- Timeout and nonzero exit follow the same postimage checks after process
  termination.
- A valid model result cannot override a failing scoped verifier.
- An invalid model result cannot invalidate a passing scoped verifier.

### Workflow integration tests

- Legacy mode reproduces existing RE and Phase A routing.
- Shadow mode changes neither artifact nor route.
- In-flight states without the schema remain legacy.
- Evidence-resolution and human-decision findings bypass atomic repair.
- Unsupported SAGE-only qualitative findings retain legacy routing.
- Queue drain reruns the complete existing quality chain.
- RE exhaustion records partial-quality debt and advances per RE policy.
- Phase A exhaustion remains blocked.
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
4. Review telemetry for scope restoration, no-progress, queue regeneration,
   token use, and final-gate equivalence.
5. Enable `atomic` explicitly for selected Phase A runs.
6. Consider default changes or additional artifact types only through a later
   design backed by rollout evidence.

## Acceptance Criteria

The design is successfully implemented when:

- both workflows can opt into the same durable element-centered repair engine;
- the model never owns routing for an atomic repair node;
- a passing persisted repair can survive `finish_reason=length` or a missing
  result;
- unrelated edits are deterministically rejected and restored;
- continuation resumes the exact active or next unit;
- no-progress and exhaustion terminate without a manual retry loop;
- RE and Phase A preserve their different exhaustion policies;
- legacy is the default and existing in-flight runs behave exactly as before;
- complete existing quality gates still decide whether either workflow may
  advance.
