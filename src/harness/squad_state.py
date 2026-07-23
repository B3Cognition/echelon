"""SquadStateStore — atomic reads/writes for squad/<run-id>/state.json."""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import secrets
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from harness.blocked_decision import ensure_blocked_decision
from harness.echelon_result_schema import (
    EchelonResultValidationError,
    validate_echelon_result,
)
from harness.prepared_phase_result import (
    PreparedPhaseResult,
    PreparedPhaseResultAttestationError,
    PreparedRoutingDecision,
    prepare_routing_decision as seal_routing_decision,
    verify_prepared_routing_decision_attestation,
)
from harness.state_transaction_namespace import (
    PENDING_EXTERNAL_PUBLICATION_KEY,
    PHASE_A_IDENTITY_KEYS,
    PROVIDER_CONTROL_INTENT_KEYS,
    store_owned_update_keys,
    validate_pending_external_publication,
)

logger = logging.getLogger(__name__)

AUTONOMY_MODES = {"guided", "semi", "banzai"}
PROJECT_MODES = {"greenfield", "brownfield", "self_analysis"}
VALID_SQUAD_TRANSITIONS: dict[str, set[str]] = {
    "running": {"blocked", "done"},
    "blocked": {"running"},
    "done": set(),
}
_EXTERNAL_PUBLICATION_FAILURE_KEY = "external_publication_failure"
_EXTERNAL_PUBLICATION_FAILURE_CODES = frozenset(
    {
        "manifest_invalid",
        "manifest_mismatch",
        "publish_io",
        "stage_corrupt",
        "stage_missing",
        "state_finalize",
        "target_drift",
    }
)
_EXTERNAL_PUBLICATION_FAILURE_KEYS = frozenset(
    {
        "schema_version",
        "code",
        "resume_status",
        "resume_blocked_reason",
    }
)


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
    conditional_skip: bool
    dispatch_id: str = ""
    state_revision: int = 0
    routing_decision_sha256: str = ""


@dataclass(frozen=True)
class RoutingStateSnapshot:
    """Immutable state and CAS identity used for one routing evaluation."""

    phase: str
    state_revision: int
    previous_dispatch_sha256: str
    _state_json: str

    @property
    def state(self) -> dict[str, Any]:
        value = json.loads(self._state_json)
        if type(value) is not dict:
            raise StateAdvanceError(
                "routing snapshot state is invalid",
                json_path="$.routing_snapshot.state",
                validator="type",
            )
        return value


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


def _validate_external_publication_failure(
    value: object,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or frozenset(dict.keys(value))
        != _EXTERNAL_PUBLICATION_FAILURE_KEYS
    ):
        raise ValueError(
            "external publication failure diagnostic has invalid fields"
        )
    schema_version = dict.__getitem__(value, "schema_version")
    code = dict.__getitem__(value, "code")
    resume_status = dict.__getitem__(value, "resume_status")
    resume_blocked_reason = dict.__getitem__(
        value,
        "resume_blocked_reason",
    )
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError(
            "external publication failure schema version is invalid"
        )
    if (
        type(code) is not str
        or code not in _EXTERNAL_PUBLICATION_FAILURE_CODES
    ):
        raise ValueError("external publication failure code is invalid")
    if type(resume_status) is not str:
        raise ValueError("external publication resume status is invalid")
    if (
        resume_blocked_reason is not None
        and type(resume_blocked_reason) is not str
    ):
        raise ValueError(
            "external publication resume blocked reason is invalid"
        )
    return {
        "schema_version": schema_version,
        "code": code,
        "resume_status": resume_status,
        "resume_blocked_reason": resume_blocked_reason,
    }


def _validate_routing_decision(
    decision: PreparedRoutingDecision,
    *,
    from_phase: str,
    to_phase: str,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    frozenset[str],
    PreparedPhaseResult,
]:
    """Validate the immutable payload and its ownership receipt together."""
    if type(decision) is not PreparedRoutingDecision:
        raise _prepared_result_error(
            "advance requires a PreparedRoutingDecision",
            validator="routing_decision",
        )
    try:
        verified = verify_prepared_routing_decision_attestation(
            decision,
            from_phase=from_phase,
            to_phase=to_phase,
        )
    except PreparedPhaseResultAttestationError as exc:
        raise _prepared_result_error(
            "routing decision attestation validation failed",
            json_path="$.routing_decision.attestation",
            validator="attestation",
        ) from exc
    prepared = decision.prepared_result
    attested_payload = verified.prepared_payload

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

    payload_updates = attested_payload.get("state_updates")
    if type(payload_updates) is not dict:
        raise _prepared_result_error(
            "prepared echelon_result state updates are invalid",
            json_path="$.echelon_result.state_updates",
            validator="echelon_result",
        )
    promoted_control_keys = (
        frozenset(payload_updates)
        & frozenset(prepared.control_updates)
        & PROVIDER_CONTROL_INTENT_KEYS
    )
    for key in promoted_control_keys:
        if (
            type(payload_updates[key]) is not str
            or payload_updates[key] != prepared.control_updates[key]
        ):
            raise _prepared_result_error(
                "prepared control intent does not match promoted effect",
                json_path=f"$.state_updates.{key}",
                validator="ownership",
            )
    try:
        result = validate_echelon_result(
            attested_payload,
            allowed_state_update_keys=(
                provider_keys
                | controller_keys
                | promoted_control_keys
            ),
        )
    except EchelonResultValidationError as exc:
        raise _prepared_result_error(
            "prepared echelon_result validation failed",
            json_path="$.echelon_result",
            validator="echelon_result",
        ) from exc

    result_keys = frozenset(result["state_updates"])
    owned_keys = provider_keys | controller_keys
    if result_keys != owned_keys | promoted_control_keys:
        raise _prepared_result_error(
            "prepared state update ownership does not match payload",
            json_path="$.prepared_result.ownership",
        )
    reserved_updates = store_owned_update_keys(
        (result_keys - promoted_control_keys)
        | frozenset(verified.queued_state_updates)
    )
    if reserved_updates:
        key = sorted(reserved_updates)[0]
        raise _prepared_result_error(
            f"prepared state update contains transaction-owned key {key!r}",
            json_path=f"$.state_updates.{key}",
        )
    result["state_updates"] = {
        key: value
        for key, value in result["state_updates"].items()
        if key not in promoted_control_keys
    }
    if PENDING_EXTERNAL_PUBLICATION_KEY in verified.transaction_state_updates:
        try:
            verified.transaction_state_updates[
                PENDING_EXTERNAL_PUBLICATION_KEY
            ] = validate_pending_external_publication(
                verified.transaction_state_updates[
                    PENDING_EXTERNAL_PUBLICATION_KEY
                ]
            )
        except ValueError as exc:
            raise _prepared_result_error(
                "pending external publication marker is invalid",
                json_path=(
                    "$.transaction_state_updates."
                    f"{PENDING_EXTERNAL_PUBLICATION_KEY}"
                ),
                validator="type",
            ) from exc
    return (
        result,
        verified.queued_state_updates,
        verified.transaction_state_updates,
        verified.transaction_state_removals,
        prepared,
    )


def _last_dispatch_sha256(state: dict[str, Any]) -> str:
    payload = json.dumps(
        state.get("last_dispatch"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class SquadStateStore:
    def __init__(self, squad_dir: Path) -> None:
        self._squad_dir = squad_dir
        self._path = squad_dir / "state.json"
        self._lock_path = squad_dir / "state.lock"
        self._staging_dir = squad_dir / "staging"
        self._squad_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    @property
    def squad_dir(self) -> Path:
        return self._squad_dir

    @property
    def staging_dir(self) -> Path:
        return self._staging_dir

    @contextmanager
    def _lock(self, *, exclusive: bool) -> Iterator[None]:
        with self._lock_path.open("a+b") as lock_file:
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lock_file.fileno(), operation)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())

    def load(self) -> dict:
        with self._lock(exclusive=False):
            return self._load_unlocked()

    def _save_unlocked(self, state: dict) -> dict:
        next_state = deepcopy(state)
        previous_revision = 0
        if self._path.exists():
            old_text = self._path.read_text()
            bak = self._path.with_suffix(".json.bak")
            try:
                bak.write_text(old_text)
            except OSError:
                logger.warning("Could not write .bak file: %s", bak)
            try:
                old_state = json.loads(old_text)
                self._check_monotonics(old_state, next_state)
                old_revision = old_state.get("state_revision", 0)
                if type(old_revision) is int and old_revision >= 0:
                    previous_revision = old_revision
            except json.JSONDecodeError:
                pass

        next_state["state_revision"] = previous_revision + 1
        ensure_blocked_decision(next_state)
        if (
            next_state.get("status") == "blocked"
            and next_state.get("escalation_question")
        ):
            next_state["escalation_resolved"] = False
        next_state["updated_at"] = datetime.now(timezone.utc).isoformat()
        content = json.dumps(next_state, indent=2)
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
        return next_state

    def save(self, state: dict) -> None:
        with self._lock(exclusive=True):
            current = self._load_unlocked()
            if self._path.exists():
                current_revision = current.get("state_revision", 0)
                candidate_revision = state.get("state_revision", 0)
                if (
                    type(current_revision) is not int
                    or current_revision < 0
                    or type(candidate_revision) is not int
                    or candidate_revision < 0
                ):
                    raise StateAdvanceError(
                        "state revision is invalid",
                        json_path="$.state_revision",
                        validator="type",
                    )
                if candidate_revision != current_revision:
                    raise StateAdvanceError(
                        "state changed before save",
                        json_path="$.state_revision",
                        validator="stale_state",
                    )
            self._save_unlocked(state)

    def _mutate(self, mutation: Callable[[dict], Any]) -> Any:
        """Apply one mutation to current state under the exclusive lock."""
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            result = mutation(state)
            self._save_unlocked(state)
            return result

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
        initial_state = {
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
        }
        with self._lock(exclusive=True):
            self._save_unlocked(initial_state)

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

    def capture_routing_snapshot(
        self,
        *,
        expected_phase: str | None = None,
    ) -> RoutingStateSnapshot:
        """Capture one detached routing state and CAS identity under lock."""
        if expected_phase is not None and (
            type(expected_phase) is not str or not expected_phase
        ):
            raise StateAdvanceError(
                "routing snapshot phase is invalid",
                json_path="$.phase",
                validator="type",
            )
        with self._lock(exclusive=False):
            state = self._load_unlocked()
        phase = state.get("phase")
        if type(phase) is not str or not phase:
            raise StateAdvanceError(
                "persisted routing phase is invalid",
                json_path="$.phase",
                validator="type",
            )
        if expected_phase is not None and phase != expected_phase:
            raise StateAdvanceError(
                "persisted phase does not match routing source",
                json_path="$.phase",
                validator="stale_state",
            )
        revision = state.get("state_revision", 0)
        if type(revision) is not int or revision < 0:
            raise StateAdvanceError(
                "persisted state revision is invalid",
                json_path="$.state_revision",
                validator="type",
            )
        return RoutingStateSnapshot(
            phase=phase,
            state_revision=revision,
            previous_dispatch_sha256=_last_dispatch_sha256(state),
            _state_json=json.dumps(
                state,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )

    def commit_routing_snapshot_state(
        self,
        snapshot: RoutingStateSnapshot,
        next_state: dict[str, Any],
    ) -> bool:
        """Publish a snapshot-derived failure state only while identity matches."""
        if type(snapshot) is not RoutingStateSnapshot:
            raise StateAdvanceError(
                "routing snapshot is invalid",
                json_path="$.routing_snapshot",
                validator="type",
            )
        if type(next_state) is not dict:
            raise StateAdvanceError(
                "snapshot state update must be an object",
                json_path="$.state",
                validator="type",
            )
        if next_state.get("state_revision") != snapshot.state_revision:
            raise StateAdvanceError(
                "snapshot state revision was modified",
                json_path="$.state_revision",
                validator="stale_state",
            )
        with self._lock(exclusive=True):
            current = self._load_unlocked()
            if (
                current.get("phase") != snapshot.phase
                or current.get("state_revision", 0)
                != snapshot.state_revision
                or _last_dispatch_sha256(current)
                != snapshot.previous_dispatch_sha256
            ):
                return False
            self._save_unlocked(next_state)
            return True

    def prepare_routing_decision(
        self,
        prepared: PreparedPhaseResult,
        *,
        snapshot: RoutingStateSnapshot,
        from_phase: str,
        to_phase: str,
        queued_state_updates: dict[str, Any] | None = None,
        judgment_payloads: object = (),
        source: str = "transition",
        transition_index: int | None = None,
        increment_iteration: bool = False,
        manual_phase_run: bool = False,
        conditional_skip: bool = False,
        record_completion: bool = True,
        token_usage_delta: int = 0,
        transaction_state_updates: dict[str, Any] | None = None,
        transaction_state_removals: object = (),
    ) -> PreparedRoutingDecision:
        """Bind a prepared result to the currently persisted routing identity."""
        for name, value in (
            ("increment_iteration", increment_iteration),
            ("manual_phase_run", manual_phase_run),
            ("conditional_skip", conditional_skip),
            ("record_completion", record_completion),
        ):
            if type(value) is not bool:
                raise StateAdvanceError(
                    f"{name.replace('_', ' ')} identity must be a Boolean",
                    json_path=f"$.{name}",
                    validator="type",
                )
        if type(snapshot) is not RoutingStateSnapshot:
            raise StateAdvanceError(
                "routing decision requires a store snapshot",
                json_path="$.routing_snapshot",
                validator="type",
            )
        if snapshot.phase != from_phase:
            raise StateAdvanceError(
                "routing snapshot phase does not match routing source",
                json_path="$.phase",
                validator="stale_state",
            )
        with self._lock(exclusive=False):
            current = self._load_unlocked()
        if (
            current.get("phase") != snapshot.phase
            or current.get("state_revision", 0)
            != snapshot.state_revision
            or _last_dispatch_sha256(current)
            != snapshot.previous_dispatch_sha256
        ):
            raise StateAdvanceError(
                "persisted state changed before routing decision sealing",
                json_path="$.state_revision",
                validator="stale_state",
            )
        try:
            return seal_routing_decision(
                prepared,
                from_phase=from_phase,
                to_phase=to_phase,
                expected_state_revision=snapshot.state_revision,
                expected_previous_dispatch_sha256=(
                    snapshot.previous_dispatch_sha256
                ),
                queued_state_updates=queued_state_updates,
                judgment_payloads=judgment_payloads,
                source=source,
                transition_index=transition_index,
                increment_iteration=increment_iteration,
                manual_phase_run=manual_phase_run,
                conditional_skip=conditional_skip,
                record_completion=record_completion,
                token_usage_delta=token_usage_delta,
                transaction_state_updates=transaction_state_updates,
                transaction_state_removals=transaction_state_removals,
            )
        except PreparedPhaseResultAttestationError as exc:
            raise StateAdvanceError(
                "routing decision preparation failed",
                json_path="$.routing_decision",
                validator="attestation",
            ) from exc

    def advance(
        self,
        from_phase: str,
        to_phase: str,
        decision: PreparedRoutingDecision,
    ) -> AdvanceReceipt:
        try:
            (
                result,
                queued_updates,
                transaction_updates,
                transaction_removals,
                prepared,
            ) = _validate_routing_decision(
                decision,
                from_phase=from_phase,
                to_phase=to_phase,
            )
        except StateAdvanceError:
            raise
        except Exception as exc:
            raise StateAdvanceError(
                "prepared result validation failed",
                validator="prepared_result",
            ) from exc

        with self._lock(exclusive=True):
            state = self._load_unlocked()
            revision = state.get("state_revision", 0)
            if state.get("phase") != from_phase:
                raise StateAdvanceError(
                    "persisted phase changed before state advance",
                    json_path="$.phase",
                    validator="stale_state",
                )
            if (
                type(revision) is not int
                or revision != decision.expected_state_revision
            ):
                raise StateAdvanceError(
                    "persisted state revision changed before state advance",
                    json_path="$.state_revision",
                    validator="stale_state",
                )
            if (
                _last_dispatch_sha256(state)
                != decision.expected_previous_dispatch_sha256
            ):
                raise StateAdvanceError(
                    "persisted dispatch identity changed before state advance",
                    json_path="$.last_dispatch",
                    validator="stale_state",
                )

            next_state = deepcopy(state)
            logger.debug(
                "squad advance %s → %s verdict=%s run_id=%s",
                from_phase,
                to_phase,
                result["verdict"],
                state.get("run_id", "?"),
            )
            completed_at = datetime.now(timezone.utc).isoformat()
            dispatch_id = secrets.token_hex(16)
            committed_revision = revision + 1
            next_state["phase"] = to_phase
            next_state["last_dispatch"] = {
                "dispatch_id": dispatch_id,
                "phase_id": from_phase,
                "next_phase": to_phase,
                "verdict": result["verdict"],
                "completed_at": completed_at,
                "state_revision": committed_revision,
                "previous_dispatch_sha256": (
                    decision.expected_previous_dispatch_sha256
                ),
                "preparation_sha256": prepared.preparation_sha256,
                "routing_decision_sha256": decision.routing_sha256,
                "routing_source": decision.source,
                "transition_index": decision.transition_index,
                "judgment_payload_sha256": list(
                    decision.judgment_payload_sha256
                ),
                "controller_contract": prepared.controller_contract_name,
                "controller_contract_sha256": (
                    prepared.controller_contract_sha256
                ),
                "controller_normalized": bool(prepared.normalized_paths),
                "controller_normalized_paths": list(
                    prepared.normalized_paths
                ),
                "conditional_skip": decision.conditional_skip,
                "record_completion": decision.record_completion,
            }
            if decision.manual_phase_run:
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
                        "verdict": result["verdict"],
                        "completed_at": completed_at,
                    }
                )
                next_state["manual_phase_runs"] = manual_runs
            if decision.record_completion:
                completed = next_state.get("completed_phases")
                if not isinstance(completed, list):
                    completed = []
                else:
                    completed = list(completed)
                if from_phase not in completed:
                    completed.append(from_phase)
                next_state["completed_phases"] = completed
            for key in prepared.state_removals:
                next_state.pop(key, None)
            for key in transaction_removals:
                next_state.pop(key, None)
            identity_is_bootstrapped = bool(
                next_state.get("feature_branch")
            )
            combined_updates = {
                **result["state_updates"],
                **queued_updates,
            }
            try:
                for key, value in combined_updates.items():
                    if (
                        identity_is_bootstrapped
                        and key in PHASE_A_IDENTITY_KEYS
                    ):
                        if next_state.get(key) != value:
                            logger.warning(
                                "Ignoring agent attempt to change "
                                "controller-owned Phase A identity %s: "
                                "%r -> %r (run_id=%s)",
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
                for key, value in prepared.control_updates.items():
                    if key == "status":
                        self._transition_status(next_state, value)
                    else:
                        next_state[key] = value
                for key, value in transaction_updates.items():
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
            if (
                decision.increment_iteration
                and "iteration" not in combined_updates
                and "iteration" not in transaction_updates
            ):
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
            next_state["token_usage"] = (
                int(next_state.get("token_usage") or 0)
                + decision.token_usage_delta
            )
            next_state.pop("controller_contract_error", None)

            try:
                saved_state = self._save_unlocked(next_state)
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
            conditional_skip=decision.conditional_skip,
            dispatch_id=dispatch_id,
            state_revision=saved_state["state_revision"],
            routing_decision_sha256=decision.routing_sha256,
        )

    def merge_advance_failure_diagnostic(
        self,
        *,
        from_phase: str,
        expected_state_revision: int,
        expected_previous_dispatch_sha256: str | None,
        updates: dict[str, Any],
        token_usage_delta: int = 0,
    ) -> bool:
        """Merge a failure only if no phase/dispatch publication won the race."""
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            if state.get("phase") != from_phase:
                return False
            if (
                state.get("state_revision", 0)
                != expected_state_revision
            ):
                return False
            if (
                expected_previous_dispatch_sha256 is not None
                and _last_dispatch_sha256(state)
                != expected_previous_dispatch_sha256
            ):
                return False
            next_state = deepcopy(state)
            next_state.update(deepcopy(updates))
            next_state["token_usage"] = (
                int(next_state.get("token_usage") or 0)
                + token_usage_delta
            )
            self._save_unlocked(next_state)
            return True

    def begin_external_publication(
        self,
        marker: object,
        *,
        snapshot: RoutingStateSnapshot,
        state_updates: dict[str, object] | None = None,
    ) -> None:
        """Install one terminal publication marker under an exact state CAS."""
        try:
            expected_marker = validate_pending_external_publication(marker)
        except ValueError as exc:
            raise StateAdvanceError(
                "external publication marker is invalid",
                json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                validator="type",
            ) from exc
        if not isinstance(snapshot, RoutingStateSnapshot):
            raise StateAdvanceError(
                "external publication snapshot is invalid",
                json_path="$.routing_snapshot",
                validator="type",
            )
        updates = deepcopy(state_updates or {})
        if frozenset(updates) - {"published_spec_dir"}:
            raise StateAdvanceError(
                "external publication state update is not owned",
                json_path="$.state_updates",
                validator="ownership",
            )
        if "published_spec_dir" in updates and (
            type(updates["published_spec_dir"]) is not str
            or not updates["published_spec_dir"].strip()
        ):
            raise StateAdvanceError(
                "published spec directory is invalid",
                json_path="$.state_updates.published_spec_dir",
                validator="type",
            )
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            revision = state.get("state_revision", 0)
            if (
                state.get("phase") != snapshot.phase
                or type(revision) is not int
                or revision != snapshot.state_revision
                or _last_dispatch_sha256(state)
                != snapshot.previous_dispatch_sha256
                or PENDING_EXTERNAL_PUBLICATION_KEY in state
            ):
                raise StateAdvanceError(
                    "persisted state changed before external publication",
                    json_path="$.routing_snapshot",
                    validator="stale_state",
                )
            next_state = deepcopy(state)
            next_state.update(updates)
            next_state[PENDING_EXTERNAL_PUBLICATION_KEY] = expected_marker
            try:
                self._save_unlocked(next_state)
            except Exception as exc:
                raise StateAdvanceError(
                    "atomic external publication marker save failed",
                    json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                    validator="save",
                ) from exc

    @staticmethod
    def _require_external_publication_marker(
        state: dict[str, Any],
        expected_marker: dict[str, object],
    ) -> None:
        try:
            current_marker = validate_pending_external_publication(
                state.get(PENDING_EXTERNAL_PUBLICATION_KEY)
            )
        except ValueError as exc:
            raise StateAdvanceError(
                "persisted external publication marker is invalid",
                json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                validator="state_contract",
            ) from exc
        if current_marker != expected_marker:
            raise StateAdvanceError(
                "external publication marker changed",
                json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                validator="stale_state",
            )

    def record_external_publication_failure(
        self,
        marker: object,
        code: object,
    ) -> None:
        try:
            expected_marker = validate_pending_external_publication(marker)
        except ValueError as exc:
            raise StateAdvanceError(
                "external publication marker is invalid",
                json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                validator="type",
            ) from exc
        if (
            type(code) is not str
            or code not in _EXTERNAL_PUBLICATION_FAILURE_CODES
        ):
            raise StateAdvanceError(
                "external publication failure code is invalid",
                json_path=f"$.{_EXTERNAL_PUBLICATION_FAILURE_KEY}.code",
                validator="enum",
            )
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            self._require_external_publication_marker(
                state,
                expected_marker,
            )
            if _EXTERNAL_PUBLICATION_FAILURE_KEY in state:
                try:
                    diagnostic = _validate_external_publication_failure(
                        state[_EXTERNAL_PUBLICATION_FAILURE_KEY]
                    )
                except ValueError as exc:
                    raise StateAdvanceError(
                        "persisted external publication failure is invalid",
                        json_path=f"$.{_EXTERNAL_PUBLICATION_FAILURE_KEY}",
                        validator="state_contract",
                    ) from exc
                diagnostic["code"] = code
            else:
                resume_status = state.get("status", "running")
                resume_blocked_reason = state.get("blocked_reason")
                diagnostic = _validate_external_publication_failure(
                    {
                        "schema_version": 1,
                        "code": code,
                        "resume_status": resume_status,
                        "resume_blocked_reason": resume_blocked_reason,
                    }
                )
            state[_EXTERNAL_PUBLICATION_FAILURE_KEY] = diagnostic
            state["status"] = "blocked"
            state["blocked_reason"] = "external_publication_pending"
            self._save_unlocked(state)

    def complete_external_publication(self, marker: object) -> None:
        try:
            expected_marker = validate_pending_external_publication(marker)
        except ValueError as exc:
            raise StateAdvanceError(
                "external publication marker is invalid",
                json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                validator="type",
            ) from exc
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            self._require_external_publication_marker(
                state,
                expected_marker,
            )
            if _EXTERNAL_PUBLICATION_FAILURE_KEY in state:
                try:
                    diagnostic = _validate_external_publication_failure(
                        state[_EXTERNAL_PUBLICATION_FAILURE_KEY]
                    )
                except ValueError as exc:
                    raise StateAdvanceError(
                        "persisted external publication failure is invalid",
                        json_path=f"$.{_EXTERNAL_PUBLICATION_FAILURE_KEY}",
                        validator="state_contract",
                    ) from exc
                state["status"] = diagnostic["resume_status"]
                resume_blocked_reason = diagnostic[
                    "resume_blocked_reason"
                ]
                if resume_blocked_reason is None:
                    state.pop("blocked_reason", None)
                else:
                    state["blocked_reason"] = resume_blocked_reason
            state.pop(PENDING_EXTERNAL_PUBLICATION_KEY, None)
            state.pop(_EXTERNAL_PUBLICATION_FAILURE_KEY, None)
            self._save_unlocked(state)

    def set_blocked(self, reason: str) -> None:
        def mutate(state: dict) -> None:
            logger.debug(
                "squad blocked run_id=%s reason=%r",
                state.get("run_id", "?"),
                reason,
            )
            self._transition_status(state, "blocked")
            state["blocked_reason"] = reason

        self._mutate(mutate)

    def set_cancel_requested(self) -> None:
        self._mutate(
            lambda state: state.__setitem__("cancel_requested", True)
        )

    def is_cancel_requested(self) -> bool:
        return bool(self.load().get("cancel_requested", False))

    def token_usage(self) -> int:
        return int(self.load().get("token_usage", 0))

    def increment_token_usage(self, tokens: int) -> None:
        def mutate(state: dict) -> None:
            state["token_usage"] = state.get("token_usage", 0) + tokens

        self._mutate(mutate)

    def increment_why_fail_count(self) -> int:
        def mutate(state: dict) -> int:
            count = state.get("why_fail_count", 0) + 1
            state["why_fail_count"] = count
            return count

        return int(self._mutate(mutate))

    def reset_why_fail_count(self) -> None:
        self._mutate(
            lambda state: state.__setitem__("why_fail_count", 0)
        )

    def increment_phase_dispatch_count(self, phase: str) -> int:
        def mutate(state: dict) -> int:
            counts = state.get("phase_dispatch_counts") or {}
            counts[phase] = counts.get(phase, 0) + 1
            state["phase_dispatch_counts"] = counts
            return counts[phase]

        return int(self._mutate(mutate))

    def get_phase_dispatch_count(self, phase: str) -> int:
        state = self.load()
        return (state.get("phase_dispatch_counts") or {}).get(phase, 0)

    def reset_phase_dispatch_count(self, phase: str) -> None:
        """Forget attempts that never reached the phase agent."""
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            counts = state.get("phase_dispatch_counts") or {}
            if phase not in counts:
                return
            counts.pop(phase)
            state["phase_dispatch_counts"] = counts
            self._save_unlocked(state)

    def increment_convergence_guard_fires(self) -> int:
        def mutate(state: dict) -> int:
            count = state.get("convergence_guard_fire_count", 0) + 1
            state["convergence_guard_fire_count"] = count
            return count

        return int(self._mutate(mutate))

    def reset_convergence_guard_fires(self) -> None:
        self._mutate(
            lambda state: state.__setitem__(
                "convergence_guard_fire_count",
                0,
            )
        )

    def increment_cost(self, amount: float) -> None:
        if not amount:
            return
        def mutate(state: dict) -> None:
            state["cost_usd"] = round(
                state.get("cost_usd", 0.0) + amount,
                6,
            )

        self._mutate(mutate)

    def token_budget(self) -> int:
        return int(self.load().get("token_budget", 0))
