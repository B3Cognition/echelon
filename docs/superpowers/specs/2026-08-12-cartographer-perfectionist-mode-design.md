# Cartographer Perfectionist Mode Design

**Status:** Approved for implementation

**Date:** 2026-08-12

## Goal

Allow a user to request deliberately exhaustive specification authoring without
adding another workflow agent or changing downstream Phase A contracts.

## Decision

`echelon.cartographer` remains the only agent assigned to `phase1-what` and
continues to produce the canonical `spec.md` and `requirements-overview.md`.
Cartographer gains two operating modes:

- `proportional`: the current default, producing the smallest complete
  evidence-backed specification;
- `perfectionist`: an explicit opt-in that systematically explores every
  applicable evidence-backed behavior and quality dimension.

Both modes use the same Prosaic frontmatter, model tier, effort policy, tools,
templates, result contract, quality thresholds, SAGE review, Understanding
analysis, Lexicon derivation, and downstream planning workflow.

## CLI Contract

The opt-in form is:

```bash
echelon spec run --perfectionist "<feature description>"
```

The option changes specification-authoring depth only. It does not change
autonomy, provider, model, effort, token budget, or delivery behavior.

The CLI treats the option as tri-state intent:

- a fresh run without the option persists `proportional`;
- a fresh run with the option persists `perfectionist`;
- an active run without the option inherits its persisted mode;
- an active `perfectionist` run accepts the repeated option;
- an active `proportional` run rejects the option and directs the user to start
  a new run with `--reset --perfectionist`;
- `--reset` without the option starts a new `proportional` run;
- `--reset --perfectionist` starts a new `perfectionist` run.

A prepared run that is retried before normal controller initialization retains
the mode already written to its state. Legacy active state without the field is
normalized to `proportional`.

## State Contract

Persist one controller-owned run identity field:

```json
{
  "spec_authoring_mode": "proportional"
}
```

The accepted values are exactly `proportional` and `perfectionist`. New
`SquadStateStore` state includes the field. The canonical state schema declares
its enum, and the transaction namespace reserves it from agent-authored state
updates.

Fresh Phase A preparation does not need a new bootstrap parameter: the spec CLI
resolves and writes the mode immediately after selecting the run directory and
before constructing or running `SquadController`. Prepared-state initialization
preserves it. Retarget preparation copies the normalized mode from the baseline
run so a retarget cannot silently change authoring behavior.

Continue, resume, manual phase recovery, and ordinary WHY2 or evidence loops use
the same active state and therefore need no mode flag or routing branch.

## Prompt Contract

Only `phase1-what` receives an explicit controller-authored context block:

```text
## Specification Authoring Mode
Mode: proportional|perfectionist
...
```

The block defines the selected strategy and states that common grounding,
atomicity, testability, and no-duplication rules remain mandatory. It is
assembled from trusted state by the existing `AgentExecutor`; it is not taken
from the user message or an agent update.

The compact generic state projection need not expose the mode to every other
agent. SAGE and Understanding remain strategy-neutral and judge the resulting
canonical specification against the same quality contract. They must not
reward document length, requirement count, or template population.

## Cartographer Behavior

Cartographer's common invariants apply in both modes:

- one canonical formal requirement per distinct observable obligation;
- no invented thresholds, entities, quality attributes, or product behavior;
- acceptance criteria are verification paths rather than duplicate
  obligations;
- all requirements remain technology-neutral, atomic, testable, and grounded;
- unresolved facts remain explicit rather than guessed.

In `proportional` mode, Cartographer retains its current complexity-sensitive
behavior and omits unsupported optional depth.

In `perfectionist` mode, Cartographer performs a systematic applicability
review before writing. It explores every evidence-backed dimension that could
materially change the contract:

- actors and independently meaningful goals;
- happy, alternate, invalid, failure, boundary, and recovery paths;
- inputs, outputs, invariants, state transitions, and lifecycle behavior;
- integrations, ownership boundaries, and externally observable failures;
- security, privacy, performance, reliability, accessibility, operability,
  compatibility, compliance, and data-governance constraints;
- assumptions, unknowns, conflicting evidence, and unresolved decisions;
- MVP, post-MVP, and explicitly excluded scope;
- acceptance-to-requirement and product-input traceability.

An inapplicable dimension produces no fabricated requirement. Insufficient
evidence becomes an open question, assumption, or evidence request using the
existing contracts. Perfectionist may split genuine compound obligations into
atomic requirements and add materially distinct verification paths, but may not
restate one obligation to make the document longer.

The current Cartographer specification and overview templates remain canonical.
No mode-specific template or coverage artifact is introduced in this slice.

## Presentation

The spec-run banner shows the resolved authoring mode so users can verify what
will run. Help and README command documentation include `--perfectionist` and
describe it as exhaustive Cartographer authoring.

## Compatibility

- Existing workspaces and active state without the new field behave exactly as
  `proportional`.
- The workflow graph still names only `echelon.cartographer`.
- Agent frontmatter and provider routing are unchanged.
- Existing spec artifacts require no migration.
- Existing SAGE, Understanding, Lexicon, plan, and task behavior receives the
  same artifact shapes.

## Verification

Automated tests must prove:

- mode normalization and invalid-value rejection;
- fresh, active, repeated, reset, prepared-retry, legacy, and retarget mode
  semantics;
- controller ownership of `spec_authoring_mode`;
- new squad state defaults to `proportional`;
- only WHAT prompt assembly receives the explicit mode block;
- proportional and perfectionist blocks contain their distinct strategy;
- Cartographer prose preserves common invariants and defines both modes;
- the graph still dispatches `echelon.cartographer`;
- CLI help and README expose the opt-in accurately.

Focused tests are followed by the existing Cartographer, Phase A, CLI, state,
retarget, package-install, and runtime-deployment suites. A later live paired
benchmark may compare the two modes on the same request, but live-provider
output is not a merge gate for this controller-safe implementation.

## Non-Goals

This work does not add `echelon.perfectionist`, dynamic graph agents,
mode-specific SAGE thresholds, a new specification schema, a second template,
an exact legacy-output reproduction mode, or automatic model and effort
changes.
