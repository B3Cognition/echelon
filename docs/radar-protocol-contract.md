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
