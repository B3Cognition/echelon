# RADAR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement RADAR - a Python SSE server that enables real-time monitoring of cognitive-squad agent execution via the squad-monitor UI.

**Architecture:** RADAR is a lightweight Flask server with watchdog file monitoring. It watches `agent-states.json` and `agent-states-events.jsonl`, streaming state changes to connected browsers via SSE. The MANAGER starts RADAR at run init and stops it at finalize. An emitter module writes agent state changes to the watched files.

**Tech Stack:** Python 3.11+, Flask, flask-cors, watchdog

**Spec Document:** `/Users/michalbachorik/work/overwatch/squad-monitor/docs/radar-implementation-spec.md`

---

## File Structure

**Development paths** (in this repo):
```
cognitive-squad/
  radar/
    __init__.py          ← Package marker
    server.py            ← Flask SSE server + watchdog file monitoring
    emitter.py           ← Writes agent-states.json + .jsonl files
    requirements.txt     ← Dependencies: flask, flask-cors, watchdog
    README.md            ← Quick-start documentation
  config-template.yml    ← Add radar: section
  commands/cognitive-squad.run.md  ← Add RADAR lifecycle + emitter calls
  commands/cognitive-squad.build.md ← Add RADAR lifecycle + emitter calls
```

**Installed paths** (when extension is installed in a project):
```
project/
  .specify/extensions/cognitive-squad/
    radar/
      __init__.py, server.py, emitter.py, requirements.txt, README.md
```

**Note:** When the MANAGER runs RADAR, it runs from the project root with:
```bash
PYTHONPATH=.specify/extensions/cognitive-squad python -m radar.server
```

---

## Task 1: Create radar package structure

**Files:**
- Create: `radar/__init__.py`
- Create: `radar/requirements.txt`

- [ ] **Step 1: Create radar directory**

```bash
mkdir -p radar
```

- [ ] **Step 2: Create __init__.py**

```python
"""RADAR - Real-time Agent Display And Relay.

A lightweight SSE server for monitoring cognitive-squad agent execution.
"""

__version__ = "1.0.0"
```

- [ ] **Step 3: Create requirements.txt**

```
flask>=3.0.0
flask-cors>=4.0.0
watchdog>=4.0.0
```

- [ ] **Step 4: Commit**

```bash
git add radar/__init__.py radar/requirements.txt
git commit -m "feat(radar): initialize radar package structure"
```

---

## Task 2: Implement emitter module

**Files:**
- Create: `radar/emitter.py`
- Test: Manual verification with Python REPL

- [ ] **Step 1: Create emitter.py with core functions**

```python
"""State emitter for cognitive-squad agent monitoring.

Writes agent state changes to files that RADAR watches and streams to the UI.
"""

import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SQUAD_DIR = Path(".specify/squad")
AGENT_STATES_PATH = SQUAD_DIR / "agent-states.json"
EVENTS_JSONL_PATH = SQUAD_DIR / "agent-states-events.jsonl"


def init_run(run_id: str) -> None:
    """Initialize files for a new run.

    Call once when a new run starts. Truncates both files so RADAR
    doesn't replay stale history.

    Args:
        run_id: Unique identifier for this run (e.g., "squad-1711036800")
    """
    SQUAD_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(AGENT_STATES_PATH, json.dumps({
        "run_id": run_id,
        "updated_at": _now(),
        "agents": {},
        "dispatch_order": [],
    }, indent=2))
    EVENTS_JSONL_PATH.write_text("")


def on_dispatched(run_id: str, dispatch_id: str, codename: str, phase: str) -> None:
    """Record agent dispatch.

    Call immediately before dispatching an agent (Agent tool call).

    Args:
        run_id: Current run ID
        dispatch_id: Unique agent instance ID (e.g., "SCOUT-1")
        codename: Agent type (e.g., "SCOUT")
        phase: Current squad phase (e.g., "discover")
    """
    _append_event(run_id, dispatch_id, codename, "working", phase, {})
    _patch_snapshot(run_id, dispatch_id, codename, "working", phase, {
        "dispatched_at": _now(),
        "completed_at": None,
        "artifacts_produced": [],
        "blocked_reason": None,
    })


def on_complete(
    run_id: str,
    dispatch_id: str,
    codename: str,
    phase: str,
    artifacts: Optional[list[str]] = None
) -> None:
    """Record successful agent completion.

    Call after reading a successful agent result.

    Args:
        run_id: Current run ID
        dispatch_id: Agent instance ID
        codename: Agent type
        phase: Squad phase when completed
        artifacts: List of artifact filenames produced (not full paths)
    """
    artifacts = artifacts or []
    _append_event(run_id, dispatch_id, codename, "complete", phase,
                  {"artifacts_produced": artifacts})
    _patch_snapshot(run_id, dispatch_id, codename, "complete", phase, {
        "completed_at": _now(),
        "artifacts_produced": artifacts,
        "blocked_reason": None,
    })


def on_error(run_id: str, dispatch_id: str, codename: str, phase: str) -> None:
    """Record agent failure.

    Call when an agent produces no output or fails.
    """
    _append_event(run_id, dispatch_id, codename, "error", phase, {})
    _patch_snapshot(run_id, dispatch_id, codename, "error", phase, {
        "completed_at": _now(),
    })


def on_blocked(
    run_id: str,
    dispatch_id: str,
    codename: str,
    phase: str,
    reason: str
) -> None:
    """Record agent blocked state.

    Call when an agent is blocked (human escalation).
    """
    _append_event(run_id, dispatch_id, codename, "blocked", phase,
                  {"blocked_reason": reason})
    _patch_snapshot(run_id, dispatch_id, codename, "blocked", phase, {
        "blocked_reason": reason,
    })


def on_resumed(run_id: str, dispatch_id: str, codename: str, phase: str) -> None:
    """Record agent resumption.

    Call when a blocked agent resumes (MANAGER resolves the escalation).
    """
    _append_event(run_id, dispatch_id, codename, "working", phase, {})
    _patch_snapshot(run_id, dispatch_id, codename, "working", phase, {
        "blocked_reason": None,
    })


# ── Internal helpers ─────────────────────────────────────────────────────────

def _append_event(
    run_id: str,
    dispatch_id: str,
    codename: str,
    state: str,
    phase: str,
    extras: dict
) -> None:
    """Append a single event line to the JSONL file."""
    event = {
        "id": dispatch_id,
        "codename": codename,
        "state": state,
        "ts": _now(),
        "phase": phase,
        "run_id": run_id,
        **extras,
    }
    with open(EVENTS_JSONL_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")


def _patch_snapshot(
    run_id: str,
    dispatch_id: str,
    codename: str,
    state: str,
    phase: str,
    patch: dict
) -> None:
    """Update the snapshot file with new agent state."""
    try:
        snapshot = json.loads(AGENT_STATES_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        snapshot = {"run_id": run_id, "agents": {}, "dispatch_order": []}

    existing = snapshot["agents"].get(dispatch_id, {
        "id": dispatch_id,
        "codename": codename,
        "state": "idle",
        "dispatched_at": None,
        "completed_at": None,
        "phase": phase,
        "run_id": run_id,
        "artifacts_produced": [],
        "blocked_reason": None,
    })

    snapshot["agents"][dispatch_id] = {**existing, "state": state, "phase": phase, **patch}
    snapshot["updated_at"] = _now()

    if dispatch_id not in snapshot["dispatch_order"]:
        snapshot["dispatch_order"].append(dispatch_id)

    _atomic_write(AGENT_STATES_PATH, json.dumps(snapshot, indent=2))


def _atomic_write(file_path: Path, content: str) -> None:
    """Write atomically via temp file + rename (POSIX atomic)."""
    tmp_path = Path(tempfile.gettempdir()) / f"radar-{secrets.token_hex(6)}.tmp"
    tmp_path.write_text(content)
    tmp_path.rename(file_path)


def _now() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
```

- [ ] **Step 2: Verify emitter works**

```bash
cd /Users/michalbachorik/work/cognitive-squad
python3 -c "
from radar.emitter import init_run, on_dispatched, on_complete
init_run('test-001')
on_dispatched('test-001', 'SCOUT-1', 'SCOUT', 'discover')
on_complete('test-001', 'SCOUT-1', 'SCOUT', 'discover', ['glossary.md'])
print(open('.specify/squad/agent-states.json').read())
"
```

Expected output (timestamps will vary):
```json
{
  "run_id": "test-001",
  "updated_at": "2026-03-21T...",
  "agents": {
    "SCOUT-1": {
      "id": "SCOUT-1",
      "codename": "SCOUT",
      "state": "complete",
      "dispatched_at": "2026-03-21T...",
      "completed_at": "2026-03-21T...",
      "phase": "discover",
      "run_id": "test-001",
      "artifacts_produced": ["glossary.md"],
      "blocked_reason": null
    }
  },
  "dispatch_order": ["SCOUT-1"]
}
```

- [ ] **Step 3: Clean up test files**

```bash
rm -rf .specify/squad/agent-states.json .specify/squad/agent-states-events.jsonl
```

- [ ] **Step 4: Commit**

```bash
git add radar/emitter.py
git commit -m "feat(radar): add emitter module for agent state file writing"
```

---

## Task 3: Implement SSE server

**Files:**
- Create: `radar/server.py`

- [ ] **Step 1: Create server.py with Flask + watchdog**

```python
"""RADAR SSE Server.

A lightweight Flask server that watches agent state files and streams
changes to connected browsers via Server-Sent Events (SSE).
"""

import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Generator

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


# ── Configuration ────────────────────────────────────────────────────────────

SQUAD_DIR = Path(".specify/squad")
AGENT_STATES_PATH = SQUAD_DIR / "agent-states.json"
EVENTS_JSONL_PATH = SQUAD_DIR / "agent-states-events.jsonl"
STATE_JSON_PATH = SQUAD_DIR / "state.json"

DEFAULT_PORT = 7891
MAX_PORT_ATTEMPTS = 10
HEARTBEAT_INTERVAL = 15  # seconds


# ── Application State ────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

# In-memory state
snapshot: dict = {"run_id": None, "agents": {}, "dispatch_order": [], "updated_at": None}
jsonl_offset: int = 0
clients: dict[str, Queue] = {}  # client_id -> event queue
start_time: float = time.time()
observer: Observer | None = None


# ── File Watching ────────────────────────────────────────────────────────────

class AgentStateHandler(FileSystemEventHandler):
    """Handle file changes for agent state files."""

    def on_modified(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)

        if path.name == "agent-states.json":
            self._handle_snapshot_change()
        elif path.name == "agent-states-events.jsonl":
            self._handle_events_change()
        elif path.name == "state.json":
            self._handle_run_state_change()

    def _handle_snapshot_change(self):
        global snapshot
        try:
            new_snapshot = json.loads(AGENT_STATES_PATH.read_text())
            old_agents = snapshot.get("agents", {})
            new_agents = new_snapshot.get("agents", {})

            # Detect changed agents
            for dispatch_id, agent in new_agents.items():
                if dispatch_id not in old_agents or agent != old_agents[dispatch_id]:
                    broadcast_event("agent_state_change", agent)

            snapshot = new_snapshot
            broadcast_event("snapshot", snapshot)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            broadcast_event("parse_error", {"error": str(e), "file": "agent-states.json"})

    def _handle_events_change(self):
        global jsonl_offset
        try:
            file_size = EVENTS_JSONL_PATH.stat().st_size

            # Handle truncation
            if file_size < jsonl_offset:
                jsonl_offset = 0

            # Read new lines
            with open(EVENTS_JSONL_PATH, "r") as f:
                f.seek(jsonl_offset)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            event = json.loads(line)
                            broadcast_event("agent_state_change", event)
                        except json.JSONDecodeError:
                            pass  # Incomplete line, wait for more
                jsonl_offset = f.tell()
        except FileNotFoundError:
            pass

    def _handle_run_state_change(self):
        try:
            run_state = json.loads(STATE_JSON_PATH.read_text())
            broadcast_event("run_state_change", run_state)
        except (FileNotFoundError, json.JSONDecodeError):
            pass


def broadcast_event(event_type: str, data: dict) -> None:
    """Send event to all connected clients."""
    event_str = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    dead_clients = []

    for client_id, queue in clients.items():
        try:
            queue.put_nowait(event_str)
        except Exception:
            dead_clients.append(client_id)

    for client_id in dead_clients:
        clients.pop(client_id, None)


def heartbeat_loop():
    """Send periodic heartbeats to all clients."""
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        broadcast_event("heartbeat", {"ts": _now()})


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/events")
def events() -> Response:
    """SSE endpoint - streams events to connected clients."""
    client_id = f"{time.time()}-{os.urandom(4).hex()}"
    queue: Queue = Queue()
    clients[client_id] = queue

    def generate() -> Generator[str, None, None]:
        # Send initial snapshot
        yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"

        try:
            while True:
                event = queue.get(timeout=60)
                yield event
        except Exception:
            pass
        finally:
            clients.pop(client_id, None)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.route("/snapshot")
def get_snapshot():
    """Return current in-memory snapshot."""
    return jsonify(snapshot)


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "port": app.config.get("PORT", DEFAULT_PORT),
        "uptime_s": round(time.time() - start_time, 2),
        "clients_connected": len(clients),
    })


@app.route("/journal")
def journal():
    """Return reasoning journal entries (placeholder)."""
    run_id = request.args.get("run_id")
    # TODO: Read from reasoning-journal.json when implemented
    return jsonify({"entries": [], "run_id": run_id})


# ── Startup ──────────────────────────────────────────────────────────────────

def find_available_port(start_port: int) -> int:
    """Find an available port, starting from start_port."""
    for offset in range(MAX_PORT_ATTEMPTS):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))
                return port
        except OSError:
            if offset > 0:
                print(f"[RADAR] port {port - 1} in use — trying {port}", file=sys.stderr)

    print(f"[RADAR] ERROR: Could not find available port after {MAX_PORT_ATTEMPTS} attempts", file=sys.stderr)
    sys.exit(1)


def load_initial_state():
    """Load existing state files on startup."""
    global snapshot, jsonl_offset

    SQUAD_DIR.mkdir(parents=True, exist_ok=True)

    if AGENT_STATES_PATH.exists():
        try:
            snapshot = json.loads(AGENT_STATES_PATH.read_text())
        except json.JSONDecodeError:
            pass

    if EVENTS_JSONL_PATH.exists():
        jsonl_offset = EVENTS_JSONL_PATH.stat().st_size


def setup_file_watcher() -> Observer:
    """Set up watchdog observer for state files."""
    SQUAD_DIR.mkdir(parents=True, exist_ok=True)

    handler = AgentStateHandler()
    obs = Observer()
    obs.schedule(handler, str(SQUAD_DIR), recursive=False)
    obs.start()
    return obs


def shutdown_handler(signum, frame):
    """Handle graceful shutdown."""
    global observer
    print("\n[RADAR] Shutting down...", file=sys.stderr)

    if observer:
        observer.stop()
        observer.join(timeout=2)

    # Clear all client queues
    for queue in clients.values():
        try:
            queue.put_nowait("")
        except Exception:
            pass
    clients.clear()

    sys.exit(0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main():
    global observer

    # Parse port from args or env
    port = DEFAULT_PORT
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
            break
    port = int(os.environ.get("PORT", port))

    # Find available port
    actual_port = find_available_port(port)
    app.config["PORT"] = actual_port

    # Write port file
    SQUAD_DIR.mkdir(parents=True, exist_ok=True)
    (SQUAD_DIR / "radar.port").write_text(str(actual_port) + "\n")

    # Load initial state
    load_initial_state()

    # Set up file watcher
    observer = setup_file_watcher()

    # Set up signal handlers
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Start heartbeat thread
    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    # Log startup
    print(f"[RADAR] listening on port {actual_port} — project: {os.getcwd()}", file=sys.stderr)

    # Run server
    app.run(host="localhost", port=actual_port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify server starts**

```bash
cd /Users/michalbachorik/work/cognitive-squad
timeout 3 python3 -m radar.server --port 7891 2>&1 || true
```

Expected: "[RADAR] listening on port 7891" followed by timeout.

- [ ] **Step 3: Commit**

```bash
git add radar/server.py
git commit -m "feat(radar): add Flask SSE server with watchdog file monitoring"
```

---

## Task 4: Add README documentation

**Files:**
- Create: `radar/README.md`

- [ ] **Step 1: Create README.md**

```markdown
# RADAR - Real-time Agent Display And Relay

RADAR is a lightweight SSE server that enables real-time monitoring of cognitive-squad agent execution via the squad-monitor UI.

## Quick Start

RADAR starts automatically when you run a squad. To start manually:

```bash
# Install dependencies (one time)
pip install -r radar/requirements.txt

# Start RADAR
python -m radar.server --port 7891
```

Then open the squad-monitor UI and connect to `localhost:7891`.

## How It Works

1. **MANAGER starts RADAR** at the beginning of a squad run
2. **Emitter writes state files** as agents are dispatched and complete
3. **RADAR watches files** via watchdog and streams changes via SSE
4. **UI displays live state** in fleet view and timeline

## Files

| File | Purpose |
|------|---------|
| `server.py` | Flask SSE server + watchdog monitoring |
| `emitter.py` | Writes agent state changes to files |
| `requirements.txt` | Python dependencies |

## State Files (created at runtime)

| File | Purpose |
|------|---------|
| `.specify/squad/agent-states.json` | Full snapshot (overwritten on each change) |
| `.specify/squad/agent-states-events.jsonl` | Append-only event log |
| `.specify/squad/radar.port` | Actual port RADAR is listening on |
| `.specify/squad/radar.pid` | RADAR process PID |
| `.specify/squad/radar.log` | RADAR stdout/stderr |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/events` | SSE stream of agent state changes |
| GET | `/snapshot` | Current in-memory state |
| GET | `/health` | Health check with uptime and client count |
| GET | `/journal` | Reasoning journal entries (placeholder) |

## Configuration

In `squad-config.yml`:

```yaml
radar:
  enabled: true    # Set false to disable
  port: 7891       # Default port
```
```

- [ ] **Step 2: Commit**

```bash
git add radar/README.md
git commit -m "docs(radar): add README with usage instructions"
```

---

## Task 5: Add radar config section

**Files:**
- Modify: `config-template.yml` (add after execution section, around line 50)

- [ ] **Step 1: Add radar section to config-template.yml**

Add after the `execution:` section (around line 50):

```yaml
# =============================================================================
# RADAR — Real-time monitoring server
# =============================================================================

radar:
  # Enable/disable RADAR monitoring server
  # [default: true] Set false to disable automatic RADAR startup
  enabled: true

  # Port for RADAR SSE server
  # [range: 1024-65535] [default: 7891]
  # If port is in use, RADAR auto-increments until it finds an available port
  port: 7891

  # Host binding
  # [default: localhost] Set to 0.0.0.0 to expose on LAN
  # host: localhost
```

- [ ] **Step 2: Commit**

```bash
git add config-template.yml
git commit -m "feat(config): add radar configuration section"
```

---

## Task 6: Integrate RADAR into cognitive-squad.run.md - Init

**Files:**
- Modify: `commands/cognitive-squad.run.md` (section 1.3, after state.json creation)

- [ ] **Step 1: Add RADAR startup after state.json creation**

After section 1.3 "Initialize State" (around line 205), add a new section 1.3.1:

```markdown
### 1.3.1 Start RADAR (if enabled)

Read `radar.enabled` from squad-config.yml (default: true). If enabled:

```bash
# Extension path (where RADAR lives when installed)
RADAR_EXT=".specify/extensions/cognitive-squad"

# Install RADAR dependencies if needed
pip install -q -r ${RADAR_EXT}/radar/requirements.txt 2>/dev/null || true

# Read port from config (default 7891)
RADAR_PORT=$(grep -A2 "^radar:" squad-config.yml 2>/dev/null | grep "port:" | awk '{print $2}' || echo 7891)

# Start RADAR in background (PYTHONPATH allows python -m radar.server to work)
PYTHONPATH=${RADAR_EXT} python -m radar.server --port ${RADAR_PORT:-7891} \
  >> .specify/squad/radar.log 2>&1 &
echo $! > .specify/squad/radar.pid

# Initialize emitter (creates/truncates agent-states files)
PYTHONPATH=${RADAR_EXT} python -c "from radar.emitter import init_run; init_run('${run_id}')"
```

**Note:** If RADAR fails to start, log a warning but continue the run. The squad executes without live monitoring.
```

- [ ] **Step 2: Commit**

```bash
git add commands/cognitive-squad.run.md
git commit -m "feat(squad.run): add RADAR startup in INIT phase"
```

---

## Task 7: Integrate RADAR into cognitive-squad.run.md - Finalize

**Files:**
- Modify: `commands/cognitive-squad.run.md` (section 12.8, after setting final state)

- [ ] **Step 1: Add RADAR shutdown in FINALIZE**

After section 12.8 "Set Final State" (around line 1125), add section 12.8.1:

```markdown
### 12.8.1 Stop RADAR

```bash
# Stop RADAR if running
if [ -f .specify/squad/radar.pid ]; then
  kill $(cat .specify/squad/radar.pid) 2>/dev/null || true
  rm -f .specify/squad/radar.pid
fi
```
```

- [ ] **Step 2: Add RADAR shutdown helper function for all exit paths**

At the top of cognitive-squad.run.md (in a preamble or helper section if one exists), add:

```markdown
### Helper: Stop RADAR

Use this command at any exit point (kill verdict, error, completion):

```bash
[ -f .specify/squad/radar.pid ] && kill $(cat .specify/squad/radar.pid) 2>/dev/null; rm -f .specify/squad/radar.pid
```
```

- [ ] **Step 3: Commit**

```bash
git add commands/cognitive-squad.run.md
git commit -m "feat(squad.run): add RADAR shutdown in FINALIZE phase"
```

---

## Task 8: Add emitter calls for agent dispatches

**Files:**
- Modify: `commands/cognitive-squad.run.md` (various agent dispatch sections)

- [ ] **Step 1: Document emitter pattern**

Add to cognitive-squad.run.md preamble (before section 1):

```markdown
### RADAR Emitter Pattern

For every agent dispatch, wrap the Agent tool call with emitter calls.

**Setup (at start of run):**
```bash
RADAR_EXT=".specify/extensions/cognitive-squad"
```

**Before dispatching:**
```bash
PYTHONPATH=${RADAR_EXT} python -c "from radar.emitter import on_dispatched; on_dispatched('${run_id}', '${DISPATCH_ID}', '${CODENAME}', '${phase}')"
```

**After successful completion:**
```bash
PYTHONPATH=${RADAR_EXT} python -c "from radar.emitter import on_complete; on_complete('${run_id}', '${DISPATCH_ID}', '${CODENAME}', '${phase}', ${ARTIFACTS_LIST})"
```

**After error/failure:**
```bash
PYTHONPATH=${RADAR_EXT} python -c "from radar.emitter import on_error; on_error('${run_id}', '${DISPATCH_ID}', '${CODENAME}', '${phase}')"
```

**Dispatch ID format:** `CODENAME-N` (e.g., SCOUT-1, SAGE-2). Track counter per codename in state.json under `dispatch_counters`.
```

- [ ] **Step 2: Add dispatch_counters to state.json schema**

In section 1.3 "Initialize State", add to the state.json template:

```json
{
  "dispatch_counters": {}
}
```

- [ ] **Step 3: Commit**

```bash
git add commands/cognitive-squad.run.md
git commit -m "feat(squad.run): add RADAR emitter pattern documentation"
```

---

## Task 9: Integrate RADAR into cognitive-squad.build.md

**Files:**
- Modify: `commands/cognitive-squad.build.md`

The same RADAR lifecycle applies to build runs. Add identical sections.

- [ ] **Step 1: Find INIT section in cognitive-squad.build.md**

```bash
grep -n "Initialize State\|state\.json" commands/cognitive-squad.build.md | head -5
```

- [ ] **Step 2: Add RADAR startup after state.json creation**

Add the same section 1.3.1 content as in cognitive-squad.run.md (see Task 6).

- [ ] **Step 3: Find FINALIZE section in cognitive-squad.build.md**

```bash
grep -n "FINALIZE\|Final State\|status.*done" commands/cognitive-squad.build.md | head -5
```

- [ ] **Step 4: Add RADAR shutdown in FINALIZE**

Add the same shutdown block as in cognitive-squad.run.md (see Task 7).

- [ ] **Step 5: Add emitter pattern reference**

Reference the RADAR Emitter Pattern (can link to cognitive-squad.run.md or duplicate).

- [ ] **Step 6: Commit**

```bash
git add commands/cognitive-squad.build.md
git commit -m "feat(squad.build): add RADAR lifecycle integration"
```

---

## Task 10: Final verification

- [ ] **Step 1: Verify all files exist**

```bash
cd /Users/michalbachorik/work/cognitive-squad
ls -la radar/
cat radar/requirements.txt
```

Expected output:
```
__init__.py
emitter.py
README.md
requirements.txt
server.py
```

- [ ] **Step 2: Test full RADAR flow (development mode)**

```bash
cd /Users/michalbachorik/work/cognitive-squad

# Install deps
pip install -q -r radar/requirements.txt

# Start RADAR in background (dev mode - radar is in current dir)
python -m radar.server --port 7891 &
RADAR_PID=$!
sleep 2

# Test health endpoint
curl -s http://localhost:7891/health | python -m json.tool
```

Expected health output:
```json
{
    "status": "ok",
    "port": 7891,
    "uptime_s": 2.0,
    "clients_connected": 0
}
```

- [ ] **Step 3: Test emitter writes**

```bash
# Test emitter writes
python -c "
from radar.emitter import init_run, on_dispatched, on_complete
init_run('test-verify')
on_dispatched('test-verify', 'SCOUT-1', 'SCOUT', 'discover')
on_complete('test-verify', 'SCOUT-1', 'SCOUT', 'discover', ['test.md'])
"

# Check agent-states.json
cat .specify/squad/agent-states.json
```

Expected agent-states.json structure:
```json
{
  "run_id": "test-verify",
  "updated_at": "...",
  "agents": {
    "SCOUT-1": {
      "id": "SCOUT-1",
      "codename": "SCOUT",
      "state": "complete",
      "dispatched_at": "...",
      "completed_at": "...",
      "phase": "discover",
      "run_id": "test-verify",
      "artifacts_produced": ["test.md"],
      "blocked_reason": null
    }
  },
  "dispatch_order": ["SCOUT-1"]
}
```

- [ ] **Step 4: Cleanup test artifacts**

```bash
kill $RADAR_PID 2>/dev/null
rm -rf .specify/squad/agent-states.json .specify/squad/agent-states-events.jsonl .specify/squad/radar.port
```

- [ ] **Step 5: Review all commits**

```bash
git status
git log --oneline -10
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Package structure | `radar/__init__.py`, `radar/requirements.txt` |
| 2 | Emitter module | `radar/emitter.py` |
| 3 | SSE server | `radar/server.py` |
| 4 | Documentation | `radar/README.md` |
| 5 | Config section | `config-template.yml` |
| 6 | INIT integration | `commands/cognitive-squad.run.md` |
| 7 | FINALIZE integration | `commands/cognitive-squad.run.md` |
| 8 | Emitter pattern | `commands/cognitive-squad.run.md` |
| 9 | Build integration | `commands/cognitive-squad.build.md` |
| 10 | Final verification | Manual testing |
