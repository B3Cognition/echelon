# RADAR Mock Scenarios Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the RADAR mock server with 3 one-shot lifecycle scenarios, a recorder/replay system, a corrected /journal endpoint, and a UI protocol contract document.

**Architecture:** Changes flow outward from the data model: Scenario dataclass first → existing scenario updates → mock_server core → new lifecycle scenarios → replay module → recorder → infra/docs. Each task produces working, tested code that passes the full test suite before the next task starts.

**Tech Stack:** Python 3.12, Flask, dataclasses, threading, argparse, JSONL

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `radar/scenarios/__init__.py` | Add `initial_run`+`journal_entries` to Scenario; flip loop default; update imports |
| Modify | `radar/scenarios/default.py` | Add `initial_run`, `journal_entries: {}`; migrate display_name convention |
| Modify | `radar/scenarios/all_blocked.py` | Same as default.py |
| Modify | `radar/mock_server.py` | `create_app` signature; mock_snapshot with `run`; scenario_loop run_state_change branch; /journal replacement; --replay flag |
| Modify | `radar/tests/conftest.py` | Update fixtures for new create_app signature |
| Modify | `radar/tests/unit/test_journal_endpoint.py` | Replace tests for new array-returning /journal |
| Modify | `radar/tests/unit/test_scenario_data.py` | Add assertions for new Scenario fields |
| Create | `radar/scenarios/greenfield.py` | 13-agent happy-path lifecycle scenario |
| Create | `radar/scenarios/brownfield.py` | 14-agent lifecycle with GOLDDIGGER-1 |
| Create | `radar/scenarios/blocked_escalation.py` | 15-agent GATEKEEPER block + rework loop |
| Create | `radar/scenarios/replay.py` | `load_replay(filepath) -> Scenario` |
| Modify | `radar/server.py` | `--record PATH` flag + `_record_lock` JSONL appender |
| Modify | `config-template.yml` | Add `record: false` in radar block |
| Modify | `commands/cognitive-squad.run.md` | Add RADAR_RECORD_FLAG block |
| Create | `docs/radar-protocol-contract.md` | UI handover interface contract |
| Create | `radar/tests/unit/test_new_scenarios.py` | Tests for greenfield/brownfield/blocked-escalation |
| Create | `radar/tests/unit/test_replay.py` | Tests for load_replay |
| Create | `radar/tests/unit/test_recorder.py` | Tests for --record flag in server.py |

---

## Task 1: Scenario dataclass + existing scenario updates

**Files:**
- Modify: `radar/scenarios/__init__.py`
- Modify: `radar/scenarios/default.py`
- Modify: `radar/scenarios/all_blocked.py`
- Modify: `radar/tests/unit/test_scenario_data.py`

### Context

`Scenario` currently has no `initial_run` or `journal_entries` fields, and `loop` defaults to `True`. The new lifecycle scenarios need these fields; the mock_server.py changes in Task 2 depend on them being present on ALL scenarios including the existing two. Both fields need real data on `default` and `all-blocked` (not just empty dicts) so that Task 2's snapshot initialization works correctly.

The `display_name` convention in existing scenarios uses hyphens (`"Scout-1"`). New convention is title-case + space (`"Scout 1"`). Both files must be migrated.

- [ ] **Step 1: Write failing tests for new fields**

Add to `radar/tests/unit/test_scenario_data.py`:

```python
# --- New field assertions ---

def test_default_has_initial_run():
    s = get_scenario("default")
    assert isinstance(s.initial_run, dict)
    assert "run_id" in s.initial_run
    assert "status" in s.initial_run
    assert "phase" in s.initial_run

def test_default_has_journal_entries():
    s = get_scenario("default")
    assert isinstance(s.journal_entries, dict)

def test_all_blocked_has_initial_run():
    s = get_scenario("all-blocked")
    assert isinstance(s.initial_run, dict)
    assert "run_id" in s.initial_run

def test_all_blocked_has_journal_entries():
    s = get_scenario("all-blocked")
    assert isinstance(s.journal_entries, dict)

def test_default_display_names_space_convention():
    s = get_scenario("default")
    for a in s.initial_agents:
        assert "-" not in a.display_name, f"display_name uses hyphen: {a.display_name!r}"

def test_all_blocked_display_names_space_convention():
    s = get_scenario("all-blocked")
    for a in s.initial_agents:
        assert "-" not in a.display_name, f"display_name uses hyphen: {a.display_name!r}"

def test_default_loop_is_true():
    assert get_scenario("default").loop is True

def test_all_blocked_loop_is_false():
    assert get_scenario("all-blocked").loop is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/unit/test_scenario_data.py -v 2>&1 | tail -20
```
Expected: FAIL on `test_default_has_initial_run`, `test_default_has_journal_entries`, `test_all_blocked_has_initial_run`, `test_all_blocked_has_journal_entries`, `test_default_display_names_space_convention`, `test_all_blocked_display_names_space_convention`

- [ ] **Step 3: Update `radar/scenarios/__init__.py`**

Replace the `Scenario` dataclass and imports section:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MockAgent:
    """A single simulated agent for use in mock scenarios."""

    dispatch_id: str       # e.g. "SCOUT-1"
    codename: str          # e.g. "SCOUT"
    display_name: str      # e.g. "Scout 1"  (title-case, space before number)
    state: str             # "working" | "thinking" | "blocked" | "complete" | "error" | "idle" | "unknown"
    phase: str             # e.g. "discover"
    dispatched_at: str     # ISO 8601 UTC with trailing Z

    completed_at: Optional[str] = None
    blocked_reason: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.dispatch_id,
            "codename": self.codename,
            "display_name": self.display_name,
            "state": self.state,
            "phase": self.phase,
            "dispatched_at": self.dispatched_at,
        }
        if self.completed_at is not None:
            d["completed_at"] = self.completed_at
        if self.blocked_reason is not None:
            d["blocked_reason"] = self.blocked_reason
        return d


@dataclass
class ScenarioEvent:
    """A single event step inside a Scenario's event sequence."""

    event_type: str   # "agent_state_change" | "run_state_change" | "heartbeat"
    payload: dict
    delay_ms: int     # milliseconds to wait before emitting this event


@dataclass
class Scenario:
    """A complete mock scenario definition."""

    name: str
    description: str
    initial_agents: list            # list[MockAgent]
    event_sequence: list            # list[ScenarioEvent]
    initial_run: dict               # SquadRun dict for snapshot + run state tracking
    journal_entries: dict = field(default_factory=dict)  # keyed by dispatch_id
    loop: bool = False              # default False — one-shot is the new norm
```

Keep the registry section (`_REGISTRY`, `register`, `get_scenario`, `list_scenarios`) unchanged.

Replace the bottom import block:

```python
# ---------------------------------------------------------------------------
# Scenario modules register themselves on import:
from radar.scenarios import default as _default          # noqa: F401
from radar.scenarios import all_blocked as _all_blocked  # noqa: F401
# ---------------------------------------------------------------------------
```

- [ ] **Step 4: Update `radar/scenarios/default.py`**

Add `_INITIAL_RUN` dict and update the `Scenario(...)` call. Also migrate all `display_name` values from hyphen to space convention.

```python
"""
radar/scenarios/default.py — Default scenario.

Cycles all 8 mock agents through all 7 state values indefinitely.
Registers itself as "default" on import.
"""

from __future__ import annotations

from radar.mock_server import _now
from radar.scenarios import MockAgent, Scenario, ScenarioEvent, register

# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------

_INITIAL_RUN = {
    "run_id": "mock-run-default",
    "status": "running",
    "phase": "operations",
    "phase_display": "OPERATIONS",
    "iteration": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "completed_at": None,
}

# ---------------------------------------------------------------------------
# Initial agents (8 total — display_name uses "Agent N" space convention)
# ---------------------------------------------------------------------------

_AGENTS = [
    MockAgent(dispatch_id="MOCK-SCOUT-1", codename="SCOUT", display_name="Scout 1",
              state="working", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-SAGE-1", codename="SAGE", display_name="Sage 1",
              state="thinking", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-CARTOGRAPHER-1", codename="CARTOGRAPHER", display_name="Cartographer 1",
              state="idle", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-STRATEGIST-1", codename="STRATEGIST", display_name="Strategist 1",
              state="blocked", phase="OPERATIONS", dispatched_at=_now(),
              blocked_reason="Waiting for human decision"),
    MockAgent(dispatch_id="MOCK-ARCHITECT-1", codename="ARCHITECT", display_name="Architect 1",
              state="complete", phase="OPERATIONS", dispatched_at=_now(), completed_at=_now()),
    MockAgent(dispatch_id="MOCK-SENTINEL-1", codename="SENTINEL", display_name="Sentinel 1",
              state="error", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-BUILDER-1", codename="BUILDER", display_name="Builder 1",
              state="unknown", phase="OPERATIONS", dispatched_at=_now()),
    MockAgent(dispatch_id="MOCK-MANAGER-1", codename="MANAGER", display_name="Manager 1",
              state="working", phase="OPERATIONS", dispatched_at=_now()),
]
```

Keep `_EVENTS` unchanged. Update `Scenario(...)` constructor call:

```python
DEFAULT = Scenario(
    name="default",
    description="Cycles through all 7 agent states indefinitely (8 mock agents, ~35s per loop)",
    initial_agents=_AGENTS,
    event_sequence=_EVENTS,
    initial_run=_INITIAL_RUN,
    journal_entries={},
    loop=True,
)
register(DEFAULT)
```

- [ ] **Step 5: Update `radar/scenarios/all_blocked.py`**

Add `_INITIAL_RUN` and migrate display names:

```python
_INITIAL_RUN = {
    "run_id": "mock-run-blocked",
    "status": "blocked",
    "phase": "operations",
    "phase_display": "OPERATIONS",
    "iteration": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "completed_at": None,
}
```

Migrate all 8 agent display_name values (hyphen → space):
- `"Scout-1"` → `"Scout 1"`
- `"Sage-1"` → `"Sage 1"`
- `"Cartographer-1"` → `"Cartographer 1"`
- `"Strategist-1"` → `"Strategist 1"`
- `"Architect-1"` → `"Architect 1"`
- `"Sentinel-1"` → `"Sentinel 1"`
- `"Builder-1"` → `"Builder 1"`
- `"Manager-1"` → `"Manager 1"`

Update `Scenario(...)` constructor:

```python
ALL_BLOCKED = Scenario(
    name="all-blocked",
    description="All agents in blocked state waiting for human escalation",
    initial_agents=_agents,
    event_sequence=event_sequence,
    initial_run=_INITIAL_RUN,
    journal_entries={},
    loop=False,
)
register(ALL_BLOCKED)
```

- [ ] **Step 6: Run all tests**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v 2>&1 | tail -30
```
Expected: ALL PASS. The existing tests don't check for absence of `initial_run`; they only check specific keys exist.

- [ ] **Step 7: Commit**

```bash
git add radar/scenarios/__init__.py radar/scenarios/default.py radar/scenarios/all_blocked.py radar/tests/unit/test_scenario_data.py
git commit -m "feat(radar): add initial_run+journal_entries to Scenario; migrate display_name convention"
```

---

## Task 2: mock_server.py core changes + test fixes

**Files:**
- Modify: `radar/mock_server.py`
- Modify: `radar/tests/conftest.py`
- Modify: `radar/tests/unit/test_journal_endpoint.py`

### Context

`create_app()` currently takes `scenario_name: str` and resolves it internally. It must be refactored to accept a `Scenario` object directly — `main()` resolves the scenario before calling `create_app`. The `mock_snapshot` gains a `run` key from `scenario.initial_run`. The `scenario_loop` gets a `run_state_change` branch. The `/journal` endpoint returns a JSON array (not a dict). The conftest fixtures must be updated for the new signature.

- [ ] **Step 1: Write failing tests**

Replace all content in `radar/tests/unit/test_journal_endpoint.py`:

```python
"""Tests for the /journal endpoint — returns JSON array."""
import pytest

def test_journal_no_params_returns_empty_list(mock_app):
    r = mock_app.get("/journal")
    assert r.status_code == 200
    assert r.get_json() == []

def test_journal_missing_agent_returns_empty_list(mock_app):
    r = mock_app.get("/journal?run_id=mock-run-default")
    assert r.get_json() == []

def test_journal_missing_run_id_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=MOCK-SCOUT-1")
    assert r.get_json() == []

def test_journal_empty_agent_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=&run_id=mock-run-default")
    assert r.get_json() == []

def test_journal_empty_run_id_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=MOCK-SCOUT-1&run_id=")
    assert r.get_json() == []

def test_journal_unknown_agent_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=NONEXISTENT&run_id=mock-run-default")
    assert r.get_json() == []

def test_journal_wrong_run_id_returns_empty_list(mock_app):
    r = mock_app.get("/journal?agent=MOCK-SCOUT-1&run_id=wrong-run-id")
    assert r.get_json() == []


# Test non-empty response using a scenario that has journal entries.
# The "default" scenario has journal_entries: {} so we need a fresh app.
@pytest.fixture
def journal_app(squad_dir):
    """App backed by a minimal scenario that has journal entries."""
    from radar.mock_server import create_app
    from radar.scenarios import MockAgent, Scenario

    _RUN_ID = "test-journal-run-001"
    scenario = Scenario(
        name="test-journal",
        description="Scenario with journal entries for testing",
        initial_agents=[
            MockAgent("SCOUT-1", "SCOUT", "Scout 1", "idle", "discover", "2026-03-22T10:00:00Z")
        ],
        event_sequence=[],
        initial_run={
            "run_id": _RUN_ID, "status": "running", "phase": "discover",
            "phase_display": "DISCOVER", "iteration": 1,
            "created_at": "2026-03-22T10:00:00Z", "updated_at": "2026-03-22T10:00:00Z",
            "completed_at": None,
        },
        journal_entries={
            "SCOUT-1": [
                {"id": "j-001", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
                 "run_id": _RUN_ID, "timestamp_ms": 2000, "type": "finding",
                 "content": "Found bounded context A"},
                {"id": "j-002", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
                 "run_id": _RUN_ID, "timestamp_ms": 1000, "type": "decision",
                 "content": "Older entry"},
            ]
        },
        loop=False,
    )
    app, stop_event = create_app(scenario, squad_dir=squad_dir)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, _RUN_ID
    stop_event.set()


def test_journal_returns_entries_sorted_newest_first(journal_app):
    client, run_id = journal_app
    r = client.get(f"/journal?agent=SCOUT-1&run_id={run_id}")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 2
    # newest-first: timestamp_ms 2000 before 1000
    assert data[0]["timestamp_ms"] == 2000
    assert data[1]["timestamp_ms"] == 1000

def test_journal_returns_list_not_dict(journal_app):
    client, run_id = journal_app
    r = client.get(f"/journal?agent=SCOUT-1&run_id={run_id}")
    assert isinstance(r.get_json(), list)

def test_journal_entry_has_required_fields(journal_app):
    client, run_id = journal_app
    r = client.get(f"/journal?agent=SCOUT-1&run_id={run_id}")
    entry = r.get_json()[0]
    for field in ("id", "dispatch_id", "codename", "run_id", "timestamp_ms", "type", "content"):
        assert field in entry, f"missing field: {field}"
```

Also add to `radar/tests/unit/test_snapshot_endpoint.py`:

```python
def test_snapshot_has_run_key(mock_app):
    r = mock_app.get("/snapshot")
    data = r.get_json()
    assert "run" in data
    assert isinstance(data["run"], dict)
    assert "run_id" in data["run"]
    assert "status" in data["run"]
    assert "phase" in data["run"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/unit/test_journal_endpoint.py radar/tests/unit/test_snapshot_endpoint.py -v 2>&1 | tail -20
```
Expected: journal tests FAIL (old dict shape returned), `test_snapshot_has_run_key` FAIL.

- [ ] **Step 3: Update `radar/mock_server.py` — `create_app` signature and `mock_snapshot`**

Change the `create_app` function signature and `mock_snapshot` initialization. Find the current `create_app` definition at line 131 and replace:

```python
def create_app(
    scenario,                           # Scenario object (not a name string)
    squad_dir: Optional[Path] = None,
    port: int = DEFAULT_PORT,
    heartbeat_interval: int = HEARTBEAT_INTERVAL,
) -> tuple:
    # scenario is already resolved by caller (main() or test fixture)

    app = Flask(__name__)
    CORS(app)

    # Build initial mock_snapshot — run key from scenario.initial_run
    mock_snapshot = {
        "run_id": scenario.initial_run["run_id"],
        "run": dict(scenario.initial_run),
        "agents": {a.dispatch_id: a.to_dict() for a in scenario.initial_agents},
        "dispatch_order": [a.dispatch_id for a in scenario.initial_agents],
        # updated_at from scenario (not _now()) — preserves authored timeline
        "updated_at": scenario.initial_run["updated_at"],
    }
```

Remove the old `from radar.scenarios import get_scenario` and `scenario = get_scenario(scenario_name)` lines that were at the top of the old `create_app`.

- [ ] **Step 4: Update `scenario_loop` in `radar/mock_server.py`**

Replace the block that updates `mock_snapshot` in `scenario_loop`:

```python
def scenario_loop(scenario, mock_snapshot: dict, clients: dict, stop_event: threading.Event, broadcast_fn) -> None:
    while not stop_event.is_set():
        for event in scenario.event_sequence:
            if stop_event.wait(timeout=event.delay_ms / 1000):
                return
            if stop_event.is_set():
                return
            # Update mock_snapshot based on event type
            if event.event_type == "run_state_change":
                mock_snapshot["run"] = event.payload["run"]
                mock_snapshot["updated_at"] = _now()
            elif event.event_type == "agent_state_change":
                dispatch_id = event.payload.get("dispatch_id")
                if dispatch_id and dispatch_id in mock_snapshot["agents"]:
                    agent_entry = mock_snapshot["agents"][dispatch_id]
                    for k, v in event.payload.items():
                        if k != "dispatch_id":
                            agent_entry[k] = v
                    mock_snapshot["updated_at"] = _now()
            broadcast_fn(event.event_type, event.payload, clients, stop_event)
        if not scenario.loop:
            break
```

- [ ] **Step 5: Replace `/journal` endpoint in `radar/mock_server.py`**

Replace the existing `/journal` route:

```python
@app.route("/journal")
def journal():
    agent = request.args.get("agent", "")
    run_id = request.args.get("run_id", "")
    if not agent or not run_id:
        return jsonify([])
    entries = scenario.journal_entries.get(agent)
    if not entries:
        return jsonify([])
    if run_id != scenario.initial_run.get("run_id"):
        return jsonify([])
    sorted_entries = sorted(entries, key=lambda e: e.get("timestamp_ms", 0), reverse=True)
    return jsonify(sorted_entries)
```

- [ ] **Step 6: Update `main()` in `radar/mock_server.py` to resolve scenario before calling `create_app`**

In `main()`, change the validation and `create_app` call:

```python
# --list-scenarios
if args.list_scenarios:
    scenarios = list_scenarios()
    print("Available scenarios:")
    for s in scenarios:
        print(f"  {s.name:<14}{s.description}")
    print(f"  {'replay <PATH>':<14}Replay a recorded session (.jsonl file)")
    sys.exit(0)

# Resolve scenario
scenario = get_scenario(args.scenario)
if scenario is None:
    available = ", ".join(s.name for s in list_scenarios())
    print(f'[RADAR-MOCK] Error: unknown scenario "{args.scenario}"', file=sys.stderr)
    print(f"Available scenarios: {available}", file=sys.stderr)
    sys.exit(1)

# ... (squad_dir and port resolution unchanged) ...

# Create app — pass resolved Scenario object
app, stop_event = create_app(scenario, squad_dir=squad_dir, port=actual_port)
```

Remove the old validation block `if get_scenario(args.scenario) is None:` since it's now combined with the resolution step.

- [ ] **Step 7: Update `radar/tests/conftest.py`**

Update both fixtures to resolve the scenario before calling `create_app`:

```python
@pytest.fixture
def mock_app(squad_dir):
    """Flask test client backed by create_app() with an isolated squad_dir."""
    from radar.mock_server import create_app
    from radar.scenarios import get_scenario
    scenario = get_scenario("default")
    app, stop_event = create_app(scenario, squad_dir=squad_dir)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
    stop_event.set()
    time.sleep(0.05)

@pytest.fixture
def live_server(squad_dir):
    """Live Flask server in a background thread. Yields actual port number."""
    from radar.mock_server import create_app
    from radar.scenarios import get_scenario
    scenario = get_scenario("default")
    app, stop_event = create_app(scenario, squad_dir=squad_dir, heartbeat_interval=1)
    server = make_server("127.0.0.1", 0, app)
    actual_port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield actual_port
    stop_event.set()
    server.shutdown()
    thread.join(timeout=5)
```

The `running_process` fixture remains unchanged (it invokes `mock_server` via subprocess with `--scenario default`).

- [ ] **Step 8: Run all tests**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v 2>&1 | tail -30
```
Expected: ALL PASS. If CLI tests fail, check that `main()` still handles `--scenario default` correctly via subprocess.

- [ ] **Step 9: Commit**

```bash
git add radar/mock_server.py radar/tests/conftest.py radar/tests/unit/test_journal_endpoint.py radar/tests/unit/test_snapshot_endpoint.py
git commit -m "feat(radar): refactor create_app to accept Scenario; add run to snapshot; run_state_change in loop; fix /journal to return array"
```

---

## Task 3: `greenfield` scenario

**Files:**
- Create: `radar/scenarios/greenfield.py`
- Modify: `radar/scenarios/__init__.py` (add import)
- Create/Modify: `radar/tests/unit/test_new_scenarios.py`

### Context

13 agents across 9 phases. Each agent: `working` → optional `thinking` → `complete`. A `run_state_change` fires after the last agent in each phase completes. Terminal `run_state_change` has `status: "done"`.

- [ ] **Step 1: Write failing tests**

Create `radar/tests/unit/test_new_scenarios.py`:

```python
"""Tests for greenfield, brownfield, and blocked-escalation scenarios."""
import pytest
from radar.scenarios import get_scenario

# ── greenfield ────────────────────────────────────────────────────────────

def test_greenfield_registered():
    assert get_scenario("greenfield") is not None

def test_greenfield_loop_false():
    assert get_scenario("greenfield").loop is False

def test_greenfield_agent_count():
    assert len(get_scenario("greenfield").initial_agents) == 13

def test_greenfield_has_initial_run():
    s = get_scenario("greenfield")
    assert s.initial_run["run_id"] == "squad-gf-20260322-1000"
    assert s.initial_run["status"] == "running"

def test_greenfield_terminal_event_is_done():
    s = get_scenario("greenfield")
    run_events = [e for e in s.event_sequence if e.event_type == "run_state_change"]
    terminal = run_events[-1]
    assert terminal.payload["run"]["status"] == "done"
    assert terminal.payload["run"]["completed_at"] is not None

def test_greenfield_has_journal_entries():
    s = get_scenario("greenfield")
    assert len(s.journal_entries) >= 3  # at least 3 agents have journal entries

def test_greenfield_display_names_space_convention():
    s = get_scenario("greenfield")
    for a in s.initial_agents:
        assert "-" not in a.display_name, f"display_name uses hyphen: {a.display_name!r}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/unit/test_new_scenarios.py::test_greenfield_registered -v 2>&1 | tail -10
```
Expected: ImportError or NameError (scenario not registered yet).

- [ ] **Step 3: Create `radar/scenarios/greenfield.py`**

```python
"""
radar/scenarios/greenfield.py — Greenfield lifecycle scenario.

13 agents, 9 phases, happy-path run that ends with status "done".
Registers itself as "greenfield" on import.
"""

from __future__ import annotations
from radar.scenarios import MockAgent, Scenario, ScenarioEvent, register

_RUN_ID = "squad-gf-20260322-1000"

_INITIAL_RUN = {
    "run_id": _RUN_ID,
    "status": "running",
    "phase": "discover",
    "phase_display": "DISCOVER",
    "iteration": 1,
    "created_at": "2026-03-22T10:00:00Z",
    "updated_at": "2026-03-22T10:00:00Z",
    "completed_at": None,
}

_T = "2026-03-22T10:00:00Z"   # static dispatched_at for all agents

_AGENTS = [
    MockAgent("PROSPECTOR-1",  "PROSPECTOR",  "Prospector 1",  "idle", "discover",     _T),
    MockAgent("SCOUT-1",       "SCOUT",       "Scout 1",       "idle", "discover",     _T),
    MockAgent("SYNTHESIZER-1", "SYNTHESIZER", "Synthesizer 1", "idle", "synthesize",   _T),
    MockAgent("TRACKER-1",     "TRACKER",     "Tracker 1",     "idle", "synthesize",   _T),
    MockAgent("SAGE-1",        "SAGE",        "Sage 1",        "idle", "why1",         _T),
    MockAgent("CARTOGRAPHER-1","CARTOGRAPHER","Cartographer 1","idle", "cartographer", _T),
    MockAgent("SAGE-2",        "SAGE",        "Sage 2",        "idle", "why2",         _T),
    MockAgent("GATEKEEPER-1",  "GATEKEEPER",  "Gatekeeper 1",  "idle", "assess",       _T),
    MockAgent("ARCHITECT-1",   "ARCHITECT",   "Architect 1",   "idle", "solution",     _T),
    MockAgent("SENTINEL-1",    "SENTINEL",    "Sentinel 1",    "idle", "solution",     _T),
    MockAgent("ORCHESTRATOR-1","ORCHESTRATOR","Orchestrator 1","idle", "plan",         _T),
    MockAgent("REALIST-1",     "REALIST",     "Realist 1",     "idle", "finalize",     _T),
    MockAgent("AUDITOR-1",     "AUDITOR",     "Auditor 1",     "idle", "finalize",     _T),
]


def _ev(dispatch_id: str, state: str, phase: str, phase_display: str, delay_ms: int,
        completed_at: str | None = None, blocked_reason: str | None = None) -> ScenarioEvent:
    payload = {
        "dispatch_id": dispatch_id,
        "state": state,
        "phase": phase,
        "phase_display": phase_display,
        "updated_at": "2026-03-22T10:00:00Z",
    }
    if completed_at is not None:
        payload["completed_at"] = completed_at
    if blocked_reason is not None:
        payload["blocked_reason"] = blocked_reason
    return ScenarioEvent("agent_state_change", payload, delay_ms)


def _rsc(phase: str, phase_display: str, status: str = "running",
         completed_at: str | None = None, delay_ms: int = 500) -> ScenarioEvent:
    run = {
        "run_id": _RUN_ID,
        "status": status,
        "phase": phase,
        "phase_display": phase_display,
        "iteration": 1,
        "created_at": "2026-03-22T10:00:00Z",
        "updated_at": "2026-03-22T10:15:00Z",
        "completed_at": completed_at,
    }
    return ScenarioEvent("run_state_change", {"ts": "2026-03-22T10:15:00Z", "run": run}, delay_ms)


_EVENTS = [
    # ── discover ─────────────────────────────────────────────────────────────
    _ev("PROSPECTOR-1", "working",  "discover", "DISCOVER", 2000),
    _ev("PROSPECTOR-1", "complete", "discover", "DISCOVER", 2000, completed_at="2026-03-22T10:04:00Z"),
    _ev("SCOUT-1",      "working",  "discover", "DISCOVER", 2000),
    _ev("SCOUT-1",      "thinking", "discover", "DISCOVER", 3000),
    _ev("SCOUT-1",      "complete", "discover", "DISCOVER", 2000, completed_at="2026-03-22T10:09:00Z"),
    _rsc("synthesize", "SYNTHESIZE"),

    # ── synthesize ────────────────────────────────────────────────────────────
    _ev("SYNTHESIZER-1", "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("SYNTHESIZER-1", "thinking", "synthesize", "SYNTHESIZE", 3000),
    _ev("SYNTHESIZER-1", "complete", "synthesize", "SYNTHESIZE", 2000, completed_at="2026-03-22T10:14:00Z"),
    _ev("TRACKER-1",     "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("TRACKER-1",     "complete", "synthesize", "SYNTHESIZE", 2000, completed_at="2026-03-22T10:18:00Z"),
    _rsc("why1", "WHY1 — Assumption Challenge"),

    # ── why1 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-1", "working",  "why1", "WHY1 — Assumption Challenge", 2000),
    _ev("SAGE-1", "thinking", "why1", "WHY1 — Assumption Challenge", 3000),
    _ev("SAGE-1", "complete", "why1", "WHY1 — Assumption Challenge", 2000, completed_at="2026-03-22T10:23:00Z"),
    _rsc("cartographer", "CARTOGRAPHER"),

    # ── cartographer ──────────────────────────────────────────────────────────
    _ev("CARTOGRAPHER-1", "working",  "cartographer", "CARTOGRAPHER", 2000),
    _ev("CARTOGRAPHER-1", "thinking", "cartographer", "CARTOGRAPHER", 3000),
    _ev("CARTOGRAPHER-1", "complete", "cartographer", "CARTOGRAPHER", 2000, completed_at="2026-03-22T10:28:00Z"),
    _rsc("why2", "WHY2 — Spec Validation"),

    # ── why2 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-2", "working",  "why2", "WHY2 — Spec Validation", 2000),
    _ev("SAGE-2", "thinking", "why2", "WHY2 — Spec Validation", 3000),
    _ev("SAGE-2", "complete", "why2", "WHY2 — Spec Validation", 2000, completed_at="2026-03-22T10:33:00Z"),
    _rsc("assess", "ASSESS — Kill Gate"),

    # ── assess ────────────────────────────────────────────────────────────────
    _ev("GATEKEEPER-1", "working",  "assess", "ASSESS — Kill Gate", 2000),
    _ev("GATEKEEPER-1", "thinking", "assess", "ASSESS — Kill Gate", 3000),
    _ev("GATEKEEPER-1", "complete", "assess", "ASSESS — Kill Gate", 2000, completed_at="2026-03-22T10:38:00Z"),
    _rsc("solution", "SOLUTION"),

    # ── solution ──────────────────────────────────────────────────────────────
    _ev("ARCHITECT-1", "working",  "solution", "SOLUTION", 2000),
    _ev("ARCHITECT-1", "thinking", "solution", "SOLUTION", 3000),
    _ev("ARCHITECT-1", "complete", "solution", "SOLUTION", 2000, completed_at="2026-03-22T10:43:00Z"),
    _ev("SENTINEL-1",  "working",  "solution", "SOLUTION", 2000),
    _ev("SENTINEL-1",  "complete", "solution", "SOLUTION", 2000, completed_at="2026-03-22T10:47:00Z"),
    _rsc("plan", "PLAN"),

    # ── plan ──────────────────────────────────────────────────────────────────
    _ev("ORCHESTRATOR-1", "working",  "plan", "PLAN", 2000),
    _ev("ORCHESTRATOR-1", "thinking", "plan", "PLAN", 3000),
    _ev("ORCHESTRATOR-1", "complete", "plan", "PLAN", 2000, completed_at="2026-03-22T10:52:00Z"),
    _rsc("finalize", "FINALIZE"),

    # ── finalize ──────────────────────────────────────────────────────────────
    _ev("REALIST-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("REALIST-1", "complete", "finalize", "FINALIZE", 2000, completed_at="2026-03-22T10:56:00Z"),
    _ev("AUDITOR-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("AUDITOR-1", "thinking", "finalize", "FINALIZE", 3000),
    _ev("AUDITOR-1", "complete", "finalize", "FINALIZE", 2000, completed_at="2026-03-22T11:01:00Z"),
    # terminal run_state_change — status: done
    _rsc("finalize", "FINALIZE", status="done",
         completed_at="2026-03-22T11:01:30Z", delay_ms=1000),
]

_JOURNAL = {
    "SCOUT-1": [
        {"id": "j-SCOUT-1-001", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742637060000, "type": "finding",
         "content": "Identified 3 bounded contexts: auth, payments, notifications — different ownership, separate schemas"},
        {"id": "j-SCOUT-1-002", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742637090000, "type": "decision",
         "content": "Treating payments and notifications as separate bounded contexts — different release cadence confirmed by git log"},
        {"id": "j-SCOUT-1-003", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742637125000, "type": "risk",
         "content": "No API versioning strategy found — /v1/ prefix exists but no deprecation policy in docs"},
    ],
    "CARTOGRAPHER-1": [
        {"id": "j-CART-1-001", "dispatch_id": "CARTOGRAPHER-1", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742638200000, "type": "finding",
         "content": "Payment flow requires 4 external integrations: Stripe, fraud-check, email, ledger"},
        {"id": "j-CART-1-002", "dispatch_id": "CARTOGRAPHER-1", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742638260000, "type": "decision",
         "content": "Separating idempotency key management as a cross-cutting concern — applies to all payment mutations"},
        {"id": "j-CART-1-003", "dispatch_id": "CARTOGRAPHER-1", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742638320000, "type": "concern",
         "content": "Refund flow is underspecified — no mention of partial refunds or currency conversion"},
    ],
    "GATEKEEPER-1": [
        {"id": "j-GATE-1-001", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742640000000, "type": "assessment",
         "content": "PASS — spec coverage 94%, all critical requirements resolved, RICE score 78"},
        {"id": "j-GATE-1-002", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742640060000, "type": "finding",
         "content": "3 low-priority requirements deferred to v2 — documented in spec with rationale"},
    ],
    "ORCHESTRATOR-1": [
        {"id": "j-ORCH-1-001", "dispatch_id": "ORCHESTRATOR-1", "codename": "ORCHESTRATOR",
         "run_id": _RUN_ID, "timestamp_ms": 1742641800000, "type": "decision",
         "content": "Splitting into 6 implementation tasks — payment core, webhook handler, idempotency, refunds, admin UI, migration"},
        {"id": "j-ORCH-1-002", "dispatch_id": "ORCHESTRATOR-1", "codename": "ORCHESTRATOR",
         "run_id": _RUN_ID, "timestamp_ms": 1742641860000, "type": "finding",
         "content": "Payment core and idempotency must be sequential — all other tasks can run in parallel after"},
    ],
}

GREENFIELD = Scenario(
    name="greenfield",
    description="Happy-path lifecycle: 13 agents, 9 phases, ends with status=done (~8 min simulated)",
    initial_agents=_AGENTS,
    event_sequence=_EVENTS,
    initial_run=_INITIAL_RUN,
    journal_entries=_JOURNAL,
    loop=False,
)
register(GREENFIELD)
```

- [ ] **Step 4: Register in `radar/scenarios/__init__.py`**

Add after the existing import block at the bottom of `__init__.py`:

```python
from radar.scenarios import greenfield as _greenfield  # noqa: F401
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v -k "greenfield or test_list or test_scenario" 2>&1 | tail -20
```
Expected: All greenfield tests PASS. `test_list_scenarios_has_at_least_two` still PASS (now has 3+).

- [ ] **Step 6: Commit**

```bash
git add radar/scenarios/greenfield.py radar/scenarios/__init__.py radar/tests/unit/test_new_scenarios.py
git commit -m "feat(radar): add greenfield lifecycle scenario (13 agents, 9 phases, one-shot)"
```

---

## Task 4: `brownfield` scenario

**Files:**
- Create: `radar/scenarios/brownfield.py`
- Modify: `radar/scenarios/__init__.py`
- Modify: `radar/tests/unit/test_new_scenarios.py`

### Context

Identical to greenfield but with GOLDDIGGER-1 inserted between PROSPECTOR-1 and SCOUT-1 in the discover phase. 14 agents total. SCOUT-1 events begin only after GOLDDIGGER-1 completes.

- [ ] **Step 1: Write failing tests**

Add to `radar/tests/unit/test_new_scenarios.py`:

```python
# ── brownfield ────────────────────────────────────────────────────────────

def test_brownfield_registered():
    assert get_scenario("brownfield") is not None

def test_brownfield_agent_count():
    assert len(get_scenario("brownfield").initial_agents) == 14

def test_brownfield_has_golddigger():
    s = get_scenario("brownfield")
    ids = [a.dispatch_id for a in s.initial_agents]
    assert "GOLDDIGGER-1" in ids

def test_brownfield_golddigger_before_scout():
    s = get_scenario("brownfield")
    ids = [a.dispatch_id for a in s.initial_agents]
    assert ids.index("GOLDDIGGER-1") < ids.index("SCOUT-1")

def test_brownfield_terminal_event_is_done():
    s = get_scenario("brownfield")
    run_events = [e for e in s.event_sequence if e.event_type == "run_state_change"]
    assert run_events[-1].payload["run"]["status"] == "done"

def test_brownfield_loop_false():
    assert get_scenario("brownfield").loop is False
```

- [ ] **Step 2: Create `radar/scenarios/brownfield.py`**

```python
"""
radar/scenarios/brownfield.py — Brownfield lifecycle scenario.

14 agents, 9 phases — identical to greenfield but GOLDDIGGER-1 runs between
PROSPECTOR-1 and SCOUT-1 in the discover phase.
Registers itself as "brownfield" on import.
"""

from __future__ import annotations
from radar.scenarios import MockAgent, Scenario, ScenarioEvent, register

_RUN_ID = "squad-bf-20260322-1000"

_INITIAL_RUN = {
    "run_id": _RUN_ID,
    "status": "running",
    "phase": "discover",
    "phase_display": "DISCOVER",
    "iteration": 1,
    "created_at": "2026-03-22T10:00:00Z",
    "updated_at": "2026-03-22T10:00:00Z",
    "completed_at": None,
}

_T = "2026-03-22T10:00:00Z"

_AGENTS = [
    MockAgent("PROSPECTOR-1",  "PROSPECTOR",  "Prospector 1",  "idle", "discover",     _T),
    MockAgent("GOLDDIGGER-1",  "GOLDDIGGER",  "Golddigger 1",  "idle", "discover",     _T),
    MockAgent("SCOUT-1",       "SCOUT",       "Scout 1",       "idle", "discover",     _T),
    MockAgent("SYNTHESIZER-1", "SYNTHESIZER", "Synthesizer 1", "idle", "synthesize",   _T),
    MockAgent("TRACKER-1",     "TRACKER",     "Tracker 1",     "idle", "synthesize",   _T),
    MockAgent("SAGE-1",        "SAGE",        "Sage 1",        "idle", "why1",         _T),
    MockAgent("CARTOGRAPHER-1","CARTOGRAPHER","Cartographer 1","idle", "cartographer", _T),
    MockAgent("SAGE-2",        "SAGE",        "Sage 2",        "idle", "why2",         _T),
    MockAgent("GATEKEEPER-1",  "GATEKEEPER",  "Gatekeeper 1",  "idle", "assess",       _T),
    MockAgent("ARCHITECT-1",   "ARCHITECT",   "Architect 1",   "idle", "solution",     _T),
    MockAgent("SENTINEL-1",    "SENTINEL",    "Sentinel 1",    "idle", "solution",     _T),
    MockAgent("ORCHESTRATOR-1","ORCHESTRATOR","Orchestrator 1","idle", "plan",         _T),
    MockAgent("REALIST-1",     "REALIST",     "Realist 1",     "idle", "finalize",     _T),
    MockAgent("AUDITOR-1",     "AUDITOR",     "Auditor 1",     "idle", "finalize",     _T),
]


def _ev(dispatch_id, state, phase, phase_display, delay_ms, completed_at=None):
    payload = {"dispatch_id": dispatch_id, "state": state, "phase": phase,
               "phase_display": phase_display, "updated_at": "2026-03-22T10:00:00Z"}
    if completed_at:
        payload["completed_at"] = completed_at
    return ScenarioEvent("agent_state_change", payload, delay_ms)


def _rsc(phase, phase_display, status="running", completed_at=None, delay_ms=500):
    run = {"run_id": _RUN_ID, "status": status, "phase": phase, "phase_display": phase_display,
           "iteration": 1, "created_at": "2026-03-22T10:00:00Z",
           "updated_at": "2026-03-22T10:15:00Z", "completed_at": completed_at}
    return ScenarioEvent("run_state_change", {"ts": "2026-03-22T10:15:00Z", "run": run}, delay_ms)


_EVENTS = [
    # ── discover (with GOLDDIGGER-1) ──────────────────────────────────────────
    _ev("PROSPECTOR-1",  "working",  "discover", "DISCOVER", 2000),
    _ev("PROSPECTOR-1",  "complete", "discover", "DISCOVER", 2000, "2026-03-22T10:04:00Z"),
    _ev("GOLDDIGGER-1",  "working",  "discover", "DISCOVER", 2000),
    _ev("GOLDDIGGER-1",  "thinking", "discover", "DISCOVER", 5000),  # Mode 1 survey
    _ev("GOLDDIGGER-1",  "complete", "discover", "DISCOVER", 1000,  "2026-03-22T10:12:00Z"),
    _ev("SCOUT-1",       "working",  "discover", "DISCOVER", 2000),
    _ev("SCOUT-1",       "thinking", "discover", "DISCOVER", 3000),
    _ev("SCOUT-1",       "complete", "discover", "DISCOVER", 2000,  "2026-03-22T10:19:00Z"),
    _rsc("synthesize", "SYNTHESIZE"),

    # ── synthesize → finalize (identical to greenfield) ───────────────────────
    _ev("SYNTHESIZER-1", "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("SYNTHESIZER-1", "thinking", "synthesize", "SYNTHESIZE", 3000),
    _ev("SYNTHESIZER-1", "complete", "synthesize", "SYNTHESIZE", 2000, "2026-03-22T10:24:00Z"),
    _ev("TRACKER-1",     "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("TRACKER-1",     "complete", "synthesize", "SYNTHESIZE", 2000, "2026-03-22T10:28:00Z"),
    _rsc("why1", "WHY1 — Assumption Challenge"),

    _ev("SAGE-1", "working",  "why1", "WHY1 — Assumption Challenge", 2000),
    _ev("SAGE-1", "thinking", "why1", "WHY1 — Assumption Challenge", 3000),
    _ev("SAGE-1", "complete", "why1", "WHY1 — Assumption Challenge", 2000, "2026-03-22T10:33:00Z"),
    _rsc("cartographer", "CARTOGRAPHER"),

    _ev("CARTOGRAPHER-1", "working",  "cartographer", "CARTOGRAPHER", 2000),
    _ev("CARTOGRAPHER-1", "thinking", "cartographer", "CARTOGRAPHER", 3000),
    _ev("CARTOGRAPHER-1", "complete", "cartographer", "CARTOGRAPHER", 2000, "2026-03-22T10:38:00Z"),
    _rsc("why2", "WHY2 — Spec Validation"),

    _ev("SAGE-2", "working",  "why2", "WHY2 — Spec Validation", 2000),
    _ev("SAGE-2", "thinking", "why2", "WHY2 — Spec Validation", 3000),
    _ev("SAGE-2", "complete", "why2", "WHY2 — Spec Validation", 2000, "2026-03-22T10:43:00Z"),
    _rsc("assess", "ASSESS — Kill Gate"),

    _ev("GATEKEEPER-1", "working",  "assess", "ASSESS — Kill Gate", 2000),
    _ev("GATEKEEPER-1", "thinking", "assess", "ASSESS — Kill Gate", 3000),
    _ev("GATEKEEPER-1", "complete", "assess", "ASSESS — Kill Gate", 2000, "2026-03-22T10:48:00Z"),
    _rsc("solution", "SOLUTION"),

    _ev("ARCHITECT-1", "working",  "solution", "SOLUTION", 2000),
    _ev("ARCHITECT-1", "thinking", "solution", "SOLUTION", 3000),
    _ev("ARCHITECT-1", "complete", "solution", "SOLUTION", 2000, "2026-03-22T10:53:00Z"),
    _ev("SENTINEL-1",  "working",  "solution", "SOLUTION", 2000),
    _ev("SENTINEL-1",  "complete", "solution", "SOLUTION", 2000, "2026-03-22T10:57:00Z"),
    _rsc("plan", "PLAN"),

    _ev("ORCHESTRATOR-1", "working",  "plan", "PLAN", 2000),
    _ev("ORCHESTRATOR-1", "thinking", "plan", "PLAN", 3000),
    _ev("ORCHESTRATOR-1", "complete", "plan", "PLAN", 2000, "2026-03-22T11:02:00Z"),
    _rsc("finalize", "FINALIZE"),

    _ev("REALIST-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("REALIST-1", "complete", "finalize", "FINALIZE", 2000, "2026-03-22T11:06:00Z"),
    _ev("AUDITOR-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("AUDITOR-1", "thinking", "finalize", "FINALIZE", 3000),
    _ev("AUDITOR-1", "complete", "finalize", "FINALIZE", 2000, "2026-03-22T11:11:00Z"),
    _rsc("finalize", "FINALIZE", status="done", completed_at="2026-03-22T11:11:30Z", delay_ms=1000),
]

_JOURNAL = {
    "GOLDDIGGER-1": [
        {"id": "j-GD-1-001", "dispatch_id": "GOLDDIGGER-1", "codename": "GOLDDIGGER",
         "run_id": _RUN_ID, "timestamp_ms": 1742637600000, "type": "finding",
         "content": "Mode 1 survey complete: 23 domain objects identified across 4 bounded contexts"},
        {"id": "j-GD-1-002", "dispatch_id": "GOLDDIGGER-1", "codename": "GOLDDIGGER",
         "run_id": _RUN_ID, "timestamp_ms": 1742637660000, "type": "decision",
         "content": "brownfield-index.md written — SCOUT-1 can proceed with pre-seeded domain vocabulary"},
    ],
    "SCOUT-1": [
        {"id": "j-SCOUT-1-001", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742638200000, "type": "finding",
         "content": "Seeded from brownfield-index.md — 23 domain objects pre-mapped, validating against live code"},
        {"id": "j-SCOUT-1-002", "dispatch_id": "SCOUT-1", "codename": "SCOUT",
         "run_id": _RUN_ID, "timestamp_ms": 1742638260000, "type": "risk",
         "content": "3 hotspot files changed > 40x in past year — StripeWebhookHandler, PaymentService, RefundPolicy"},
    ],
    "GATEKEEPER-1": [
        {"id": "j-GATE-1-001", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742641800000, "type": "assessment",
         "content": "PASS — spec coverage 91%, all critical requirements resolved"},
    ],
}

BROWNFIELD = Scenario(
    name="brownfield",
    description="Brownfield lifecycle with GOLDDIGGER-1 survey: 14 agents, 9 phases, ends status=done",
    initial_agents=_AGENTS,
    event_sequence=_EVENTS,
    initial_run=_INITIAL_RUN,
    journal_entries=_JOURNAL,
    loop=False,
)
register(BROWNFIELD)
```

- [ ] **Step 3: Register in `radar/scenarios/__init__.py`**

Add after the greenfield import:

```python
from radar.scenarios import brownfield as _brownfield  # noqa: F401
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v -k "brownfield" 2>&1 | tail -15
```
Expected: All brownfield tests PASS.

- [ ] **Step 5: Commit**

```bash
git add radar/scenarios/brownfield.py radar/scenarios/__init__.py radar/tests/unit/test_new_scenarios.py
git commit -m "feat(radar): add brownfield lifecycle scenario (14 agents, GOLDDIGGER-1 in discover phase)"
```

---

## Task 5: `blocked-escalation` scenario

**Files:**
- Create: `radar/scenarios/blocked_escalation.py`
- Modify: `radar/scenarios/__init__.py`
- Modify: `radar/tests/unit/test_new_scenarios.py`

### Context

Same pipeline as greenfield up to GATEKEEPER-1 at `assess`. GATEKEEPER-1 blocks (`status: blocked` run_state_change), then resumes after 8000ms pause. A rework loop follows: CARTOGRAPHER-2, SAGE-3, GATEKEEPER-2. Then solution through finalize. 15 agents total. Terminal status is `"done"`.

- [ ] **Step 1: Write failing tests**

Add to `radar/tests/unit/test_new_scenarios.py`:

```python
# ── blocked-escalation ────────────────────────────────────────────────────

def test_blocked_escalation_registered():
    assert get_scenario("blocked-escalation") is not None

def test_blocked_escalation_agent_count():
    assert len(get_scenario("blocked-escalation").initial_agents) == 15

def test_blocked_escalation_has_gatekeeper_block():
    s = get_scenario("blocked-escalation")
    blocked_events = [e for e in s.event_sequence
                      if e.event_type == "agent_state_change"
                      and e.payload.get("state") == "blocked"]
    assert len(blocked_events) >= 1
    assert blocked_events[0].payload["dispatch_id"] == "GATEKEEPER-1"

def test_blocked_escalation_has_blocked_run_state():
    s = get_scenario("blocked-escalation")
    run_events = [e for e in s.event_sequence if e.event_type == "run_state_change"]
    statuses = [e.payload["run"]["status"] for e in run_events]
    assert "blocked" in statuses

def test_blocked_escalation_terminal_event_is_done():
    s = get_scenario("blocked-escalation")
    run_events = [e for e in s.event_sequence if e.event_type == "run_state_change"]
    assert run_events[-1].payload["run"]["status"] == "done"

def test_blocked_escalation_has_cartographer2():
    s = get_scenario("blocked-escalation")
    ids = [a.dispatch_id for a in s.initial_agents]
    assert "CARTOGRAPHER-2" in ids

def test_blocked_escalation_loop_false():
    assert get_scenario("blocked-escalation").loop is False
```

- [ ] **Step 2: Create `radar/scenarios/blocked_escalation.py`**

```python
"""
radar/scenarios/blocked_escalation.py — Blocked escalation lifecycle scenario.

GATEKEEPER-1 blocks at assess, triggering a CARTOGRAPHER-2 rework loop.
15 agents, 11 phases, ends with status=done.
Registers itself as "blocked-escalation" on import.
"""

from __future__ import annotations
from radar.scenarios import MockAgent, Scenario, ScenarioEvent, register

_RUN_ID = "squad-be-20260322-1000"

_INITIAL_RUN = {
    "run_id": _RUN_ID,
    "status": "running",
    "phase": "discover",
    "phase_display": "DISCOVER",
    "iteration": 1,
    "created_at": "2026-03-22T10:00:00Z",
    "updated_at": "2026-03-22T10:00:00Z",
    "completed_at": None,
}

_T = "2026-03-22T10:00:00Z"

_AGENTS = [
    MockAgent("PROSPECTOR-1",  "PROSPECTOR",  "Prospector 1",  "idle", "discover",      _T),
    MockAgent("SCOUT-1",       "SCOUT",       "Scout 1",       "idle", "discover",      _T),
    MockAgent("SYNTHESIZER-1", "SYNTHESIZER", "Synthesizer 1", "idle", "synthesize",    _T),
    MockAgent("TRACKER-1",     "TRACKER",     "Tracker 1",     "idle", "synthesize",    _T),
    MockAgent("SAGE-1",        "SAGE",        "Sage 1",        "idle", "why1",          _T),
    MockAgent("CARTOGRAPHER-1","CARTOGRAPHER","Cartographer 1","idle", "cartographer",  _T),
    MockAgent("SAGE-2",        "SAGE",        "Sage 2",        "idle", "why2",          _T),
    MockAgent("GATEKEEPER-1",  "GATEKEEPER",  "Gatekeeper 1",  "idle", "assess",        _T),
    MockAgent("CARTOGRAPHER-2","CARTOGRAPHER","Cartographer 2","idle", "cartographer",  _T),
    MockAgent("SAGE-3",        "SAGE",        "Sage 3",        "idle", "why3",          _T),
    MockAgent("GATEKEEPER-2",  "GATEKEEPER",  "Gatekeeper 2",  "idle", "assess",        _T),
    MockAgent("ARCHITECT-1",   "ARCHITECT",   "Architect 1",   "idle", "solution",      _T),
    MockAgent("SENTINEL-1",    "SENTINEL",    "Sentinel 1",    "idle", "solution",      _T),
    MockAgent("ORCHESTRATOR-1","ORCHESTRATOR","Orchestrator 1","idle", "plan",          _T),
    MockAgent("REALIST-1",     "REALIST",     "Realist 1",     "idle", "finalize",      _T),
]


def _ev(dispatch_id, state, phase, phase_display, delay_ms,
        completed_at=None, blocked_reason=None):
    payload = {"dispatch_id": dispatch_id, "state": state, "phase": phase,
               "phase_display": phase_display, "updated_at": "2026-03-22T10:00:00Z"}
    if completed_at:
        payload["completed_at"] = completed_at
    if blocked_reason is not None:
        payload["blocked_reason"] = blocked_reason
    return ScenarioEvent("agent_state_change", payload, delay_ms)


def _rsc(phase, phase_display, status="running", completed_at=None, delay_ms=500):
    run = {"run_id": _RUN_ID, "status": status, "phase": phase, "phase_display": phase_display,
           "iteration": 1, "created_at": "2026-03-22T10:00:00Z",
           "updated_at": "2026-03-22T10:15:00Z", "completed_at": completed_at}
    return ScenarioEvent("run_state_change", {"ts": "2026-03-22T10:15:00Z", "run": run}, delay_ms)


_EVENTS = [
    # ── discover ─────────────────────────────────────────────────────────────
    _ev("PROSPECTOR-1", "working",  "discover", "DISCOVER", 2000),
    _ev("PROSPECTOR-1", "complete", "discover", "DISCOVER", 2000, "2026-03-22T10:04:00Z"),
    _ev("SCOUT-1",      "working",  "discover", "DISCOVER", 2000),
    _ev("SCOUT-1",      "thinking", "discover", "DISCOVER", 3000),
    _ev("SCOUT-1",      "complete", "discover", "DISCOVER", 2000, "2026-03-22T10:09:00Z"),
    _rsc("synthesize", "SYNTHESIZE"),

    # ── synthesize ────────────────────────────────────────────────────────────
    _ev("SYNTHESIZER-1", "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("SYNTHESIZER-1", "thinking", "synthesize", "SYNTHESIZE", 3000),
    _ev("SYNTHESIZER-1", "complete", "synthesize", "SYNTHESIZE", 2000, "2026-03-22T10:14:00Z"),
    _ev("TRACKER-1",     "working",  "synthesize", "SYNTHESIZE", 2000),
    _ev("TRACKER-1",     "complete", "synthesize", "SYNTHESIZE", 2000, "2026-03-22T10:18:00Z"),
    _rsc("why1", "WHY1 — Assumption Challenge"),

    # ── why1 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-1", "working",  "why1", "WHY1 — Assumption Challenge", 2000),
    _ev("SAGE-1", "thinking", "why1", "WHY1 — Assumption Challenge", 3000),
    _ev("SAGE-1", "complete", "why1", "WHY1 — Assumption Challenge", 2000, "2026-03-22T10:23:00Z"),
    _rsc("cartographer", "CARTOGRAPHER"),

    # ── cartographer (first pass) ─────────────────────────────────────────────
    _ev("CARTOGRAPHER-1", "working",  "cartographer", "CARTOGRAPHER", 2000),
    _ev("CARTOGRAPHER-1", "thinking", "cartographer", "CARTOGRAPHER", 3000),
    _ev("CARTOGRAPHER-1", "complete", "cartographer", "CARTOGRAPHER", 2000, "2026-03-22T10:28:00Z"),
    _rsc("why2", "WHY2 — Spec Validation"),

    # ── why2 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-2", "working",  "why2", "WHY2 — Spec Validation", 2000),
    _ev("SAGE-2", "thinking", "why2", "WHY2 — Spec Validation", 3000),
    _ev("SAGE-2", "complete", "why2", "WHY2 — Spec Validation", 2000, "2026-03-22T10:33:00Z"),
    _rsc("assess", "ASSESS — Kill Gate"),

    # ── assess (GATEKEEPER-1 blocks) ─────────────────────────────────────────
    _ev("GATEKEEPER-1", "working",  "assess", "ASSESS — Kill Gate", 2000),
    _ev("GATEKEEPER-1", "thinking", "assess", "ASSESS — Kill Gate", 4000),
    _ev("GATEKEEPER-1", "blocked",  "assess", "ASSESS — Kill Gate", 3000,
        blocked_reason="Spec coverage below kill threshold — 3 critical requirements unresolved"),
    _rsc("assess", "ASSESS — Kill Gate", status="blocked"),

    # 8000ms simulates human review window; GATEKEEPER-1 resumes working
    _ev("GATEKEEPER-1", "working", "assess", "ASSESS — Kill Gate", 8000,
        blocked_reason=None),  # blocked_reason=None clears it in mock_snapshot
    _rsc("cartographer", "CARTOGRAPHER (rework)", status="running"),

    # ── cartographer rework (CARTOGRAPHER-2) ─────────────────────────────────
    _ev("CARTOGRAPHER-2", "working",  "cartographer", "CARTOGRAPHER (rework)", 1000),
    _ev("CARTOGRAPHER-2", "thinking", "cartographer", "CARTOGRAPHER (rework)", 3000),
    _ev("CARTOGRAPHER-2", "complete", "cartographer", "CARTOGRAPHER (rework)", 2000, "2026-03-22T10:56:00Z"),
    _rsc("why3", "WHY3 — Consensus"),

    # ── why3 ──────────────────────────────────────────────────────────────────
    _ev("SAGE-3", "working",  "why3", "WHY3 — Consensus", 2000),
    _ev("SAGE-3", "thinking", "why3", "WHY3 — Consensus", 3000),
    _ev("SAGE-3", "complete", "why3", "WHY3 — Consensus", 2000, "2026-03-22T11:01:00Z"),
    _rsc("assess", "ASSESS — Kill Gate"),

    # ── assess (GATEKEEPER-2 passes) ──────────────────────────────────────────
    _ev("GATEKEEPER-2", "working",  "assess", "ASSESS — Kill Gate", 2000),
    _ev("GATEKEEPER-2", "thinking", "assess", "ASSESS — Kill Gate", 3000),
    _ev("GATEKEEPER-2", "complete", "assess", "ASSESS — Kill Gate", 2000, "2026-03-22T11:06:00Z"),
    _rsc("solution", "SOLUTION"),

    # ── solution ──────────────────────────────────────────────────────────────
    _ev("ARCHITECT-1", "working",  "solution", "SOLUTION", 2000),
    _ev("ARCHITECT-1", "thinking", "solution", "SOLUTION", 3000),
    _ev("ARCHITECT-1", "complete", "solution", "SOLUTION", 2000, "2026-03-22T11:11:00Z"),
    _ev("SENTINEL-1",  "working",  "solution", "SOLUTION", 2000),
    _ev("SENTINEL-1",  "complete", "solution", "SOLUTION", 2000, "2026-03-22T11:15:00Z"),
    _rsc("plan", "PLAN"),

    # ── plan ──────────────────────────────────────────────────────────────────
    _ev("ORCHESTRATOR-1", "working",  "plan", "PLAN", 2000),
    _ev("ORCHESTRATOR-1", "thinking", "plan", "PLAN", 3000),
    _ev("ORCHESTRATOR-1", "complete", "plan", "PLAN", 2000, "2026-03-22T11:20:00Z"),
    _rsc("finalize", "FINALIZE"),

    # ── finalize ──────────────────────────────────────────────────────────────
    _ev("REALIST-1", "working",  "finalize", "FINALIZE", 2000),
    _ev("REALIST-1", "complete", "finalize", "FINALIZE", 2000, "2026-03-22T11:24:00Z"),
    # AUDITOR-1 not in initial_agents (15 agents per spec); omit or add if needed.
    _rsc("finalize", "FINALIZE", status="done", completed_at="2026-03-22T11:24:30Z", delay_ms=1000),
]

_JOURNAL = {
    "GATEKEEPER-1": [
        {"id": "j-GATE-1-001", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742641200000, "type": "assessment",
         "content": "BLOCK — 3 critical requirements unresolved: payment idempotency (REQ-047), refund edge cases (REQ-051), fraud-check timeout handling (REQ-059)"},
        {"id": "j-GATE-1-002", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742641260000, "type": "decision",
         "content": "Routing back to CARTOGRAPHER-2 for rework — spec must explicitly define all three failure modes before re-assessment"},
        {"id": "j-GATE-1-003", "dispatch_id": "GATEKEEPER-1", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742649600000, "type": "assessment",
         "content": "Resumed after human review — rework completed, requirements now fully specified"},
    ],
    "CARTOGRAPHER-2": [
        {"id": "j-CART-2-001", "dispatch_id": "CARTOGRAPHER-2", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742650200000, "type": "decision",
         "content": "Added explicit failure mode specs for REQ-047, REQ-051, REQ-059 — idempotency key TTL set to 24h"},
        {"id": "j-CART-2-002", "dispatch_id": "CARTOGRAPHER-2", "codename": "CARTOGRAPHER",
         "run_id": _RUN_ID, "timestamp_ms": 1742650260000, "type": "amendment",
         "content": "Updated REQ-059: fraud-check timeout falls back to allow-with-flag, not reject — reduces false negatives"},
    ],
    "GATEKEEPER-2": [
        {"id": "j-GATE-2-001", "dispatch_id": "GATEKEEPER-2", "codename": "GATEKEEPER",
         "run_id": _RUN_ID, "timestamp_ms": 1742652600000, "type": "assessment",
         "content": "PASS — all previously blocked requirements now resolved, spec coverage 97%"},
    ],
}

BLOCKED_ESCALATION = Scenario(
    name="blocked-escalation",
    description="GATEKEEPER blocks at assess, triggers rework loop: 15 agents, 11 phases, ends status=done",
    initial_agents=_AGENTS,
    event_sequence=_EVENTS,
    initial_run=_INITIAL_RUN,
    journal_entries=_JOURNAL,
    loop=False,
)
register(BLOCKED_ESCALATION)
```

**Note on AUDITOR-1:** The spec table for blocked-escalation (section 3.2.3) lists exactly 15 agents: PROSPECTOR-1, SCOUT-1, SYNTHESIZER-1, TRACKER-1, SAGE-1, CARTOGRAPHER-1, SAGE-2, GATEKEEPER-1, CARTOGRAPHER-2, SAGE-3, GATEKEEPER-2, ARCHITECT-1, SENTINEL-1, ORCHESTRATOR-1, REALIST-1. AUDITOR-1 is intentionally absent from this scenario — the finalize phase is simplified to REALIST-1 only. The `_AGENTS` list above is correct at 15 entries. The test assertion `assert len(...) == 15` is authoritative.

- [ ] **Step 3: Register in `radar/scenarios/__init__.py`**

Add:
```python
from radar.scenarios import blocked_escalation as _blocked_escalation  # noqa: F401
```

- [ ] **Step 4: Run all tests**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v 2>&1 | tail -30
```
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add radar/scenarios/blocked_escalation.py radar/scenarios/__init__.py radar/tests/unit/test_new_scenarios.py
git commit -m "feat(radar): add blocked-escalation scenario (GATEKEEPER block + rework loop, 15 agents)"
```

---

## Task 6: `replay.py` — load_replay function

**Files:**
- Create: `radar/scenarios/replay.py`
- Create: `radar/tests/unit/test_replay.py`

### Context

`load_replay(filepath)` reads a JSONL recording, extracts the snapshot event to build `initial_agents` and `initial_run`, converts remaining events to `ScenarioEvent` with timing deltas. First non-snapshot event always gets `delay_ms=0`. NOT imported in `__init__.py` — imported directly in `mock_server.py` in Task 7.

- [ ] **Step 1: Write failing tests**

Create `radar/tests/unit/test_replay.py`:

```python
"""Tests for load_replay — JSONL recording to Scenario conversion."""
import json
import pytest
from pathlib import Path


def _write_recording(tmp_path, lines):
    p = tmp_path / "recording.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return str(p)


_SNAPSHOT_PAYLOAD = {
    "run_id": "test-run-001",
    "run": {"run_id": "test-run-001", "status": "running", "phase": "discover",
            "phase_display": "DISCOVER", "iteration": 1,
            "created_at": "2026-03-22T10:00:00Z", "updated_at": "2026-03-22T10:00:00Z",
            "completed_at": None},
    "agents": {
        "SCOUT-1": {"id": "SCOUT-1", "codename": "SCOUT", "display_name": "Scout 1",
                    "state": "idle", "phase": "discover", "dispatched_at": "2026-03-22T10:00:00Z"}
    },
    "dispatch_order": ["SCOUT-1"],
    "updated_at": "2026-03-22T10:00:00Z",
}

_SNAPSHOT_LINE = {"recorded_at_ms": 1000000, "event_type": "snapshot", "payload": _SNAPSHOT_PAYLOAD}
_EVENT_1 = {"recorded_at_ms": 1005000, "event_type": "agent_state_change",
             "payload": {"dispatch_id": "SCOUT-1", "state": "working"}}
_EVENT_2 = {"recorded_at_ms": 1012000, "event_type": "agent_state_change",
             "payload": {"dispatch_id": "SCOUT-1", "state": "complete"}}


def test_load_replay_missing_file_raises(tmp_path):
    from radar.scenarios.replay import load_replay
    with pytest.raises(FileNotFoundError):
        load_replay(str(tmp_path / "nonexistent.jsonl"))

def test_load_replay_returns_scenario(tmp_path):
    from radar.scenarios.replay import load_replay
    from radar.scenarios import Scenario
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1, _EVENT_2])
    s = load_replay(path)
    assert isinstance(s, Scenario)

def test_load_replay_name_is_replay(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert s.name == "replay"

def test_load_replay_description_contains_filename(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert "recording.jsonl" in s.description

def test_load_replay_loop_false(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert s.loop is False

def test_load_replay_initial_run_from_snapshot(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert s.initial_run["run_id"] == "test-run-001"
    assert s.initial_run["status"] == "running"

def test_load_replay_agents_from_snapshot(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1])
    s = load_replay(path)
    assert len(s.initial_agents) == 1
    assert s.initial_agents[0].dispatch_id == "SCOUT-1"

def test_load_replay_snapshot_not_in_event_sequence(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1, _EVENT_2])
    s = load_replay(path)
    types = [e.event_type for e in s.event_sequence]
    assert "snapshot" not in types

def test_load_replay_first_event_delay_zero(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1, _EVENT_2])
    s = load_replay(path)
    assert s.event_sequence[0].delay_ms == 0

def test_load_replay_subsequent_delay_from_timestamps(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_SNAPSHOT_LINE, _EVENT_1, _EVENT_2])
    s = load_replay(path)
    # _EVENT_2.recorded_at_ms - _EVENT_1.recorded_at_ms = 1012000 - 1005000 = 7000
    assert s.event_sequence[1].delay_ms == 7000

def test_load_replay_no_snapshot_raises(tmp_path):
    from radar.scenarios.replay import load_replay
    path = _write_recording(tmp_path, [_EVENT_1, _EVENT_2])
    with pytest.raises(ValueError, match="No snapshot event"):
        load_replay(path)

def test_load_replay_skips_malformed_lines(tmp_path):
    from radar.scenarios.replay import load_replay
    p = tmp_path / "recording.jsonl"
    p.write_text(
        json.dumps(_SNAPSHOT_LINE) + "\n"
        + "NOT_JSON\n"
        + json.dumps(_EVENT_1) + "\n"
    )
    s = load_replay(str(p))
    assert len(s.event_sequence) == 1  # only _EVENT_1; malformed skipped
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/unit/test_replay.py -v 2>&1 | tail -15
```
Expected: ModuleNotFoundError (`radar.scenarios.replay` does not exist).

- [ ] **Step 3: Create `radar/scenarios/replay.py`**

```python
"""
radar/scenarios/replay.py — Load a recorded JSONL session as a Scenario.

Usage (in mock_server.py main()):
    from radar.scenarios.replay import load_replay
    scenario = load_replay(args.replay)

NOT imported in radar/scenarios/__init__.py — does not register a scenario.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

from radar.scenarios import MockAgent, Scenario, ScenarioEvent


def load_replay(filepath: str) -> Scenario:
    """Read a JSONL recording file and return a one-shot Scenario for replay.

    Delay rule:
    - Snapshot event is excluded from event_sequence.
    - First non-snapshot event gets delay_ms = 0.
    - Each subsequent event: delay_ms = max(0, recorded_at_ms[i] - recorded_at_ms[i-1])
      where i-1 is the *previous non-snapshot event's* index.

    # TODO: speed multiplier — divide all delay_ms by factor when --speed N is added.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Recording file not found: {filepath}")

    records = []
    with open(path, "r") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[RADAR-REPLAY] Warning: skipping malformed line {lineno} in {filepath}",
                      file=sys.stderr)

    # Find snapshot event
    snapshot_record = None
    for record in records:
        if record.get("event_type") == "snapshot":
            snapshot_record = record
            break

    if snapshot_record is None:
        raise ValueError(f"No snapshot event found in recording file: {filepath}")

    payload = snapshot_record["payload"]
    initial_run = payload.get("run", {})
    agents_dict = payload.get("agents", {})
    dispatch_order = payload.get("dispatch_order", list(agents_dict.keys()))

    initial_agents = []
    for dispatch_id in dispatch_order:
        a = agents_dict.get(dispatch_id, {})
        initial_agents.append(MockAgent(
            dispatch_id=dispatch_id,
            codename=a.get("codename", dispatch_id),
            display_name=a.get("display_name", dispatch_id),
            state=a.get("state", "unknown"),
            phase=a.get("phase", ""),
            dispatched_at=a.get("dispatched_at", ""),
            completed_at=a.get("completed_at"),
            blocked_reason=a.get("blocked_reason"),
        ))

    # Build event_sequence — skip snapshot, compute delays
    non_snapshot = [r for r in records if r.get("event_type") != "snapshot"]
    event_sequence = []
    for i, record in enumerate(non_snapshot):
        delay_ms = 0 if i == 0 else max(0, record["recorded_at_ms"] - non_snapshot[i - 1]["recorded_at_ms"])
        event_sequence.append(ScenarioEvent(
            event_type=record["event_type"],
            payload=record["payload"],
            delay_ms=delay_ms,
        ))

    return Scenario(
        name="replay",
        description=f"Replay of {path.name}",
        initial_agents=initial_agents,
        event_sequence=event_sequence,
        initial_run=initial_run,
        journal_entries={},
        loop=False,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/unit/test_replay.py -v 2>&1 | tail -20
```
Expected: ALL PASS.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v 2>&1 | tail -10
```
Expected: ALL PASS (replay.py not auto-imported, doesn't affect other tests).

- [ ] **Step 6: Commit**

```bash
git add radar/scenarios/replay.py radar/tests/unit/test_replay.py
git commit -m "feat(radar): add load_replay — JSONL recording to Scenario with timing preservation"
```

---

## Task 7: `--replay` flag in `mock_server.py`

**Files:**
- Modify: `radar/mock_server.py`
- Modify: `radar/tests/cli/test_list_scenarios.py`

### Context

`main()` gains `--replay PATH` as a mutually exclusive alternative to `--scenario`. When `--replay` is used, `load_replay(path)` is called and the returned `Scenario` is passed to `create_app`. `--list-scenarios` output is updated to mention replay.

- [ ] **Step 1: Write failing tests**

Add to `radar/tests/cli/test_list_scenarios.py`:

```python
def test_list_scenarios_mentions_replay(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--list-scenarios"],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert "replay" in r.stdout
```

Create `radar/tests/cli/test_replay_flag.py`:

```python
"""CLI tests for --replay flag."""
import json
import subprocess
import sys
import os
import time
from pathlib import Path

RADAR_EXT = str(Path(__file__).parent.parent.parent.parent.resolve())


def _minimal_recording(tmp_path) -> str:
    """Write a minimal JSONL recording that starts and immediately ends."""
    snap = {
        "run_id": "replay-test-001",
        "run": {"run_id": "replay-test-001", "status": "running", "phase": "discover",
                "phase_display": "DISCOVER", "iteration": 1,
                "created_at": "2026-03-22T10:00:00Z", "updated_at": "2026-03-22T10:00:00Z",
                "completed_at": None},
        "agents": {
            "SCOUT-1": {"id": "SCOUT-1", "codename": "SCOUT", "display_name": "Scout 1",
                        "state": "idle", "phase": "discover",
                        "dispatched_at": "2026-03-22T10:00:00Z"}
        },
        "dispatch_order": ["SCOUT-1"],
        "updated_at": "2026-03-22T10:00:00Z",
    }
    lines = [
        {"recorded_at_ms": 1000000, "event_type": "snapshot", "payload": snap},
        {"recorded_at_ms": 1001000, "event_type": "agent_state_change",
         "payload": {"dispatch_id": "SCOUT-1", "state": "working"}},
    ]
    p = tmp_path / "test.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return str(p)


def test_replay_nonexistent_file_exits_nonzero(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    env["RADAR_SQUAD_DIR"] = str(tmp_path / "squad")
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--replay", str(tmp_path / "nonexistent.jsonl")],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert r.returncode != 0
    assert "not found" in r.stderr.lower() or "not found" in r.stdout.lower()


def test_replay_scenario_and_replay_mutually_exclusive(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = RADAR_EXT
    recording = _minimal_recording(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "radar.mock_server", "--scenario", "default", "--replay", recording],
        env=env, capture_output=True, text=True, timeout=5,
    )
    assert r.returncode != 0  # argparse rejects mutually exclusive args
```

- [ ] **Step 2: Modify `main()` in `radar/mock_server.py`**

Replace the `--scenario` argument definition and the validation block with a mutually exclusive group:

```python
def main() -> None:
    global _written_port, _squad_dir, _stop_event, _clients

    import argparse
    import os
    from radar.scenarios import get_scenario, list_scenarios

    parser = argparse.ArgumentParser(
        prog="python -m radar.mock_server",
        description="Fake RADAR mock server — sends scripted SSE events to squad-monitor UI",
    )

    # IMPORTANT: do NOT set default="default" on --scenario inside the mutually
    # exclusive group. Argparse sets the default regardless of which flag the user
    # actually passed, making args.scenario always "default" even when --replay is
    # used — which defeats the mutual exclusion check and generates a Python 3.12
    # argparse warning. Instead, default=None here and resolve below.
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--scenario",
        default=None,        # NOT "default" — handle the default case below
        metavar="NAME",
        help="Named scenario to run (default: default)",
    )
    mode_group.add_argument(
        "--replay",
        metavar="PATH",
        help="Replay a recorded JSONL session file",
    )

    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List all available scenarios and exit",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Starting port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--squad-dir",
        default=None,
        metavar="PATH",
        help="Path to squad state directory (default: .specify/squad or RADAR_SQUAD_DIR env var)",
    )
    args = parser.parse_args()

    # --list-scenarios
    if args.list_scenarios:
        scenarios = list_scenarios()
        print("Available scenarios:")
        for s in scenarios:
            print(f"  {s.name:<18}{s.description}")
        print(f"  {'replay <PATH>':<18}Replay a recorded session (.jsonl file)")
        sys.exit(0)

    # Resolve scenario
    if args.replay:
        from radar.scenarios.replay import load_replay
        try:
            scenario = load_replay(args.replay)
        except FileNotFoundError as e:
            print(f"[RADAR-MOCK] Error: {e}", file=sys.stderr)
            sys.exit(1)
        scenario_label = f"replay ({Path(args.replay).name})"
    else:
        # args.scenario is None when neither flag is passed; default to "default"
        scenario_name = args.scenario or "default"
        scenario = get_scenario(scenario_name)
        if scenario is None:
            available = ", ".join(s.name for s in list_scenarios())
            print(f'[RADAR-MOCK] Error: unknown scenario "{scenario_name}"', file=sys.stderr)
            print(f"Available scenarios: {available}", file=sys.stderr)
            sys.exit(1)
        scenario_label = scenario_name

    # Resolve squad_dir
    if args.squad_dir:
        squad_dir = Path(args.squad_dir)
    else:
        squad_dir = Path(os.environ.get("RADAR_SQUAD_DIR", ".specify/squad"))
    squad_dir.mkdir(parents=True, exist_ok=True)

    # Find available port
    try:
        actual_port = find_available_port(start=args.port)
    except RuntimeError:
        print(f"[RADAR-MOCK] Error: no available port in range {args.port}–{args.port + MAX_PORT_ATTEMPTS - 1}",
              file=sys.stderr)
        sys.exit(1)

    _written_port = actual_port
    _squad_dir = squad_dir

    app, stop_event = create_app(scenario, squad_dir=squad_dir, port=actual_port)
    _stop_event = stop_event
    _clients = app.config["clients"]

    (squad_dir / "radar.port").write_text(str(actual_port) + "\n")

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    print(f"[RADAR-MOCK] Starting on port {actual_port} with scenario '{scenario_label}'")
    print(f"[RADAR-MOCK] Squad dir: {squad_dir}")
    print(f"[RADAR-MOCK] Press Ctrl-C to stop")

    app.run(host="0.0.0.0", port=actual_port, threaded=True, use_reloader=False)
```

Also add `from pathlib import Path` to the import at the top of `main()` if not already present (it already is at module level).

- [ ] **Step 3: Run all tests**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v 2>&1 | tail -30
```
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add radar/mock_server.py radar/tests/cli/test_list_scenarios.py radar/tests/cli/test_replay_flag.py
git commit -m "feat(radar): add --replay flag to mock_server for JSONL recording playback"
```

---

## Task 8: `--record` flag in `radar/server.py`

**Files:**
- Modify: `radar/server.py`
- Create: `radar/tests/unit/test_recorder.py`

### Context

The production server (`radar/server.py`) gains a `--record PATH` CLI flag. When set, every call to `broadcast_event` appends a JSONL line to the recording file. A module-level `threading.Lock` (`_record_lock`) serializes concurrent append operations. The snapshot is also recorded on startup.

- [ ] **Step 1: Write failing tests**

Create `radar/tests/unit/test_recorder.py`:

```python
"""Tests for the --record flag in radar/server.py's broadcast_event."""
import json
import threading
import time
import pytest


def _make_recorder(tmp_path):
    """Helper: set up _record_path in server module and return path."""
    import radar.server as srv
    p = tmp_path / "recording.jsonl"
    srv._record_path = str(p)
    yield str(p)
    srv._record_path = None  # cleanup


def test_record_event_creates_file(tmp_path):
    import radar.server as srv
    path = str(tmp_path / "rec.jsonl")
    srv._record_path = path
    try:
        srv._record_event("heartbeat", {"ts": "2026-03-22T10:00:00Z"})
        assert (tmp_path / "rec.jsonl").exists()
    finally:
        srv._record_path = None


def test_record_event_appends_valid_jsonl(tmp_path):
    import radar.server as srv
    path = str(tmp_path / "rec.jsonl")
    srv._record_path = path
    try:
        srv._record_event("heartbeat", {"ts": "2026-03-22T10:00:00Z"})
        srv._record_event("agent_state_change", {"dispatch_id": "SCOUT-1", "state": "working"})
        lines = (tmp_path / "rec.jsonl").read_text().strip().split("\n")
        assert len(lines) == 2
        record = json.loads(lines[0])
        assert record["event_type"] == "heartbeat"
        assert "recorded_at_ms" in record
        assert "payload" in record
    finally:
        srv._record_path = None


def test_record_event_noop_when_path_none(tmp_path):
    import radar.server as srv
    srv._record_path = None
    specific_file = tmp_path / "should_not_exist.jsonl"
    # Temporarily override to a known path so we can check it wasn't created
    # (don't set _record_path — it's None, so no file should be written)
    srv._record_event("heartbeat", {"ts": "2026-03-22T10:00:00Z"})
    # Check the specific file was not created (not any(iterdir()) is fragile
    # if pytest writes other fixtures into tmp_path)
    assert not specific_file.exists()


def test_record_event_thread_safe(tmp_path):
    """Multiple threads appending should produce all expected lines."""
    import radar.server as srv
    path = str(tmp_path / "rec.jsonl")
    srv._record_path = path
    try:
        errors = []
        def write_events():
            try:
                for i in range(10):
                    srv._record_event("heartbeat", {"i": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_events) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        lines = (tmp_path / "rec.jsonl").read_text().strip().split("\n")
        assert len(lines) == 50  # 5 threads × 10 events each
        for line in lines:
            json.loads(line)  # each line must be valid JSON
    finally:
        srv._record_path = None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/unit/test_recorder.py -v 2>&1 | tail -15
```
Expected: AttributeError (`radar.server` has no `_record_path` or `_record_event`).

- [ ] **Step 3: Add `_record_path`, `_record_lock`, and `_record_event` to `radar/server.py`**

Add after the existing module-level state (after the `clients` dict, around line 45):

```python
import time  # already imported above — verify; add if missing

# ── Recording ─────────────────────────────────────────────────────────────────

_record_path: str | None = None   # set by --record PATH at startup
_record_lock = threading.Lock()


def _record_event(event_type: str, payload: dict) -> None:
    """Append one JSONL line to the recording file (thread-safe, no-op if not recording)."""
    if _record_path is None:
        return
    line = json.dumps({
        "recorded_at_ms": int(time.time() * 1000),
        "event_type": event_type,
        "payload": payload,
    })
    with _record_lock:
        with open(_record_path, "a") as f:
            f.write(line + "\n")
```

- [ ] **Step 4: Call `_record_event` inside `broadcast_event`**

Find `broadcast_event` in `radar/server.py` (around line 117). Add a recording call at the start of the function:

```python
def broadcast_event(event_type: str, data: dict) -> None:
    """Send event to all connected clients."""
    _record_event(event_type, data)   # ← ADD THIS LINE (no-op if _record_path is None)

    event_str = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    dead_clients = []
    # ... rest of function unchanged
```

- [ ] **Step 5: Add `--record PATH` argument to `main()` in `radar/server.py`**

Replace the manual argv parsing in `main()`:

```python
def main():
    global observer, _record_path

    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m radar.server",
        description="RADAR SSE server — watches agent state files and streams to UI",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Starting port (default: {DEFAULT_PORT})")
    parser.add_argument("--record", metavar="PATH", default=None,
                        help="Path to record all SSE events as JSONL for replay")
    args = parser.parse_args()

    port = int(os.environ.get("PORT", args.port))
    _record_path = args.record
```

Remove the old manual argv parsing loop (the `for i, arg in enumerate(sys.argv): if arg == "--port"` block).

- [ ] **Step 6: Record initial snapshot on startup**

In `main()`, after `load_initial_state()` is called, add:

```python
    load_initial_state()

    # Record initial snapshot if recording is active
    if _record_path:
        _record_event("snapshot", snapshot)
```

- [ ] **Step 7: Run all tests**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v 2>&1 | tail -20
```
Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add radar/server.py radar/tests/unit/test_recorder.py
git commit -m "feat(radar): add --record PATH flag to server.py for SSE event recording"
```

---

## Task 9: Infrastructure — `config-template.yml` + `commands/cognitive-squad.run.md`

**Files:**
- Modify: `config-template.yml`
- Modify: `commands/cognitive-squad.run.md`

### Context

Two small additions: (1) `record: false` in the `radar:` block of `config-template.yml`, (2) `RADAR_RECORD_FLAG` shell block in `cognitive-squad.run.md` before the `python3 -m radar.server` invocation.

- [ ] **Step 1: Update `config-template.yml`**

Find the `radar:` block (lines ~54-67). Add `record: false` after the `port:` line:

```yaml
radar:
  # Enable/disable RADAR monitoring server
  # [default: true] Set false to disable automatic RADAR startup
  enabled: true

  # Port for RADAR SSE server
  # [range: 1024-65535] [default: 7891]
  # If port is in use, RADAR auto-increments until it finds an available port
  port: 7891

  # Record all SSE events to a JSONL file for later replay in the mock server
  # [default: false] Set true to enable recording.
  # Recording file: .specify/squad/radar-recording-{run_id}.jsonl
  record: false

  # Host binding
  # [default: localhost] Set to 0.0.0.0 to expose on LAN
  # host: localhost
```

- [ ] **Step 2: Update `commands/cognitive-squad.run.md`**

Find lines 305-310 (the RADAR startup block):

```bash
# Read port from config (default 7891)
RADAR_PORT=$(grep -A2 "^radar:" squad-config.yml 2>/dev/null | grep "port:" | awk '{print $2}' || echo 7891)

# Start RADAR in background (PYTHONPATH allows python -m radar.server to work)
PYTHONPATH=${RADAR_EXT} python3 -m radar.server --port ${RADAR_PORT:-7891} \
  >> .specify/squad/radar.log 2>&1 &
```

Replace with:

```bash
# Read port from config (default 7891)
RADAR_PORT=$(grep -A2 "^radar:" squad-config.yml 2>/dev/null | grep "port:" | awk '{print $2}' || echo 7891)

# Optional: record SSE events for replay (set radar.record: true in squad-config.yml)
# Note: -A3 is intentional — config-template.yml has a comment line between
# "radar:" and "record:", so -A1 would miss it.
RADAR_RECORD_FLAG=""
if [ "$(grep -A3 'radar:' squad-config.yml 2>/dev/null | grep 'record:' | awk '{print $2}')" = "true" ]; then
  RADAR_RECORD_FLAG="--record .specify/squad/radar-recording-${run_id}.jsonl"
fi

# Start RADAR in background (PYTHONPATH allows python -m radar.server to work)
PYTHONPATH=${RADAR_EXT} python3 -m radar.server --port ${RADAR_PORT:-7891} \
  ${RADAR_RECORD_FLAG} \
  >> .specify/squad/radar.log 2>&1 &
```

- [ ] **Step 3: Run full test suite**

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v 2>&1 | tail -10
```
Expected: ALL PASS (no test covers these YAML/shell changes directly).

- [ ] **Step 4: Commit**

```bash
git add config-template.yml commands/cognitive-squad.run.md
git commit -m "feat(radar): add record flag to config-template; add RADAR_RECORD_FLAG to cognitive-squad.run.md"
```

---

## Task 10: Protocol contract doc

**Files:**
- Create: `docs/radar-protocol-contract.md`

### Context

Handover document for the UI session. Describes new/updated SSE events, the /journal endpoint, and known UI gaps that need to be addressed to get full Warscape fidelity. No code changes.

- [ ] **Step 1: Create `docs/radar-protocol-contract.md`**

```markdown
# RADAR Protocol Contract — UI Handover

**Date:** 2026-03-23
**Scope:** Changes to the RADAR SSE protocol introduced in the mock-scenarios session.
**Audience:** UI developer implementing Warscape support in `squad-monitor`.

---

## 1. New / Updated SSE Events

### 1.1 `run_state_change` (existing event, now correctly emitted)

The mock server now emits `run_state_change` on every phase transition and at terminal state. Previously this event was never emitted.

**SSE wire format:**
```
event: run_state_change
data: {"ts": "2026-03-22T18:30:00Z", "run": {...}}
```

**`event.data` parsed shape:**
```json
{
  "ts": "2026-03-22T18:30:00Z",
  "run": {
    "run_id": "squad-001-1742670000",
    "status": "running",
    "phase": "why1",
    "phase_display": "WHY1 — Assumption Challenge",
    "iteration": 1,
    "created_at": "2026-03-22T18:00:00Z",
    "updated_at": "2026-03-22T18:30:00Z",
    "completed_at": null
  }
}
```

**UI action required:**
- Read `JSON.parse(event.data).run` — this is the full SquadRun object.
- Update `squad.run` in the Zustand store (or equivalent).
- When `status` transitions to `"done"` or `"blocked"`, trigger `RunSummaryPanel`.
- Use `run.phase` + `run.phase_display` to update the active Geoscape territory strip.

**Terminal payload:** same shape with `status: "done"` or `status: "blocked"` and `completed_at` set to ISO timestamp.

---

### 1.2 `snapshot` (updated — `run` object now present)

The snapshot payload now includes a top-level `run` key containing the full SquadRun object.

**Updated shape:**
```json
{
  "run_id": "squad-001-1742670000",
  "run": {
    "run_id": "squad-001-1742670000",
    "status": "running",
    "phase": "discover",
    "phase_display": "DISCOVER",
    "iteration": 1,
    "created_at": "2026-03-22T18:00:00Z",
    "updated_at": "2026-03-22T18:00:00Z",
    "completed_at": null
  },
  "agents": { ... },
  "dispatch_order": [ ... ],
  "updated_at": "2026-03-22T18:00:00Z"
}
```

**UI action required:**
- On snapshot, read `payload.run` directly and populate the Zustand `squad.run` slice.
- Do NOT derive `phase` from the first agent's phase or hardcode `status: "running"`.
- Do NOT hardcode `iteration: 1`.

---

## 2. `/journal` Endpoint

```
GET /journal?run_id=<run_id>&agent=<dispatch_id>
```

**Response:** JSON array (not a dict). Empty array `[]` on any missing/wrong param.

**Empty-return conditions:**
- `agent` param missing or empty → `[]`
- `run_id` param missing or empty → `[]`
- `agent` not in scenario's journal entries → `[]`
- `run_id` does not match current run → `[]`

**Non-empty response shape:**
```json
[
  {
    "id": "j-SCOUT-1-003",
    "dispatch_id": "SCOUT-1",
    "codename": "SCOUT",
    "run_id": "squad-001-1742670000",
    "timestamp_ms": 1742670125000,
    "type": "decision",
    "content": "Treating payments and auth as separate bounded contexts"
  },
  {
    "id": "j-SCOUT-1-002",
    ...
  }
]
```

**Sort order:** newest-first by `timestamp_ms`.

**Entry `type` values:** `decision | finding | assumption | risk | question | answer | concern | amendment | assessment`

---

## 3. Known UI Gaps (non-blocking for mock work)

These gaps exist in `squad-monitor` and must be addressed in the UI session to achieve full Warscape fidelity.

| Gap | File / Location | Impact |
|---|---|---|
| `run_state_change` handler is no-op | `App.tsx` event listener | Geoscape active territory never updates |
| Snapshot normalizer hardcodes `status: "running"`, `iteration: 1` | snapshot normalizer | `RunSummaryPanel` never fires |
| `run.phase` derived from first agent's phase | snapshot normalizer | Active territory may be wrong in multi-phase runs |
| Tile/territory click → detail panel wiring unimplemented | Warscape/Battlescape | `AgentDetailPanel` never opens from Warscape |
| No `/journal` call triggered from UI | `AgentDetailPanel` | Journal feed always empty |

---

## 4. Available Mock Scenarios

| Scenario | Agents | Phases | Terminal status | Notes |
|---|---|---|---|---|
| `default` | 8 | 1 (OPERATIONS) | — (loops) | All 7 states exercised, loops forever |
| `all-blocked` | 8 | 1 (OPERATIONS) | — (static) | Static snapshot, all blocked |
| `greenfield` | 13 | 9 | `done` | Happy-path one-shot lifecycle |
| `brownfield` | 14 | 9 | `done` | Same as greenfield + GOLDDIGGER-1 in discover |
| `blocked-escalation` | 15 | 11 | `done` | GATEKEEPER block + CARTOGRAPHER rework loop |
| `replay <PATH>` | varies | varies | varies | Replay a real `.jsonl` recording |

Run mock server: `python3 -m radar.mock_server --scenario greenfield`
Run replay: `python3 -m radar.mock_server --replay .specify/squad/radar-recording-<run_id>.jsonl`

---

## 5. Recording a Real Run

Set `record: true` in `squad-config.yml` under the `radar:` key before starting a squad run. The production RADAR server will write `.specify/squad/radar-recording-<run_id>.jsonl`. This file can be replayed in the mock server without any manual authoring.
```

- [ ] **Step 2: Commit**

```bash
git add -f docs/radar-protocol-contract.md
git commit -m "docs(radar): add UI handover protocol contract"
```

---

## Final verification

After all 10 tasks:

```bash
cd /Users/michalbachorik/work/cognitive-squad && PATH=/usr/bin:/bin python3 -m pytest radar/tests/ -v 2>&1 | tail -20
```
Expected: ALL PASS, 0 FAIL.

Smoke test all new scenarios:
```bash
cd /Users/michalbachorik/work/cognitive-squad
PATH=/usr/bin:/bin PYTHONPATH=. python3 -c "
from radar.scenarios import list_scenarios
for s in list_scenarios():
    print(s.name, len(s.initial_agents), 'agents', len(s.event_sequence), 'events')
"
```
Expected output includes: `greenfield`, `brownfield`, `blocked-escalation` with their agent/event counts.
