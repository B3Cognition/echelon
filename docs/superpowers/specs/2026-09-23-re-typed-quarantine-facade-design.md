# RE Typed Quarantine Facade Design

## Purpose

Complete the final S3 Typer cutover slice without relocating or redesigning the
6,700-line executable RE protocol kernel. All active RE routes gain typed
application-service boundaries, while the existing protocol 2.2–2.8 and legacy
extraction implementations remain unchanged and explicitly quarantined for S6.

This design optimizes for a quick, working control boundary. It does not claim
that the RE kernel itself is simplified.

## Scope

The facade covers all routes that still call `_legacy_cli()` directly:

- public `re run`
- public `re refresh`
- public `re deepen`
- public `re status`
- public `re continue`
- public `re resume`
- public `re publish`
- public `re finalize`
- public `re synthesize`
- hidden `re execute-run`
- hidden `re check-domain`

After the cutover, the executable Typer tree has no direct `_legacy_cli()`
consumer. Existing root and namespace compatibility aliases continue to reach
canonical Typer commands rather than gaining independent RE implementations.

## Non-goals

- Do not move the RE protocol kernel out of `echelon.cli` merely to reduce a
  file metric.
- Do not consolidate, delete, migrate, or select among protocol generations.
- Do not change protocol 2.2–2.8 state, manifests, events, checkpoints,
  budgets, locking, publication, or recovery behavior.
- Do not redesign the knowledge-analysis lifecycle or controller APIs.
- Do not remove private RE handlers or direct behavioral tests that still
  define the quarantined S6 migration surface.
- Do not change console output, errors, exit codes, command help, or hidden
  compatibility options.
- Do not add a generic command bus or a reusable facade framework.

## Chosen Architecture

Create `src/echelon/re_service.py` as the typed application boundary and the
only module permitted to adapt active RE commands into the quarantined legacy
kernel.

`src/echelon/cli_app.py` remains responsible for Typer declarations, Click
validation, and user-facing `BadParameter` behavior. It constructs immutable
request values and calls `re_service` directly. Declared values are never
exposed to the service as an untyped `list[str]`.

`re_service` contains no RE controller or protocol implementation. Its public
functions accept typed requests, privately reconstruct the exact legacy
argument order, and call the existing private handler. The module-local legacy
import is the quarantine seam:

```python
def _legacy_kernel():
    from echelon import cli

    return cli
```

No other new module may use this adapter. In particular, `cli_app.py` must not
import `echelon.cli` or call `_legacy_cli()` from an active RE route.

The service is intentionally a facade rather than a new source of business
logic. Cross-option checks that currently produce Click/Typer errors remain at
the Typer boundary. Existing private handlers remain the execution authority
until S6 replaces or migrates them.

## Typed Requests

The facade exposes frozen request values. Enum-backed Typer values are stored
as their stable string values so the facade does not depend on CLI-only enum
types.

```python
@dataclass(frozen=True)
class ReRunRequest:
    depth: str | None = None
    re_policy: str = "changed"
    re_max_inner: int | None = None
    profile: str | None = None
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None
    reset: bool = False
    no_reuse: bool = False
    engine: str | None = None
    shadow: bool = False
    goals: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReRefreshRequest:
    sources: tuple[str, ...] = ()
    depth: str | None = None
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None


@dataclass(frozen=True)
class ReDeepenRequest:
    target_layer: str
    all_sources: bool = False
    sources: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    from_run: str | None = None
    token_limit: int | None = None
    active_ms_limit: int | None = None
    semantic_token_limit: int | None = None
    semantic_active_ms_limit: int | None = None
    new_audit_epoch: bool = False
    shadow: bool = False


@dataclass(frozen=True)
class ReStatusRequest:
    run_id: str | None = None
    as_json: bool = False


@dataclass(frozen=True)
class ReContinueRequest:
    run_id: str | None = None
    re_max_inner: int | None = None
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None
    re_semantic_token_limit: int | None = None
    re_semantic_time_limit_minutes: int | None = None


@dataclass(frozen=True)
class ReResumeRequest:
    answer: str | None = None
    recommended: bool = False
    banzai: bool = False
    re_max_inner: int | None = None
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None
    re_semantic_token_limit: int | None = None
    re_semantic_time_limit_minutes: int | None = None


@dataclass(frozen=True)
class RePublishRequest:
    run_id: str
    allow_partial: bool = False
    commit: bool = False


@dataclass(frozen=True)
class ReFinalizeRequest:
    run_id: str | None = None
    allow_partial: bool = False


@dataclass(frozen=True)
class ReSynthesizeRequest:
    run_id: str | None = None
    allow_partial: bool = False
    re_token_limit: int | None = None
    re_time_limit_minutes: int | None = None
    from_run: str | None = None
    accept_partial: tuple[str, ...] = ()
    token_limit: int | None = None
    active_ms_limit: int | None = None
```

The hidden internal commands have only required identifiers and use explicit
keyword parameters rather than additional dataclasses.

## Public Interface

```python
run_re(request: ReRunRequest) -> None
refresh_re(request: ReRefreshRequest) -> None
deepen_re(request: ReDeepenRequest) -> None
show_re_status(request: ReStatusRequest) -> None
continue_re(request: ReContinueRequest) -> None
resume_re(request: ReResumeRequest) -> None
publish_re(request: RePublishRequest) -> None
finalize_re(request: ReFinalizeRequest) -> None
synthesize_re(request: ReSynthesizeRequest) -> None
execute_re_run(*, run_id: str) -> None
check_re_domain(*, run_id: str, source_id: str, domain_id: str) -> None
```

These functions deliberately do not accept `project_root`: the quarantined
handlers currently own their ambient-root behavior. Introducing explicit root
plumbing across the RE protocol museum is S6 work and would make this facade a
partial protocol refactor rather than a transport boundary.

## Adaptation Rules

Every adapter preserves the existing argument construction exactly:

- `run_re` preserves the current knowledge-run versus legacy-protocol branch.
  `depth` selects the knowledge handler only when no legacy controls are active;
  token/time limits remain valid in both modes exactly as today.
- Repeated values preserve their input order.
- Boolean flags are emitted only when true.
- Optional positional values remain omitted when `None`.
- Enum values use their existing lowercase or layer string spelling.
- `synthesize_re` preserves its `from_run` protocol-2.7 branch and the legacy
  synthesis branch.
- Hidden execution/check commands preserve their positional ordering.

The facade does not catch `SystemExit` or translate exceptions. The legacy
handlers retain their current output and exit behavior.

## Ownership and Dependency Rules

After the cutover:

- the nine public and two hidden RE Typer callbacks do not call `_legacy_cli()`;
- those callbacks do not import `echelon.cli`;
- `echelon.re_service` is the sole active route adapter into the legacy RE
  kernel;
- the existing RE handlers and protocol helpers remain in `echelon.cli`;
- no handler alias or duplicated protocol implementation is added;
- `echelon.cli_app._legacy_cli` may remain only for unrelated contained
  compatibility code, or be deleted if no caller remains.

This is a deliberate quarantine exception to the original literal S3 exit
wording that `cli.py` no longer own active workflows. The accurate S3 outcome
is: every public command has a typed modular front door, compatibility aliases
are isolated, and the remaining RE kernel dependency is contained behind one
named facade scheduled for S6.

## Testing Strategy

Create `tests/unit/test_re_service_boundary.py` with:

- exact request-equality routing tests for all nine public commands;
- explicit keyword routing tests for both hidden commands;
- adapter parity tests asserting the exact legacy argument list and selected
  private handler for every facade function;
- run-mode coverage for knowledge and legacy branches;
- synthesis coverage for legacy and protocol-2.7 branches;
- a source/AST guard proving active RE Typer callbacks do not import
  `echelon.cli` or call `_legacy_cli()`;
- a guard proving `re_service.py` is the only active RE route adapter allowed
  to import the quarantined kernel.

Update existing Typer routing tests to patch `echelon.re_service`. Keep direct
handler behavioral tests on `echelon.cli`; they protect the unchanged kernel
that S6 must later consolidate.

Verification occurs in three layers:

1. RE facade boundary and existing RE behavior tests;
2. the CLI regression gate;
3. repository merge verification against this design commit.

## Tracking and Milestone Outcome

After successful verification:

- recount the executable Typer tree;
- record all 104 public routes as modular at the front door;
- record zero direct public or hidden `_legacy_cli()` consumers if the recount
  confirms it;
- mark S3 `DONE` with the quarantine exception stated explicitly;
- activate S4 next, preserving the established milestone order;
- keep RE protocol consolidation in S6.

S3 completion must not be described as RE simplification. It is completion of
the typed command boundary and containment of the remaining RE debt.
