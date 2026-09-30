# Harness Simplification Control Design

## Purpose

Bring the RE, spec, delivery, and CLI control planes under control through a
short sequence of deletion-focused changes. Preserve Echelon's durability and
recovery guarantees while reducing the number of executable compatibility
paths and oversized orchestration surfaces.

The live status and work queue are maintained in
`docs/simplification-control.md`. This document fixes the governing design;
the control sheet records execution.

## Operating Model

Only one simplification milestone may be active at a time. A milestone is done
only when its stated exit checks pass and the control sheet links the concrete
evidence. New product behavior, new protocol versions, and opportunistic
refactors are outside this program unless they are required to complete the
active deletion safely.

Progress is measured by removing executable paths, compatibility branches,
controller responsibilities, circular dependencies, and production code. A
new abstraction counts as progress only when it immediately replaces and
removes an existing path.

## Execution Order

1. Remove retired SOAR execution while retaining shared MemPalace and graph
   utilities that are still used by active workflows.
2. Make controlled delivery the sole delivery path, then remove the opt-out
   branch and legacy build behavior.
3. Complete the Typer CLI cutover so commands call typed application services
   instead of constructing argument arrays for private functions in `cli.py`.
4. Decompose delivery orchestration into small phase handlers while preserving
   the existing state contract and observable behavior.
5. Reduce spec authoring to a recover-plan-execute-commit controller kernel,
   with phase rules expressed as typed decisions.
6. Select one current RE execution model and migrate historical runs into it at
   the boundary instead of inheriting historical controller implementations.
7. Break the remaining large import cycles and remove compatibility code made
   unreachable by the preceding cutovers.

The order is intentional. Early work removes already-retired or already-
migrated paths. Spec and RE consolidation begin only after the CLI and delivery
surfaces stop multiplying compatibility requirements.

## Preserved Guarantees

- Controller-only state mutation.
- Atomic publication and durable recovery evidence.
- Assignment-bound agent outputs.
- Immutable or authenticated input snapshots.
- Deterministic planning separated from model execution.
- Typed validation of persisted state and provider results.
- Recovery of supported active runs across process interruption.

Historical formats may be imported, but they do not need to remain executable
as independent current engines.

## Milestone Contract

Every milestone in the control sheet contains:

- a single outcome;
- exact in-scope and protected surfaces;
- objective exit checks;
- verification commands;
- evidence recorded after completion;
- a rollback boundary when behavior changes.

Statuses are `DONE`, `ACTIVE`, `BLOCKED`, and `PENDING`. There may be at most
one `ACTIVE` row. A row cannot be marked `DONE` merely because implementation
started or most tests pass.

## First Milestone Boundary

The first milestone removes SOAR/codegen execution surfaces that already fail
closed as retired. It preserves any codegen package modules demonstrably
imported by active MemPalace, graph, spec, telemetry, or delivery behavior.

The milestone starts with an import and command inventory. Deletion follows
only from that inventory. Its exit condition is that no user-facing command,
installer option, strategy loader, or active test can start SOAR execution,
while the retained shared utilities and normal spec/delivery flows pass their
focused test suites.

## Completion Condition

The program is complete when:

- one typed CLI dispatch path remains;
- one delivery execution path remains;
- spec authoring has one controller state model and one effect-commit boundary;
- RE has one current executable protocol with explicit historical import;
- retired execution packages are absent;
- no production import cycle spans more than five modules;
- the repository's focused and full verification gates pass.

