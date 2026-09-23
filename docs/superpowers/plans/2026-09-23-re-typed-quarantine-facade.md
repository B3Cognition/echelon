# RE Typed Quarantine Facade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every active public and hidden RE Typer command through one typed facade while leaving the existing RE protocol kernel unchanged and quarantined in `echelon.cli` for S6.

**Architecture:** `cli_app.py` keeps Typer declarations and Click-specific validation, constructs frozen requests, and calls `re_service.py`. The facade contains typed-to-legacy argument adapters and is the single active route dependency on the unchanged private RE handlers in `cli.py`; it contains no controller or protocol logic.

**Tech Stack:** Python 3.11+, dataclasses, Typer/Click, pytest, existing Echelon RE protocol 2.2–2.8 implementations.

**Spec:** `docs/superpowers/specs/2026-09-23-re-typed-quarantine-facade-design.md`

## Global Constraints

- Preserve every RE protocol, state schema, manifest, event, checkpoint, budget, lock, publication rule, recovery branch, console message, and exit code.
- Do not move, consolidate, delete, migrate, or redesign the RE protocol kernel in this slice.
- `cli_app.py` keeps Click/Typer cross-option validation and `BadParameter` behavior.
- Declared command values cross the facade as typed frozen request fields, never as `list[str]`.
- `re_service.py` is the single active route adapter allowed to reconstruct legacy argument vectors and call private RE handlers in `echelon.cli`.
- Existing direct private-handler behavior tests remain on `echelon.cli`; only Typer routing tests migrate to the facade.
- Root and namespace compatibility aliases continue to forward through canonical Typer commands.
- S3 completes only after all public routes have modular typed front doors and the RE kernel quarantine is recorded explicitly; S4 becomes active next and protocol consolidation remains S6.

## File Structure

- Create `src/echelon/re_service.py`: frozen transport requests, exact legacy argument adapters, and the single quarantine import seam.
- Modify `src/echelon/cli_app.py`: construct typed RE requests, call the facade for nine public and two hidden commands, and delete `_legacy_cli` when its last caller is gone.
- Create `tests/unit/test_re_service_boundary.py`: request routing, adapter parity, branching, and structural quarantine tests.
- Modify `tests/unit/test_cli_typer_app.py`: patch typed service functions instead of private CLI handlers.
- Modify only other RE tests that exercise the Typer route; keep direct kernel tests importing `echelon.cli`.
- Update the route inventory and simplification control only after all verification passes.

---

### Task 1: Add the Typed Facade for Run, Refresh, Deepen, and Status

**Files:**

- Create: `src/echelon/re_service.py`
- Create: `tests/unit/test_re_service_boundary.py`
- Modify: `src/echelon/cli_app.py:893-1187`
- Modify: `tests/unit/test_cli_typer_app.py:33-131`
- Modify: `tests/unit/test_cli_re_v2_protocol_22.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_24.py`

**Interfaces:**

- Produces: frozen `ReRunRequest`, `ReRefreshRequest`, `ReDeepenRequest`, and `ReStatusRequest`.
- Produces: `run_re(request: ReRunRequest) -> None`.
- Produces: `refresh_re(request: ReRefreshRequest) -> None`.
- Produces: `deepen_re(request: ReDeepenRequest) -> None`.
- Produces: `show_re_status(request: ReStatusRequest) -> None`.
- Consumes: unchanged `_cmd_re_knowledge_run`, `_cmd_re_run`, `_cmd_re_knowledge_refresh`, `_cmd_re_deepen`, and `_cmd_re_status` handlers from the quarantined kernel.

- [ ] **Step 1: Write failing typed route tests for the first four commands**

Create `test_re_service_boundary.py` and invoke the Typer app. Patch the new
facade functions and compare exact frozen requests:

```python
from typer.testing import CliRunner


def test_re_run_routes_knowledge_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.run_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        ["re", "run", "--depth", "deep", "--re-token-limit", "9000"],
    )
    assert result.exit_code == 0
    assert calls == [ReRunRequest(depth="deep", re_token_limit=9000)]


def test_re_run_routes_legacy_protocol_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReRunRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.run_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re", "run", "--engine", "v2", "--goal", "inventory",
            "--profile", "high", "--shadow",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReRunRequest(
            profile="high",
            engine="v2",
            shadow=True,
            goals=("inventory",),
        )
    ]


def test_re_refresh_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReRefreshRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.refresh_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re", "refresh", "--source", "api", "--source", "web",
            "--depth", "quick", "--re-time-limit-minutes", "12",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReRefreshRequest(
            sources=("api", "web"),
            depth="quick",
            re_time_limit_minutes=12,
        )
    ]


def test_re_deepen_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReDeepenRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.deepen_re",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(
        app,
        [
            "re", "deepen", "--to", "L3", "--source", "api",
            "--domain", "billing", "--semantic-token-limit", "4000",
            "--new-audit-epoch",
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        ReDeepenRequest(
            target_layer="L3",
            sources=("api",),
            domains=("billing",),
            semantic_token_limit=4000,
            new_audit_epoch=True,
        )
    ]


def test_re_status_routes_typed_request(monkeypatch):
    from echelon.cli_app import app
    from echelon.re_service import ReStatusRequest

    calls = []
    monkeypatch.setattr(
        "echelon.re_service.show_re_status",
        lambda request: calls.append(request),
    )
    result = CliRunner().invoke(app, ["re", "status", "re-123", "--json"])
    assert result.exit_code == 0
    assert calls == [ReStatusRequest(run_id="re-123", as_json=True)]
```

- [ ] **Step 2: Confirm the new facade boundary is absent**

```bash
.venv/bin/python -m pytest -q tests/unit/test_re_service_boundary.py \
  -k 'run_routes or refresh_routes or deepen_routes or status_routes'
```

Expected: collection/import failures report that `echelon.re_service` does not exist.

- [ ] **Step 3: Define the four frozen request values and quarantine seam**

Create `re_service.py` with the exact Task 1 dataclasses from the design and:

```python
from __future__ import annotations

from dataclasses import dataclass


def _legacy_kernel():
    from echelon import cli

    return cli


def _append_option(args: list[str], name: str, value: object | None) -> None:
    if value is not None:
        args.extend((name, str(value)))
```

The seam is intentionally module-local. Do not import controllers, protocol
contexts, state stores, or persistence modules into the facade.

- [ ] **Step 4: Write failing adapter-parity tests**

Patch `_legacy_kernel` with an object whose handler methods record their input.
Cover both run branches and exact ordered lists:

```python
def test_run_re_selects_knowledge_handler_and_preserves_limits(monkeypatch):
    from types import SimpleNamespace
    from echelon.re_service import ReRunRequest, run_re

    calls = []
    kernel = SimpleNamespace(
        _cmd_re_knowledge_run=lambda args: calls.append(("knowledge", args)),
        _cmd_re_run=lambda args: calls.append(("legacy", args)),
    )
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    run_re(
        ReRunRequest(
            depth="deep",
            re_token_limit=9000,
            re_time_limit_minutes=12,
        )
    )
    assert calls == [(
        "knowledge",
        ["--depth", "deep", "--re-token-limit", "9000", "--re-time-limit-minutes", "12"],
    )]


def test_run_re_selects_legacy_handler_and_preserves_order(monkeypatch):
    from types import SimpleNamespace
    from echelon.re_service import ReRunRequest, run_re

    calls = []
    kernel = SimpleNamespace(
        _cmd_re_knowledge_run=lambda args: calls.append(("knowledge", args)),
        _cmd_re_run=lambda args: calls.append(("legacy", args)),
    )
    monkeypatch.setattr("echelon.re_service._legacy_kernel", lambda: kernel)
    run_re(
        ReRunRequest(
            re_policy="refresh-all",
            re_max_inner=3,
            profile="high",
            reset=True,
            no_reuse=True,
            engine="v2",
            shadow=True,
            goals=("inventory",),
        )
    )
    assert calls == [(
        "legacy",
        [
            "--re-policy", "refresh-all", "--profile", "high",
            "--re-max-inner", "3", "--reset", "--no-reuse",
            "--engine", "v2", "--goal", "inventory", "--shadow",
        ],
    )]
```

Add parity cases for refresh, deepen, and status using these exact expected
orders:

```python
[
    "--source", "api", "--source", "web", "--depth", "quick",
    "--re-token-limit", "3000", "--re-time-limit-minutes", "8",
]

[
    "--to", "L3", "--source", "api", "--domain", "billing",
    "--from-run", "re-parent", "--token-limit", "5000",
    "--active-ms-limit", "60000", "--semantic-token-limit", "2500",
    "--semantic-active-ms-limit", "30000", "--new-audit-epoch",
]

["re-123", "--json"]
```

- [ ] **Step 5: Implement the four exact adapters**

`run_re` must copy the existing legacy-selection predicate exactly: `engine`,
`shadow`, `goals`, `re_max_inner`, `profile`, `reset`, `no_reuse`, or a
non-default `re_policy` select `_cmd_re_run`; token/time limits alone do not.
Construct the lists in the orders asserted above. `refresh_re` calls
`_cmd_re_knowledge_refresh`, `deepen_re` calls `_cmd_re_deepen`, and
`show_re_status` calls `_cmd_re_status`.

- [ ] **Step 6: Redirect the four Typer callbacks**

After the existing Click-specific validations, construct requests directly:

```python
from echelon.re_service import ReRunRequest, run_re

run_re(
    ReRunRequest(
        depth=depth.value if depth is not None else None,
        re_policy=re_policy,
        re_max_inner=re_max_inner,
        profile=profile,
        re_token_limit=re_token_limit,
        re_time_limit_minutes=re_time_limit_minutes,
        reset=reset,
        no_reuse=no_reuse,
        engine=engine.value if engine is not None else None,
        shadow=shadow,
        goals=tuple(item.value for item in goal),
    )
)
```

Apply the corresponding field-for-field construction to refresh, deepen, and
status. Delete their local argument-vector construction, but keep every
`BadParameter` branch and help declaration unchanged.

- [ ] **Step 7: Migrate only Typer-routing mocks**

Change tests that invoke `cli_app` and patch the four private handlers so they
patch the matching facade function and compare the request object. Do not
change tests that call `_cmd_re_*` directly to exercise kernel behavior.

- [ ] **Step 8: Run the first facade slice**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_re_service_boundary.py tests/unit/test_cli_typer_app.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_cli_re_v2_protocol_24.py
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit the analysis/control facade**

```bash
git add src/echelon/re_service.py src/echelon/cli_app.py \
  tests/unit/test_re_service_boundary.py tests/unit/test_cli_typer_app.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_cli_re_v2_protocol_24.py
git commit -m "refactor: add typed re analysis facade"
```

---

### Task 2: Cut Over Recovery, Publication, Synthesis, and Internal Routes

**Files:**

- Modify: `src/echelon/re_service.py`
- Modify: `src/echelon/cli_app.py:1190-1440,1576-1591`
- Modify: `tests/unit/test_re_service_boundary.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify: `tests/unit/test_cli_re_lifecycle.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_25.py`
- Modify: `tests/unit/test_cli_re_v2_protocol_27.py`
- Modify: `tests/unit/test_cli_re_check_domain.py`
- Modify: `tests/integration/test_re_v2_protocol_28_cli.py`

**Interfaces:**

- Consumes: `_legacy_kernel` and `_append_option` from Task 1.
- Produces: frozen `ReContinueRequest`, `ReResumeRequest`, `RePublishRequest`, `ReFinalizeRequest`, and `ReSynthesizeRequest`.
- Produces: `continue_re`, `resume_re`, `publish_re`, `finalize_re`, `synthesize_re`, `execute_re_run`, and `check_re_domain` with the design signatures.
- Establishes: no active RE Typer callback calls `_legacy_cli()` or imports `echelon.cli`.
- Establishes: `cli_app._legacy_cli` is deleted after its final caller is removed.

- [ ] **Step 1: Add failing typed-routing tests for the remaining routes**

Use the same request-equality pattern as Task 1. The principal expected values
are:

```python
ReContinueRequest(
    run_id="re-123",
    re_max_inner=3,
    re_token_limit=9000,
    re_time_limit_minutes=12,
    re_semantic_token_limit=4000,
    re_semantic_time_limit_minutes=6,
)

ReResumeRequest(
    answer="Use option 1",
    recommended=False,
    banzai=False,
    re_max_inner=3,
    re_token_limit=9000,
)

RePublishRequest(run_id="re-123", allow_partial=True, commit=True)
ReFinalizeRequest(run_id="re-123", allow_partial=True)

ReSynthesizeRequest(
    from_run="re-123",
    accept_partial=("api", "web"),
    token_limit=5000,
    active_ms_limit=60000,
)
```

For hidden commands, patch `execute_re_run` and `check_re_domain`, invoke the
Typer app, and assert exact keyword values.

- [ ] **Step 2: Confirm the remaining typed APIs are absent**

```bash
.venv/bin/python -m pytest -q tests/unit/test_re_service_boundary.py \
  -k 'continue or resume or publish or finalize or synthesize or execute or check_domain'
```

Expected: imports or monkeypatch resolution fail for the APIs not yet defined.

- [ ] **Step 3: Add the five remaining frozen requests**

Copy the exact field names, types, and defaults from the approved design. Add
the seven public functions with the design signatures. `execute_re_run` and
`check_re_domain` use keyword-only identifiers and no request dataclass.

- [ ] **Step 4: Write exact adapter-parity tests**

Assert these argument lists and handler selections:

```python
# continue
[
    "re-123", "--re-max-inner", "3", "--re-token-limit", "9000",
    "--re-time-limit-minutes", "12", "--re-semantic-token-limit", "4000",
    "--re-semantic-time-limit-minutes", "6",
]

# resume
[
    "Use option 1", "--recommended", "--re-max-inner", "3",
    "--re-token-limit", "9000", "--re-time-limit-minutes", "12",
    "--re-semantic-token-limit", "4000",
    "--re-semantic-time-limit-minutes", "6",
]

# publish, finalize, legacy synthesize
["re-123", "--allow-partial", "--commit"]
["re-123", "--allow-partial"]
[
    "re-123", "--allow-partial", "--re-token-limit", "9000",
    "--re-time-limit-minutes", "12",
]

# protocol-2.7 synthesize
[
    "--from-run", "re-parent", "--accept-partial", "api",
    "--accept-partial", "web", "--token-limit", "5000",
    "--active-ms-limit", "60000",
]

# hidden commands
["re-123"]
["re-123", "api", "billing"]
```

The resume parity fixture deliberately sets `recommended=True` with an answer;
the Typer boundary normally rejects conflicting modes, while the facade's only
job is deterministic transport parity.

- [ ] **Step 5: Implement the remaining adapters**

Emit optional positional values first, then flags/options in the exact existing
order. `synthesize_re` selects the protocol-2.7 shape when `from_run` is not
`None`; otherwise it emits the legacy shape. Call the unchanged handlers:

```python
_cmd_re_continue
_cmd_re_resume
_cmd_re_publish
_cmd_re_finalize
_cmd_re_synthesize
_cmd_re_execute_run
_cmd_re_check_domain
```

Do not catch `SystemExit`, translate exceptions, or import protocol modules.

- [ ] **Step 6: Redirect the remaining Typer callbacks and delete `_legacy_cli`**

Keep all existing cross-option `BadParameter` branches in resume and
synthesize. Replace argument-vector construction with frozen requests and
direct facade calls. Route the hidden commands using keyword arguments. Then
run:

```bash
rg -n '_legacy_cli\(' src/echelon/cli_app.py
```

Expected before deletion: only the `_legacy_cli` definition remains. Delete
that unused definition and repeat the search; expected result is no matches.

- [ ] **Step 7: Add structural quarantine guards**

Add these exact callback names:

```python
ACTIVE_RE_CALLBACKS = {
    "re_run", "re_refresh", "re_deepen", "re_status", "re_continue",
    "re_resume", "re_publish", "re_finalize", "re_synthesize",
    "re_execute_run", "re_check_domain",
}
```

For each callback, inspect source and assert it contains neither
`_legacy_cli(`, `echelon import cli`, nor `echelon.cli import`. Assert
`not hasattr(echelon.cli_app, "_legacy_cli")`. Inspect `re_service.py` and
assert the only legacy import text is inside `_legacy_kernel`; assert no import
path begins with `harness.re_v2` so protocol implementation has not leaked into
the facade.

- [ ] **Step 8: Migrate Typer mocks while preserving direct kernel tests**

Update `test_cli_typer_app.py` and any test that invokes the Typer callback to
patch `echelon.re_service`. Keep imports in tests that call `_cmd_re_*`
directly, including lifecycle/protocol behavior tests. A test's invocation
style—not its filename—decides whether it migrates.

- [ ] **Step 9: Run focused facade and RE behavior verification**

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_re_service_boundary.py tests/unit/test_cli_typer_app.py \
  tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_re_publish.py \
  tests/unit/test_cli_re_check_domain.py \
  tests/unit/test_cli_re_v2_protocol_22.py \
  tests/unit/test_cli_re_v2_protocol_24.py \
  tests/unit/test_cli_re_v2_protocol_25.py \
  tests/unit/test_cli_re_v2_protocol_27.py \
  tests/integration/test_re_v2_protocol_28_cli.py
```

Expected: all selected tests pass.

- [ ] **Step 10: Run the CLI regression gate**

```bash
.venv/bin/python -m pytest -q tests/unit/test_cli_*.py tests/unit/test_re_*.py
```

Expected: all applicable tests pass. Any failure must reproduce on design
commit `bfdb744c` before it is classified as pre-existing.

- [ ] **Step 11: Commit the completed quarantine facade**

```bash
git add src/echelon/re_service.py src/echelon/cli_app.py \
  tests/unit/test_re_service_boundary.py tests/unit/test_cli_typer_app.py \
  tests/unit/test_cli_re_lifecycle.py tests/unit/test_cli_re_v2_protocol_25.py \
  tests/unit/test_cli_re_v2_protocol_27.py \
  tests/unit/test_cli_re_check_domain.py \
  tests/integration/test_re_v2_protocol_28_cli.py
git commit -m "refactor: route active re commands through typed facade"
```

---

### Task 3: Verify S3 Completion and Activate S4

**Files:**

- Modify: `docs/findings/2026-09-21-typer-route-inventory.md`
- Modify: `docs/simplification-control.md`
- Create: generated receipt under `tests/reports/merge-verification/`

**Interfaces:**

- Consumes: all eleven facade routes and structural guards from Tasks 1–2.
- Produces: executable-tree recount with 104 public modular routes and zero direct public/hidden `_legacy_cli()` consumers, subject to measured truth.
- Produces: passing repository evidence against design commit `bfdb744c`.
- Produces: S3 `DONE`, S4 `ACTIVE`, and an explicit RE-kernel quarantine entry assigned to S6.

- [ ] **Step 1: Run structural acceptance**

```bash
rg -n '_legacy_cli\(' src/echelon/cli_app.py
.venv/bin/python -m pytest -q tests/unit/test_re_service_boundary.py
```

Expected: the search returns no matches and all facade boundary tests pass.

- [ ] **Step 2: Recount the executable command tree**

Traverse `typer.main.get_command(app)` recursively, inherit parent `hidden`
flags, unwrap each leaf callback, and inspect direct source for `_legacy_cli()`.
Record public, hidden, public direct-legacy, hidden direct-legacy, and modular
public totals. Expected values are 104 public, 23 hidden, zero direct legacy in
both groups, and 104 modular public commands; use measured results.

- [ ] **Step 3: Run repository merge verification**

```bash
.venv/bin/python scripts/merge_verification.py plan --base bfdb744c
.venv/bin/python scripts/merge_verification.py run --base bfdb744c
```

Expected: the planned full-unit gate passes and writes a receipt. Preserve the
single running process, then record exact pass, skip, deselection, failure, and
duration totals.

- [ ] **Step 4: Update route inventory and milestone control**

Move the nine public RE routes to the modular table and record both hidden RE
commands as typed facade routes. State explicitly that `re_service` is the
single quarantine adapter and `cli.py` retains the protocol kernel for S6.

In `docs/simplification-control.md`:

- mark every S3 work-queue item complete;
- change S3 from `ACTIVE` to `DONE` with exact verification evidence;
- change the current milestone to S4;
- change S4 from `PENDING` to `ACTIVE`;
- record that S4's next action is an inventory of durable Delivery controller
  steps before any decomposition;
- keep S6 pending and responsible for RE protocol consolidation.

- [ ] **Step 5: Check and commit evidence**

```bash
git diff --check
git status --short
git add docs/findings/2026-09-21-typer-route-inventory.md \
  docs/simplification-control.md tests/reports/merge-verification
git commit -m "docs: complete typer cutover milestone"
```

Expected before commit: only the two tracking documents and generated receipt
are uncommitted.

- [ ] **Step 6: Verify final state**

```bash
git status --short
git log -5 --oneline
```

Expected: clean status; S3 is done, S4 is active, and no implementation of S4
or S6 has begun.
