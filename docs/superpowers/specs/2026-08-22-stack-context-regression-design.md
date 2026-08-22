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

The deployed workflow declares a controller-runtime compatibility version. The
running controller requires that exact version and runs workflow validation
when the public Phase A runtime guard is called. That guard executes before
`_cmd_run` creates targets, source configuration, run state, or a provider.

The validator will also always require every Phase A node reachable from the
graph entry point to declare a valid checkpoint/rewind pair. A workflow that
lacks the version or policy coverage fails with a direct compatibility error
and a migration command, rather than entering `init` and later failing route
construction. The explicit version protects future controller/runtime changes
that are not expressible as checkpoint policy validation.

### Immutable stack contract

At fresh run initialization, the controller resolves the workspace stack
selection and stores a serializable, versioned stack contract in `state.json`.
For each effective and dependency-resolved stack it captures the immutable
semantic fields agents need: identity/version, description, archetypes,
provided capabilities, required commands/registries, approved tools, and the
verbatim, size-bounded content and digest of every referenced stack context
file. Snapshot creation fails clearly if trusted stack guidance exceeds the
defined contract budget; it must not silently truncate a constraint. The
snapshot is controller-owned run input. Continuing a run uses the existing
snapshot and never rereads mutable workspace selection or stack files as an
authority.

The shared prompt assembly adds one `Selected Stack Contract` section to every
provider-facing prompt path, including ordinary agents, sequential/parallel
agents, and controller judgment dispatches. It renders the complete snapshot,
including captured stack-context content; it never rereads current workspace
stack files while assembling a resumed prompt. It states that stack constraints
govern product shape, constitution choices,
requirements, architecture/HOW plans, implementation guidance, and tests. The
phase-specific agents retain their existing responsibilities; this shared
section supplies the same immutable constraint to all of them.

### Clarification retry context

The controller already writes resolved answers atomically to
`staging/user-clarifications.md`. Shared prompt assembly will render that
receipt into subsequent prompts when present. A retried provider can therefore
observe the exact question and answer that authorized its retry. The receipt
remains controller-owned; providers do not write it.

### Actionable input diagnostics

When `HumanInputPolicyError` is caught while preparing a provider question,
the controller maps it to a stable, allowlisted diagnostic code and records
that code in the durable controller diagnostic. It does not store the
provider's free-form raw output or interpolate provider-controlled values into
the diagnostic.

## Tests

- A workflow with a missing compatibility version or missing checkpoint/rewind
  policies fails validation even when no node declares either field.
- The public spec runtime guard rejects that invalid deployed workflow before
  target initialization, run state creation, or provider construction.
- A fresh run snapshots semantic stack contracts and verified context files; a
  continuation preserves that snapshot after workspace config changes.
- Every standard, nested/parallel, and judgment provider prompt includes the
  stack contract and resolved clarification receipt.
- Provider human-input preparation exposes an allowlisted safe policy code, while a
  valid resolved clarification makes a retry prompt contain its answer.

## Acceptance criteria

A fresh stack-selected hello-world run has the resolved semantic stack contract
in TRACKER and every later provider prompt. If TRACKER asks a clarification and
the controller resolves it, the next TRACKER prompt includes that answer. An
incompatible deployed workflow is rejected before it can initialize a target,
write run state, construct a provider, or consume provider tokens.
