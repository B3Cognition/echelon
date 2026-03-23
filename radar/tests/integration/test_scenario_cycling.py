import socket, json, threading
from pathlib import Path
from werkzeug.serving import make_server as ws_make_server

ALL_STATES = {"working", "thinking", "blocked", "complete", "error", "idle", "unknown"}

def test_all_7_states_seen_in_fast_scenario(squad_dir):
    """FR-006: all 7 states appear within one loop. Use fast delays (100ms)."""
    from radar.scenarios import Scenario, ScenarioEvent, MockAgent, get_scenario
    from radar.mock_server import create_app, broadcast_event
    import time

    # Build a fast test scenario
    base = get_scenario("default")
    fast_events = [
        ScenarioEvent(event_type=e.event_type, payload=e.payload, delay_ms=100)
        for e in base.event_sequence
    ]
    fast_scenario = Scenario(
        name="_test_fast",
        description="Fast test scenario",
        initial_agents=base.initial_agents,
        event_sequence=fast_events,
        initial_run=base.initial_run,
        loop=True,
    )

    # Register temporarily
    from radar.scenarios import register, _REGISTRY
    register(fast_scenario)
    try:
        app, stop_event = create_app(fast_scenario, squad_dir=squad_dir, heartbeat_interval=60)
        server = ws_make_server("127.0.0.1", 0, app)
        port = server.socket.getsockname()[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        # Collect events
        seen_states = set()
        s = socket.socket()
        s.settimeout(10)
        s.connect(("127.0.0.1", port))
        s.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\nConnection: close\r\n\r\n")
        raw = b""
        while b"\r\n\r\n" not in raw:
            raw += s.recv(4096)
        body = raw.split(b"\r\n\r\n", 1)[1].decode()
        for _ in range(50):  # read up to 50 frames
            chunk = s.recv(4096)
            if not chunk:
                break
            body += chunk.decode()
            while "\n\n" in body:
                frame, body = body.split("\n\n", 1)
                for line in frame.split("\n"):
                    if line.startswith("data: "):
                        try:
                            d = json.loads(line[6:])
                            if "state" in d:
                                seen_states.add(d["state"])
                        except Exception:
                            pass
            if seen_states >= ALL_STATES:
                break
        s.close()
    finally:
        stop_event.set()
        server.shutdown()
        t.join(timeout=3)
        _REGISTRY.pop("_test_fast", None)

    assert seen_states >= ALL_STATES, f"Missing states: {ALL_STATES - seen_states}"
