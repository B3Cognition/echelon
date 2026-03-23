from __future__ import annotations
import json
import signal
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue, Empty
from typing import Callable, Optional
from flask import Flask, Response, request, jsonify
from flask_cors import CORS

DEFAULT_PORT = 7891
MAX_PORT_ATTEMPTS = 10
HEARTBEAT_INTERVAL = 15


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_sse_frame(event_type: str, data_dict: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data_dict)}\n\n"


def _real_try_bind(port: int) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("localhost", port))
        s.close()
        return True
    except OSError:
        return False


def find_available_port(
    start: int = DEFAULT_PORT,
    max_attempts: int = MAX_PORT_ATTEMPTS,
    try_bind: Optional[Callable] = None,
) -> int:
    if try_bind is None:
        try_bind = _real_try_bind
    for port in range(start, start + max_attempts):
        if try_bind(port):
            return port
    raise RuntimeError(
        f"No available port found in range {start}\u2013{start + max_attempts - 1}"
    )


def cleanup_port_file(port_file: Path, written_port: int) -> Optional[bool]:
    if not port_file.exists():
        return None
    try:
        content = port_file.read_text().strip()
    except Exception:
        return False
    if not content:
        return False
    try:
        file_port = int(content)
    except ValueError:
        return False
    if file_port == written_port:
        port_file.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------


def broadcast_event(event_type: str, data: dict, clients: dict, stop_event: threading.Event) -> None:
    if stop_event.is_set():
        return
    frame = build_sse_frame(event_type, data)
    dead = []
    for client_id, q in list(clients.items()):
        try:
            q.put_nowait(frame)
        except Exception:
            dead.append(client_id)
    for cid in dead:
        clients.pop(cid, None)


# ---------------------------------------------------------------------------
# Background thread functions
# ---------------------------------------------------------------------------


def scenario_loop(scenario, mock_snapshot: dict, clients: dict, stop_event: threading.Event, broadcast_fn) -> None:
    while not stop_event.is_set():
        for event in scenario.event_sequence:
            if stop_event.wait(timeout=event.delay_ms / 1000):
                return
            if stop_event.is_set():
                return
            # Update mock_snapshot based on event type
            if event.event_type == "run_state_change":
                run_payload = event.payload.get("run")
                if run_payload is not None:
                    mock_snapshot["run"] = run_payload
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


def heartbeat_loop(stop_event: threading.Event, clients: dict, broadcast_fn, interval: int) -> None:
    while not stop_event.is_set():
        if stop_event.wait(timeout=interval):
            return
        if not stop_event.is_set():
            broadcast_fn("heartbeat", {"ts": _now()}, clients, stop_event)


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------


def create_app(
    scenario,                           # Scenario object (resolved by caller)
    squad_dir: Optional[Path] = None,
    port: int = DEFAULT_PORT,
    heartbeat_interval: int = HEARTBEAT_INTERVAL,
) -> tuple:
    app = Flask(__name__)
    CORS(app)

    # Build initial mock_snapshot from scenario.initial_agents
    # Shape from contracts/sse-api.md: {run_id, agents: {dispatch_id: agent_dict}, dispatch_order: [...], updated_at}
    mock_snapshot = {
        "run_id": scenario.initial_run["run_id"],
        "run": dict(scenario.initial_run),
        "agents": {a.dispatch_id: a.to_dict() for a in scenario.initial_agents},
        "dispatch_order": [a.dispatch_id for a in scenario.initial_agents],
        # updated_at from scenario (not _now()) — preserves authored timeline
        "updated_at": scenario.initial_run["updated_at"],
    }

    clients: dict = {}
    stop_event = threading.Event()

    # Store clients in app config so main() can access them for shutdown
    app.config["clients"] = clients
    app.config["stop_event"] = stop_event

    # Start background threads
    s_thread = threading.Thread(
        target=scenario_loop,
        args=(scenario, mock_snapshot, clients, stop_event, broadcast_event),
        daemon=True,
    )
    h_thread = threading.Thread(
        target=heartbeat_loop,
        args=(stop_event, clients, broadcast_event, heartbeat_interval),
        daemon=True,
    )
    s_thread.start()
    h_thread.start()

    _start_time = time.time()

    @app.route("/events")
    def events():
        client_id = str(uuid.uuid4())
        q: Queue = Queue()
        clients[client_id] = q

        # Send initial snapshot immediately (FR-005)
        initial_frame = build_sse_frame("snapshot", mock_snapshot)

        def stream():
            try:
                yield initial_frame
                while not stop_event.is_set():
                    try:
                        frame = q.get(timeout=60)
                        if frame == "":  # shutdown sentinel
                            return
                        yield frame
                    except Empty:
                        # Send keepalive comment
                        yield ": keepalive\n\n"
            finally:
                clients.pop(client_id, None)

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/health")
    def health():
        return jsonify({
            "status": "ok",
            "port": port,
            "uptime_s": round(time.time() - _start_time, 1),
            "clients_connected": len(clients),
        })

    @app.route("/snapshot")
    def snapshot():
        return jsonify(mock_snapshot)

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

    return app, stop_event


# ---------------------------------------------------------------------------
# Module-level globals used by shutdown_handler (ADR-003 pattern)
# ---------------------------------------------------------------------------

_written_port: Optional[int] = None
_squad_dir: Optional[Path] = None
_stop_event: Optional[threading.Event] = None
_clients: Optional[dict] = None


# ---------------------------------------------------------------------------
# Signal handler
# ---------------------------------------------------------------------------


def shutdown_handler(signum, frame) -> None:
    if _stop_event is not None:
        _stop_event.set()
    if _clients is not None:
        for q in list(_clients.values()):
            try:
                q.put_nowait("")  # shutdown sentinel for SSE streams
            except Exception:
                pass
        _clients.clear()
    if _squad_dir is not None and _written_port is not None:
        cleanup_port_file(_squad_dir / "radar.port", _written_port)
    sys.exit(0)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


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


if __name__ == "__main__":
    main()
