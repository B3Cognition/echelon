# Perfectionist Specification Author Design

**Status:** Approved for implementation

**Date:** 2026-08-12

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
