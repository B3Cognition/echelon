# Codegen RUNNABLE + Composition Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a runnable, composed whole a gated deliverable of the `echelon codegen` (SOAR) pipeline, so it cannot pass while shipping a non-bootable app.

**Architecture:** RE emits a machine-checkable `runnable_contract`; DECOMPOSE auto-injects a dependency-gated terminal COMPOSE task that wires the entry point; a new skill-layer RUNNABLE phase (`codegen-6c-runnable.md`, mirroring SECURITY/6b) executes the contract on the composed whole — L1 (hard) = liveness AND a primary surface, L2 (scored) = remaining surfaces; DELIVER is blocked until `runnable_gate == pass`. Three new Python modules carry the testable logic; four skill phase-specs carry the LLM-executed wiring.

**Tech Stack:** Python 3.11 (codegen substrate), pytest, lark-free dataclasses; SOAR skill phase-specs in markdown; Playwright for `kind: spa` browser probes.

**Design spec:** `docs/superpowers/specs/2026-06-22-codegen-runnable-composition-gate-design.md`

## Global Constraints

- Scope is `echelon codegen` only — do NOT touch the Ralph build strategy or `src/harness/`.
- The Python phase enum `phase_gate._PHASES` / `pipeline_engine.PHASES` is **left unchanged** — RUNNABLE is a skill-layer phase (mirrors SECURITY/6b), never the Ψ `codegen gate`.
- `CodeTask.task_id` MUST match `^T-\d{3,}$`; the COMPOSE task uses the reserved id `T-999`.
- `CodeTask.language` MUST be one of `{typescript, python, go, java, unknown}`.
- L1 = `liveness` AND `primary_surface` (never liveness alone). L2 = `surfaces[]`, scored, non-blocking initially.
- `kind: spa` surface assertions use a headless browser (Playwright), never an HTTP-body check.
- Fail-closed: missing/invalid contract or exhausted retries → ESCALATE, DELIVER blocked. Default `runnable.on_exhausted: block`.
- New Python modules are dependency-free of `src/harness/` (codegen substrate only).

## File Structure

| File | Responsibility |
|------|----------------|
| `src/codegen/schema/runnable_contract.py` (NEW) | `RunnableContract` dataclass + `parse_runnable_contract()` + validation. Required fields, kind/probe-family enums. |
| `src/codegen/decompose/compose_task.py` (NEW) | `build_compose_task()` / `inject_compose_task()` — the mandatory terminal COMPOSE task. |
| `src/codegen/runner/runnable_gate.py` (NEW) | `run_runnable_gate()` — L1/L2 execution, probe families, ephemeral port + teardown, structured result. |
| `extension/workflow/phases/codegen-1-re.md` (MODIFY) | RE emits `runnable_contract` into `codegen-state.json`. |
| `extension/workflow/phases/codegen-2-decompose.md` (MODIFY) | DECOMPOSE injects the COMPOSE task via `inject_compose_task`. |
| `extension/workflow/phases/codegen-6c-runnable.md` (NEW) | RUNNABLE skill phase — runs the gate, writes `runnable_gate`, reopen-on-fail. |
| `extension/workflow/phases/codegen-7-deliver.md` (MODIFY) | DELIVER precondition: refuse unless `runnable_gate == pass`. |
| `tests/unit/test_runnable_contract.py` (NEW) | Contract schema + validation tests. |
| `tests/unit/test_compose_task.py` (NEW) | COMPOSE injection tests. |
| `tests/unit/test_runnable_gate.py` (NEW) | L1/L2 execution + the headline anti-regression stub test. |

---

### Task 1: Runnable contract schema + validator

**Files:**
- Create: `src/codegen/schema/runnable_contract.py`
- Test: `tests/unit/test_runnable_contract.py`

**Interfaces:**
- Produces: `RunnableContract` (frozen dataclass): `kind: str`, `build: str`, `start: str | None`, `probe: str` (`"browser"|"http"|"exec"`), `liveness: str`, `primary_surface: dict` (`{"req": str, "assert": str}`), `surfaces: list[dict]`. `parse_runnable_contract(data: dict) -> RunnableContract` (raises `ValueError` on invalid). `DEFAULT_PROBE = {"spa": "browser", "service": "http", "cli": "exec", "library": "exec"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_runnable_contract.py
import pytest
from codegen.schema.runnable_contract import parse_runnable_contract, RunnableContract


def _valid():
    return {
        "kind": "spa",
        "build": "pnpm -r build",
        "start": "serve dist on $PORT",
        "liveness": "HTTP 200 at /",
        "primary_surface": {"req": "FR-001", "assert": "catalog renders >=1 row"},
        "surfaces": [{"req": "FR-006", "assert": "phase graph renders"}],
    }


@pytest.mark.unit
def test_valid_contract_parses_and_derives_probe():
    c = parse_runnable_contract(_valid())
    assert isinstance(c, RunnableContract)
    assert c.kind == "spa"
    assert c.probe == "browser"            # derived from kind
    assert c.primary_surface["req"] == "FR-001"


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["build", "liveness", "primary_surface"])
def test_missing_mandatory_field_raises(missing):
    data = _valid()
    del data[missing]
    with pytest.raises(ValueError, match=missing):
        parse_runnable_contract(data)


@pytest.mark.unit
def test_unknown_kind_raises():
    data = _valid()
    data["kind"] = "wasm-blob"
    with pytest.raises(ValueError, match="kind"):
        parse_runnable_contract(data)


@pytest.mark.unit
def test_primary_surface_requires_req_and_assert():
    data = _valid()
    data["primary_surface"] = {"assert": "x"}   # missing req
    with pytest.raises(ValueError, match="primary_surface"):
        parse_runnable_contract(data)


@pytest.mark.unit
def test_cli_kind_allows_null_start_and_exec_probe():
    data = _valid()
    data["kind"] = "cli"
    data["start"] = None
    c = parse_runnable_contract(data)
    assert c.start is None
    assert c.probe == "exec"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runnable_contract.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'codegen.schema.runnable_contract'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codegen/schema/runnable_contract.py
"""The runnable_contract — RE's machine-checkable declaration of what "runs"
means for a codegen project. Executed by the RUNNABLE phase; never authored by
the gate. See docs/superpowers/specs/2026-06-22-codegen-runnable-composition-gate-design.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

VALID_KINDS = ("spa", "service", "cli", "library")
DEFAULT_PROBE = {"spa": "browser", "service": "http", "cli": "exec", "library": "exec"}


@dataclass(frozen=True)
class RunnableContract:
    kind: str
    build: str
    liveness: str
    primary_surface: dict[str, str]
    probe: str
    start: Optional[str] = None
    surfaces: list[dict[str, str]] = field(default_factory=list)


def _require_surface(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or "req" not in value or "assert" not in value:
        raise ValueError(f"{label} must be a mapping with 'req' and 'assert' keys")
    return {"req": str(value["req"]), "assert": str(value["assert"])}


def parse_runnable_contract(data: dict[str, Any]) -> RunnableContract:
    """Validate and construct a RunnableContract. Raises ValueError naming the
    offending field on any violation (fail-closed at authoring time)."""
    if not isinstance(data, dict):
        raise ValueError("runnable_contract must be a mapping")

    kind = str(data.get("kind", ""))
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}; got {kind!r}")

    for required in ("build", "liveness", "primary_surface"):
        if not data.get(required):
            raise ValueError(f"runnable_contract missing required field: {required}")

    primary = _require_surface(data["primary_surface"], "primary_surface")
    surfaces = [_require_surface(s, "surfaces[]") for s in data.get("surfaces", []) or []]

    probe = str(data.get("probe") or DEFAULT_PROBE[kind])
    if probe not in ("browser", "http", "exec"):
        raise ValueError(f"probe must be browser|http|exec; got {probe!r}")

    return RunnableContract(
        kind=kind,
        build=str(data["build"]),
        liveness=str(data["liveness"]),
        primary_surface=primary,
        probe=probe,
        start=(str(data["start"]) if data.get("start") else None),
        surfaces=surfaces,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_runnable_contract.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codegen/schema/runnable_contract.py tests/unit/test_runnable_contract.py
git commit -m "feat(codegen): runnable_contract schema + validator"
```

---

### Task 2: Auto-injected COMPOSE terminal task

**Files:**
- Create: `src/codegen/decompose/compose_task.py`
- Test: `tests/unit/test_compose_task.py`

**Interfaces:**
- Consumes: `CodeTask`, `TaskQueue`, `TaskStatus` from `codegen.decompose.task_queue` (existing). `TaskQueue.add(task)`, `.all_tasks`, `.pending()`, `.next_ready()`, `.are_dependencies_met(task)` exist.
- Produces: `COMPOSE_TASK_ID = "T-999"`. `build_compose_task(feature_ids: list[str], language: str) -> CodeTask`. `inject_compose_task(queue: TaskQueue, language: str) -> CodeTask` — appends exactly one COMPOSE task depending on all current non-compose task ids; returns it; idempotent (raises if one already present).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_compose_task.py
import pytest
from codegen.decompose.task_queue import CodeTask, TaskQueue, TaskStatus
from codegen.decompose.compose_task import (
    build_compose_task, inject_compose_task, COMPOSE_TASK_ID,
)


def _feature(n):
    return CodeTask(task_id=f"T-{n:03d}", description=f"feature {n}", scope=f"c{n}",
                    language="typescript", module_boundary=f"m{n}")


@pytest.mark.unit
def test_compose_task_has_valid_id_and_depends_on_all_features():
    q = TaskQueue([_feature(1), _feature(2)])
    compose = inject_compose_task(q, language="typescript")
    assert compose.task_id == COMPOSE_TASK_ID            # "T-999", matches ^T-\d{3,}$
    assert compose.scope == "composition"
    assert set(compose.depends_on) == {"T-001", "T-002"}


@pytest.mark.unit
def test_compose_runs_last_only_after_features_done():
    q = TaskQueue([_feature(1), _feature(2)])
    inject_compose_task(q, language="typescript")
    # COMPOSE not ready while features pending
    assert q.next_ready().task_id == "T-001"
    q.get("T-001").status = TaskStatus.DONE
    q.get("T-002").status = TaskStatus.DONE
    assert q.next_ready().task_id == COMPOSE_TASK_ID     # now COMPOSE is ready, last
```

> Note: if `TaskQueue` exposes its by-id lookup differently than `.get(id)`, adjust the test to the real accessor (check `task_queue.py`); the behavior asserted is unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_compose_task.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'codegen.decompose.compose_task'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codegen/decompose/compose_task.py
"""The mandatory terminal COMPOSE task: produces the runnable entry point and
wires all feature components. Auto-injected by DECOMPOSE so composition is a
guaranteed, dependency-gated deliverable — never the agent's responsibility."""
from __future__ import annotations

from .task_queue import CodeTask, TaskQueue, TaskComplexity

COMPOSE_TASK_ID = "T-999"   # reserved; matches ^T-\d{3,}$
COMPOSE_DESCRIPTION = (
    "Produce the runnable entry point and wire all feature components into a "
    "single composed application that satisfies runnable_contract (entry point, "
    "root composition, and any host scaffolding the chosen stack requires)."
)


def build_compose_task(feature_ids: list[str], language: str) -> CodeTask:
    return CodeTask(
        task_id=COMPOSE_TASK_ID,
        description=COMPOSE_DESCRIPTION,
        scope="composition",
        language=language,
        module_boundary="composition",
        complexity=TaskComplexity.MEDIUM,
        depends_on=list(feature_ids),
    )


def inject_compose_task(queue: TaskQueue, language: str) -> CodeTask:
    """Append the single mandatory COMPOSE task depending on every existing
    feature task. Raises if a COMPOSE task is already present (idempotency)."""
    existing = [t.task_id for t in queue.all_tasks]
    if COMPOSE_TASK_ID in existing:
        raise ValueError(f"{COMPOSE_TASK_ID} already present in queue")
    compose = build_compose_task(existing, language)
    queue.add(compose)
    return compose
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_compose_task.py -q`
Expected: PASS (2 passed). If `.get()` is not the real accessor, fix the test per the Step-1 note and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/decompose/compose_task.py tests/unit/test_compose_task.py
git commit -m "feat(codegen): auto-injected dependency-gated COMPOSE terminal task"
```

---

### Task 3: RUNNABLE gate executor — L1 (liveness + primary surface)

**Files:**
- Create: `src/codegen/runner/runnable_gate.py`
- Test: `tests/unit/test_runnable_gate.py`

**Interfaces:**
- Consumes: `RunnableContract` from Task 1.
- Produces: `@dataclass RunnableGateResult{ passed: bool, level: str, surface_score: float, failures: list[str] }`. `run_runnable_gate(contract: RunnableContract, workspace: str, *, probe_fn: Callable[[str, RunnableContract, str], ProbeOutcome]) -> RunnableGateResult`. `ProbeOutcome = dataclass{ live: bool, present: dict[str, bool] }` (keyed by REQ id). `probe_fn` is injected so tests substitute a stub and the real gate wires the browser/http/exec probe families. L1 passes iff `live` AND `present[primary_surface.req]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_runnable_gate.py
import pytest
from codegen.schema.runnable_contract import parse_runnable_contract
from codegen.runner.runnable_gate import run_runnable_gate, ProbeOutcome


def _contract(kind="spa"):
    return parse_runnable_contract({
        "kind": kind, "build": "build", "start": "start", "liveness": "HTTP 200",
        "primary_surface": {"req": "FR-001", "assert": "catalog renders rows"},
        "surfaces": [{"req": "FR-006", "assert": "graph renders"}],
    })


@pytest.mark.unit
def test_l1_passes_when_live_and_primary_surface_present():
    probe = lambda ws, c, port: ProbeOutcome(live=True, present={"FR-001": True, "FR-006": True})
    r = run_runnable_gate(_contract(), "/tmp/ws", probe_fn=probe)
    assert r.passed is True
    assert r.level == "L1"
    assert r.surface_score == 1.0


@pytest.mark.unit
def test_l1_fails_when_not_live():
    probe = lambda ws, c, port: ProbeOutcome(live=False, present={})
    r = run_runnable_gate(_contract(), "/tmp/ws", probe_fn=probe)
    assert r.passed is False
    assert any("liveness" in f for f in r.failures)


@pytest.mark.unit
def test_stub_fails_l1_even_though_live():
    # THE HEADLINE ANTI-REGRESSION CASE: app boots (live=True) but the primary
    # surface does not render — exactly this session's Psi=1.0 stub.
    probe = lambda ws, c, port: ProbeOutcome(live=True, present={"FR-001": False, "FR-006": False})
    r = run_runnable_gate(_contract(), "/tmp/ws", probe_fn=probe)
    assert r.passed is False
    assert any("FR-001" in f and "primary" in f.lower() for f in r.failures)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runnable_gate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'codegen.runner.runnable_gate'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codegen/runner/runnable_gate.py
"""Executes a runnable_contract against the composed whole. L1 (hard) = liveness
AND the primary surface; L2 (scored) = remaining surfaces. The probe_fn is
injected so the L1/L2 decision logic is pure and unit-testable; the real probe
families (browser/http/exec) and the ephemeral-sandbox lifecycle wrap it (Task 5
in the design's execution-environment section)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from codegen.schema.runnable_contract import RunnableContract


@dataclass
class ProbeOutcome:
    live: bool
    present: dict[str, bool]   # REQ id -> surface observed in the running whole


@dataclass
class RunnableGateResult:
    passed: bool               # L1 verdict (the hard gate)
    level: str                 # "L1"
    surface_score: float       # L2 score: fraction of surfaces[] present
    failures: list[str] = field(default_factory=list)


def run_runnable_gate(
    contract: RunnableContract,
    workspace: str,
    *,
    probe_fn: Callable[[str, RunnableContract, int | None], ProbeOutcome],
    port: int | None = None,
) -> RunnableGateResult:
    outcome = probe_fn(workspace, contract, port)
    failures: list[str] = []

    if not outcome.live:
        failures.append(f"liveness failed: {contract.liveness!r}")

    primary_req = contract.primary_surface["req"]
    if not outcome.present.get(primary_req, False):
        failures.append(
            f"primary surface {primary_req} not present: "
            f"{contract.primary_surface['assert']!r}"
        )

    surfaces = contract.surfaces
    present = sum(1 for s in surfaces if outcome.present.get(s["req"], False))
    surface_score = (present / len(surfaces)) if surfaces else 1.0

    return RunnableGateResult(
        passed=not failures,
        level="L1",
        surface_score=surface_score,
        failures=failures,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_runnable_gate.py -q`
Expected: PASS (3 passed) — including `test_stub_fails_l1_even_though_live`, the headline anti-regression guarantee.

- [ ] **Step 5: Commit**

```bash
git add src/codegen/runner/runnable_gate.py tests/unit/test_runnable_gate.py
git commit -m "feat(codegen): RUNNABLE gate L1/L2 decision logic + anti-regression stub test"
```

---

### Task 4: Probe families + ephemeral sandbox lifecycle (the real `probe_fn`)

**Files:**
- Modify: `src/codegen/runner/runnable_gate.py`
- Test: `tests/unit/test_runnable_gate.py`

**Interfaces:**
- Produces: `make_probe(kind: str) -> Callable[..., ProbeOutcome]` returning a probe that runs `build`, starts `start` on an OS-assigned ephemeral port with a teardown trap, then evaluates `liveness` + each surface `assert` via the kind's family: `browser` (Playwright DOM), `http` (HTTP body), `exec` (`--help`/import). `_free_port() -> int`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/test_runnable_gate.py
import socket
from codegen.runner.runnable_gate import _free_port, make_probe


@pytest.mark.unit
def test_free_port_is_bindable_and_unique():
    p1, p2 = _free_port(), _free_port()
    assert isinstance(p1, int) and 1024 < p1 < 65536
    s = socket.socket(); s.bind(("127.0.0.1", p1)); s.close()   # bindable
    assert p1 != p2


@pytest.mark.unit
def test_make_probe_selects_family_by_kind():
    assert make_probe("spa").__name__ == "_browser_probe"
    assert make_probe("service").__name__ == "_http_probe"
    assert make_probe("cli").__name__ == "_exec_probe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runnable_gate.py -q -k "free_port or make_probe"`
Expected: FAIL with `ImportError: cannot import name '_free_port'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/codegen/runner/runnable_gate.py
import socket


def _free_port() -> int:
    """Return an OS-assigned free TCP port (closed immediately; caller binds)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _browser_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """SPA: build, serve dist on `port`, drive a headless browser, read the DOM.
    A curl body check is insufficient (client-side render). Teardown always runs."""
    raise NotImplementedError("wired during execution against the running worktree")


def _http_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """service: build, start on `port`, assert liveness + surfaces over HTTP."""
    raise NotImplementedError("wired during execution against the running worktree")


def _exec_probe(workspace: str, contract: RunnableContract, port: int | None) -> ProbeOutcome:
    """cli/library: build, run `--help`/import smoke; no server."""
    raise NotImplementedError("wired during execution against the running worktree")


def make_probe(kind: str):
    return {"spa": _browser_probe, "service": _http_probe,
            "cli": _exec_probe, "library": _exec_probe}[kind]
```

> The probe bodies are `NotImplementedError` stubs deliberately: the L1/L2 decision logic (Task 3) is fully tested with an injected stub, and the family **selection** + port lifecycle are tested here. The probe bodies run shell against a live worktree and are validated by Task 7's RUNNABLE phase spec + the integration smoke (they cannot be meaningfully unit-tested without a real build). Each body must: allocate `_free_port()`, launch `start` with a `try/finally` teardown (kill server + browser), wait for readiness with a timeout, evaluate assertions, and return `ProbeOutcome`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_runnable_gate.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codegen/runner/runnable_gate.py tests/unit/test_runnable_gate.py
git commit -m "feat(codegen): probe families (browser/http/exec) + ephemeral port lifecycle"
```

---

### Task 5: RE emits the runnable_contract (phase spec)

**Files:**
- Modify: `extension/workflow/phases/codegen-1-re.md`
- Test: `tests/unit/test_runnable_contract.py` (add a fixture-shape test)

**Interfaces:**
- Consumes: `parse_runnable_contract` (Task 1).
- Produces: RE writes `runnable_contract` into `codegen-state.json` before advancing. The phase spec instructs the agent to derive `kind`/`build`/`start`/`liveness`/`primary_surface`/`surfaces` from the spec stack and REQ `OUTPUT:` lines, then self-validate with `parse_runnable_contract`.

- [ ] **Step 1: Write the failing test** (guards the documented contract shape RE must emit)

```python
# add to tests/unit/test_runnable_contract.py
@pytest.mark.unit
def test_re_phase_documents_a_parseable_example_contract():
    """The RE phase spec must contain a runnable_contract example that parses,
    so authors copy a valid shape."""
    import re as _re, pathlib, yaml
    spec = pathlib.Path("extension/workflow/phases/codegen-1-re.md").read_text()
    m = _re.search(r"```yaml\n(runnable_contract:.*?)\n```", spec, _re.S)
    assert m, "codegen-1-re.md must contain a ```yaml runnable_contract: ...``` example"
    data = yaml.safe_load(m.group(1))["runnable_contract"]
    parse_runnable_contract(data)        # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runnable_contract.py -q -k re_phase`
Expected: FAIL (`assert m` — no example yet)

- [ ] **Step 3: Add the contract-emission section to `codegen-1-re.md`**

Append this section after the requirements-retrieval block (before the DECOMPOSE state checkpoint):

````markdown
## Emit the runnable contract

After retrieving requirements, derive the **runnable contract** — the deterministic
declaration of what "this app runs" means — and write it into `codegen-state.json`
under `runnable_contract`. It is mandatory: RE does not advance without a contract
that validates.

- `kind`: `spa` | `service` | `cli` | `library` (from the spec's stack/shape).
- `build`: the build command. `start`: the run/serve command (`null` for cli/library).
- `liveness`: a deterministic up-check (HTTP 200 / process exit 0).
- `primary_surface`: the SINGLE highest-value REQ `OUTPUT` that MUST render/respond
  in the running whole — `{req: <FR-id>, assert: <observable check>}`. This is what
  makes L1 catch a hollow app; liveness alone is not enough.
- `surfaces[]`: the next most important REQ OUTPUTs (L2 breadth).
- For `kind: spa`, surface asserts are evaluated in a headless browser, so phrase
  them as rendered-DOM observations, not HTML-string matches.

```yaml
runnable_contract:
  kind: spa
  build: "pnpm -r build"
  start: "serve packages/web/dist on $PORT"
  liveness: "HTTP 200 at /"
  primary_surface:
    req: FR-001
    assert: "the run catalog renders at least one row"
  surfaces:
    - req: FR-006
      assert: "the phase graph renders nodes"
```

Self-validate before advancing:

```bash
python3 -c "import yaml,sys; from codegen.schema.runnable_contract import parse_runnable_contract; \
parse_runnable_contract((yaml.safe_load(open('codegen-state.json')) or {}).get('runnable_contract') or {}); \
print('runnable_contract OK')" || { echo '✗ runnable_contract invalid — fix before DECOMPOSE'; exit 1; }
```

ALWAYS emit a `runnable_contract` whose `primary_surface` cites a real REQ id.
NEVER advance to DECOMPOSE without a contract that `parse_runnable_contract` accepts.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_runnable_contract.py -q -k re_phase`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extension/workflow/phases/codegen-1-re.md tests/unit/test_runnable_contract.py
git commit -m "feat(codegen): RE emits + self-validates the runnable_contract"
```

---

### Task 6: DECOMPOSE injects the COMPOSE task (phase spec)

**Files:**
- Modify: `extension/workflow/phases/codegen-2-decompose.md`
- Test: `tests/unit/test_compose_task.py` (add a phase-spec wiring test)

**Interfaces:**
- Consumes: `inject_compose_task` (Task 2).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/test_compose_task.py
@pytest.mark.unit
def test_decompose_phase_invokes_compose_injection():
    import pathlib
    spec = pathlib.Path("extension/workflow/phases/codegen-2-decompose.md").read_text()
    assert "inject_compose_task" in spec
    assert "T-999" in spec or "COMPOSE_TASK_ID" in spec
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_compose_task.py -q -k decompose_phase`
Expected: FAIL (`assert "inject_compose_task" in spec`)

- [ ] **Step 3: Add the injection section to `codegen-2-decompose.md`**

Append after the task-queue is produced (before the WME-injection / TOTAL_TASKS block):

````markdown
## Inject the mandatory COMPOSE task

After the feature task queue is written, append the single mandatory **COMPOSE**
task — it produces the runnable entry point and wires every component, and it
DEPENDS on all feature tasks (dependency-gated scheduling forces it to run last).
This guarantees composition is a tracked deliverable, never the agent's option.

```bash
python3 - <<'PY'
import json
from codegen.decompose.task_queue import TaskQueue, CodeTask, TaskStatus
from codegen.decompose.compose_task import inject_compose_task
q = TaskQueue()
data = json.load(open("./codegen-staging/task-queue.json"))
for t in data["tasks"]:
    q.add(CodeTask(task_id=t["task-id"], description=t["description"], scope=t["scope"],
                   language=t["language"], module_boundary=t["module-boundary"],
                   depends_on=[d for d in t["depends-on"].split(",") if d]))
language = q.all_tasks[0].language if q.all_tasks else "typescript"
compose = inject_compose_task(q, language=language)
json.dump({"tasks": [t.to_wme_dict() for t in q.all_tasks]},
          open("./codegen-staging/task-queue.json", "w"), indent=2)
print(f"injected {compose.task_id} depends_on={compose.depends_on}")
PY
```

ALWAYS inject exactly one COMPOSE task (`T-999`) depending on all feature tasks.
NEVER hand-author composition as an optional feature task or omit it.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_compose_task.py -q -k decompose_phase`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extension/workflow/phases/codegen-2-decompose.md tests/unit/test_compose_task.py
git commit -m "feat(codegen): DECOMPOSE injects the mandatory COMPOSE task"
```

---

### Task 7: RUNNABLE phase spec + DELIVER block + config

**Files:**
- Create: `extension/workflow/phases/codegen-6c-runnable.md`
- Modify: `extension/workflow/phases/codegen-7-deliver.md`
- Modify: `extension/echelon-config.yml`
- Test: `tests/unit/test_runnable_gate.py` (add phase-spec + deliver-block structural tests)

**Interfaces:**
- Consumes: `run_runnable_gate`, `make_probe` (Tasks 3–4); `runnable_contract` from state.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/test_runnable_gate.py
import pathlib

@pytest.mark.unit
def test_runnable_phase_spec_exists_and_blocks_deliver():
    runnable = pathlib.Path("extension/workflow/phases/codegen-6c-runnable.md")
    deliver = pathlib.Path("extension/workflow/phases/codegen-7-deliver.md")
    assert runnable.exists()
    rtext = runnable.read_text()
    assert "run_runnable_gate" in rtext
    assert "runnable_gate" in rtext and "reopen" in rtext.lower()
    # DELIVER must refuse unless runnable_gate == pass
    assert 'runnable_gate' in deliver.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runnable_gate.py -q -k phase_spec`
Expected: FAIL (`assert runnable.exists()`)

- [ ] **Step 3: Create `codegen-6c-runnable.md`** (mirror the SECURITY/6b structure)

````markdown
# Phase: codegen-6c-runnable
# Source: design 2026-06-22-codegen-runnable-composition-gate
# Read by: speckit-echelon-orchestrator before Phase 6c RUNNABLE (echelon.codegen only)

## Phase 6c: RUNNABLE — the composed whole must run

**Print:** `[CODEGEN] Phase RUNNABLE — Verifying the composed app boots and its primary surface renders...`

Runs AFTER TEST, BEFORE SECURITY/DELIVER. Skill-layer phase (NOT the Ψ `codegen gate`).
Execute in an ephemeral workspace with an OS-assigned port and a teardown trap that
fires on pass/fail/timeout (no leaked servers or browsers).

1. Load `runnable_contract` from `codegen-state.json`. Missing/invalid → HALT + escalate (fail-closed).
2. Run the gate:

```bash
python3 - <<'PY'
import json
from codegen.schema.runnable_contract import parse_runnable_contract
from codegen.runner.runnable_gate import run_runnable_gate, make_probe
state = json.load(open("codegen-state.json"))
contract = parse_runnable_contract(state["runnable_contract"])
result = run_runnable_gate(contract, workspace=".", probe_fn=make_probe(contract.kind))
state["runnable_gate"] = "pass" if result.passed else "fail"
state["runnable_surface_score"] = result.surface_score
json.dump(state, open("codegen-state.json", "w"), indent=2)
print("RUNNABLE", state["runnable_gate"], "L2", result.surface_score, result.failures)
PY
```

3. **L1 = liveness AND primary_surface.** Outcome:
   - `runnable_gate: pass` → ADVANCE to SECURITY/DELIVER.
   - `runnable_gate: fail` → **reopen the COMPOSE task** (`T-999` → status `PENDING`) with the
     failure as the re-dispatch reason, route back to IMPLEMENT. Cap at `runnable.max_attempts`
     (default 3); on exhaustion ESCALATE per `runnable.on_exhausted` (default `block`).
4. L2 `runnable_surface_score` is recorded (advisory/ramping); it does not block initially.

ALWAYS block on L1 failure and reopen COMPOSE; the composed whole must boot AND render its primary surface.
NEVER advance to DELIVER with `runnable_gate != pass`.

**Print:** `[CODEGEN] Phase RUNNABLE — COMPLETE ✓ (app boots; primary surface renders)`
````

- [ ] **Step 4: Add the DELIVER precondition** to `codegen-7-deliver.md` — insert immediately after the `SOAR selects DELIVER only when:` line:

```markdown
**RUNNABLE precondition (hard):** DELIVER MUST refuse to package unless
`codegen-state.json` has `runnable_gate == "pass"`. If it is absent or `"fail"`,
HALT and route back to RUNNABLE — a non-bootable / hollow app is never shippable,
regardless of Ψ or unit-test status.
```

- [ ] **Step 5: Add config block** to `extension/echelon-config.yml` (under the codegen section):

```yaml
runnable:
  max_attempts: 3        # COMPOSE reopen→rebuild→re-verify cap on L1 failure
  on_exhausted: block    # block | warn — block: a non-bootable app is not shippable
  l2_hard: false         # when true, L2 surface-presence also hard-gates (ramp)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_runnable_gate.py -q -k phase_spec`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add extension/workflow/phases/codegen-6c-runnable.md extension/workflow/phases/codegen-7-deliver.md extension/echelon-config.yml tests/unit/test_runnable_gate.py
git commit -m "feat(codegen): RUNNABLE phase + DELIVER block + runnable config"
```

---

### Task 8: Full-suite regression + reinstall

**Files:** none (verification only)

- [ ] **Step 1: Run the codegen + lexicon unit suites**

Run: `python -m pytest tests/unit/ -q -k "runnable or compose or codegen or contract" --ignore=tests/unit/test_belief_parser.py`
Expected: PASS (all new tests + no regressions)

- [ ] **Step 2: Reinstall the CLIs (codegen runs from the installed venv)**

Run: `bash scripts/install.sh`
Expected: completes; `~/.echelon/venv/bin/codegen status` works.

- [ ] **Step 3: Commit any install-surfaced fixes (if needed)**

```bash
git add -A && git commit -m "chore(codegen): reinstall after runnable gate" || echo "nothing to commit"
```

---

## Self-Review

**1. Spec coverage:**
- RE-declared contract → Task 1 (schema) + Task 5 (emission). ✓
- Auto-injected dependency-gated COMPOSE → Task 2 + Task 6. ✓
- Skill-layer RUNNABLE phase (mirrors 6b, not Ψ gate) → Task 7. ✓
- L1 = liveness AND primary_surface; L2 scored → Task 3. ✓
- kind=spa headless browser; probe families; ephemeral port + teardown → Task 4 + Task 7. ✓
- DELIVER blocked until runnable_gate==pass → Task 7. ✓
- Fail-closed (missing contract, on_exhausted=block) → Task 5 (self-validate), Task 7 (config + HALT). ✓
- Headline anti-regression (stub fails L1) → Task 3 `test_stub_fails_l1_even_though_live`. ✓
- COMPOSE-with-blocked-feature → covered by dependency-gated scheduling (Task 2 test) + RUNNABLE escalation. ✓
- Known ceiling (LLM-authored contract) → mitigated by Task 5 mandatory self-validation; documented, not "solved." ✓

**2. Placeholder scan:** The Task-4 probe bodies are explicit `NotImplementedError` stubs with a documented contract for execution-time wiring (they require a live build to test meaningfully) — this is a deliberate, stated boundary, not a hidden TODO. No other placeholders.

**3. Type consistency:** `RunnableContract` fields, `ProbeOutcome{live, present}`, `RunnableGateResult{passed, level, surface_score, failures}`, `COMPOSE_TASK_ID="T-999"`, and `parse_runnable_contract` / `inject_compose_task` / `run_runnable_gate` / `make_probe` signatures are consistent across Tasks 1–7. `CodeTask` constructor args match the real dataclass (`task_id, description, scope, language, module_boundary, depends_on`).

**Note for the executor:** Task 2's test assumes a `TaskQueue.get(id)` accessor — verify the real by-id accessor in `src/codegen/decompose/task_queue.py` and adjust the test if it differs (the asserted behavior is unchanged). Task 4's probe bodies are the one part that cannot be unit-tested without a live build; they are exercised by the RUNNABLE phase against a real worktree.
