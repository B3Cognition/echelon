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
