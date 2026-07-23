"""SquadStateStore — atomic reads/writes for squad/<run-id>/state.json."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness.blocked_decision import ensure_blocked_decision
from harness.echelon_result_schema import (
    EchelonResultValidationError,
    validate_echelon_result,
)
from harness.prepared_phase_result import PreparedPhaseResult

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

VALID_SQUAD_TRANSITIONS: dict[str, set[str]] = {
    "running": {"blocked", "done"},
    "blocked": {"running"},
    "done": set(),
}


class StateAdvanceError(RuntimeError):
    """Raised when a prepared phase result cannot be committed safely."""

    def __init__(
        self,
        message: str,
        *,
        json_path: str = "$.prepared_result",
        validator: str = "state_advance",
    ) -> None:
        super().__init__(message)
        self.json_path = json_path
        self.validator = validator


@dataclass(frozen=True)
class AdvanceReceipt:
    from_phase: str
    to_phase: str
    completed_at: str
    controller_contract: str | None
    controller_contract_sha256: str | None


def _prepared_result_error(
    message: str,
    *,
    json_path: str = "$.prepared_result",
    validator: str = "ownership",
) -> StateAdvanceError:
    return StateAdvanceError(
        message,
        json_path=json_path,
        validator=validator,
    )


def _validate_prepared_result(prepared: PreparedPhaseResult) -> dict:
    """Validate the immutable payload and its ownership receipt together."""
    if type(prepared) is not PreparedPhaseResult:
        raise _prepared_result_error(
            "advance requires a PreparedPhaseResult",
            validator="prepared_result",
        )

    provider_keys = prepared.provider_update_keys
    controller_keys = prepared.controller_update_keys
    if type(provider_keys) is not frozenset or type(controller_keys) is not frozenset:
        raise _prepared_result_error("prepared ownership keys must be frozen sets")
    if any(not isinstance(key, str) for key in provider_keys | controller_keys):
        raise _prepared_result_error(
            "prepared ownership keys must be strings",
            json_path="$.prepared_result.ownership",
        )
    overlap = provider_keys & controller_keys
    if overlap:
        key = sorted(overlap)[0]
        raise _prepared_result_error(
            f"prepared ownership overlaps at key {key!r}",
            json_path=f"$.state_updates.{key}",
        )

    contract_name = prepared.controller_contract_name
    contract_sha256 = prepared.controller_contract_sha256
    if (contract_name is None) != (contract_sha256 is None):
        raise _prepared_result_error(
            "prepared controller contract receipt is incomplete",
            json_path="$.prepared_result.controller_contract",
            validator="receipt",
        )
    if contract_name is None:
        if controller_keys:
            raise _prepared_result_error(
                "controller-owned updates require a controller contract receipt",
                json_path="$.prepared_result.controller_update_keys",
            )
        if prepared.normalized_paths:
            raise _prepared_result_error(
                "normalized controller paths require a controller contract receipt",
                json_path="$.prepared_result.normalized_paths",
                validator="receipt",
            )
    else:
        if not isinstance(contract_name, str) or not contract_name.strip():
            raise _prepared_result_error(
                "prepared controller contract name is invalid",
                json_path="$.prepared_result.controller_contract_name",
                validator="receipt",
            )
        if (
            not isinstance(contract_sha256, str)
            or len(contract_sha256) != 64
            or any(character not in "0123456789abcdef" for character in contract_sha256)
        ):
            raise _prepared_result_error(
                "prepared controller contract digest is invalid",
                json_path="$.prepared_result.controller_contract_sha256",
                validator="receipt",
            )

    normalized_paths = prepared.normalized_paths
    if (
        type(normalized_paths) is not tuple
        or any(
            not isinstance(path, str)
            or not path.startswith("$.state_updates")
            for path in normalized_paths
        )
        or normalized_paths != tuple(sorted(set(normalized_paths)))
    ):
        raise _prepared_result_error(
            "prepared normalized path receipt is invalid",
            json_path="$.prepared_result.normalized_paths",
            validator="receipt",
        )
    if normalized_paths and not controller_keys:
        raise _prepared_result_error(
            "normalized paths require controller-owned updates",
            json_path="$.prepared_result.normalized_paths",
            validator="receipt",
        )
    routing_override = prepared.routing_override
    if routing_override is not None and (
        not isinstance(routing_override, str) or not routing_override.strip()
    ):
        raise _prepared_result_error(
            "prepared routing override is invalid",
            json_path="$.prepared_result.routing_override",
            validator="receipt",
        )

    try:
        result = validate_echelon_result(
            prepared.echelon_result,
            allowed_state_update_keys=provider_keys | controller_keys,
        )
    except EchelonResultValidationError as exc:
        raise _prepared_result_error(
            "prepared echelon_result validation failed",
            json_path="$.echelon_result",
            validator="echelon_result",
        ) from exc

    result_keys = frozenset(result["state_updates"])
    owned_keys = provider_keys | controller_keys
    if result_keys != owned_keys:
        raise _prepared_result_error(
            "prepared state update ownership does not match payload",
            json_path="$.prepared_result.ownership",
        )
    if prepared.state_updates != result["state_updates"]:
        raise _prepared_result_error(
            "prepared state update receipt does not match payload",
            json_path="$.prepared_result.state_updates",
            validator="receipt",
        )
    if prepared.verdict != result["verdict"]:
        raise _prepared_result_error(
            "prepared verdict receipt does not match payload",
            json_path="$.prepared_result.verdict",
            validator="receipt",
        )
    return result


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
        prepared: PreparedPhaseResult,
        *,
        increment_iteration: bool = False,
        manual_phase_run: bool = False,
    ) -> AdvanceReceipt:
        state = self.load()
        next_state = deepcopy(state)
        try:
            result = _validate_prepared_result(prepared)
        except StateAdvanceError:
            raise
        except Exception as exc:
            raise StateAdvanceError(
                "prepared result validation failed",
                validator="prepared_result",
            ) from exc

        logger.debug(
            "squad advance %s → %s verdict=%s run_id=%s",
            from_phase,
            to_phase,
            prepared.verdict,
            state.get("run_id", "?"),
        )
        completed_at = datetime.now(timezone.utc).isoformat()
        next_state["phase"] = to_phase
        next_state["last_dispatch"] = {
            "phase_id": from_phase,
            "verdict": prepared.verdict,
            "completed_at": completed_at,
            "controller_contract": prepared.controller_contract_name,
            "controller_contract_sha256": prepared.controller_contract_sha256,
            "controller_normalized": bool(prepared.normalized_paths),
        }
        if manual_phase_run:
            next_state["last_dispatch"]["manual_phase_run"] = True
            manual_runs = next_state.get("manual_phase_runs")
            if not isinstance(manual_runs, list):
                manual_runs = []
            else:
                manual_runs = list(manual_runs)
            manual_runs.append(
                {
                    "phase_id": from_phase,
                    "next_phase": to_phase,
                    "verdict": prepared.verdict,
                    "completed_at": completed_at,
                }
            )
            next_state["manual_phase_runs"] = manual_runs
        completed = next_state.get("completed_phases")
        if not isinstance(completed, list):
            completed = []
        else:
            completed = list(completed)
        if from_phase not in completed:
            completed.append(from_phase)
        next_state["completed_phases"] = completed
        identity_is_bootstrapped = bool(next_state.get("feature_branch"))
        try:
            for key, value in result["state_updates"].items():
                if identity_is_bootstrapped and key in PHASE_A_IDENTITY_KEYS:
                    if next_state.get(key) != value:
                        logger.warning(
                            "Ignoring agent attempt to change controller-owned "
                            "Phase A identity %s: %r -> %r (run_id=%s)",
                            key,
                            next_state.get(key),
                            value,
                            next_state.get("run_id", "?"),
                        )
                    continue
                if key == "status":
                    self._transition_status(next_state, value)
                else:
                    next_state[key] = value
        except Exception as exc:
            raise StateAdvanceError(
                "prepared state updates could not be applied",
                json_path="$.state_updates",
                validator="state_advance",
            ) from exc
        if increment_iteration and "iteration" not in result["state_updates"]:
            try:
                next_state["iteration"] = int(
                    next_state.get("iteration") or 0
                ) + 1
            except (TypeError, ValueError) as exc:
                raise StateAdvanceError(
                    "workflow iteration is not an integer",
                    json_path="$.iteration",
                    validator="type",
                ) from exc
        next_state.pop("controller_contract_error", None)

        try:
            self.save(next_state)
        except Exception as exc:
            raise StateAdvanceError(
                "atomic state save failed",
                json_path="$.state",
                validator="save",
            ) from exc
        return AdvanceReceipt(
            from_phase=from_phase,
            to_phase=to_phase,
            completed_at=completed_at,
            controller_contract=prepared.controller_contract_name,
            controller_contract_sha256=prepared.controller_contract_sha256,
        )

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
