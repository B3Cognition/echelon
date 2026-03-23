import time
import socket, json

def read_sse_until_heartbeat(port, max_events=20, timeout=10):
    import io
    events = []
    s = socket.socket()
    s.settimeout(timeout)
    s.connect(("127.0.0.1", port))
    s.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\nConnection: close\r\n\r\n")
    raw = b""
    while b"\r\n\r\n" not in raw:
        raw += s.recv(4096)
    body = raw.split(b"\r\n\r\n", 1)[1].decode()
    for _ in range(max_events):
        chunk = s.recv(4096)
        if not chunk:
            break
        body += chunk.decode()
        while "\n\n" in body:
            frame, body = body.split("\n\n", 1)
            lines = frame.strip().split("\n")
            event_type = data_str = None
            for line in lines:
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    data_str = line[6:]
            if event_type:
                events.append(event_type)
            if "heartbeat" in events:
                s.close()
                return events
    s.close()
    return events

def test_heartbeat_received(squad_dir):
    """FR-015: heartbeat sent at configured interval. Use interval=1s for fast test."""
    from radar.mock_server import create_app
    from radar.scenarios import get_scenario
    import threading
    from werkzeug.serving import make_server as ws_make_server
    app, stop_event = create_app(get_scenario("default"), squad_dir=squad_dir, heartbeat_interval=1)
    server = ws_make_server("127.0.0.1", 0, app)
    port = server.socket.getsockname()[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        events = read_sse_until_heartbeat(port, max_events=30, timeout=8)
        assert "heartbeat" in events, f"No heartbeat in: {events}"
    finally:
        stop_event.set()
        server.shutdown()
        t.join(timeout=3)
