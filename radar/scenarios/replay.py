"""
radar/scenarios/replay.py — Load a recorded JSONL session as a Scenario.

Usage (in mock_server.py main()):
    from radar.scenarios.replay import load_replay
    scenario = load_replay(args.replay)

NOT imported in radar/scenarios/__init__.py — does not register a scenario.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

from radar.scenarios import MockAgent, Scenario, ScenarioEvent


def load_replay(filepath: str) -> Scenario:
    """Read a JSONL recording file and return a one-shot Scenario for replay.

    Delay rule:
    - Snapshot event is excluded from event_sequence.
    - First non-snapshot event gets delay_ms = 0.
    - Each subsequent event: delay_ms = max(0, recorded_at_ms[i] - recorded_at_ms[i-1])
      where i-1 is the *previous non-snapshot event's* index.

    # TODO: speed multiplier — divide all delay_ms by factor when --speed N is added.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Recording file not found: {filepath}")

    records = []
    with open(path, "r") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[RADAR-REPLAY] Warning: skipping malformed line {lineno} in {filepath}",
                      file=sys.stderr)

    # Find snapshot event
    snapshot_record = None
    for record in records:
        if record.get("event_type") == "snapshot":
            snapshot_record = record
            break

    if snapshot_record is None:
        raise ValueError(f"No snapshot event found in recording file: {filepath}")

    payload = snapshot_record["payload"]
    initial_run = payload.get("run", {})
    agents_dict = payload.get("agents", {})
    dispatch_order = payload.get("dispatch_order", list(agents_dict.keys()))

    initial_agents = []
    for dispatch_id in dispatch_order:
        a = agents_dict.get(dispatch_id, {})
        initial_agents.append(MockAgent(
            dispatch_id=dispatch_id,
            codename=a.get("codename", dispatch_id),
            display_name=a.get("display_name", dispatch_id),
            state=a.get("state", "unknown"),
            phase=a.get("phase", ""),
            dispatched_at=a.get("dispatched_at", ""),
            completed_at=a.get("completed_at"),
            blocked_reason=a.get("blocked_reason"),
        ))

    # Build event_sequence — skip snapshot, compute delays
    non_snapshot = [r for r in records if r.get("event_type") != "snapshot"]
    event_sequence = []
    for i, record in enumerate(non_snapshot):
        if i == 0:
            delay_ms = 0
        else:
            curr_ts = record.get("recorded_at_ms", 0)
            prev_ts = non_snapshot[i - 1].get("recorded_at_ms", 0)
            delay_ms = max(0, curr_ts - prev_ts)
        event_sequence.append(ScenarioEvent(
            event_type=record["event_type"],
            payload=record["payload"],
            delay_ms=delay_ms,
        ))

    return Scenario(
        name="replay",
        description=f"Replay of {path.name}",
        initial_agents=initial_agents,
        event_sequence=event_sequence,
        initial_run=initial_run,
        journal_entries={},
        loop=False,
    )
