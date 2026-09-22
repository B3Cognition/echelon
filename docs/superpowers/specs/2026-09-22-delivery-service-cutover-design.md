# Delivery Service Cutover Design

## Purpose

Complete the active Delivery slice of S3 by moving the remaining user-facing
Delivery workflows behind a typed application service. The cutover removes
active Delivery command ownership from `echelon.cli` without changing the
controlled-delivery state contract, orchestration behavior, output, or exit
codes.

This is an ownership change, not the S4 Delivery controller decomposition.

## Scope

The cutover covers these active routes:

- `echelon delivery init`
- `echelon delivery target`
- `echelon delivery verify-local`
- `echelon delivery cleanup-local`
- `echelon delivery run`
- `echelon delivery resume`
- `echelon delivery continue`
- `echelon delivery land`
- `echelon delivery checkpoint list`

`echelon delivery status` already has a typed Typer boundary in
`echelon.delivery_status`, but its implementation still imports Delivery
rendering and recovery helpers from `echelon.cli`. Those helpers move with the
rest of the Delivery kernel so the status service no longer depends on legacy
Delivery ownership.

The hidden `harness` routes and root Delivery compatibility aliases continue to
forward to canonical Typer commands. They do not receive another execution
implementation.

## Non-goals

- Do not redesign `RalphController`, `StrategyCoordinator`, delivery state, or
  recovery semantics.
- Do not split the Delivery kernel into init, execution, recovery, and landing
  subsystems. That decomposition belongs to S4.
- Do not change persisted schemas, state paths, leases, checkpoint formats,
  sandbox authority, target dispatch, publication, or landing behavior.
- Do not change provider capability rules, console text, or exit codes.
- Do not introduce a generic command bus, facade hierarchy, or third dispatch
  layer.
- Do not modify RE behavior while moving the Delivery slice.

## Chosen Architecture

Create `src/echelon/delivery_service.py` as the application-service owner for
active Delivery commands and their reachable Delivery-only helpers.

`src/echelon/cli_app.py` remains responsible for Typer declarations and parsing.
It constructs immutable request values and calls `delivery_service` directly.
Declared Typer values are never reconstructed into a full legacy argument
vector. Undeclared compatibility arguments may remain `tuple[str, ...>` and are
adapted only inside the service.

The existing Delivery kernel moves mechanically from `echelon.cli`. Branches,
mutation order, lock acquisition, target dispatch, error messages, and
controller calls remain unchanged. Private adapters may translate typed requests
into the existing internal parser shape while the kernel remains intact.

`src/echelon/delivery_status.py` remains the public status command module. Its
explicit helper imports change from `echelon.cli` to
`echelon.delivery_service`.

Two helpers remain in `echelon.cli` because they still have non-Delivery
consumers:

- `_iter_harness_build_states`
- `_load_cli_config`

`delivery_service` may import those two names narrowly. If a retained helper
calls a relocated Delivery-only helper, it must use a narrow local import rather
than retaining a duplicate implementation.

## Typed Interfaces

The service exposes immutable requests for commands with multiple declared
values:

```python
@dataclass(frozen=True)
class DeliveryRunRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    mode: str | None = None
    strategy: str | None = None
    max_outer: int | None = None
    max_inner: int | None = None
    token_budget: int | None = None
    auto_merge: bool | None = None
    kill_losers: bool = False
    reset: bool = False


@dataclass(frozen=True)
class DeliveryRecoveryRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    answer: str | None = None
    mode: str | None = None
    strategy: str | None = None


@dataclass(frozen=True)
class DeliveryLandRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    continue_existing: bool = False
    prepare_only: bool = False
    autoresolve: bool = True
    allow_fulfillment_gaps: bool = False
    strategy: str | None = None


@dataclass(frozen=True)
class LocalVerificationRequest:
    spec_id: str
    target_id: str | None = None
    engine: str = "auto"
    assume_yes: bool = False
    keep_on_failure: bool = False
```

Public entry points are:

```python
initialize_delivery(project_root: Path, *, extra_args: Sequence[str] = ()) -> None
prepare_target(project_root: Path, *, spec_id: str) -> None
verify_local(project_root: Path, request: LocalVerificationRequest) -> None
cleanup_local(project_root: Path, *, local_run_id: str) -> None
run_delivery(project_root: Path, request: DeliveryRunRequest) -> None
resume_delivery(project_root: Path, request: DeliveryRecoveryRequest) -> None
continue_delivery(project_root: Path, request: DeliveryRecoveryRequest) -> None
land_delivery(project_root: Path, request: DeliveryLandRequest) -> None
list_checkpoints(
    project_root: Path,
    *,
    spec_id: str,
    strategy: str | None,
    extra_args: Sequence[str] = (),
) -> None
```

`DeliveryRecoveryRequest.answer` is used by resume and must be `None` for
continue. The service rejects an answer supplied to continue rather than
silently changing command meaning.

## Ownership and Dependency Rules

The mechanically moved closure includes Delivery initialization, target
preparation, run setup, multi-target dispatch, checkpoint recovery, resume and
continue handling, local verification, landing, and Delivery status rendering.
Delivery-specific constants and dataclasses move with their functions.

After the cutover:

- active Delivery Typer functions do not import `echelon.cli`;
- `echelon.delivery_status` does not import `echelon.cli`;
- `echelon.cli` does not define the nine moved command handlers;
- compatibility routes call canonical Typer routes, not relocated private
  handlers;
- no forwarding aliases for removed handlers remain in `echelon.cli`.

Tests that directly exercise private Delivery behavior import the new owner.
Tests for generic helpers that remain in `echelon.cli` keep their existing
imports.

## Behavior Preservation

The move preserves:

- controlled-delivery feature and state contracts;
- workspace and target Git preflight behavior;
- single-target and multi-target dispatch;
- sandbox, mirror, and runtime preparation;
- provider capability checks;
- run, resume, continue, and outer-cap recovery semantics;
- local verification consent, journal, cleanup, and non-authoritative evidence;
- checkpoint discovery and rendering;
- landing preparation, conflict handling, fulfillment checks, cleanup, and
  archive behavior;
- existing stdout, stderr, and `SystemExit` contracts.

No compatibility argument is dropped. Declared options are represented once in
typed requests; only unknown legacy arguments are retained as ordered tuples.

## Testing Strategy

Add `tests/unit/test_delivery_service_boundary.py` with:

- typed Typer-routing assertions for all nine routes;
- equality checks for each immutable request object;
- an AST-scoped guard proving active Delivery functions and
  `delivery_status.py` do not import `echelon.cli`;
- an AST guard proving the removed handlers are absent from `echelon.cli`.

Migrate direct imports and monkeypatch targets in the existing Delivery tests.
Preserve their behavioral assertions rather than replacing them with mock-only
route tests.

Verification occurs in three layers:

1. focused Delivery boundary and behavior tests;
2. the CLI/spec/phase regression gate;
3. repository merge verification against the pre-cutover design commit.

The generated receipt and exact totals are recorded in the route inventory and
simplification control sheet.

## Delivery Order

1. Add failing typed boundary and ownership tests.
2. Create typed requests and public service entry points.
3. Move the Delivery/status kernel mechanically.
4. Redirect Typer and `delivery_status.py`.
5. Delete legacy ownership and migrate direct tests.
6. Run focused and CLI verification.
7. Run repository merge verification and update S3 tracking.

S3 remains `ACTIVE` after this slice. The active RE facade is the next and final
Typer cutover slice; RE protocol consolidation remains deferred to S6.
