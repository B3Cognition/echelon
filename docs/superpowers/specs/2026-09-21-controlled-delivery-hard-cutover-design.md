# Controlled Delivery Hard-Cutover Design

## Purpose

Make the Python-controlled delivery controller the only supported Phase B
implementation. Remove the feature switch and the legacy prompt-, marker-, and
shell-command-driven build paths instead of preserving another compatibility
mode.

This is milestone S2 in `docs/simplification-control.md`. It changes delivery
execution, not the durable state model or the public meaning of a delivery run.

## Decision

Perform a hard cutover. Do not retain a deprecated feature flag, a warning-only
compatibility shim, or a hidden opt-out path.

`echelon delivery run <id>` always executes controller-selected slices through
the configured model provider. Ralph owns selection, dispatch, validation,
repair, documentation, verification, review re-entry, durable operation
journals, and progress publication. Agent results remain assignment-bound data;
they do not own controller state or completion markers.

The strategy value `build_command: echelon build` remains temporarily as the
canonical strategy identifier. It is validated as data and is never executed
as a shell command. Renaming or replacing the strategy schema is outside S2.

## Removed Execution Paths

S2 removes:

- `llm.features.delivery_gate_controller` from parsing, templates, workflow
  documentation, and runtime branches;
- the feature-off path in `StrategyCoordinator` and `RalphController`;
- legacy delivery prompt resolution through `echelon.build`;
- `LlmBuildRunner` and its `.harness-build-status.json` /
  `echelon_result.json` compatibility behavior where it exists only for legacy
  model-driven builds;
- build and feedback fallback to arbitrary shell execution;
- recovery that reconstructs controlled task identity from legacy completion
  metadata;
- user-facing raw `echelon build` execution.

Historical specifications, findings, plans, and changelog entries remain
historical records. They are not rewritten merely because they describe the
removed path.

## Preserved Boundaries

The cutover preserves:

- controller-only durable state mutation;
- pending-operation recovery across interruption;
- assignment-bound and typed provider results;
- authenticated input snapshots and source-head checks;
- deterministic planning separated from model execution;
- bounded repair, documentation, verification, and review re-entry;
- polyrepo target dispatch;
- the standalone `echelon spec verify` / fulfillment command contract.

`FulfillmentRunner` therefore remains capable of its standalone verification
use. Ralph no longer selects its legacy mode.

## Runtime Flow

1. The CLI accepts `echelon delivery run <id>` and rejects raw
   `echelon build` with a migration message.
2. The coordinator validates that the selected strategy uses the canonical
   `echelon build` identifier and passes its arguments as controlled-delivery
   context.
3. Delivery preflight requires a configured model provider. A missing provider
   blocks before any delivery mutation or worktree build operation.
4. Ralph resumes a durable pending operation or selects the next deterministic
   controller step.
5. The controlled slice runner invokes exactly the assigned role, validates its
   typed result, and returns a normal `BuildResult` to the existing state
   machine.
6. Controller-owned repair, documentation, verification, and review stages
   continue until accepted, blocked, or exhausted under their existing bounds.

No step resolves `echelon.build` prose, executes the strategy string, or trusts
an agent-written completion marker.

## Failure and Recovery Semantics

A missing model provider is a configuration failure with a direct remediation
message. Provider failures and invalid typed results remain controlled operation
failures and use the existing durable attempt and recovery rules.

An already-persisted controlled operation remains resumable. Persisted legacy
build markers are not treated as authoritative delivery results. S2 does not
silently reset attempts, rewrite journals, or infer task identity from legacy
agent output.

## Compatibility Policy

The cutover intentionally breaks configurations that explicitly set
`delivery_gate_controller: false` and callers that invoke raw `echelon build`.
The supported replacement is `echelon delivery run <id>` with a configured LLM
provider.

Unknown keys under `llm.features` retain the configuration system's existing
general behavior; S2 removes only the named delivery feature and its special
validation.

## Verification

Implementation proceeds deletion-first with focused tests after each boundary:

- configuration and CLI rejection;
- coordinator prompt/context selection;
- controlled build and source-repair execution;
- continuation and pending-operation recovery;
- documentation, fulfillment, verification, and review re-entry;
- static absence of the feature flag and legacy runner/prompt imports.

After focused delivery tests pass, run the repository merge-verification gate
and record the receipt in `docs/simplification-control.md`. S2 is complete only
when the switch and feature-off execution path are absent and the supported
controller flow passes.

## Out of Scope

- Decomposing the large coordinator and Ralph methods (S4).
- Replacing the strategy schema or renaming its canonical identifier.
- Completing the Typer service cutover (S3), beyond removing raw build access.
- Consolidating spec authoring or RE protocols (S5 and S6).
- Broad cleanup of shared `BuildResult` or recovery primitives still used by
  controlled delivery.
