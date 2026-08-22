# Stack Context Regression Repair Design

## Problem

Two fresh `echelon spec run` invocations demonstrated incompatible runtime and
controller behavior. One run accepted a deployed workflow without the
checkpoint policies required by the controller. A subsequent run reached
`phase1-tracker`, but selected stack information and an already-resolved
clarification were absent from the retry prompt. TRACKER therefore raised the
same question again and a malformed follow-up payload produced a generic,
non-actionable controller failure after substantial token use.

## Goals

- Reject deployed workflow/controller incompatibility before a run creates
  target repositories, state, or provider work.
- Capture the resolved stack selection once at run initialization and preserve
  it for the lifetime of the run.
- Deliver that stack contract to every provider-facing Phase A, structural,
  parallel, and judgment prompt so product, constitution, requirements,
  architecture, implementation planning, and verification decisions use the
  same stack constraints.
- Deliver resolved clarification receipts to the provider retry that follows a
  clarification resolution.
- Preserve the bounded reason when provider human-input preparation fails.

## Non-goals

- Do not special-case "Hello World" or hard-code a default interface.
- Do not allow agents to mutate the selected stack contract.
- Do not change stack selection persisted in workspace configuration during a
  run.

## Design

### Runtime compatibility boundary

The workflow validator will always require every Phase A node reachable from
the graph entry point to declare a valid checkpoint/rewind pair. The CLI
runtime-loading boundary will run that validator before a spec controller is
constructed. An invalid deployed runtime fails with a direct compatibility
error rather than entering `init` and later failing route construction.

### Immutable stack contract

At fresh run initialization, the controller resolves the workspace stack
selection (explicit, effective, and dependency-resolved IDs) and stores a
serializable snapshot in `state.json`. The snapshot is controller-owned run
input. Continuing a run uses the existing snapshot and never rereads mutable
workspace selection as an authority.

The shared prompt assembly adds one `Selected Stack Contract` section to every
provider-facing prompt path. It lists the effective and resolved IDs and
states that stack constraints govern product shape, constitution choices,
requirements, architecture/HOW plans, implementation guidance, and tests.
The phase-specific agents retain their existing responsibilities; this shared
section supplies the same immutable constraint to all of them.

### Clarification retry context

The controller already writes resolved answers atomically to
`staging/user-clarifications.md`. Shared prompt assembly will render that
receipt into subsequent prompts when present. A retried provider can therefore
observe the exact question and answer that authorized its retry. The receipt
remains controller-owned; providers do not write it.

### Actionable input diagnostics

When `HumanInputPolicyError` is caught while preparing a provider question,
the controller will record its bounded validation message in the durable
controller diagnostic. It will not store the provider's free-form raw output.

## Tests

- A workflow with missing checkpoint/rewind policies fails validation even
  when no node declares either field.
- Spec runtime loading rejects that invalid deployed workflow before dispatch.
- A fresh run snapshots the stack selection; a continuation preserves it after
  workspace config changes.
- Both standard and nested/parallel provider prompt assembly include the stack
  contract and resolved clarification receipt.
- Provider human-input preparation exposes the safe policy error, while a
  valid resolved clarification makes a retry prompt contain its answer.

## Acceptance criteria

A fresh stack-selected hello-world run has the resolved stack contract in
TRACKER and every later provider prompt. If TRACKER asks a clarification and
the controller resolves it, the next TRACKER prompt includes that answer. An
incompatible deployed workflow is rejected before it can initialize a run or
consume provider tokens.
