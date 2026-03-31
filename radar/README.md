# RADAR - Real-time Agent Display And Relay

RADAR is a lightweight SSE server that enables real-time monitoring of echelon agent execution via the squad-monitor UI.

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
