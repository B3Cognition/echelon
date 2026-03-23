import pytest
import threading
import time
import subprocess
from pathlib import Path
from werkzeug.serving import make_server

@pytest.fixture
def squad_dir(tmp_path):
    """Isolated squad directory for tests — never touches real .specify/squad/."""
    d = tmp_path / "squad"
    d.mkdir()
    return d

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
    time.sleep(0.05)  # brief wait for daemon threads to notice stop_event

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

@pytest.fixture
def running_process(squad_dir, tmp_path):
    """Runs mock_server as a subprocess. Yields (process, port)."""
    import sys, time, os, random
    radar_ext = str((Path(__file__).parent.parent.parent).resolve())
    env = os.environ.copy()
    env["PYTHONPATH"] = radar_ext
    env["RADAR_SQUAD_DIR"] = str(squad_dir)
    # Use a random high port range to avoid collisions with live_server fixture
    start_port = random.randint(19000, 29000)
    proc = subprocess.Popen(
        [sys.executable, "-m", "radar.mock_server", "--scenario", "default", "--port", str(start_port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for radar.port to appear
    port_file = squad_dir / "radar.port"
    for _ in range(30):
        if port_file.exists():
            break
        time.sleep(0.1)
    port = int(port_file.read_text().strip()) if port_file.exists() else None
    yield proc, port
    proc.terminate()
    proc.wait(timeout=5)
