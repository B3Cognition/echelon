# Delivery Service Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the nine remaining active Delivery commands and Delivery-status helper ownership behind one typed application service, deleting their legacy ownership from `cli.py` without changing behavior.

**Architecture:** `cli_app.py` keeps Typer parsing and constructs immutable requests for `delivery_service.py`. The existing Delivery kernel and status rendering move mechanically into that module; `delivery_status.py` remains the status command facade but consumes the new owner. Controller decomposition remains deferred to S4.

**Tech Stack:** Python 3.11+, Typer/Click, pytest, existing Echelon controlled-delivery controllers and persisted-state contracts.

**Spec:** `docs/superpowers/specs/2026-09-22-delivery-service-cutover-design.md`

## Global Constraints

- Preserve controlled-delivery schemas, state paths, leases, checkpoints, sandbox authority, target dispatch, publication, landing behavior, console output, and exit codes.
- Do not redesign `RalphController`, `StrategyCoordinator`, run/recovery semantics, or the Delivery controller boundary; that work belongs to S4.
- Do not change RE behavior or introduce a third CLI dispatch layer.
- Do not leave forwarding aliases, duplicate active Delivery handlers, or Delivery-status helper ownership in `cli.py`.
- Typer passes declared values as typed fields; only undeclared compatibility arguments remain ordered tuples.
- Keep hidden `harness` and root Delivery compatibility aliases forwarding through canonical Typer routes.
- Keep S3 `ACTIVE` after this slice; the active RE facade remains its final cutover slice.

## File Structure

- Create `src/echelon/delivery_service.py`: immutable request types, public Delivery entry points, and the mechanically relocated Delivery/status kernel.
- Modify `src/echelon/cli_app.py`: construct typed requests and route the nine active Delivery commands directly to the new service.
- Modify `src/echelon/delivery_status.py`: retain the status command facade while importing its Delivery implementation from `delivery_service`.
- Modify `src/echelon/cli.py`: delete the nine legacy command handlers and all helpers, constants, and dataclasses that become Delivery-only.
- Create `tests/unit/test_delivery_service_boundary.py`: typed-routing and structural-ownership guards.
- Modify focused Delivery tests so direct imports and monkeypatch targets name the new owner.
- Update `docs/findings/2026-09-21-typer-route-inventory.md` and `docs/simplification-control.md` only after verification.

---

### Task 1: Cut Over Delivery Initialization, Targeting, Local Verification, and Checkpoints

**Files:**

- Create: `src/echelon/delivery_service.py`
- Create: `tests/unit/test_delivery_service_boundary.py`
- Modify: `src/echelon/cli_app.py:4527-4543,4562-4616,4799-4814`
- Modify: `src/echelon/cli.py:728-1153,1225-1420,3197-3514,4339-4422`
- Modify: `tests/unit/test_cli_delivery.py`
- Modify: `tests/unit/test_cli_delivery_local.py`
- Modify: `tests/unit/test_cli_harness_init_summary.py`
- Modify: `tests/unit/test_cli_typer_app.py`

**Interfaces:**

- Consumes: existing workspace Git preflight, provider-capability gate, configuration loader, sandbox/mirror setup, local-verification journal, and checkpoint state contracts.
- Produces: immutable `LocalVerificationRequest`.
- Produces: `initialize_delivery(project_root: Path, *, extra_args: Sequence[str] = ()) -> None`.
- Produces: `prepare_target(project_root: Path, *, spec_id: str) -> None`.
- Produces: `verify_local(project_root: Path, request: LocalVerificationRequest) -> None`.
- Produces: `cleanup_local(project_root: Path, *, local_run_id: str) -> None`.
- Produces: `list_checkpoints(project_root: Path, *, spec_id: str, strategy: str | None, extra_args: Sequence[str] = ()) -> None`.
- Retains in `echelon.cli`: generic `_iter_harness_build_states`, `_load_cli_config`, `_require_provider_capability`, `_banner`, and any other helper with a proven non-Delivery caller.

- [ ] **Step 1: Write failing typed-routing tests for the five leaf routes**

Create `tests/unit/test_delivery_service_boundary.py` with direct request equality and explicit keyword assertions:

```python
from pathlib import Path

from typer.testing import CliRunner


def test_delivery_init_routes_extra_args_to_service(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.initialize_delivery",
        lambda project_root, *, extra_args=(): calls.append(
            (project_root, tuple(extra_args))
        ),
    )
    result = CliRunner().invoke(app, ["delivery", "init", "provider=claude"])
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), ("provider=claude",))]


def test_delivery_target_routes_spec_id_to_service(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.prepare_target",
        lambda project_root, *, spec_id: calls.append((project_root, spec_id)),
    )
    result = CliRunner().invoke(app, ["delivery", "target", "001-demo"])
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "001-demo")]


def test_delivery_verify_local_routes_immutable_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import LocalVerificationRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.verify_local",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        [
            "delivery", "verify-local", "001-demo", "--target", "api",
            "--engine", "podman", "--yes", "--keep-on-failure",
        ],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        LocalVerificationRequest(
            spec_id="001-demo",
            target_id="api",
            engine="podman",
            assume_yes=True,
            keep_on_failure=True,
        ),
    )]


def test_delivery_cleanup_local_routes_run_id(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.cleanup_local",
        lambda project_root, *, local_run_id: calls.append(
            (project_root, local_run_id)
        ),
    )
    result = CliRunner().invoke(app, ["delivery", "cleanup-local", "local-123"])
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "local-123")]


def test_delivery_checkpoint_list_routes_typed_values(monkeypatch):
    from echelon.cli_app import app

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.list_checkpoints",
        lambda project_root, *, spec_id, strategy, extra_args=(): calls.append(
            (project_root, spec_id, strategy, tuple(extra_args))
        ),
    )
    result = CliRunner().invoke(
        app,
        ["delivery", "checkpoint", "list", "001-demo", "--strategy", "safe"],
    )
    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "001-demo", "safe", ())]
```

- [ ] **Step 2: Verify the leaf boundary is absent**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_delivery_service_boundary.py
```

Expected: collection or monkeypatch resolution fails because `echelon.delivery_service` does not exist.

- [ ] **Step 3: Define the local-verification request and public leaf entry points**

Create `delivery_service.py` with the request type below. In the same edit,
declare the five public signatures exactly as listed in this task's Interfaces
block and give them the moved bodies described in Step 4.

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class LocalVerificationRequest:
    spec_id: str
    target_id: str | None = None
    engine: str = "auto"
    assume_yes: bool = False
    keep_on_failure: bool = False
```

Private adapters may build the old parser-shaped argument list inside the
service, but Typer must pass declared values separately.

- [ ] **Step 4: Move the leaf kernel without changing behavior**

Move `LocalActionPlan`, `HarnessWorkspaceTarget`, and the Delivery-only closure rooted at `_cmd_harness_init`, `_cmd_delivery_target`, `_cmd_delivery_verify_local`, `_cmd_delivery_cleanup_local`, and `_cmd_delivery_checkpoint`. This includes init summary/detection, target verification detection, local action planning/confirmation/execution/reporting, checkpoint selection/rendering, and workspace-target resolution used by later Delivery tasks.

Keep generic helpers in `cli.py` when another active subsystem still calls them. Import those names narrowly inside `delivery_service.py`; do not copy their implementations. Replace ambient `Path.cwd()` in public entry paths with the supplied `project_root`, while preserving paths passed to lower-level operations.

- [ ] **Step 5: Redirect the five Typer routes**

Use local service imports in each command. The local-verification error translation remains at the Typer boundary:

```python
from echelon.delivery_service import LocalVerificationRequest, verify_local

try:
    verify_local(
        Path.cwd(),
        LocalVerificationRequest(
            spec_id=spec_id,
            target_id=target,
            engine=engine,
            assume_yes=assume_yes,
            keep_on_failure=keep_on_failure,
        ),
    )
except ValueError as exc:
    typer.echo(f"✗ {exc}", err=True)
    raise typer.Exit(code=1) from exc
```

Apply the same direct pattern to init, target, cleanup-local, and checkpoint list. Do not call a private legacy handler from these Typer functions.

- [ ] **Step 6: Migrate leaf tests and remove leaf handler definitions**

Move imports and monkeypatch targets for the five removed handlers and their Delivery-only helpers from `echelon.cli` to `echelon.delivery_service`. Preserve test bodies and expected messages. In particular, update `LocalActionPlan`, `_build_local_action_plan`, `_run_local_delivery_verification`, `_harness_init_detection_fields`, and `_harness_init_next_step` targets.

Delete the five legacy handler definitions after their tests use the new owner. Do not create aliases in `cli.py`.

- [ ] **Step 7: Run focused leaf verification**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_service_boundary.py \
  tests/unit/test_cli_delivery.py tests/unit/test_cli_delivery_local.py \
  tests/unit/test_cli_harness_init_summary.py tests/unit/test_cli_typer_app.py \
  tests/unit/test_harness_init_app_runtime.py tests/unit/test_harness_init_verify.py
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit the leaf cutover**

```bash
git add src/echelon/delivery_service.py src/echelon/cli_app.py \
  src/echelon/cli.py tests/unit/test_delivery_service_boundary.py \
  tests/unit/test_cli_delivery.py tests/unit/test_cli_delivery_local.py \
  tests/unit/test_cli_harness_init_summary.py tests/unit/test_cli_typer_app.py
git commit -m "refactor: move leaf delivery commands to service"
```

---

### Task 2: Cut Over Delivery Run, Resume, and Continue

**Files:**

- Modify: `src/echelon/delivery_service.py`
- Modify: `src/echelon/cli_app.py:2645-2740,4619-4747`
- Modify: `src/echelon/cli.py:571-725,959-978,1069-1098,1191-1222,1423-2922,11976-11979`
- Modify: `tests/unit/test_delivery_service_boundary.py`
- Modify: `tests/unit/test_cli_delivery.py`
- Modify: `tests/unit/test_cli_harness_run.py`
- Modify: `tests/unit/test_cli_harness_resume.py`
- Modify: `tests/unit/test_harness_single_repo_unchanged.py`
- Modify: `tests/integration/test_egr_151_lifecycle_flow.py`

**Interfaces:**

- Consumes: `HarnessWorkspaceTarget` and shared target-resolution helpers moved in Task 1.
- Produces: immutable `DeliveryRunRequest` and `DeliveryRecoveryRequest`.
- Produces: `run_delivery(project_root: Path, request: DeliveryRunRequest) -> None`.
- Produces: `resume_delivery(project_root: Path, request: DeliveryRecoveryRequest) -> None`.
- Produces: `continue_delivery(project_root: Path, request: DeliveryRecoveryRequest) -> None`.
- Preserves: all provider, preparation, dispatch, outcome, blocking, refresh, retry, outer-cap, and session-limit behavior.

- [ ] **Step 1: Add failing typed run/recovery route tests**

Append to `test_delivery_service_boundary.py`:

```python
def test_delivery_run_routes_immutable_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import DeliveryRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.run_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        [
            "delivery", "run", "001-demo", "legacy=value",
            "--mode", "banzai", "--strategy", "safe",
            "--max-outer", "4", "--max-inner", "2",
            "--token-budget", "9000", "--no-auto-merge",
            "--kill-losers", "--reset",
        ],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        DeliveryRunRequest(
            spec_id="001-demo",
            extra_args=("legacy=value",),
            mode="banzai",
            strategy="safe",
            max_outer=4,
            max_inner=2,
            token_budget=9000,
            auto_merge=False,
            kill_losers=True,
            reset=True,
        ),
    )]


def test_delivery_resume_routes_answer_and_options(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import DeliveryRecoveryRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.resume_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        ["delivery", "resume", "001-demo", "Use option 1", "--mode", "semi", "--strategy", "safe"],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        DeliveryRecoveryRequest(
            spec_id="001-demo",
            answer="Use option 1",
            mode="semi",
            strategy="safe",
        ),
    )]


def test_delivery_continue_routes_answerless_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import DeliveryRecoveryRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.continue_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        ["delivery", "continue", "001-demo", "--mode", "banzai"],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        DeliveryRecoveryRequest(spec_id="001-demo", mode="banzai"),
    )]
```

Add a direct service test asserting `continue_delivery` rejects a request whose `answer` is not `None` with the stable message `delivery continue does not accept an answer`.

- [ ] **Step 2: Run the new tests and confirm the missing interfaces fail**

```bash
.venv/bin/python -m pytest -q tests/unit/test_delivery_service_boundary.py \
  -k 'run_routes or resume_routes or continue_routes or rejects_answer'
```

Expected: failures report missing request classes and service functions.

- [ ] **Step 3: Add the immutable execution requests**

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
```

The public functions accept these objects. Private adapters may create the parser-shaped list expected by the mechanically moved kernel. The display argument list for run must still omit compatibility-only normalization exactly as `_display_run_args` does today.

- [ ] **Step 4: Move the run and recovery kernel mechanically**

Move the closure rooted at `_cmd_harness_run`, `_cmd_harness_resume`, and `_cmd_harness_continue`. Include provisioning checks, runtime refresh, stack contract resolution, build-state preparation, outcome exit mapping, blocked-state writes, error rendering, resume parsing, outer-cap action, and provider-session limits.

Preserve every branch, state-write order, command prefix, and `SystemExit` value. Keep generic helpers with active non-Delivery consumers in their existing module and import them narrowly. Reuse Task 1 target-resolution definitions rather than creating duplicates.

Implement the answer guard before adapting `DeliveryRecoveryRequest`:

```python
def continue_delivery(
    project_root: Path,
    request: DeliveryRecoveryRequest,
) -> None:
    if request.answer is not None:
        raise ValueError("delivery continue does not accept an answer")
    _run_delivery_continue(project_root, _recovery_args(request))
```

- [ ] **Step 5: Redirect Typer and delete argument reconstruction from `cli_app.py`**

Construct `DeliveryRunRequest` and `DeliveryRecoveryRequest` directly in `delivery_run`, `delivery_resume`, and `delivery_continue`. Delete `_merge_run_args`, `_display_run_args`, and `_merge_resume_args` after their logic has moved behind private service adapters. Do not leave service calls to `echelon.cli` handlers.

- [ ] **Step 6: Migrate execution/recovery tests and delete the three handlers**

Use this search as the migration checklist:

```bash
rg -n '_cmd_harness_run|_cmd_harness_resume|_cmd_harness_continue|_delivery_outcome_exit_code|_mark_current_harness_state_blocked|_refresh_harness_state_spec_paths|_resolve_harness_workspace_target|_sync_polyrepo_runtime_extension|_apply_target_verify_command_detection' \
  tests/unit/test_cli_delivery.py tests/unit/test_cli_harness_run.py \
  tests/unit/test_cli_harness_resume.py \
  tests/unit/test_harness_single_repo_unchanged.py \
  tests/integration/test_egr_151_lifecycle_flow.py
```

Change every import and patch target for a moved symbol to `echelon.delivery_service`. Preserve all behavioral assertions. Then delete `_cmd_harness_run`, `_cmd_harness_resume`, and `_cmd_harness_continue` from `cli.py`; do not add compatibility aliases there.

- [ ] **Step 7: Run focused execution/recovery verification**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_service_boundary.py tests/unit/test_cli_delivery.py \
  tests/unit/test_cli_harness_run.py tests/unit/test_cli_harness_resume.py \
  tests/unit/test_harness_single_repo_unchanged.py \
  tests/integration/test_egr_151_lifecycle_flow.py
```

Expected: all selected tests pass. Poll a long-running pytest process rather than restarting it.

- [ ] **Step 8: Commit the execution/recovery cutover**

```bash
git add src/echelon/delivery_service.py src/echelon/cli_app.py \
  src/echelon/cli.py tests/unit/test_delivery_service_boundary.py \
  tests/unit/test_cli_delivery.py tests/unit/test_cli_harness_run.py \
  tests/unit/test_cli_harness_resume.py \
  tests/unit/test_harness_single_repo_unchanged.py \
  tests/integration/test_egr_151_lifecycle_flow.py
git commit -m "refactor: move delivery run recovery to service"
```

---

### Task 3: Cut Over Landing and Delivery Status, Then Enforce Ownership

**Files:**

- Modify: `src/echelon/delivery_service.py`
- Modify: `src/echelon/cli_app.py:2723-2740,4750-4796`
- Modify: `src/echelon/delivery_status.py`
- Modify: `src/echelon/cli.py:291-576,2959-2977,3517-4336`
- Modify: `tests/unit/test_delivery_service_boundary.py`
- Modify: `tests/unit/test_cli_delivery.py`
- Modify: `tests/unit/test_cli_delivery_status.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify: `tests/unit/test_land_cli.py`

**Interfaces:**

- Consumes: `HarnessWorkspaceTarget`, target resolution, configuration, and run/recovery helpers from Tasks 1 and 2.
- Produces: immutable `DeliveryLandRequest`.
- Produces: `land_delivery(project_root: Path, request: DeliveryLandRequest) -> None`.
- Produces for `delivery_status.py`: `_delivery_status_summary`, `_delivery_status_fields`, and the Delivery-owned status helper closure.
- Establishes: no active Delivery Typer function and no code in `delivery_status.py` imports `echelon.cli`.
- Establishes: `cli.py` defines none of the nine removed handlers.

- [ ] **Step 1: Add failing land and ownership tests**

Append the land route test:

```python
def test_delivery_land_routes_immutable_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.delivery_service import DeliveryLandRequest

    calls = []
    monkeypatch.setattr(
        "echelon.delivery_service.land_delivery",
        lambda project_root, request: calls.append((project_root, request)),
    )
    result = CliRunner().invoke(
        app,
        [
            "delivery", "land", "001-demo", "legacy=value", "--continue",
            "--prepare-only", "--no-autoresolve",
            "--allow-fulfillment-gaps", "--strategy", "rebase",
        ],
    )
    assert result.exit_code == 0
    assert calls == [(
        Path.cwd(),
        DeliveryLandRequest(
            spec_id="001-demo",
            extra_args=("legacy=value",),
            continue_existing=True,
            prepare_only=True,
            autoresolve=False,
            allow_fulfillment_gaps=True,
            strategy="rebase",
        ),
    )]
```

Add structural tests using AST/source inspection:

```python
import ast
import inspect
import textwrap


ACTIVE_DELIVERY_FUNCTIONS = {
    "delivery_init",
    "delivery_target",
    "delivery_verify_local",
    "delivery_cleanup_local",
    "delivery_run",
    "delivery_resume",
    "delivery_continue",
    "delivery_land",
    "delivery_checkpoint_list",
}

REMOVED_HANDLERS = {
    "_cmd_land",
    "_cmd_harness_init",
    "_cmd_delivery_target",
    "_cmd_harness_run",
    "_cmd_harness_resume",
    "_cmd_harness_continue",
    "_cmd_delivery_verify_local",
    "_cmd_delivery_cleanup_local",
    "_cmd_delivery_checkpoint",
}


def test_active_delivery_surfaces_do_not_import_legacy_cli():
    import echelon.cli_app as cli_app
    import echelon.delivery_status as delivery_status

    for name in ACTIVE_DELIVERY_FUNCTIONS:
        source = textwrap.dedent(inspect.getsource(getattr(cli_app, name)))
        assert "echelon import cli" not in source
        assert "echelon.cli import" not in source
    status_source = inspect.getsource(delivery_status)
    assert "echelon import cli" not in status_source
    assert "echelon.cli import" not in status_source


def test_legacy_cli_does_not_define_delivery_handlers():
    from echelon import cli

    tree = ast.parse(inspect.getsource(cli))
    definitions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert definitions.isdisjoint(REMOVED_HANDLERS)
```

- [ ] **Step 2: Verify land and ownership tests fail for the expected reasons**

```bash
.venv/bin/python -m pytest -q tests/unit/test_delivery_service_boundary.py \
  -k 'land_routes or active_delivery_surfaces or legacy_cli'
```

Expected: the missing land request/API and remaining status/handler ownership cause failures.

- [ ] **Step 3: Add the immutable land request and public entry point**

```python
@dataclass(frozen=True)
class DeliveryLandRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    continue_existing: bool = False
    prepare_only: bool = False
    autoresolve: bool = True
    allow_fulfillment_gaps: bool = False
    strategy: str | None = None
```

Implement `land_delivery` by adapting this request inside `delivery_service.py` and then entering the relocated landing kernel. `continue_existing` maps to the existing `--continue` behavior; `autoresolve=False` maps to the existing `--no-autoresolve` behavior.

- [ ] **Step 4: Move landing and status ownership mechanically**

Move the closure rooted at `_cmd_land`, including squad-run archival, target dispatch, landing preflight, conflict handling, fulfillment checks, cleanup, and archive behavior. Reuse target/config helpers already owned by `delivery_service`; do not duplicate them.

Move the closure rooted at `_delivery_status_summary` and `_delivery_status_fields`, including escalation, next-step selection, effective state, local evidence, normalized runnability, normalized coverage observation, and nonnegative counts. Change `delivery_status.py` to import these functions from `echelon.delivery_service`. Import generic rendering/capability/state-iteration helpers into the service as narrow dependencies so `delivery_status.py` itself has no `cli` dependency.

- [ ] **Step 5: Redirect landing and delete obsolete CLI adapters**

Construct `DeliveryLandRequest` in `delivery_land` and call `land_delivery(Path.cwd(), request)`. Delete `_merge_land_args` after its adaptation logic lives in the service. Keep the hidden `harness land` and root `land` aliases forwarding through the canonical Typer route; they must not call a relocated private handler directly.

- [ ] **Step 6: Migrate land/status tests and remove final Delivery ownership**

Change `test_land_cli.py` imports and patch targets for `_cmd_land`, `_archive_squad_run`, `HarnessWorkspaceTarget`, `_resolve_harness_workspace_target`, and `_sync_polyrepo_runtime_extension` to `echelon.delivery_service`. Change direct status-helper imports in `test_cli_delivery_status.py` to the same module. Update old routing mocks in `test_cli_delivery.py` and `test_cli_typer_app.py` to assert typed service calls.

Delete `_cmd_land`, the status helper closure, and any helper/constant/dataclass that now has no non-Delivery caller from `cli.py`. Leave no forwarding alias. Run this residual search and classify every match before proceeding:

```bash
rg -n '_cmd_land|_cmd_harness_init|_cmd_delivery_target|_cmd_harness_run|_cmd_harness_resume|_cmd_harness_continue|_cmd_delivery_verify_local|_cmd_delivery_cleanup_local|_cmd_delivery_checkpoint|_delivery_status_fields|_delivery_status_summary' \
  src tests
```

Expected: production matches are service definitions/calls and status imports only; test matches target `echelon.delivery_service`; `src/echelon/cli.py` has no matches for removed definitions.

- [ ] **Step 7: Run focused Delivery verification**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_delivery_service_boundary.py tests/unit/test_cli_delivery.py \
  tests/unit/test_cli_delivery_local.py tests/unit/test_cli_delivery_status.py \
  tests/unit/test_cli_harness_init_summary.py tests/unit/test_cli_harness_run.py \
  tests/unit/test_cli_harness_resume.py \
  tests/unit/test_harness_single_repo_unchanged.py \
  tests/unit/test_land_cli.py tests/unit/test_cli_typer_app.py \
  tests/integration/test_egr_151_lifecycle_flow.py
```

Expected: all selected tests pass.

- [ ] **Step 8: Run the CLI regression gate**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_cli_*.py tests/unit/test_delivery_*.py \
  tests/unit/test_harness_*.py tests/unit/test_land*.py \
  tests/unit/test_controlled_delivery_*.py
```

Expected: all applicable selected tests pass. Any failure must reproduce on design commit `3abca341` before it can be classified as pre-existing.

- [ ] **Step 9: Commit the completed ownership cutover**

```bash
git add src/echelon/delivery_service.py src/echelon/delivery_status.py \
  src/echelon/cli_app.py src/echelon/cli.py \
  tests/unit/test_delivery_service_boundary.py tests/unit/test_cli_delivery.py \
  tests/unit/test_cli_delivery_status.py tests/unit/test_cli_typer_app.py \
  tests/unit/test_land_cli.py
git commit -m "refactor: move delivery landing and status ownership"
```

---

### Task 4: Verify and Record the Delivery Slice

**Files:**

- Modify: `docs/findings/2026-09-21-typer-route-inventory.md`
- Modify: `docs/simplification-control.md`
- Create: generated receipt under `tests/reports/merge-verification/`

**Interfaces:**

- Consumes: the three production commits and design baseline `3abca341`.
- Produces: exact focused, CLI, and repository verification evidence.
- Produces: route totals of 96 modular public commands and 11 still owned by `cli.py`, subject to recount from the inventory script.
- Produces: S3 remains `ACTIVE`; active RE facade is recorded as the next and final Typer cutover slice.

- [ ] **Step 1: Run structural ownership guards**

```bash
rg -n '^def (_cmd_land|_cmd_harness_init|_cmd_delivery_target|_cmd_harness_run|_cmd_harness_resume|_cmd_harness_continue|_cmd_delivery_verify_local|_cmd_delivery_cleanup_local|_cmd_delivery_checkpoint|_delivery_status_fields|_delivery_status_summary)\b' \
  src/echelon/cli.py
.venv/bin/python -m pytest -q tests/unit/test_delivery_service_boundary.py
```

Expected: the search returns no matches and all boundary tests pass.

- [ ] **Step 2: Run repository merge verification**

```bash
.venv/bin/python scripts/merge_verification.py plan --base 3abca341
.venv/bin/python scripts/merge_verification.py run --base 3abca341
```

Expected: the planned repository gate passes and writes a receipt. Record exact pass, skip, deselection, failure, and duration totals. Poll the running process; do not restart a quiet long-running suite.

- [ ] **Step 3: Update route and milestone tracking**

In `docs/findings/2026-09-21-typer-route-inventory.md`, move the nine cut-over routes to the modular-service table and name `echelon.delivery_service`; retain `delivery status` under `echelon.delivery_status` while noting that its kernel now belongs to the service. Recount rather than blindly copying totals; the expected result is 96 modular public commands and 11 still delegated to `cli.py`.

In `docs/simplification-control.md`, check the Delivery cutover step, record commit IDs, focused and CLI totals, full repository totals, duration, and receipt path. Keep S3 `ACTIVE` and set the active RE facade as next. Keep RE protocol consolidation assigned to S6.

- [ ] **Step 4: Check and commit verification evidence**

```bash
git diff --check
git status --short
git add docs/findings/2026-09-21-typer-route-inventory.md \
  docs/simplification-control.md tests/reports/merge-verification
git commit -m "docs: record delivery service cutover verification"
```

Expected before commit: only the two tracking documents and generated receipt are uncommitted.

- [ ] **Step 5: Verify final state**

```bash
git status --short
git log -6 --oneline
```

Expected: clean status and the design, plan, three implementation commits, and evidence commit are present in recent history. S3 remains active with RE next.
