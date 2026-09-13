# Delivery Controller Ownership

## Problem and accepted direction

Delivery currently resolves `echelon.build`, injects Ralph context, and asks one
provider invocation to implement work and sequence review agents. The build
command mixes a bounded slice contract with legacy state-machine instructions.
Shared rendering additionally assigns COMMANDER before the command assigns
MANAGER. A missing command can degrade to bare arguments with COMMANDER framing.
Tests for review order currently inspect prose and graph declarations rather
than executing delivery's reviewer dispatch sequence.

The accepted direction is Python-owned orchestration beneath Ralph. Models
implement or review a bounded assignment; Python selects work, routes verdicts,
persists progress, and determines whether a slice is accepted.

## Staged rollout

Each phase is independently reviewable and has a passing regression gate. The
first phase is implemented separately; the remaining phases need their own
implementation plans against the resulting interfaces.

### Phase 1: explicit delivery command loading

Introduce a delivery-only resolver over the existing Prosaic loader. It accepts
the supported `echelon build` command, requires the canonical command bundle,
and uses role-neutral execution framing so the selected command supplies the
role. Missing, malformed, mismatched, or unsupported command resources raise a
typed setup error instead of returning bare arguments. Arguments remain literal
data substituted through the existing renderer. Companion assembly remains
Prosaic-owned.

The coordinator resolves the build prompt lazily, once per strategy execution,
immediately before build or repair work. Pure downstream resume/publication
must not require a build prompt. A resolution failure records a recoverable
`delivery_prompt_invalid` block in the active delivery phase, retains a concise
diagnostic, releases the state lock, and invokes no build provider.
Continue/resume recognizes this setup blocker without initiating Git recovery.
If a downstream repair needs a missing command, retain its new usage, pending
review batch, and visual/verification evidence while blocking at that phase.

Direct commands and review/fulfillment loading keep their existing framing and
dispatch behavior in this phase. Custom sandbox commands remain supported when
LLM execution is disabled. Unsupported LLM strategy commands now fail explicitly
instead of silently losing their command and executing a bare prompt.

Phase 1 does **not** enforce reviewer order or prove review completion. Keep the
existing build/gate instructions until Phase 2 has an executing replacement.

### Phase 2: Python-owned slice and gate execution

Add a focused slice executor beneath Ralph using the existing provider facade.
Resolve permitted tasks and dependencies before dispatch. Invoke IMPLEMENTER,
SPEC GUARD, CODE REVIEWER, and TEST GUARDIAN as separate bounded assignments.
Collect schema-validated results. Python controls retry limits and transitions;
agents never dispatch the next gate or update workflow state. A completion marker
alone cannot establish successful review. User-approved policy (2026-09-11):
allow the initial implementation plus at most two repair implementations per
slice. After every repair restart all three reviews. Exhaustion blocks in every
mode, including banzai; DEGRADED and skipped gates never authorize acceptance.

Bind gate evidence to task scope, source/test candidate contents, and relevant
spec inputs. Read-only reviewers may produce only declared run-local artifacts.
After an implementation repair, invalidate affected reviews before proceeding.
Keep Ralph's authoritative verification and fulfillment checks as subsequent
acceptance gates; distinguish implementation progress from verified delivery.

Acceptance: real controller tests with scripted external provider responses
observe exact dispatch order, failure/repair routing, malformed results, task
scope refusal, mutation detection, and rejection of unsupported skips. Existing
outer-loop, feedback, documentation, and containment suites must remain green.

Phase 2 is an explicit opt-in trial via `llm.features.delivery_gate_controller:
true`, not a production-default cutover before phases 3 and 4. Existing runs
remain on the old path unless enabled. The controlled path never falls back to
that old path. It requires an advertised enforced read-only provider boundary
(Claude and Codex on a supported host), and all four installed delivery-scoped
Prosaic roles. Unsupported providers block before implementation; provider
configuration is never silently changed. Separate delivery role profiles avoid
feeding legacy dispatch/state-writing recipes into the new controller.

Select one dependency-ready canonical task, constrained by the persisted target
scope. Feedback repairs the last accepted task, not the next open task. Refuse
missing/invalid scope and all-tasks-complete builds rather than silently invoking
legacy documentation orchestration; documentation-only dispatch is phase 4.
This phase writes diagnostic dispatch/results but never resumes from them or
reuses a previous review. Cross-restart receipt/retry authority remains phase 3.

### Phase 3: durable interruption and recovery

Persist the selected slice, current step, dispatch identity, candidate/input
fingerprints, completed gate receipts, and bounded retry usage using existing
atomic state primitives. Save the dispatch intent before invoking a provider and
persist validated completion before advancing. Resume reuses only matching
receipts. Unknown completion requires explicit reconciliation; it cannot be
promoted to reviewed success from provider prose or a stale status marker.

Acceptance: reconstruct the controller after interruptions before dispatch,
after provider return, and before state advancement; prove no skipped gate,
double progress application, stale evidence reuse, or retry-budget reset.

Implemented checkpoint policy: one locked atomic journal per strategy/run-scoped
operation, with a strict ordered receipt history rather than a trusted mutable
next-step or retry counter. The initial empty journal is saved before Ralph
records its operation pointer; that pointer is durable before provider intent.
The pointer requires the journal on subsequent calls. Unknown completion cannot
be reconciled from diagnostic output, even when the diagnostic looks successful.

Ralph records and reuses the original worktree before its ordinary destructive
creation path. Resuming skips Phase A copying, but compares the independently
published source binding and all candidate/spec/role fingerprints. Missing or
unsafe paths and changed source inputs block without overwriting the candidate.
After accepted task progress, retain the operation through the uncommitted
checkpoint gap; same-iteration recovery replays it idempotently. A subsequent
iteration or explicit repair can start a new operation after progress application.
Normal worktree cleanup retires its pointer; all journals remain as evidence.

Only the exact recorded DONE transformation of the selected task is allowed as
a progress-only input change after all reviews pass. Other spec/report changes
invalidate reuse. This deliberately includes controller-generated report changes
after later verification: they may require reconciliation rather than automatic
replay. A crash after normal committed-worktree cleanup but before pointer removal
also blocks on the missing candidate. These conservative availability limits do
not authorize stale approvals or reconstruction from status markers; subsequent
finalization/output ownership remains phase 4.

Cumulative provider usage is journaled; strategy state accounts only the unseen
delta, and controlled visual/review re-entry subtracts already-persisted usage.
Unknown usage remains unknown. An operation's finite ceiling can tighten, but an
ordinary restart cannot loosen it. The trial remains off by default. This phase
introduces no automatic reconciliation/reset command and does not install or run
live provider delivery; unresolved or mismatched operations require operator
inspection, not deleting a journal or retrying until it passes.

### Phase 4: entry points, finalization, and prose migration

Move documentation/finalization routing to explicit controller steps. Resolve
output ownership per step and publish validated reports through their owning
controller. Route public build entry points through the controller; a raw
provider invocation cannot masquerade as a delivery slice. Preserve supported
CLI arguments and make incompatible legacy invocations actionable errors.

Remove obsolete build orchestration recipes, invocation-environment branches,
state/journal writes, and conflicting output channels from active model prose.
Update AGENTS.md and CLAUDE.md to describe actual Python ownership. Audit active
build companions and deployed bundles, excluding historical plans/run logs.

Acceptance: direct entry, delivery entry, visual repair, review repair,
all-tasks-complete documentation repair, single-repo and external-spec delivery,
and installed bundle smoke checks. A provider must receive one role and one
step-specific output contract with no instruction-discovery dependency.

Implemented first finalization-routing checkpoint (2026-09-13): an already
completed canonical target scope and its dependency closure can hand off from
the controlled runner to Ralph's existing authoritative verification gates
without another implementation dispatch, fake task ID, or progress mutation.
Pending receipt recovery still takes precedence; only an already-applied
operation eligible for advancement can retire its pointer. A successful build
handoff is not delivery acceptance. Missing/invalid documentation still fails
its gate; documentation production and bounded repair remain unfinished.

## Rollout constraints

- Keep each phase separately testable and do not label the full issue fixed
  before controller-enforced reviews and recovery are active.
- Preserve canonical spec/task identities and existing target containment.
- Reuse Prosaic loading, provider adapters, and atomic state primitives.
- Do not change provider configuration, install dependencies, or run a live
  delivery against user projects as part of offline validation.
- Test consuming behavior at the external provider boundary; prose substring
  assertions do not prove orchestration or review completion.

## Alternatives considered

Moving conditional prose into phase Markdown reduces duplication but retains
model-owned orchestration. Replacing the whole delivery loop at once combines
dispatch, evidence, recovery, and publication risks. Incremental controller
ownership keeps each changed boundary independently observable.
