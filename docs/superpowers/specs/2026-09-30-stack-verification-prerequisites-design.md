# Stack and verification prerequisites

Status: design and implementation plan approved; implementation in progress.

## Outcome and boundaries

Echelon must discover an unsupported verification contract before it spends a
Delivery run implementing the product. Require an explicit stack choice for
Spec entry and sufficient verification capabilities before declaring a spec
ready for Delivery. Recheck those capabilities at Delivery admission.

This extends existing stack resolution, preflight and readiness code. It adds
no coordinator, agent, workflow engine, parallel journal, CLI recovery rule or
candidate-specific exception. S6/S7 remain parked. Generated product code,
planning coverage statuses, live run state and review gates are not manually
changed. No old-run migration or reset is part of this work.

The already implemented missing-observer guard in `CandidateEvidenceRunner`
remains the final defensive check; it is not a substitute for early admission.

## Evidence and existing owners

- `stacks/context.py` currently returns no context for an empty selection.
- `verification_stack_runtime.py` resolves source-local selection when a source
  has its own Echelon configuration, otherwise workspace selection.
- `stacks/loader.py` already supports bundled and workspace-owned local stacks.
- `stacks/preflight.py` already checks required observers against planned test
  types; optional observers do not satisfy mandatory coverage.
- `phase_a_readiness.py` checks artifacts and coverage integrity, but does not
  currently validate resolved target verification capabilities.
- `spec_service.py`, `squad.py`, and `delivery_service.py` consume readiness.
  Their rendered summaries must not disagree with publication/admission.

The latest acceptance candidate passed ordinary verification, but an empty
selection disabled structured observers. Fulfillment consequently classified
54 requirements using their old planning statuses. A stack name alone would
not prevent this: its capabilities must satisfy the actual spec.

## Policy

### 1. Spec entry: explicit intent

Before a new Spec run dispatches a provider, require a valid explicit stack
selection in authoritative owner configuration. Existing stack commands remain
the way to select it; do not introduce a second selection store or flag.

Empty selection produces an actionable `stack_selection_required` prerequisite.
Unknown IDs, conflicts and malformed configuration retain the existing resolver
errors. Detection may recommend stacks but never silently selects one.

Add a bundled `generic` policy stack using the existing schema. It declares no
framework, package manager, observer, runtime guarantee or implicit exemption.
Selecting it means technology is undecided and authorizes Spec discovery only.
Do not make it an implicit default in workspace configuration.

Before targets are known, workspace selection governs discovery. Once targets
are known, apply the existing source-local-over-workspace ownership rule to
each target. A source-owned empty selection must not fall back silently.

### 2. Readiness: concrete capability coverage

Before a Spec run may publish a ready-for-Delivery outcome, validate the resolved
contract for each declared target against its active obligations:

- Every planned test type has a compatible required structured observer.
- Required browser/runnability obligations have a supported runner and declared
  execution capabilities.
- A required semantic visual verdict has the existing supported visual phase
  and validator execution configuration; merely capturing screenshots is not
  enough.
- Unsupported runners, malformed contracts, missing capabilities and ambiguous
  target ownership produce explicit prerequisites, never a passing result.

Use canonical coverage parsing, owner-controlled deferrals and existing target
task ownership. Do not demand that every target support other targets' tests.
Conversely, unresolved ownership must not make an obligation disappear.

This is a static capability check, not execution proof: greenfield test files,
application services and candidate verification scripts need not exist yet.
Actual commands, structured reports and acceptance evidence are still checked
during Delivery in the supported sandbox. Do not run product commands on the
host to prove planning readiness.

`generic` alone cannot satisfy Delivery readiness, including an apparently empty
coverage map. The owner must replace it with a concrete/custom stack or compose
it with concrete capability stacks that satisfy all obligations. In the latter
case `generic` remains a neutral marker and grants no capabilities. Explicitly
non-runnable work still needs a concrete contract declaring that disposition;
generic must not classify an unknown product as non-runnable by default.

### 3. Delivery admission: same contract, current inputs

After resolving targets and before dispatching an implementer, apply the same
capability check to authoritative owner configuration and the published spec.
Do not trust a stale ready status or the existence of a stack name. Validate all
targets before launching a multi-target Delivery so an unsupported sibling does
not cause partial dispatch.

Missing capability is an owner/configuration prerequisite, not a source defect.
Report the target, missing selection/capability and corrective action. Do not
dispatch a product repair agent, spend meaningful repair attempts, alter limits,
rewrite coverage-map.md or automatically choose a framework.

Admission belongs to shared harness helpers and their existing controllers;
application services forward inputs and render outcomes. Direct controller and
service entry points must not differ. CLI wrappers gain no policy of their own.

Native continuation remains responsible for journal recovery. Resolve pending
effects under their sealed inputs; never reinterpret an in-flight dispatch
under a newly selected stack. At the next safe dispatch boundary, revalidate
the current owner contract and let existing fingerprint/receipt validation
invalidate mismatched evidence. Do not add an unknown-dispatch reconciliation
shortcut or edit the paused acceptance run to retrofit selection.

## Integration shape

Extend the existing stack verification/preflight helpers with one deterministic
capability evaluation consumed by Spec readiness and Delivery admission. Keep
artifact-only readiness checks available for structural validation, but require
explicit authoritative project/target context at production ready/publication
and admission boundaries. Missing context at those boundaries is an error, not
permission to skip capability checks.

Reuse the same resolved stack contract for prompts and execution. Candidate
worktrees and provider output cannot select, disable or replace owner observers.
The owner can use the existing project-local stack mechanism for a custom stack;
supporting npm/Three.js must not force React or pnpm just to obtain observers.

Approved schema adjustment: policy stacks may declare empty capability and
archetype lists. An empty policy archetype list means unrestricted applicability,
not an inferred application type. Other stack kinds retain non-empty requirements;
explicitly scoped policies still enforce their declared archetypes. No new schema
fields or synthetic capabilities are introduced.

A compatible npm/Three.js observer bundle
is separate follow-up work, tested against the preserved candidate before use.
This prerequisite change does not claim to solve visual gate ordering or
requirement-level fulfillment repair routing; both remain explicit work items.

## Incremental verification

Implement and verify one increment before starting the next:

1. Explicit Spec selection and the capability-free generic stack. Test empty,
   generic, concrete, unknown and conflicting selections at actual dispatch
   boundaries; failed admission must make no provider call.
2. Shared target-aware readiness evaluation. Test generic-only rejection,
   compatible custom stacks, optional-only/missing observers, owner deferrals,
   unsupported runtime/visual capabilities and greenfield inputs with no code.
3. Wire publication and Delivery admission to that evaluation. Test direct and
   service entry points, source ownership, multi-target all-or-nothing admission,
   configuration drift and pending-effect preservation.

For each increment: failing regression first, focused tests including its real
consumer boundary, and a disposable functional probe. Record repository-suite
failures separately; do not hide the known convergence fixture failure.

Acceptance requires a disposable Spec-to-Delivery admission flow showing that
generic permits discovery, missing capabilities prevent readiness/dispatch,
and a compatible concrete contract permits implementation to begin. This does
not require reimplementing all twelve acceptance tasks. Full product acceptance
still requires the later execution-evidence, visual and repair-flow work.

## Alternatives considered

- Keep stacks optional and rely only on the final evidence gate: catches the
  error too late and repeats the observed wasted implementation effort.
- Require a named concrete stack before discovery: prevents unconfigured runs
  but unnecessarily forces technology before requirements are understood.
- Explicit generic for discovery plus capability-complete readiness/admission:
  chosen; preserves discovery while refusing unsupported Delivery.
