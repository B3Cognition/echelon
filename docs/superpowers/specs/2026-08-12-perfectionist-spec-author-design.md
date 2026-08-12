# Perfectionist Specification Author Design

**Status:** Deferred exploration — do not implement

**Date:** 2026-08-12

## Current Decision

Do not implement Perfectionist as a separate dynamically selected Prosaic
subagent in the current migration. The proposal below is retained as an
architecture note for future brainstorming, not as an approved implementation
contract.

The near-term direction is deliberately smaller: keep
`echelon.cartographer` as the only `phase1-what` author and consider an
opt-in `perfectionist` operating mode inside that agent. That alternative needs
its own reviewed design before implementation. This document does not approve
or specify it.

The separate-agent concept remains interesting because a distinct role could
eventually provide a genuinely different requirements-engineering discipline,
independent calibration, its own model policy, and explicit comparative
telemetry. We are deferring it because Echelon does not currently have a
first-class abstraction for interchangeable agents occupying one graph node.
Adding Perfectionist now would therefore be a controller refactor disguised as
a prose feature.

## Why This Was Deferred

The initial proposal assumed that selecting a second Markdown agent would be a
local change. Review of the current runtime showed that the static
`PhaseNode.agent` identity is consumed transitively throughout the system:

- prompt body and frontmatter loading;
- provider model, effort, tools, and color metadata;
- context-budget policy and reports;
- calibration and belief-register lookup;
- telemetry dispatch identity and attempt history;
- role-contract and routed-agent validation;
- journal-entry authorization;
- blocker and human-resolution messages;
- phase labels and CLI presentation;
- retry, resume, amendment, and output-recovery behavior.

The author of `spec.md` also affects later agents. SAGE reviews the author's
work, Understanding certifies it, Lexicon derives from it, and Architect and
Orchestrator consume it. A new authoring strategy therefore cannot be treated
as an isolated prompt substitution unless the downstream contract explicitly
defines which effects are strategy-neutral and which must vary.

Implementing only the visible dispatch change would risk mixed identity: for
example, loading Perfectionist prose while using Cartographer metadata,
calibration, telemetry, journal permissions, or recovery instructions. A broad
change replacing every direct `node.agent` read would be difficult to audit and
would enlarge the active Prosaic migration with unrelated controller risk.

## Identified Ambiguities And Concerns

### 1. Dynamic Agent Resolution Has No Single Boundary

The proposal introduced `agent_variants` and an effective-agent resolver, but
did not define where resolution becomes authoritative. If every consumer calls
the resolver independently, one missed call creates inconsistent behavior. If
the controller materializes an effective node, its lifetime, immutability, and
relationship to the canonical graph must be specified.

Before revisiting the design, Echelon would need a general routed-role
abstraction that resolves an agent exactly once and supplies the same resolved
identity to prompt assembly, provider policy, telemetry, validation, recovery,
and presentation.

### 2. The Workflow Graph Is Currently Static

`runtime/workflow/definition.yaml` declares one agent per ordinary agent node.
Conditional and staged nodes exist, but their semantics are dispatch sequences,
not interchangeable implementations of one role contract. Reusing those types
for Perfectionist would either create a second workflow branch or run both
authors, neither of which matches the desired behavior.

Future work must decide whether interchangeable role implementations are a
general graph feature worth supporting beyond this one use case. A one-off
`phase1-what` special case is not acceptable for the separate-agent design.

### 3. Shared Prompt Composition And Validation Disagree

The proposal moved stable authoring rules into a Markdown companion. Runtime
prompt loading recursively expands companions, but routed-role validation
currently inspects the raw agent file. Moving required `echelon_result`, output,
or state-update contracts exclusively into a companion could therefore make a
valid composed prompt fail static validation, or make an incomplete raw prompt
appear valid only at execution time.

We need to decide whether role contracts are validated from raw source or the
fully composed Prosaic artifact. Until that decision is made, controller,
evidence-routing, and result-shape rules should remain explicit in the phase
contract and in every independently validated agent where required.

### 4. Exhaustive Coverage Was Not Machine-Defined

The proposal said that Perfectionist reviews all applicable dimensions while
omitting irrelevant ones. That leaves no observable distinction between
"reviewed and not applicable" and "forgotten." SAGE cannot enforce an
exhaustive promise without receiving both the selected strategy and a
machine-inspectable coverage record.

A future Perfectionist likely needs a coverage matrix with stable dimensions
and dispositions such as `covered`, `not_applicable`, and `unresolved`, plus
evidence and mapped requirement IDs. We must still determine whether that
matrix belongs in `requirements-overview.md`, a separate supporting artifact,
or controller state. It must not become a second requirements source of truth.

### 5. Downstream Quality Semantics Are Unclear

SAGE and Understanding should not reward length, requirement count, or template
population. It remains unclear whether they should validate different coverage
expectations for Cartographer and Perfectionist or apply one strategy-neutral
definition of specification quality.

If SAGE becomes strategy-aware, the author selection must be injected into its
context and preserved through WHY2 and WHY3. That creates a transitive behavior
change requiring its own tests. If SAGE remains strategy-neutral, Perfectionist
is only a best-effort authoring style and Echelon cannot claim that exhaustive
coverage was certified.

### 6. Template Ownership Was Incomplete

The proposal named a Perfectionist specification template but placed its
coverage record in `requirements-overview.md` without defining a matching
overview template. Current WHAT execution supplies a concrete specification
and overview template pair. Literal Markdown references are recursively
inlined, so referencing both author pairs could accidentally expose competing
templates to the model.

A future design must select exactly one complete template pair and prove that
the assembled prompt contains no instructions from the unselected strategy.

### 7. Run Selection Semantics Were Underspecified

The proposal made `spec_author` both required and optional for legacy state. It
also did not distinguish an omitted CLI option from an explicit request for
Cartographer. Those distinctions matter during resume, reset, retarget, manual
recovery, and sealed human-decision flows.

Any future design must define tri-state CLI intent and immutable run behavior:

- omitted on a fresh run selects the default;
- omitted on an active run inherits the persisted selection;
- an explicit conflicting selection is rejected unless a new run is created;
- every recovery path preserves the same selection;
- old state has one deterministic normalization rule.

The selected author must be controller-owned run identity and unavailable to
agent-authored state updates.

### 8. Existing Cartographer-Specific Names Would Leak

Runtime prose, graph labels, calibration context, journal registries, recovery
markers such as `cartographer_resume_existing_spec`, tests, and diagnostics
still name Cartographer directly. Some names represent true role identity;
others actually mean "the specification author."

A future separate-agent implementation would first need an inventory and a
careful naming migration with compatibility handling. Renaming these during the
current Speckit-to-Prosaic migration would combine two refactors and obscure
regressions.

### 9. Provider Metadata And Calibration Policy Are Undefined

A separate agent has independent Prosaic frontmatter, but the desired policy is
not settled. It could intentionally share Cartographer's `model_tier`, effort,
tools, and color, or eventually request a stronger model and different effort.
Calibration and belief registers might be shared by role or separated by
agent. Either choice changes how performance comparisons should be interpreted.

The first implementation must not silently give Perfectionist a stronger model
and then attribute output differences solely to authoring strategy.

### 10. Historical Reproduction Is Not Yet A Stable Product Contract

The original oversized Hello World artifacts exist in the retained test
workspace and their metrics are recorded in findings, but the repository does
not currently contain a complete sanitized fixture set. The exact old output
was also emergent from its prompt, templates, provider behavior, and quality
loops rather than a named mode.

Before claiming historical equivalence, retain a repository-owned benchmark
fixture and decide whether the goal is exact old behavior or a new
evidence-backed exhaustive discipline. These are different products. Exact
legacy behavior should remain test-only unless there is a compelling use case
for its known duplication and unsupported obligations.

## What Remains Attractive About A Separate Agent

The idea should not be discarded. A separate Perfectionist could become the
right design if Echelon later supports interchangeable role implementations as
a first-class concept. It would offer:

- a clean and recognizable requirements-engineering persona;
- independent Prosaic metadata, calibration, and performance history;
- stronger isolation between proportional and exhaustive instructions;
- explicit A/B comparison in telemetry;
- room for genuinely different methods rather than a growing conditional
  Cartographer prompt;
- future selection of authoring specialists based on domain or governance
  needs.

Those benefits become compelling when more than one workflow role needs
pluggable implementations, or when Perfectionist's method diverges enough that
one Cartographer prompt becomes difficult to understand and test.

## Conditions For Reconsideration

Reopen the separate-agent design when at least one of these is true:

- Echelon needs interchangeable implementations for multiple workflow roles;
- Cartographer's operating modes have accumulated conflicting instructions or
  cannot be independently evaluated;
- regulated or high-consequence work requires certified exhaustive coverage;
- provider/model policy must differ by authoring discipline;
- comparative telemetry and calibration need distinct agent identities;
- a second specification author besides Perfectionist is proposed, making a
  general abstraction clearly worthwhile.

Before implementation, the following foundations should exist or be designed
together:

1. One authoritative role-resolution boundary.
2. A graph schema for interchangeable role implementations.
3. Composed-prompt role-contract validation.
4. Controller-owned immutable strategy selection.
5. A coverage artifact and explicit certification semantics.
6. Strategy-aware or explicitly strategy-neutral downstream contracts.
7. Complete template-pair selection without prompt contamination.
8. Provider, model, effort, calibration, and belief-register policy.
9. Repository-owned legacy and current benchmark fixtures.
10. End-to-end tests for fresh run, retries, evidence routing, WHY repairs,
    resume, retarget, manual recovery, telemetry, and packaging.

## Future Brainstorming Questions

When this topic returns, start with these questions rather than assuming the
original proposal:

1. Is Perfectionist a different agent, an authoring mode, a prompt overlay, or
   a second-pass reviewer?
2. Does it create the initial specification, enrich an existing proportional
   specification, or produce an independent comparison artifact?
3. What observable contract makes a specification "perfectionist" without
   using size or count targets?
4. Which coverage dimensions are universal, domain-specific, optional, or
   constitution-derived?
5. Should SAGE certify exhaustive coverage, or only ordinary specification
   quality?
6. Is the desired comparison exact legacy reproduction or a new exhaustive but
   non-duplicative method?
7. Can both strategies produce the same canonical `spec.md`, or should a
   comparison run preserve two candidate artifacts before one is selected?
8. How are cost, duration, quality, distinct obligations, unsupported claims,
   and downstream task inflation compared fairly?
9. Should Perfectionist share Cartographer's model and effort for controlled
   experiments, or use an intentionally stronger execution profile?
10. Is interchangeable role resolution valuable enough elsewhere in Echelon to
    justify the controller abstraction?

## Safe Experimental Path

Before introducing dynamic graph routing, the separate prose can be explored
outside production execution:

1. Preserve a sanitized legacy Hello World artifact set as a fixture.
2. Draft `echelon.perfectionist.md` in an experimental or test-only location.
3. Render it directly through Prosaic and run it against copied discovery
   context in an isolated workspace.
4. Compare its output to current Cartographer using deterministic structural
   measurements and independent review.
5. Repeat on small, moderate, and genuinely complex requests.
6. Use the evidence to decide whether operating mode, overlay, reviewer, or
   separate agent is the right production abstraction.

This path tests the product idea without changing Echelon's workflow graph or
active controller behavior.

## Goal

Add an explicit exhaustive specification-authoring option without weakening
Cartographer's proportional default or creating a second Phase A workflow.

Users can select Perfectionist when they deliberately want a broad, highly
detailed specification for comparison, governance, or a consequential feature.
The resulting artifacts remain compatible with the existing Understanding,
SAGE, planning, task, and delivery pipeline.

## Decision

Perfectionist is a separate Prosaic subagent that can occupy the existing
`phase1-what` specification-author slot:

```text
phase1-what
    spec_author=cartographer  -> echelon.cartographer
    spec_author=perfectionist -> echelon.perfectionist
```

Cartographer remains the default. Perfectionist replaces Cartographer for the
entire run, including WHY2 amendments, evidence-resolution returns, retries,
resume, and manual recovery. The two agents are never dispatched sequentially
for the same WHAT pass.

Perfectionist restores the useful intent of the pre-proportional Cartographer:
systematic treatment of actors, workflows, alternate and failure paths,
boundaries, lifecycle states, uncertainty, risks, entities, scope horizons,
quality attributes, and traceability. It does not restore accidental duplicate
obligations, fabricated facts, score-directed filler, or obsolete controller
behavior.

## CLI Contract

The public opt-in is:

```bash
echelon spec run --perfectionist "<feature description>"
```

Without the flag, a fresh run persists `spec_author: cartographer`. With the
flag, it persists `spec_author: perfectionist`.

The selection is immutable for an active run. Resume and continue commands use
the persisted value and require no repeated flag. Re-running the same active
request with a conflicting author selection is rejected with guidance to use
`--reset`; a reset starts a new run with the newly requested selection.

`--perfectionist` controls specification depth only. It does not imply an
autonomy mode, provider, model tier, reasoning-effort override, token budget,
or implementation profile.

## Run-State Contract

Add the required run-state field:

```json
{
  "spec_author": "cartographer"
}
```

Accepted values are `cartographer` and `perfectionist`. Fresh state creation,
prepared Phase A identity preservation, checkpoint/resume, retarget recovery,
and state validation retain this field. Legacy active states that lack the
field normalize to `cartographer` so existing workspaces remain usable.

The resolved dispatch ID is recorded normally in `last_dispatch`, telemetry,
and journal data. `spec_author` records user intent; it is not rewritten from
the last-dispatch record.

## Phase-Graph Selection

Keep one `phase1-what` node and add a general state-selected agent declaration:

```yaml
agent: echelon.cartographer
agent_variants:
  state_key: spec_author
  mapping:
    cartographer: echelon.cartographer
    perfectionist: echelon.perfectionist
```

`agent` remains the default for compatibility and structural tooling. The phase
graph validates the selector shape, every mapped value, and every referenced
Prosaic subagent during graph loading.

A single resolver on `PhaseNode` returns the effective agent for a supplied
state. Prompt assembly, dispatch, calibration lookup, context budgeting,
telemetry, role-contract validation, and last-dispatch recording must use that
resolver. No caller special-cases `phase1-what` or the Perfectionist name.

An absent state value selects the static default. An invalid persisted value is
a state-validation error rather than a silent fallback.

## Prosaic Authoring Contract

Add:

```text
prosaic/subagents/echelon.perfectionist.md
```

Both specification authors share a companion resource containing their stable
contract:

```text
prosaic/subagents/appendices/spec-authoring-contract.md
```

The companion owns common rules for:

- technology-neutral requirements;
- controller-owned Phase A identity and validation;
- artifact mutation boundaries;
- requirement IDs and machine-recognizable syntax;
- evidence grounding and cross-references;
- Product Input Contract dispositions;
- `spec.md`, `requirements-overview.md`, and `echelon_result` expectations;
- one canonical formal requirement per distinct product obligation.

Cartographer and Perfectionist reference the companion through the existing
Markdown companion loader. Their own prose contains only role identity,
authoring strategy, and strategy-specific process. This avoids copying a large
prompt and allowing operational rules to drift.

## Authoring Strategies

### Cartographer

Cartographer keeps the current proportional behavior:

- classify the discovered feature's inherent complexity;
- include only materially distinct behavior and evidence-backed constraints;
- omit unsupported optional sections and categories;
- produce the smallest complete specification regardless of requested prose
  volume.

### Perfectionist

Perfectionist performs an explicit coverage inventory before authoring and then
works through every applicable dimension:

- actors and independently meaningful goals;
- happy, alternate, invalid, failure, recovery, and boundary paths;
- inputs, outputs, state transitions, invariants, and lifecycle behavior;
- integrations, ownership boundaries, and externally observable failures;
- security, privacy, performance, reliability, accessibility, operability,
  compatibility, compliance, and data-governance constraints;
- assumptions, unknowns, conflicting evidence, and unresolved decisions;
- MVP, post-MVP, and explicitly excluded scope;
- acceptance-to-requirement and source-input traceability.

Every dimension receives an evidence-based disposition: represented when it is
applicable, explicitly identified as unresolved when evidence is insufficient,
or omitted when it is genuinely irrelevant. Perfectionist may split compound
behavior into more atomic requirements and verification paths, but it may not
repeat one observable obligation under several labels or invent thresholds and
product behavior.

## Template Strategy

Cartographer continues using the conditional proportional template:

```text
prosaic/agents/exploration/templates/cartographer-spec-template.md
```

Perfectionist receives a dedicated full-depth template:

```text
prosaic/agents/exploration/templates/perfectionist-spec-template.md
```

The Perfectionist template is derived from the useful coverage structure that
predated commit `da83a238`, then aligned with the current machine-recognizable
requirement syntax and one-obligation rule. It keeps the same canonical
top-level artifact concepts and requirement IDs, so all downstream analyzers
and agents consume either specification without branching.

The template requires a coverage review inside `requirements-overview.md`.
That review records which applicable dimensions were represented and which
remain unresolved. It is supporting evidence, not another source of product
requirements.

## Runtime Phase Prose

Neutralize `runtime/workflow/phases/phase1-what.md` from Cartographer-specific
language to the selected specification author. The phase prose continues to own
context assembly, state-update requirements, evidence routing, controller
boundaries, and artifact existence checks.

Strategy-specific authoring instructions remain in the selected Prosaic
subagent. The phase prose must not restate proportional or exhaustive policy,
because that would make one strategy leak into the other.

SAGE and deterministic Understanding remain common gates. SAGE receives the
persisted author selection as context so it can verify the promised coverage
without rewarding document length or requirement count.

## Historical Comparison

The retained oversized Hello World artifacts remain the legacy behavior
baseline. The pre-`da83a238` Cartographer prose and template are historical
references, not a third production agent.

A comparison run should evaluate:

- distinct product obligations and their traceability;
- applicable path and quality-attribute coverage;
- duplicated or unsupported requirements;
- Understanding and SAGE results;
- specification, plan, task, token, duration, and cost size;
- downstream implementation usefulness.

Line count and requirement count are reported as observations, never treated as
quality targets.

## Failure Handling

- Missing Perfectionist prose or template fails package/runtime validation
  before dispatch.
- An unknown `spec_author` fails state validation with the accepted values.
- Changing author on an active run requires `--reset` and never silently mixes
  authoring strategies.
- WHY2 repair, evidence resolution, and resume always resolve the author from
  persisted state.
- A malformed `agent_variants` declaration fails phase-graph construction.
- Provider or model selection errors retain their existing behavior because
  specification-author selection does not alter provider policy.

## Verification

Focused tests will cover:

- CLI parsing and active-run immutability for `--perfectionist`;
- fresh, resumed, reset, and legacy state behavior;
- phase-graph validation and effective-agent resolution;
- prompt assembly selecting exactly one specification author;
- calibration, telemetry, journal, and last-dispatch use of the resolved agent;
- recursive resolution of the shared companion and both templates;
- package installation of all new Prosaic artifacts;
- static Cartographer proportionality and Perfectionist exhaustive-coverage
  contracts;
- unchanged output and state-update contracts for `phase1-what`;
- default runs continuing to dispatch Cartographer;
- a live paired benchmark using the same request and isolated run directories.

## Non-Goals

This work does not add another workflow, run both authors in sequence, change
the specification schema consumed downstream, alter quality thresholds, select
a stronger model automatically, or expose the exact historical prompt as a
supported production mode.
