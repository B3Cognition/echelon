"""SquadStateStore — atomic reads/writes for .specify/squad/state.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from harness.squad_provider import SquadAgentResult


class SquadStateStore:
    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())

    def save(self, state: dict) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(self._path)

    def initialize(
        self,
        run_id: str,
        mode: str,
        user_message: str,
        token_budget: int,
        entry_phase: str,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        self.save({
            "run_id": run_id,
            "status": "running",
            "phase": entry_phase,
            "mode": mode,
            "iteration": 0,
            "token_usage": 0,
            "token_budget": token_budget,
            "user_message": user_message,
            "created_at": ts,
            "updated_at": ts,
            "last_dispatch": None,
            "cancel_requested": False,
            "convergence_detected": False,
            "quality_scores": [],
            "issues_log": [],
        })

    def current_phase(self) -> str:
        return self.load().get("phase", "init")

    def advance(
        self, from_phase: str, to_phase: str, result: "SquadAgentResult"
    ) -> None:
        state = self.load()
        state["phase"] = to_phase
        state["last_dispatch"] = {
            "phase_id": from_phase,
            "verdict": result.verdict,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        for key, value in result.state_updates.items():
            state[key] = value
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save(state)

    def set_blocked(self, reason: str) -> None:
        state = self.load()
        state["status"] = "blocked"
        state["blocked_reason"] = reason
        self.save(state)

    def set_cancel_requested(self) -> None:
        state = self.load()
        state["cancel_requested"] = True
        self.save(state)

    def is_cancel_requested(self) -> bool:
        return bool(self.load().get("cancel_requested", False))

    def token_usage(self) -> int:
        return int(self.load().get("token_usage", 0))

    def increment_token_usage(self, tokens: int) -> None:
        state = self.load()
        state["token_usage"] = state.get("token_usage", 0) + tokens
        self.save(state)

    def token_budget(self) -> int:
        return int(self.load().get("token_budget", 0))
