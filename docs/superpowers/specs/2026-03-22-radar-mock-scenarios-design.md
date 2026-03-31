# RADAR Mock Scenarios: Rich Lifecycle Scenarios + Record/Replay

**Date:** 2026-03-22
**Status:** Approved
**Scope:** `radar/` — mock server, scenarios, recorder, replay; `docs/radar-protocol-contract.md`

---

## 1. Problem Statement

The current mock server (`radar/mock_server.py`) has two scenarios:

- `default` — 8 agents in a single "OPERATIONS" phase cycling through all 7 states every ~35 seconds, looping indefinitely
- `all-blocked` — static snapshot, all agents blocked

Neither scenario exercises Warscape meaningfully:
- All agents share one phase — Geoscape shows one territory, fog never lifts
- No phase transitions — `run_state_change` events never emitted
- `run.status` is never `"done"` or `"blocked"` — `RunSummaryPanel` never fires
- `/journal` endpoint returns empty list — `AgentDetailPanel` journal feed is always empty
- No path from a real squad run to the mock server — every scenario is hand-authored

---

## 2. Design Goals

- Warscape Battlescape and Geoscape are exercised fully: fog lifts progressively, active territory updates, terminal state reached
- `RunSummaryPanel` fires correctly at run completion
- `AgentDetailPanel` journal feed has realistic entries
- Mock server emits the protocol as it *should be*, not worked around for current UI gaps
- A real squad run can be recorded and replayed in the mock server without manual authoring
- Protocol additions are captured in a handover doc for the UI session

---

## 3. Components

### 3.1 Data Model Changes — `radar/scenarios/__init__.py`

`Scenario` dataclass gains two fields and flips the `loop` default:

```python
@dataclass
class Scenario:
    name: str
    description: str
    initial_agents: list[MockAgent]
    event_sequence: list[ScenarioEvent]
    initial_run: dict                    # NEW — SquadRun dict for snapshot and run state tracking
    journal_entries: dict[str, list[dict]]  # NEW — keyed by dispatch_id, served from /journal
    loop: bool = False                   # default flipped to False (one-shot is the new norm)
```

`initial_run` required fields: `run_id`, `status`, `phase`, `phase_display`, `iteration`, `created_at`, `updated_at`, `completed_at`.

`journal_entries` keys are `dispatch_id` strings (e.g. `"SCOUT-1"`). Values are lists of journal entry dicts matching the `/journal` response schema in Section 3.3.3. Entries may be defined in any order — the mock server sorts newest-first before serving.

`ScenarioEvent` and `MockAgent` are unchanged.

**`MockAgent.display_name` convention:** title-case from dispatch_id with space before the number. `"SCOUT-1"` → `"Scout 1"`, `"CARTOGRAPHER-2"` → `"Cartographer 2"`, `"SAGE-3"` → `"Sage 3"`.

The existing `default` and `all-blocked` scenarios gain `initial_run` and `journal_entries: {}` (empty). They retain their existing `loop` values (`default: loop=True`, `all-blocked: loop=False`).

**Migration of existing `display_name` values:** The current `default.py` and `all_blocked.py` use the old convention (`"Scout-1"`, hyphen). Both files must be updated so all `MockAgent.display_name` values match the new title-case-space convention (`"Scout 1"`). An implementer who updates only new scenarios will produce inconsistent `display_name` values across scenarios.

---

### 3.2 Three New One-Shot Lifecycle Scenarios

All three scenarios:
- `loop=False` — run once, then stop emitting events
- Emit `run_state_change` on every phase transition and at terminal state
- Include synthetic journal entries per agent (3–5 entries per dispatch_id)
- End with a terminal `run_state_change`: `status: "done"` or `status: "blocked"`

#### 3.2.1 `greenfield` — `radar/scenarios/greenfield.py`

Clean happy-path run. 13 agents, ~65 events, ~8 minutes simulated duration.

**Phase sequence and agents:**

| Phase | `phase_display` | Agents |
|---|---|---|
| `discover` | DISCOVER | PROSPECTOR-1, SCOUT-1 |
| `synthesize` | SYNTHESIZE | SYNTHESIZER-1, TRACKER-1 |
| `why1` | WHY1 — Assumption Challenge | SAGE-1 |
| `cartographer` | CARTOGRAPHER | CARTOGRAPHER-1 |
| `why2` | WHY2 — Spec Validation | SAGE-2 |
| `assess` | ASSESS — Kill Gate | GATEKEEPER-1 |
| `solution` | SOLUTION | ARCHITECT-1, SENTINEL-1 |
| `plan` | PLAN | ORCHESTRATOR-1 |
| `finalize` | FINALIZE | REALIST-1, AUDITOR-1 |

**Event cadence per agent:** `working` (delay 2000ms) → optional `thinking` (delay 3000ms) → `complete` (delay 2000ms). Phase transition `run_state_change` fires after the last agent in that phase reaches `complete` (delay 500ms after that agent's complete event).

**Terminal `run_state_change`:** fired 1000ms after AUDITOR-1 and REALIST-1 both complete. Payload: `status: "done"`, `completed_at` set to ISO timestamp.

#### 3.2.2 `brownfield` — `radar/scenarios/brownfield.py`

Same pipeline as `greenfield` but the `discover` phase adds GOLDDIGGER-1 between PROSPECTOR-1 and SCOUT-1. 14 agents total.

GOLDDIGGER-1 state sequence: `working` (delay 2000ms) → `thinking` (delay 5000ms, Mode 1 survey) → `complete` (delay 1000ms). SCOUT-1 events begin only after GOLDDIGGER-1 reaches `complete`.

Note: `artifacts_produced` is not included in GOLDDIGGER-1's `complete` event payload. The UI does not currently display agent artifacts; artifact surfacing in the UI is out of scope for this session and should be addressed in the UI session.

This is the only structural difference from `greenfield`. All other phases and agents are identical.

#### 3.2.3 `blocked-escalation` — `radar/scenarios/blocked_escalation.py`

GATEKEEPER blocks at `assess`, triggering a rework loop before the run eventually completes. 15 agents, ~85 events.

**Phase sequence:**

| Phase | `phase_display` | Agents | Notes |
|---|---|---|---|
| `discover` | DISCOVER | PROSPECTOR-1, SCOUT-1 | Normal |
| `synthesize` | SYNTHESIZE | SYNTHESIZER-1, TRACKER-1 | Normal |
| `why1` | WHY1 — Assumption Challenge | SAGE-1 | Normal |
| `cartographer` | CARTOGRAPHER | CARTOGRAPHER-1 | Normal |
| `why2` | WHY2 — Spec Validation | SAGE-2 | Normal |
| `assess` | ASSESS — Kill Gate | GATEKEEPER-1 | Blocks then resumes |
| `cartographer` | CARTOGRAPHER (rework) | CARTOGRAPHER-2 | Appears in sequence after GATEKEEPER-1 resumes |
| `why3` | WHY3 — Consensus | SAGE-3 | |
| `assess` | ASSESS — Kill Gate | GATEKEEPER-2 | Passes |
| `solution` | SOLUTION | ARCHITECT-1, SENTINEL-1 | |
| `plan` | PLAN | ORCHESTRATOR-1 | |
| `finalize` | FINALIZE | REALIST-1, AUDITOR-1 | |

**GATEKEEPER-1 event sequence in `event_sequence`:**

```
ScenarioEvent("agent_state_change", {dispatch_id: "GATEKEEPER-1", state: "working", ...}, delay_ms=2000)
ScenarioEvent("agent_state_change", {dispatch_id: "GATEKEEPER-1", state: "thinking", ...}, delay_ms=4000)
ScenarioEvent("agent_state_change", {dispatch_id: "GATEKEEPER-1", state: "blocked",
    blocked_reason: "Spec coverage below kill threshold — 3 critical requirements unresolved", ...}, delay_ms=3000)
ScenarioEvent("run_state_change", {ts: "...", run: {status: "blocked", phase: "assess", ...}}, delay_ms=500)
# 8000ms pause simulates human review window
ScenarioEvent("agent_state_change", {dispatch_id: "GATEKEEPER-1", state: "working", blocked_reason: null, ...}, delay_ms=8000)
# CARTOGRAPHER-2 events follow immediately in the sequence
ScenarioEvent("run_state_change", {ts: "...", run: {status: "running", phase: "cartographer", ...}}, delay_ms=500)
ScenarioEvent("agent_state_change", {dispatch_id: "CARTOGRAPHER-2", state: "working", phase: "cartographer", ...}, delay_ms=1000)
# ... CARTOGRAPHER-2 progresses through thinking → complete, then SAGE-3, GATEKEEPER-2, etc.
```

CARTOGRAPHER-2 and subsequent agents are plain `ScenarioEvent` entries in the sequence — there is no conditional dispatch mechanism. The event_sequence is a flat ordered list; the scenario author is responsible for correct ordering.

**Terminal `run_state_change`:** `status: "done"`, after AUDITOR-1 and REALIST-1 complete.

---

### 3.3 Protocol Extension

#### 3.3.1 SSE Wire Format Clarification

The mock server's `broadcast_sse(event_type, data)` function constructs:
```
event: <event_type>\ndata: <json.dumps(data)>\n\n
```

The SSE `event:` line carries the event type. The `data:` line carries the payload dict. The UI reads `event.type` (SSE named event) and `JSON.parse(event.data)`.

**`run_state_change` payload dict** (what goes into `ScenarioEvent.payload` and into `data:`):

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

`ts` is a static string included in the payload by the scenario author (not injected by the server). Terminal payload: same shape with `status: "done"` or `status: "blocked"` and `completed_at` set.

The UI's `event.data` for a `run_state_change` event will be this dict. The UI reads `JSON.parse(event.data).run`.

#### 3.3.2 `snapshot` Event — `run` Object Added

`mock_snapshot` in `mock_server.py` gains a `run` key initialized from `scenario.initial_run`. On `GET /snapshot` and on the initial SSE `snapshot` event, the full `mock_snapshot` is sent — including `run`.

When `scenario_loop` processes a `run_state_change` event, before broadcasting, it updates `mock_snapshot["run"]` with the `run` dict from the event payload. This ensures `GET /snapshot` always reflects the current run state.

Updated snapshot payload (what the UI receives as `JSON.parse(event.data)`):

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
  "dispatch_order": [ ... ]
}
```

#### 3.3.3 `/journal` Endpoint Contract

```
GET /journal?run_id=<run_id>&agent=<dispatch_id>
```

- If `agent` is missing or empty: return `[]`
- If `run_id` is missing or empty: return `[]`
- If `agent` does not match any key in `scenario.journal_entries`: return `[]`
- If `run_id` does not match `scenario.initial_run["run_id"]`: return `[]`

Response: JSON array, sorted newest-first by `timestamp_ms`:

```json
[
  {
    "id": "j-SCOUT-1-003",
    "dispatch_id": "SCOUT-1",
    "codename": "SCOUT",
    "run_id": "squad-001-1742670000",
    "timestamp_ms": 1742670125000,
    "type": "decision",
    "content": "Treating payments and auth as separate bounded contexts — different ownership, different release cadence"
  },
  {
    "id": "j-SCOUT-1-002",
    "dispatch_id": "SCOUT-1",
    "codename": "SCOUT",
    "run_id": "squad-001-1742670000",
    "timestamp_ms": 1742670090000,
    "type": "finding",
    "content": "Identified 3 bounded contexts: auth, payments, notifications"
  }
]
```

Entry `type` values (matching existing UI types): `decision | finding | assumption | risk | question | answer | concern | amendment`.

---

### 3.4 `mock_server.py` Changes

**`scenario_loop` — handle `run_state_change`:**

The existing agent-patching code in `scenario_loop` runs for `agent_state_change` events. For `run_state_change` events, a separate branch updates `mock_snapshot["run"]` with `event.payload["run"]` before broadcasting. No agent-patching occurs.

```python
if event.event_type == "run_state_change":
    mock_snapshot["run"] = event.payload["run"]
    broadcast_sse("run_state_change", event.payload)
elif event.event_type == "agent_state_change":
    # existing agent patching logic
    dispatch_id = event.payload.get("dispatch_id")
    if dispatch_id and dispatch_id in mock_snapshot["agents"]:
        mock_snapshot["agents"][dispatch_id].update(event.payload)
    broadcast_sse("agent_state_change", event.payload)
```

**`mock_snapshot` initialization:**

```python
mock_snapshot = {
    "run_id": scenario.initial_run["run_id"],
    "run": dict(scenario.initial_run),        # NEW
    "agents": {a.dispatch_id: a.to_dict() for a in scenario.initial_agents},
    "dispatch_order": [a.dispatch_id for a in scenario.initial_agents],
    "updated_at": scenario.initial_run["updated_at"],
}
```

Note: `updated_at` is taken from `scenario.initial_run` (the scenario's authored value), not from `_now()` at server startup. This is intentional — it preserves the run's authored timeline for replay fidelity and avoids the snapshot appearing newer than the agent events that follow it.

**`/journal` endpoint:** added to `create_app()`. Reads `run_id` and `agent` from query params; looks up `scenario.journal_entries.get(agent, [])`; filters by `run_id`; sorts newest-first by `timestamp_ms`; returns JSON.

**`create_app()` signature change:** `create_app()` currently takes `scenario_name: str` and calls `get_scenario(scenario_name)` internally. It must be refactored to accept a `Scenario` object directly: `create_app(scenario: Scenario)`. `main()` resolves the `Scenario` (either via `get_scenario(args.scenario)` or `load_replay(args.replay)`) before calling `create_app(scenario)`. This keeps all resolution logic in `main()`.

**`--replay PATH` flag:** added to `main()`. Mutually exclusive with `--scenario` (argparse `mutually_exclusive_group`). Calls `load_replay(path)` imported directly in `mock_server.py` (not via `__init__.py` — see Section 3.7). If `PATH` does not exist, exit with error: `"Recording file not found: {PATH}"`. Listed in `--list-scenarios` output as `replay (<filename>)`.

---

### 3.5 Recorder — `radar/server.py`

Production server gains `--record PATH` CLI flag. When set, every SSE event broadcast is also appended to a JSONL recording file.

**Thread safety:** The server has multiple SSE client threads. Appending to a file is not atomic under concurrent access. A `threading.Lock` (module-level `_record_lock`) guards all append operations. Pattern:

```python
_record_lock = threading.Lock()

def _record_event(path: str, event_type: str, payload: dict) -> None:
    line = json.dumps({
        "recorded_at_ms": int(time.time() * 1000),
        "event_type": event_type,
        "payload": payload,
    })
    with _record_lock:
        with open(path, "a") as f:
            f.write(line + "\n")
```

No temp-file/rename pattern — plain append with lock. Partial lines are not possible because the lock serialises writes and `write()` of a complete line is atomic at the OS level for local filesystems.

**Recording format:**

```jsonl
{"recorded_at_ms": 1742670000000, "event_type": "snapshot", "payload": {...}}
{"recorded_at_ms": 1742670062000, "event_type": "agent_state_change", "payload": {...}}
{"recorded_at_ms": 1742670125000, "event_type": "run_state_change", "payload": {...}}
```

Recording is append-safe on server restart (file opened in `"a"` mode). Partial files are replayable up to the last complete line.

**`commands/echelon.run.md` integration** — RADAR startup block gains, before the `python3 -m radar.server` call:

```bash
RADAR_RECORD_FLAG=""
if [ "$(grep -A1 'radar:' squad-config.yml 2>/dev/null | grep 'record:' | awk '{print $2}')" = "true" ]; then
  RADAR_RECORD_FLAG="--record .specify/squad/radar-recording-${run_id}.jsonl"
fi

PYTHONPATH=${RADAR_EXT} python3 -m radar.server --port ${RADAR_PORT:-7891} \
  ${RADAR_RECORD_FLAG} \
  >> .specify/squad/radar.log 2>&1 &
```

**`config-template.yml` addition** — add `record: false` inside the existing `radar:` block (alongside `enabled` and `port`):

```yaml
radar:
  enabled: true
  port: 7891
  record: false   # Set true to record SSE events to .specify/squad/radar-recording-{run_id}.jsonl for replay
```

---

### 3.6 Replay — `radar/scenarios/replay.py`

`load_replay(filepath: str) -> Scenario`:

1. If `filepath` does not exist, raise `FileNotFoundError` (caller — `mock_server.main()` — catches and exits with error message)
2. Read JSONL file line by line; skip and warn on malformed lines
3. Find the first `snapshot` event — extract `initial_run` from `payload["run"]` and `initial_agents` from `payload["agents"]`; if no snapshot event found, raise `ValueError`
4. Convert remaining events to `ScenarioEvent` list using this delay rule:
   - The snapshot event itself is not included in `event_sequence`
   - The **first** non-snapshot event always gets `delay_ms = 0`
   - All **subsequent** non-snapshot events get `delay_ms = max(0, recorded_at_ms[i] - recorded_at_ms[i-1])` where `i-1` is the previous non-snapshot event's index
5. Return `Scenario(name="replay", description=f"Replay of {Path(filepath).name}", loop=False, journal_entries={}, ...)`

```python
# TODO: speed multiplier — divide all delay_ms by factor when --speed N is added to mock_server
```

**Import location:** `load_replay` is imported directly in `mock_server.py`:

```python
from radar.scenarios.replay import load_replay
```

It is NOT imported in `radar/scenarios/__init__.py` — it does not register a scenario and must not be auto-executed at import time.

**Usage:**

```bash
python -m radar.mock_server --replay .specify/squad/radar-recording-squad-001-1742670000.jsonl
```

---

### 3.7 `radar/scenarios/__init__.py` — Registration

The three new scenario modules must be imported at the bottom of `__init__.py` to self-register, following the existing pattern:

```python
# existing — also update to aliased+noqa form for consistency
from radar.scenarios import default as _default  # noqa: F401
from radar.scenarios import all_blocked as _all_blocked  # noqa: F401

# new
from radar.scenarios import greenfield as _greenfield  # noqa: F401
from radar.scenarios import brownfield as _brownfield  # noqa: F401
from radar.scenarios import blocked_escalation as _blocked_escalation  # noqa: F401
```

The two existing import lines (`from . import default`, `from . import all_blocked`) must be updated to the aliased+noqa form shown above. This ensures a consistent import style across the file and avoids linter warnings on the existing lines.

`replay.py` is NOT imported here.

---

### 3.8 Interface Contract Doc — `docs/radar-protocol-contract.md`

Handover document for the UI session. Three sections:

1. **New/updated events to handle:**
   - `run_state_change` — full payload schema (Section 3.3.1), when it fires, what the UI must do: update `squad.run` in Zustand store; trigger `RunSummaryPanel` when `status` transitions to `"done"` or `"blocked"`
   - `snapshot` — `run` object now present at top level; normalizer must read `payload.run` directly instead of deriving `phase` from first agent and hardcoding `status`/`iteration`

2. **`/journal` endpoint** — full request/response schema (Section 3.3.3), entry type enum, sort order guarantee, empty-response conditions

3. **Known UI gaps** (non-blocking for mock work, required for full Warscape fidelity):
   - `run_state_change` handler is no-op in `App.tsx` → Geoscape active territory won't update until implemented
   - Snapshot normalizer hardcodes `status: "running"`, `iteration: 1` → `RunSummaryPanel` never fires
   - `run.phase` derived from first agent's phase → active territory may be wrong in multi-phase runs
   - Tile/territory click → detail panel wiring unimplemented (OQ-001)
   - Speed multiplier hook point: `_to_scenario_events()` comment in `replay.py`

---

## 4. Files to Create / Modify

| Action | Path | Notes |
|---|---|---|
| Modify | `radar/scenarios/__init__.py` | Add `initial_run` + `journal_entries` to `Scenario`; flip `loop` default; add imports for 3 new scenario modules (NOT replay.py) |
| Modify | `radar/scenarios/default.py` | Add `initial_run` and `journal_entries: {}`; migrate `display_name` to new convention |
| Modify | `radar/scenarios/all_blocked.py` | Add `initial_run` and `journal_entries: {}`; migrate `display_name` to new convention |
| Create | `radar/scenarios/greenfield.py` | |
| Create | `radar/scenarios/brownfield.py` | |
| Create | `radar/scenarios/blocked_escalation.py` | |
| Create | `radar/scenarios/replay.py` | `load_replay()` only; no scenario registration |
| Modify | `radar/mock_server.py` | `run_state_change` handling in `scenario_loop`, `run` in `mock_snapshot`, `/journal` endpoint, `--replay` flag |
| Modify | `radar/server.py` | `--record PATH` flag + `_record_lock` append logic |
| Modify | `commands/echelon.run.md` | `RADAR_RECORD_FLAG` block before `python3 -m radar.server` call |
| Modify | `config-template.yml` | Add `record: false` inside existing `radar:` block |
| Create | `docs/radar-protocol-contract.md` | UI handover interface contract |

---

## 5. What Is Not Changing

- `radar/emitter.py` — no changes
- `radar/requirements.txt` — no new dependencies
- Existing scenario behavior (`default`, `all-blocked`) — only `initial_run` and `journal_entries: {}` added; loop values and event sequences unchanged
- UI (`squad-monitor`) — no changes in this session; gaps documented in protocol contract for UI session
- `agents.yaml`, agent prompt files — not in scope
