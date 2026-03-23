import socket, json, threading
from werkzeug.serving import make_server as ws_make_server

def connect_and_read_first_event(host, port, result_list, index):
    """Thread target: connect to /events and store first event type."""
    try:
        s = socket.socket()
        s.settimeout(5)
        s.connect((host, port))
        s.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\nConnection: close\r\n\r\n")
        raw = b""
        while b"\r\n\r\n" not in raw:
            raw += s.recv(4096)
        body = raw.split(b"\r\n\r\n", 1)[1].decode()
        # Check if initial snapshot already arrived with the headers
        for _ in range(10):
            if "\n\n" in body:
                frame, _ = body.split("\n\n", 1)
                for line in frame.split("\n"):
                    if line.startswith("event: "):
                        result_list[index] = line[7:]
                        s.close()
                        return
            chunk = s.recv(4096)
            if not chunk:
                break
            body += chunk.decode()
        s.close()
    except Exception as e:
        result_list[index] = f"ERROR: {e}"

def test_two_clients_both_get_snapshot(squad_dir):
    """FR-018: 2 simultaneous clients each receive snapshot as first event."""
    from radar.mock_server import create_app
    from radar.scenarios import get_scenario
    app, stop_event = create_app(get_scenario("default"), squad_dir=squad_dir, heartbeat_interval=60)
    server = ws_make_server("127.0.0.1", 0, app, threaded=True)
    port = server.socket.getsockname()[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        results = [None, None]
        t1 = threading.Thread(target=connect_and_read_first_event, args=("127.0.0.1", port, results, 0))
        t2 = threading.Thread(target=connect_and_read_first_event, args=("127.0.0.1", port, results, 1))
        t1.start()
        t2.start()
        t1.join(timeout=6)
        t2.join(timeout=6)
        assert results[0] == "snapshot", f"Client 0 first event: {results[0]}"
        assert results[1] == "snapshot", f"Client 1 first event: {results[1]}"
    finally:
        stop_event.set()
        server.shutdown()
        t.join(timeout=3)
