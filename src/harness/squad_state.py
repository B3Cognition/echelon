"""SquadStateStore — atomic reads/writes for squad/<run-id>/state.json."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from harness.blocked_decision import ensure_blocked_decision
from harness.echelon_result_schema import (
    EchelonResultValidationError,
    validate_echelon_result,
)

logger = logging.getLogger(__name__)

AUTONOMY_MODES = {"guided", "semi", "banzai"}
PROJECT_MODES = {"greenfield", "brownfield", "self_analysis"}
PHASE_A_IDENTITY_KEYS = frozenset(
    {
        "spec_id",
        "spec_number",
        "spec_dir",
        "published_spec_dir",
        "feature_branch",
        "phase_a_default_branch",
        "phase_a_base_commit",
        "specify_feature_directory",
    }
)

if TYPE_CHECKING:
    from harness.squad_provider import SquadAgentResult


VALID_SQUAD_TRANSITIONS: dict[str, set[str]] = {
    "running": {"blocked", "done"},
    "blocked": {"running"},
    "done": set(),
}


class SquadStateStore:
    def __init__(self, squad_dir: Path) -> None:
        self._squad_dir = squad_dir
        self._path = squad_dir / "state.json"
        self._staging_dir = squad_dir / "staging"
        self._squad_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    @property
    def squad_dir(self) -> Path:
        return self._squad_dir

    @property
    def staging_dir(self) -> Path:
        return self._staging_dir

    def load(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())

    def save(self, state: dict) -> None:
        if self._path.exists():
            old_text = self._path.read_text()
            bak = self._path.with_suffix(".json.bak")
            try:
                bak.write_text(old_text)
            except OSError:
                logger.warning("Could not write .bak file: %s", bak)
            try:
                self._check_monotonics(json.loads(old_text), state)
            except json.JSONDecodeError:
                pass

        ensure_blocked_decision(state)
        if state.get("status") == "blocked" and state.get("escalation_question"):
            state["escalation_resolved"] = False
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        content = json.dumps(state, indent=2)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._squad_dir),
            prefix=".state-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            Path(tmp).replace(self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def initialize(
        self,
        run_id: str,
        mode: str,
        user_message: str,
        token_budget: int,
        entry_phase: str,
        max_iterations: int = 5,
        autonomy_mode: str = "semi",
        implementation_targets: list[str] | None = None,
        product_inputs: dict[str, object] | None = None,
    ) -> None:
        if autonomy_mode == "semi" and mode in AUTONOMY_MODES and mode not in PROJECT_MODES:
            autonomy_mode = mode
            mode = "greenfield"
        logger.debug("squad init run_id=%s mode=%s entry_phase=%s", run_id, mode, entry_phase)
        ts = datetime.now(timezone.utc).isoformat()
        self.save({
            "run_id": run_id,
            "status": "running",
            "phase": entry_phase,
            "mode": mode,
            "autonomy_mode": autonomy_mode,
            "iteration": 0,
            "max_iterations": max_iterations,
            "token_usage": 0,
            "token_budget": token_budget,
            "cost_usd": 0.0,
            "user_message": user_message,
            "implementation_targets": list(implementation_targets or []),
            "product_inputs": dict(product_inputs or {}),
            "created_at": ts,
            "updated_at": ts,
            "last_dispatch": None,
            "cancel_requested": False,
            "convergence_detected": False,
            "quality_scores": [],
            "issues_log": [],
            "why_fail_count": 0,
            "phase_dispatch_counts": {},
            "completed_phases": [],
            "convergence_guard_fire_count": 0,
            "squad_dir": str(self._squad_dir),
            "staging_dir": str(self._staging_dir),
            "context_dir": str(self._squad_dir / "context"),
        })

    def _check_monotonics(self, old: dict, new: dict) -> None:
        old_tokens = old.get("token_usage", 0)
        new_tokens = new.get("token_usage", 0)
        if new_tokens < old_tokens:
            logger.warning(
                "token_usage decreased: %d → %d (run_id=%s)",
                old_tokens,
                new_tokens,
                new.get("run_id", "?"),
            )

    def _transition_status(self, state: dict, new_status: str) -> None:
        current = state.get("status", "running")
        allowed = VALID_SQUAD_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            logger.warning(
                "Invalid squad status transition %r → %r (run_id=%s)",
                current,
                new_status,
                state.get("run_id", "?"),
            )
        state["status"] = new_status

    def current_phase(self) -> str:
        return self.load().get("phase", "init")

    def advance(
        self,
        from_phase: str,
        to_phase: str,
        result: "SquadAgentResult",
        *,
        allowed_state_update_keys: Iterable[str] | None = None,
        manual_phase_run: bool = False,
    ) -> None:
        state = self.load()
        try:
            result.echelon_result = validate_echelon_result(
                result.echelon_result,
                allowed_state_update_keys=allowed_state_update_keys,
            )
        except EchelonResultValidationError as exc:
            logger.warning(
                "Invalid echelon_result blocked before state advance: %s "
                "(run_id=%s)",
                exc,
                state.get("run_id", "?"),
            )
            self._transition_status(state, "blocked")
            state["blocked_reason"] = f"echelon_result validation failed: {exc}"
            self.save(state)
            return
        logger.debug(
            "squad advance %s → %s verdict=%s run_id=%s",
            from_phase,
            to_phase,
            result.verdict,
            state.get("run_id", "?"),
        )
        state["phase"] = to_phase
        state["last_dispatch"] = {
            "phase_id": from_phase,
            "verdict": result.verdict,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if manual_phase_run:
            state["last_dispatch"]["manual_phase_run"] = True
            manual_runs = state.get("manual_phase_runs")
            if not isinstance(manual_runs, list):
                manual_runs = []
            manual_runs.append(
                {
                    "phase_id": from_phase,
                    "next_phase": to_phase,
                    "verdict": result.verdict,
                    "completed_at": state["last_dispatch"]["completed_at"],
                }
            )
            state["manual_phase_runs"] = manual_runs
        completed = state.get("completed_phases")
        if not isinstance(completed, list):
            completed = []
        if from_phase not in completed:
            completed.append(from_phase)
        state["completed_phases"] = completed
        identity_is_bootstrapped = bool(state.get("feature_branch"))
        for key, value in result.state_updates.items():
            if identity_is_bootstrapped and key in PHASE_A_IDENTITY_KEYS:
                if state.get(key) != value:
                    logger.warning(
                        "Ignoring agent attempt to change controller-owned Phase A identity "
                        "%s: %r -> %r (run_id=%s)",
                        key,
                        state.get(key),
                        value,
                        state.get("run_id", "?"),
                    )
                continue
            if key == "status":
                self._transition_status(state, value)
            else:
                state[key] = value
        self.save(state)

    def set_blocked(self, reason: str) -> None:
        state = self.load()
        logger.debug("squad blocked run_id=%s reason=%r", state.get("run_id", "?"), reason)
        self._transition_status(state, "blocked")
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

    def increment_why_fail_count(self) -> int:
        state = self.load()
        count = state.get("why_fail_count", 0) + 1
        state["why_fail_count"] = count
        self.save(state)
        return count

    def reset_why_fail_count(self) -> None:
        state = self.load()
        state["why_fail_count"] = 0
        self.save(state)

    def increment_phase_dispatch_count(self, phase: str) -> int:
        state = self.load()
        counts = state.get("phase_dispatch_counts") or {}
        counts[phase] = counts.get(phase, 0) + 1
        state["phase_dispatch_counts"] = counts
        self.save(state)
        return counts[phase]

    def get_phase_dispatch_count(self, phase: str) -> int:
        state = self.load()
        return (state.get("phase_dispatch_counts") or {}).get(phase, 0)

    def reset_phase_dispatch_count(self, phase: str) -> None:
        """Forget attempts that never reached the phase agent."""
        state = self.load()
        counts = state.get("phase_dispatch_counts") or {}
        if phase in counts:
            counts.pop(phase)
            state["phase_dispatch_counts"] = counts
            self.save(state)

    def increment_convergence_guard_fires(self) -> int:
        state = self.load()
        count = state.get("convergence_guard_fire_count", 0) + 1
        state["convergence_guard_fire_count"] = count
        self.save(state)
        return count

    def reset_convergence_guard_fires(self) -> None:
        state = self.load()
        state["convergence_guard_fire_count"] = 0
        self.save(state)

    def increment_cost(self, amount: float) -> None:
        if not amount:
            return
        state = self.load()
        state["cost_usd"] = round(state.get("cost_usd", 0.0) + amount, 6)
        self.save(state)

    def token_budget(self) -> int:
        return int(self.load().get("token_budget", 0))
