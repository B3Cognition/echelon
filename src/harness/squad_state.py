"""SquadStateStore — atomic reads/writes for squad/<run-id>/state.json."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import logging
import os
import secrets
import stat
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal, Mapping

from harness.blocked_decision import (
    BlockedDecisionError,
    build_blocked_decision_v2,
    ensure_blocked_decision,
    normalize_escalation_options,
    validate_blocked_decision_v2,
)
from harness.controller_lock_order import controller_lock_order
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
from harness.human_input import HumanInputResolution, PreparedHumanInput
from harness.recovery_instruction import (
    RecoveryInstruction,
    RecoveryInstructionError,
    RecoveryKind,
    validate_decision_recovery_pair,
)
from harness.squad_completion import (
    CompletionIntent,
    CompletionMarker,
    PreparedControllerCompletion,
)
from harness.state_transaction_namespace import (
    PENDING_CONTROLLER_COMPLETION_KEY,
    PENDING_EXTERNAL_PUBLICATION_KEY,
    PHASE_A_IDENTITY_KEYS,
    PROVIDER_CONTROL_INTENT_KEYS,
    store_owned_update_keys,
    validate_pending_controller_completion,
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
_CONTROLLER_COMPLETION_FAILURE_KEY = "controller_completion_failure"
_CONTROLLER_COMPLETION_FAILURE_CODES = frozenset(
    {
        "completion_missing",
        "intent_invalid",
        "intent_mismatch",
        "receipts_invalid",
        "receipts_mismatch",
        "stage_corrupt",
        "stage_io",
        "stage_missing",
    }
)
_CONTROLLER_COMPLETION_FAILURE_KEYS = frozenset(
    {
        "schema_version",
        "code",
        "resume_status",
        "resume_blocked_reason",
    }
)
_COMPLETION_EFFECT_ORDER = (
    "journal",
    "timing",
    "checkpoint",
    "context",
    "mining",
)
_SHA256_CHARACTERS = frozenset("0123456789abcdef")
_MAX_COMPLETION_DOCUMENT_BYTES = 4_194_304
_MAX_COMPLETION_RECEIPTS_BYTES = 1_048_576
_MAX_STATE_BYTES = 16_777_216
_ACTIVE_HUMAN_INPUT_DECISION_STATUSES = frozenset(
    {"pending", "resolving", "awaiting_human"}
)
_ACTIVE_HUMAN_INPUT_AUTHORITY_KEYS = frozenset(
    {
        "blocked_decision",
        "recovery_instruction",
        "phase",
        "status",
        "blocked_reason",
        "escalation_question",
        "escalation_options",
    }
)
_HUMAN_INPUT_DISPLAY_AUTHORITY_KEYS = frozenset(
    {
        "escalation_question",
        "escalation_options",
        "escalation_resolved",
        "escalation_resolver",
        "escalation_selected_option",
        "escalation_risk_level",
        "escalation_recommended_answer",
        "escalation_default_answer",
    }
)
_HUMAN_INPUT_PAIR_AUTHORITY_KEYS = frozenset(
    {"blocked_decision", "recovery_instruction"}
)
_PROVIDER_ADVANCE_SAFEGUARD_PRODUCERS = frozenset(
    {"consecutive_why_fails", "why2_metric_stagnation"}
)
_HUMAN_INPUT_STATE_EFFECT_RESERVED_KEYS = frozenset(
    {
        "blocked_decision",
        "recovery_instruction",
        "escalation_question",
        "escalation_options",
        "state_revision",
        "updated_at",
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


class StateDurabilityError(StateAdvanceError):
    """A bounded failure to prove one state filesystem postimage durable."""

    _STAGES = frozenset(
        {
            "directory_create",
            "pre_replace",
            "post_replace",
            "confirm",
        }
    )

    def __init__(self, message: str, *, stage: str) -> None:
        bounded_stage = stage if stage in self._STAGES else "confirm"
        super().__init__(
            message,
            json_path="$.state",
            validator="durability",
        )
        self.stage = bounded_stage


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _fsync_retry(descriptor: int) -> None:
    while True:
        try:
            os.fsync(descriptor)
            return
        except OSError as exc:
            if exc.errno != errno.EINTR:
                raise


def _open_real_directory(
    path: Path,
    *,
    stage: str,
) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        named = os.lstat(path)
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise StateDurabilityError(
            "state directory is unavailable",
            stage=stage,
        ) from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or stat.S_ISLNK(named.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or _identity(opened) != _identity(named)
    ):
        os.close(descriptor)
        raise StateDurabilityError(
            "state directory identity changed",
            stage=stage,
        )
    return descriptor


def _ensure_directory_durable(path: Path) -> None:
    """Create missing path components and sync each child into its parent."""

    absolute = path.absolute()
    missing: list[Path] = []
    cursor = absolute
    while True:
        try:
            metadata = os.lstat(cursor)
        except FileNotFoundError:
            if cursor.parent == cursor:
                raise StateDurabilityError(
                    "state directory has no existing ancestor",
                    stage="directory_create",
                )
            missing.append(cursor)
            cursor = cursor.parent
            continue
        except OSError as exc:
            raise StateDurabilityError(
                "state directory could not be inspected",
                stage="directory_create",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
            metadata.st_mode
        ):
            raise StateDurabilityError(
                "state directory must be a real directory",
                stage="directory_create",
            )
        break

    for directory in reversed(missing):
        parent = directory.parent
        parent_fd = _open_real_directory(
            parent,
            stage="directory_create",
        )
        child_fd = -1
        try:
            try:
                os.mkdir(directory.name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            flags = os.O_RDONLY
            flags |= getattr(os, "O_DIRECTORY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            child_fd = os.open(
                directory.name,
                flags,
                dir_fd=parent_fd,
            )
            opened = os.fstat(child_fd)
            named = os.stat(
                directory.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or not stat.S_ISDIR(named.st_mode)
                or _identity(opened) != _identity(named)
            ):
                raise StateDurabilityError(
                    "created state directory identity changed",
                    stage="directory_create",
                )
            _fsync_retry(child_fd)
            _fsync_retry(parent_fd)
            current = os.stat(
                directory.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(current.st_mode)
                or _identity(current) != _identity(opened)
            ):
                raise StateDurabilityError(
                    "created state directory identity changed",
                    stage="directory_create",
                )
        except StateDurabilityError:
            raise
        except OSError as exc:
            raise StateDurabilityError(
                "state directory could not be created durably",
                stage="directory_create",
            ) from exc
        finally:
            if child_fd >= 0:
                os.close(child_fd)
            os.close(parent_fd)

    parent_fd = _open_real_directory(
        absolute.parent,
        stage="directory_create",
    )
    directory_fd = -1
    try:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        directory_fd = os.open(
            absolute.name,
            flags,
            dir_fd=parent_fd,
        )
        opened = os.fstat(directory_fd)
        named = os.stat(
            absolute.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or _identity(opened) != _identity(named)
        ):
            raise StateDurabilityError(
                "state directory identity changed",
                stage="directory_create",
            )
        _fsync_retry(directory_fd)
        _fsync_retry(parent_fd)
        final_named = os.stat(
            absolute.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(final_named.st_mode)
            or _identity(final_named) != _identity(opened)
        ):
            raise StateDurabilityError(
                "state directory identity changed",
                stage="directory_create",
            )
    except StateDurabilityError:
        raise
    except OSError as exc:
        raise StateDurabilityError(
            "state directory durability confirmation failed",
            stage="directory_create",
        ) from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(parent_fd)


def _read_regular_descriptor(
    descriptor: int,
    *,
    maximum: int,
) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(descriptor, min(1_048_576, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > maximum:
        raise StateDurabilityError(
            "state file exceeds the durability bound",
            stage="confirm",
        )
    return content


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


def _validate_controller_completion_failure(
    value: object,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or frozenset(dict.keys(value))
        != _CONTROLLER_COMPLETION_FAILURE_KEYS
    ):
        raise ValueError(
            "controller completion failure diagnostic has invalid fields"
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
            "controller completion failure schema version is invalid"
        )
    if (
        type(code) is not str
        or code not in _CONTROLLER_COMPLETION_FAILURE_CODES
    ):
        raise ValueError("controller completion failure code is invalid")
    if (
        type(resume_status) is not str
        or resume_status not in VALID_SQUAD_TRANSITIONS
    ):
        raise ValueError(
            "controller completion resume status is invalid"
        )
    if (
        resume_blocked_reason is not None
        and (
            type(resume_blocked_reason) is not str
            or len(resume_blocked_reason) > 4_096
        )
    ):
        raise ValueError(
            "controller completion resume blocked reason is invalid"
        )
    return {
        "schema_version": schema_version,
        "code": code,
        "resume_status": resume_status,
        "resume_blocked_reason": resume_blocked_reason,
    }


def _valid_completion_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and frozenset(value) <= _SHA256_CHARACTERS
    )


def _canonical_completion_document(
    value: object,
    *,
    maximum: int = _MAX_COMPLETION_DOCUMENT_BYTES,
) -> tuple[bytes, str]:
    try:
        encoded = (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise StateAdvanceError(
            "controller completion document is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            validator="completion_intent",
        ) from exc
    if len(encoded) > maximum:
        raise StateAdvanceError(
            "controller completion document is too large",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            validator="completion_intent",
        )
    return encoded, hashlib.sha256(encoded).hexdigest()


def _validate_prepared_controller_completion(
    prepared: object,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    str,
    str,
]:
    if (
        type(prepared) is not PreparedControllerCompletion
        or type(prepared.marker) is not CompletionMarker
        or type(prepared.intent) is not CompletionIntent
    ):
        raise StateAdvanceError(
            "controller completion requires a loaded typed intent",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            validator="completion_intent",
        )
    try:
        marker = validate_pending_controller_completion(
            prepared.marker.to_dict()
        )
        intent = prepared.intent.to_dict()
        receipts = prepared.receipts
    except Exception as exc:
        raise StateAdvanceError(
            "controller completion typed intent is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            validator="completion_intent",
        ) from exc
    if (
        type(intent) is not dict
        or frozenset(dict.keys(intent))
        != frozenset(
            {
                "schema_version",
                "completion_id",
                "origin",
                "publication",
                "route",
                "effect_plan",
                "checkpoint_prestate",
                "context_reason",
                "mine_phase_a",
                "judgment_payload_sha256",
                "judgments",
            }
        )
        or type(intent["schema_version"]) is not int
        or intent["schema_version"] != 1
        or intent["completion_id"] != marker["completion_id"]
        or intent["origin"] != marker["origin"]
    ):
        raise StateAdvanceError(
            "controller completion intent identity is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            validator="completion_intent",
        )
    intent_bytes, intent_sha256 = _canonical_completion_document(intent)
    if (
        len(intent_bytes) > _MAX_COMPLETION_DOCUMENT_BYTES
        or intent_sha256 != marker["intent_sha256"]
    ):
        raise StateAdvanceError(
            "controller completion intent digest changed",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.intent_sha256",
            validator="completion_intent",
        )
    publication = intent["publication"]
    if type(publication) is not dict:
        raise StateAdvanceError(
            "controller completion publication binding is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            validator="completion_intent",
        )
    _, publication_sha256 = _canonical_completion_document(publication)
    if publication_sha256 != marker["publication_binding_sha256"]:
        raise StateAdvanceError(
            "controller completion publication binding changed",
            json_path=(
                f"$.{PENDING_CONTROLLER_COMPLETION_KEY}."
                "publication_binding_sha256"
            ),
            validator="completion_intent",
        )
    route = intent["route"]
    if type(route) is not dict or route.get("kind") != intent["origin"]:
        raise StateAdvanceError(
            "controller completion route binding is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            validator="completion_intent",
        )
    plan_value = intent["effect_plan"]
    if type(plan_value) is not list:
        raise StateAdvanceError(
            "controller completion effect plan is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.step",
            validator="completion_step",
        )
    plan = tuple(plan_value)
    if any(type(effect) is not str for effect in plan):
        raise StateAdvanceError(
            "controller completion effect plan is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.step",
            validator="completion_step",
        )
    try:
        indexes = tuple(
            _COMPLETION_EFFECT_ORDER.index(effect)
            for effect in plan
        )
    except ValueError as exc:
        raise StateAdvanceError(
            "controller completion effect plan is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.step",
            validator="completion_step",
        ) from exc
    if indexes != tuple(sorted(set(indexes))):
        raise StateAdvanceError(
            "controller completion effect plan is not monotonic",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.step",
            validator="completion_step",
        )
    if (
        type(receipts) is not dict
        or frozenset(dict.keys(receipts))
        != frozenset({"schema_version", "completion_id", "effects"})
        or type(receipts["schema_version"]) is not int
        or receipts["schema_version"] != 1
        or receipts["completion_id"] != marker["completion_id"]
        or type(receipts["effects"]) is not dict
    ):
        raise StateAdvanceError(
            "controller completion receipts are invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.receipts_sha256",
            validator="completion_receipts",
        )
    effects = receipts["effects"]
    if any(
        type(key) is not str or type(value) is not dict
        for key, value in dict.items(effects)
    ):
        raise StateAdvanceError(
            "controller completion receipts are invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.receipts_sha256",
            validator="completion_receipts",
        )
    receipt_keys = frozenset(dict.keys(effects))
    expected_prefix = frozenset(plan[: len(receipt_keys)])
    if receipt_keys != expected_prefix:
        raise StateAdvanceError(
            "controller completion receipt prefix is invalid",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.receipts_sha256",
            validator="completion_receipts",
        )
    _, receipts_sha256 = _canonical_completion_document(
        receipts,
        maximum=_MAX_COMPLETION_RECEIPTS_BYTES,
    )
    step = marker["step"]
    receipt_count = len(receipt_keys)
    if step == "awaiting_publication":
        prefix_kind = "bound"
        valid_prefix = (
            publication.get("kind") == "external"
            and receipt_count == 0
            and receipts_sha256 == marker["receipts_sha256"]
        )
    elif step == "complete":
        prefix_kind = "bound"
        valid_prefix = (
            receipt_count == len(plan)
            and receipts_sha256 == marker["receipts_sha256"]
        )
    elif step in plan:
        step_index = plan.index(step)
        if receipt_count == step_index:
            prefix_kind = "bound"
            valid_prefix = receipts_sha256 == marker["receipts_sha256"]
        elif receipt_count == step_index + 1:
            prior_effects = {
                effect: effects[effect]
                for effect in plan[:step_index]
            }
            _, prior_sha256 = _canonical_completion_document(
                {
                    "schema_version": 1,
                    "completion_id": marker["completion_id"],
                    "effects": prior_effects,
                },
                maximum=_MAX_COMPLETION_RECEIPTS_BYTES,
            )
            prefix_kind = "one_ahead"
            valid_prefix = prior_sha256 == marker["receipts_sha256"]
        else:
            prefix_kind = "invalid"
            valid_prefix = False
    else:
        prefix_kind = "invalid"
        valid_prefix = False
    if not valid_prefix:
        raise StateAdvanceError(
            "controller completion receipt prefix does not match marker",
            json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.receipts_sha256",
            validator="completion_receipts",
        )
    return marker, intent, receipts, receipts_sha256, prefix_kind


def _is_human_input_decision_v2(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and type(value.get("schema_version")) is int
        and value.get("schema_version") == 2
    )


def _human_input_recovery_for_decision(
    decision: Mapping[str, object],
) -> RecoveryInstruction | None:
    status = decision["status"]
    if status == "resolved":
        return None
    kind, phase, requires_human_input = {
        "pending": (
            RecoveryKind.RESOLVE_DECISION,
            decision["source_phase"],
            False,
        ),
        "resolving": (
            RecoveryKind.RESOLVE_DECISION,
            decision["source_phase"],
            False,
        ),
        "awaiting_human": (
            RecoveryKind.AWAIT_HUMAN_ANSWER,
            decision["source_phase"],
            True,
        ),
        "failed": (RecoveryKind.MANUAL_DIAGNOSIS, "", False),
    }[str(status)]
    return RecoveryInstruction(
        schema_version=2,
        kind=kind,
        reason_code=str(decision["reason_code"]),
        phase=str(phase),
        requires_human_input=requires_human_input,
        decision_id=str(decision["id"]),
    )


def _validate_human_input_authority_write(
    current: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    allow_update: bool,
) -> None:
    current_decision = current.get("blocked_decision")
    candidate_decision = candidate.get("blocked_decision")
    current_is_v2 = _is_human_input_decision_v2(current_decision)
    candidate_is_v2 = _is_human_input_decision_v2(candidate_decision)

    if candidate_is_v2:
        try:
            validate_decision_recovery_pair(
                candidate_decision,
                candidate.get("recovery_instruction"),
            )
        except BlockedDecisionError as exc:
            raise StateAdvanceError(
                f"invalid schema-v2 decision authority: {exc}",
                json_path="$.blocked_decision",
                validator="human_input_authority",
            ) from exc
        except RecoveryInstructionError as exc:
            raise StateAdvanceError(
                f"invalid schema-v2 recovery authority: {exc}",
                json_path="$.recovery_instruction",
                validator="human_input_authority",
            ) from exc
    if allow_update:
        return
    if current_is_v2 != candidate_is_v2:
        raise StateAdvanceError(
            "generic state writes cannot create or clear schema-v2 decision authority",
            json_path="$.blocked_decision",
            validator="human_input_authority",
        )
    if not current_is_v2:
        return
    if current_decision != candidate_decision:
        raise StateAdvanceError(
            "generic state writes cannot replace schema-v2 decision authority",
            json_path="$.blocked_decision",
            validator="human_input_authority",
        )
    if current.get("recovery_instruction") != candidate.get(
        "recovery_instruction"
    ):
        raise StateAdvanceError(
            "generic state writes cannot mutate schema-v2 recovery authority",
            json_path="$.recovery_instruction",
            validator="human_input_authority",
        )
    validated = validate_blocked_decision_v2(current_decision)
    if validated["status"] not in _ACTIVE_HUMAN_INPUT_DECISION_STATUSES:
        for key in _HUMAN_INPUT_DISPLAY_AUTHORITY_KEYS:
            if current.get(key) != candidate.get(key):
                raise StateAdvanceError(
                    "generic state writes cannot mutate terminal "
                    f"decision display field {key!r}",
                    json_path=f"$.{key}",
                    validator="human_input_authority",
                )
        return
    for key in _ACTIVE_HUMAN_INPUT_AUTHORITY_KEYS:
        if current.get(key) != candidate.get(key):
            raise StateAdvanceError(
                f"generic state writes cannot mutate active decision field {key!r}",
                json_path=f"$.{key}",
                validator="human_input_authority",
            )


def _prepare_exact_state_postimage(
    before: dict[str, Any],
    desired: dict[str, Any],
) -> dict[str, Any]:
    old_revision = before.get("state_revision", 0)
    if type(old_revision) is not int or old_revision < 0:
        raise StateAdvanceError(
            "persisted state revision is invalid",
            json_path="$.state_revision",
            validator="type",
        )
    attempted = deepcopy(desired)
    ensure_blocked_decision(attempted)
    if (
        attempted.get("status") == "blocked"
        and attempted.get("escalation_question")
    ):
        attempted["escalation_resolved"] = False
    attempted["state_revision"] = old_revision + 1
    attempted["updated_at"] = datetime.now(timezone.utc).isoformat()
    return attempted


def _state_matches_exact_save(
    attempted: dict[str, Any],
    observed: dict[str, Any],
) -> bool:
    return observed == attempted


def _validate_human_input_seal_path(
    request: PreparedHumanInput,
    *,
    transaction: Literal["advance", "setter"],
    from_phase: str | None = None,
) -> None:
    if type(request) is not PreparedHumanInput or request.schema_version != 1:
        raise StateAdvanceError(
            "human-input sealing requires a prepared request",
            json_path="$.human_input",
            validator="type",
        )
    if transaction == "advance":
        accepted = (
            request.source_kind == "provider_escalation"
            or (
                request.source_kind == "controller_safeguard"
                and request.producer_id
                in _PROVIDER_ADVANCE_SAFEGUARD_PRODUCERS
            )
        )
        if request.phase_id != from_phase:
            raise StateAdvanceError(
                "human-input source phase does not match state advance",
                json_path="$.human_input.phase_id",
                validator="human_input_authority",
            )
    else:
        accepted = (
            request.source_kind in {"human_gate", "legacy_recovery"}
            or (
                request.source_kind == "controller_safeguard"
                and request.producer_id == "phase_dispatch_limit"
            )
        )
    if not accepted:
        raise StateAdvanceError(
            f"human-input source is invalid for {transaction} sealing",
            json_path="$.human_input.source_kind",
            validator="human_input_authority",
        )


def _validate_human_input_routing_effects(
    *,
    update_sets: Iterable[Mapping[str, Any]],
    removal_sets: Iterable[Iterable[str]],
) -> None:
    for updates in update_sets:
        forbidden = set(updates) & _HUMAN_INPUT_PAIR_AUTHORITY_KEYS
        if forbidden:
            key = sorted(forbidden)[0]
            raise StateAdvanceError(
                "human-input advance effects cannot write decision authority",
                json_path=f"$.{key}",
                validator="human_input_authority",
            )
    for removals in removal_sets:
        forbidden = set(removals) & _HUMAN_INPUT_PAIR_AUTHORITY_KEYS
        if forbidden:
            key = sorted(forbidden)[0]
            raise StateAdvanceError(
                "human-input advance effects cannot remove decision authority",
                json_path=f"$.{key}",
                validator="human_input_authority",
            )


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
        _ensure_directory_durable(self._squad_dir)
        _ensure_directory_durable(self._staging_dir)

    @property
    def squad_dir(self) -> Path:
        return self._squad_dir

    @property
    def staging_dir(self) -> Path:
        return self._staging_dir

    @contextmanager
    def _lock(self, *, exclusive: bool) -> Iterator[None]:
        with controller_lock_order(
            "state",
            str(self._lock_path.absolute()),
        ):
            descriptor = -1
            directory_fd = -1
            named_locked = False
            directory_locked = False
            created = False
            body_exception = False
            operation = (
                fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            )
            create_flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            open_flags = (
                os.O_RDWR
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            try:
                # The directory inode is the stable authority.  Taking it
                # before opening the named lock prevents another conforming
                # writer from entering through a replacement state.lock.
                directory_fd = _open_real_directory(
                    self._squad_dir,
                    stage="confirm",
                )
                directory_identity = _identity(os.fstat(directory_fd))
                fcntl.flock(directory_fd, operation)
                directory_locked = True
                current_directory = os.lstat(self._squad_dir)
                if (
                    stat.S_ISLNK(current_directory.st_mode)
                    or not stat.S_ISDIR(current_directory.st_mode)
                    or _identity(current_directory) != directory_identity
                ):
                    raise StateDurabilityError(
                        "state directory identity changed",
                        stage="confirm",
                    )
                try:
                    descriptor = os.open(
                        self._lock_path,
                        create_flags,
                        0o600,
                    )
                    created = True
                except FileExistsError:
                    descriptor = os.open(
                        self._lock_path,
                        open_flags,
                    )
                opened = os.fstat(descriptor)
                named = os.lstat(self._lock_path)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or stat.S_ISLNK(named.st_mode)
                    or not stat.S_ISREG(named.st_mode)
                    or _identity(opened) != _identity(named)
                ):
                    raise StateDurabilityError(
                        "state lock identity changed",
                        stage="confirm",
                    )
                if created:
                    _fsync_retry(descriptor)
                    _fsync_retry(directory_fd)
                fcntl.flock(descriptor, operation)
                named_locked = True
                locked_metadata = os.fstat(descriptor)
                current = os.lstat(self._lock_path)
                if (
                    not stat.S_ISREG(locked_metadata.st_mode)
                    or stat.S_ISLNK(current.st_mode)
                    or not stat.S_ISREG(current.st_mode)
                    or _identity(locked_metadata) != _identity(opened)
                    or _identity(current) != _identity(opened)
                ):
                    raise StateDurabilityError(
                        "state lock identity changed",
                        stage="confirm",
                    )
                try:
                    yield
                except BaseException:
                    body_exception = True
                    raise
                final_named = os.lstat(self._lock_path)
                if (
                    stat.S_ISLNK(final_named.st_mode)
                    or not stat.S_ISREG(final_named.st_mode)
                    or _identity(final_named) != _identity(opened)
                ):
                    raise StateDurabilityError(
                        "state lock identity changed",
                        stage="confirm",
                    )
            except StateDurabilityError:
                raise
            except OSError as exc:
                if body_exception:
                    raise
                raise StateDurabilityError(
                    "state lock is unavailable",
                    stage="confirm",
                ) from exc
            finally:
                if named_locked:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    except OSError:
                        pass
                if descriptor >= 0:
                    os.close(descriptor)
                if directory_locked:
                    try:
                        fcntl.flock(directory_fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                if directory_fd >= 0:
                    os.close(directory_fd)

    def _load_unlocked(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())

    def load(self) -> dict:
        with self._lock(exclusive=False):
            return self._load_unlocked()

    def _confirm_durable_state_unlocked(
        self,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        """Prove one exact state file and directory entry durable."""

        if type(expected) is not dict:
            raise StateDurabilityError(
                "expected state must be an object",
                stage="confirm",
            )
        expected_state = deepcopy(expected)
        flags = os.O_RDONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        state_fd = -1
        directory_fd = -1
        try:
            state_fd = os.open(self._path, flags)
            opened = os.fstat(state_fd)
            named = os.lstat(self._path)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or _identity(opened) != _identity(named)
                or opened.st_size > _MAX_STATE_BYTES
            ):
                raise StateDurabilityError(
                    "state file identity changed",
                    stage="confirm",
                )
            content = _read_regular_descriptor(
                state_fd,
                maximum=_MAX_STATE_BYTES,
            )
            after_read = os.fstat(state_fd)
            if (
                _identity(after_read) != _identity(opened)
                or after_read.st_size != opened.st_size
            ):
                raise StateDurabilityError(
                    "state file changed while read",
                    stage="confirm",
                )
            try:
                observed = json.loads(content.decode("utf-8"))
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                RecursionError,
            ) as exc:
                raise StateDurabilityError(
                    "state file is not valid JSON",
                    stage="confirm",
                ) from exc
            if type(observed) is not dict or observed != expected_state:
                raise StateDurabilityError(
                    "state postimage does not match",
                    stage="confirm",
                )

            _fsync_retry(state_fd)
            directory_fd = _open_real_directory(
                self._squad_dir,
                stage="confirm",
            )
            directory_before = os.fstat(directory_fd)
            _fsync_retry(directory_fd)

            final_opened = os.fstat(state_fd)
            final_named = os.lstat(self._path)
            directory_after = os.fstat(directory_fd)
            directory_named = os.lstat(self._squad_dir)
            if (
                not stat.S_ISREG(final_named.st_mode)
                or _identity(final_opened) != _identity(opened)
                or _identity(final_named) != _identity(opened)
                or final_opened.st_size != opened.st_size
                or _identity(directory_after)
                != _identity(directory_before)
                or not stat.S_ISDIR(directory_named.st_mode)
                or stat.S_ISLNK(directory_named.st_mode)
                or _identity(directory_named)
                != _identity(directory_after)
            ):
                raise StateDurabilityError(
                    "state durability identity changed",
                    stage="confirm",
                )
            final_content = _read_regular_descriptor(
                state_fd,
                maximum=_MAX_STATE_BYTES,
            )
            if final_content != content:
                raise StateDurabilityError(
                    "state file changed after synchronization",
                    stage="confirm",
                )
            return deepcopy(observed)
        except StateDurabilityError:
            raise
        except (OSError, ValueError) as exc:
            raise StateDurabilityError(
                "state durability confirmation failed",
                stage="confirm",
            ) from exc
        finally:
            if directory_fd >= 0:
                os.close(directory_fd)
            if state_fd >= 0:
                os.close(state_fd)

    def confirm_durable_state(
        self,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock(exclusive=True):
            return self._confirm_durable_state_unlocked(expected)

    def _save_unlocked(
        self,
        state: dict,
        *,
        allow_human_input_authority_update: bool = False,
    ) -> dict:
        next_state = deepcopy(state)
        previous_revision = 0
        current_state: dict[str, Any] = {}
        if self._path.exists():
            old_text = self._path.read_text()
            bak = self._path.with_suffix(".json.bak")
            try:
                bak.write_text(old_text)
            except OSError:
                logger.warning("Could not write .bak file: %s", bak)
            try:
                old_state = json.loads(old_text)
                if type(old_state) is dict:
                    current_state = old_state
                self._check_monotonics(old_state, next_state)
                old_revision = old_state.get("state_revision", 0)
                if type(old_revision) is int and old_revision >= 0:
                    previous_revision = old_revision
            except json.JSONDecodeError:
                pass

        _validate_human_input_authority_write(
            current_state,
            next_state,
            allow_update=allow_human_input_authority_update,
        )
        is_exact_postimage = (
            type(next_state.get("state_revision")) is int
            and next_state["state_revision"] == previous_revision + 1
            and type(next_state.get("updated_at")) is str
        )
        if not is_exact_postimage:
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
        replaced = False
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
                f.flush()
                _fsync_retry(f.fileno())
            os.replace(tmp, self._path)
            replaced = True
            directory_fd = _open_real_directory(
                self._squad_dir,
                stage="post_replace",
            )
            try:
                _fsync_retry(directory_fd)
            except OSError as exc:
                raise StateDurabilityError(
                    "state parent directory sync failed",
                    stage="post_replace",
                ) from exc
            finally:
                os.close(directory_fd)
        except Exception:
            if not replaced:
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

    def _save_exact_state_unlocked(
        self,
        before: dict[str, Any],
        desired: dict[str, Any],
        *,
        allow_human_input_authority_update: bool = False,
        json_path: str,
        error_message: str,
    ) -> dict[str, Any]:
        attempted = _prepare_exact_state_postimage(before, desired)
        try:
            if allow_human_input_authority_update:
                return self._save_unlocked(
                    attempted,
                    allow_human_input_authority_update=True,
                )
            return self._save_unlocked(attempted)
        except StateDurabilityError as exc:
            if exc.stage == "post_replace":
                raise
            cause: Exception = exc
        except Exception as exc:
            cause = exc

        observed = self._load_unlocked()
        if _state_matches_exact_save(attempted, observed):
            return self._confirm_durable_state_unlocked(attempted)
        raise StateAdvanceError(
            error_message,
            json_path=json_path,
            validator="save",
        ) from cause

    def _commit_human_input_state_unlocked(
        self,
        before: dict[str, Any],
        desired: dict[str, Any],
    ) -> dict[str, Any]:
        return self._save_exact_state_unlocked(
            before,
            desired,
            allow_human_input_authority_update=True,
            json_path="$.blocked_decision",
            error_message="atomic human-input state save failed",
        )

    def _seal_human_input_decision_unlocked(
        self,
        state: dict[str, Any],
        request: PreparedHumanInput,
        *,
        initial_status: str,
    ) -> dict[str, object]:
        if type(request) is not PreparedHumanInput or request.schema_version != 1:
            raise StateAdvanceError(
                "human-input sealing requires a prepared request",
                json_path="$.human_input",
                validator="type",
            )
        if initial_status not in {"pending", "awaiting_human"}:
            raise StateAdvanceError(
                "human-input initial status is invalid",
                json_path="$.blocked_decision.status",
                validator="human_input_authority",
            )
        revision = state.get("state_revision", 0)
        if type(revision) is not int or revision < 0:
            raise StateAdvanceError(
                "persisted state revision is invalid",
                json_path="$.state_revision",
                validator="type",
            )
        if request.source_state_revision != revision:
            raise StateAdvanceError(
                "human-input source state revision is stale",
                json_path="$.state_revision",
                validator="stale_state",
            )

        self._validate_human_input_replaceability_unlocked(state)

        autonomy_mode = state.get("autonomy_mode")
        if autonomy_mode not in AUTONOMY_MODES:
            raise StateAdvanceError(
                "persisted autonomy mode is invalid",
                json_path="$.autonomy_mode",
                validator="type",
            )
        options = [
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
                "recommended": option.recommended,
                "risk_level": option.risk_level,
                "next_phase": option.next_phase,
                "outcome": option.outcome,
            }
            for option in request.options
        ]
        decision = build_blocked_decision_v2(
            decision_id=f"dec-{secrets.token_hex(16)}",
            status=initial_status,
            source_kind=request.source_kind,
            producer_id=request.producer_id,
            source_phase=request.phase_id,
            reason_code=request.reason_code,
            classification=request.classification,
            question=request.question,
            options=options,
            recommended_answer=request.recommended_answer,
            risk_level=request.risk_level,
            resolution_handler=request.resolution_handler,
            autonomy_mode=str(autonomy_mode),
            source_state_revision=request.source_state_revision,
        )
        recovery = _human_input_recovery_for_decision(decision)
        if recovery is None:
            raise StateAdvanceError(
                "initial human-input decision requires recovery",
                json_path="$.recovery_instruction",
                validator="human_input_authority",
            )
        instruction = recovery.to_dict()
        validate_decision_recovery_pair(decision, instruction)
        state["status"] = "blocked"
        state["blocked_decision"] = decision
        state["recovery_instruction"] = instruction
        state["blocked_reason"] = request.reason_code
        state["escalation_question"] = request.question
        state["escalation_options"] = normalize_escalation_options(options)
        return decision

    @staticmethod
    def _validate_human_input_replaceability_unlocked(
        state: Mapping[str, Any],
    ) -> None:
        existing = state.get("blocked_decision")
        if _is_human_input_decision_v2(existing):
            validated_existing = validate_blocked_decision_v2(existing)
            validate_decision_recovery_pair(
                validated_existing,
                state.get("recovery_instruction"),
            )
            if (
                validated_existing["status"]
                in _ACTIVE_HUMAN_INPUT_DECISION_STATUSES
            ):
                raise StateAdvanceError(
                    "an unresolved human-input decision already exists",
                    json_path="$.blocked_decision",
                    validator="human_input_authority",
                )

    def set_human_input_decision(
        self,
        request: PreparedHumanInput,
        *,
        initial_status: Literal["pending", "awaiting_human"],
    ) -> dict[str, Any]:
        _validate_human_input_seal_path(
            request,
            transaction="setter",
        )
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            desired = deepcopy(before)
            self._seal_human_input_decision_unlocked(
                desired,
                request,
                initial_status=initial_status,
            )
            return self._commit_human_input_state_unlocked(before, desired)

    def _human_input_decision_for_cas_unlocked(
        self,
        state: dict[str, Any],
        decision_id: str,
        *,
        expected_state_revision: int,
        allowed_statuses: frozenset[str],
    ) -> dict[str, object]:
        revision = state.get("state_revision", 0)
        if (
            type(expected_state_revision) is not int
            or type(revision) is not int
            or revision != expected_state_revision
        ):
            raise StateAdvanceError(
                "human-input state revision changed",
                json_path="$.state_revision",
                validator="stale_state",
            )
        decision = state.get("blocked_decision")
        if not _is_human_input_decision_v2(decision):
            raise StateAdvanceError(
                "schema-v2 human-input decision is missing",
                json_path="$.blocked_decision",
                validator="human_input_authority",
            )
        validated = validate_blocked_decision_v2(decision)
        validate_decision_recovery_pair(
            validated,
            state.get("recovery_instruction"),
        )
        if validated["id"] != decision_id:
            raise StateAdvanceError(
                "human-input decision id does not match",
                json_path="$.blocked_decision.id",
                validator="stale_state",
            )
        if validated["status"] not in allowed_statuses:
            raise StateAdvanceError(
                "human-input decision status does not permit this transition",
                json_path="$.blocked_decision.status",
                validator="human_input_authority",
            )
        return validated

    def _replace_human_input_decision_unlocked(
        self,
        state: dict[str, Any],
        decision: Mapping[str, object],
    ) -> None:
        validated = validate_blocked_decision_v2(decision)
        recovery = _human_input_recovery_for_decision(validated)
        instruction = recovery.to_dict() if recovery is not None else None
        validate_decision_recovery_pair(validated, instruction)
        state["blocked_decision"] = validated
        if instruction is None:
            state.pop("recovery_instruction", None)
        else:
            state["recovery_instruction"] = instruction

    def claim_human_input_decision(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
    ) -> dict[str, Any]:
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._human_input_decision_for_cas_unlocked(
                before,
                decision_id,
                expected_state_revision=expected_state_revision,
                allowed_statuses=frozenset({"pending"}),
            )
            desired = deepcopy(before)
            resolving = {
                **decision,
                "status": "resolving",
                "attempts": int(decision["attempts"]) + 1,
            }
            self._replace_human_input_decision_unlocked(
                desired,
                resolving,
            )
            return self._commit_human_input_state_unlocked(before, desired)

    def recover_interrupted_human_input_decision(self) -> dict[str, Any]:
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            raw_decision = before.get("blocked_decision")
            if not _is_human_input_decision_v2(raw_decision):
                return deepcopy(before)
            decision = validate_blocked_decision_v2(raw_decision)
            validate_decision_recovery_pair(
                decision,
                before.get("recovery_instruction"),
            )
            if decision["status"] != "resolving":
                return deepcopy(before)
            desired = deepcopy(before)
            if int(decision["attempts"]) < 2:
                recovered = {
                    **decision,
                    "status": "pending",
                    "failure_code": None,
                }
            else:
                recovered = {
                    **decision,
                    "status": "failed",
                    "failure_code": "resolution_attempts_exhausted",
                }
                desired.pop("escalation_question", None)
            self._replace_human_input_decision_unlocked(
                desired,
                recovered,
            )
            return self._commit_human_input_state_unlocked(before, desired)

    def record_human_input_resolution_failure(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
        failure_code: str,
        token_usage_delta: int = 0,
    ) -> dict[str, Any]:
        if type(token_usage_delta) is not int or token_usage_delta < 0:
            raise StateAdvanceError(
                "human-input token usage delta is invalid",
                json_path="$.token_usage_delta",
                validator="type",
            )
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._human_input_decision_for_cas_unlocked(
                before,
                decision_id,
                expected_state_revision=expected_state_revision,
                allowed_statuses=frozenset({"resolving"}),
            )
            desired = deepcopy(before)
            exhausted = int(decision["attempts"]) >= 2
            failed = {
                **decision,
                "status": "failed" if exhausted else "pending",
                "failure_code": failure_code if exhausted else None,
            }
            if exhausted:
                desired.pop("escalation_question", None)
            desired["token_usage"] = (
                int(desired.get("token_usage") or 0) + token_usage_delta
            )
            self._replace_human_input_decision_unlocked(desired, failed)
            return self._commit_human_input_state_unlocked(before, desired)

    def apply_human_input_state_resolution(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
        resolution: HumanInputResolution,
        state_updates: Mapping[str, Any],
        state_removals: Iterable[str],
        token_usage_delta: int = 0,
    ) -> dict[str, Any]:
        if type(resolution) is not HumanInputResolution:
            raise StateAdvanceError(
                "human-input resolution is invalid",
                json_path="$.resolution",
                validator="type",
            )
        if type(token_usage_delta) is not int or token_usage_delta < 0:
            raise StateAdvanceError(
                "human-input token usage delta is invalid",
                json_path="$.token_usage_delta",
                validator="type",
            )
        if not isinstance(state_updates, Mapping):
            raise StateAdvanceError(
                "human-input state updates are invalid",
                json_path="$.state_updates",
                validator="type",
            )
        try:
            detached_updates = deepcopy(dict(state_updates))
        except Exception as exc:
            raise StateAdvanceError(
                "human-input state updates are invalid",
                json_path="$.state_updates",
                validator="type",
            ) from exc
        if not all(isinstance(key, str) for key in detached_updates):
            raise StateAdvanceError(
                "human-input state updates are invalid",
                json_path="$.state_updates",
                validator="type",
            )
        if isinstance(state_removals, (str, bytes)):
            raise StateAdvanceError(
                "human-input state removals are invalid",
                json_path="$.state_removals",
                validator="type",
            )
        try:
            removals = tuple(state_removals)
        except TypeError as exc:
            raise StateAdvanceError(
                "human-input state removals are invalid",
                json_path="$.state_removals",
                validator="type",
            ) from exc
        if not all(isinstance(key, str) and key for key in removals):
            raise StateAdvanceError(
                "human-input state removals are invalid",
                json_path="$.state_removals",
                validator="type",
            )
        forbidden = (
            set(detached_updates) | set(removals)
        ) & _HUMAN_INPUT_STATE_EFFECT_RESERVED_KEYS
        if forbidden:
            key = sorted(forbidden)[0]
            raise StateAdvanceError(
                "resolution effects cannot write human-input authority",
                json_path=f"$.{key}",
                validator="human_input_authority",
            )

        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._human_input_decision_for_cas_unlocked(
                before,
                decision_id,
                expected_state_revision=expected_state_revision,
                allowed_statuses=_ACTIVE_HUMAN_INPUT_DECISION_STATUSES,
            )
            resolved = validate_blocked_decision_v2(
                {
                    **decision,
                    "status": "resolved",
                    "selected_option_id": resolution.selected_option_id,
                    "answer_text": resolution.answer_text,
                    "resolved_by": resolution.resolved_by,
                    "failure_code": None,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            desired = deepcopy(before)
            for key in removals:
                desired.pop(key, None)
            for key in (
                "blocked_reason",
                "escalation_question",
                "escalation_options",
                "escalation_resolved",
            ):
                desired.pop(key, None)
            for key, value in detached_updates.items():
                if key == "status":
                    self._transition_status(desired, value)
                else:
                    desired[key] = value
            desired["token_usage"] = (
                int(desired.get("token_usage") or 0) + token_usage_delta
            )
            self._replace_human_input_decision_unlocked(desired, resolved)
            return self._commit_human_input_state_unlocked(before, desired)

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
        dispatch_id: str | None = None,
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
                dispatch_id=dispatch_id,
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
        *,
        human_input: PreparedHumanInput | None = None,
        human_input_initial_status: Literal[
            "pending",
            "awaiting_human",
        ]
        | None = None,
    ) -> AdvanceReceipt:
        if (human_input is None) != (human_input_initial_status is None):
            raise StateAdvanceError(
                "human-input request and initial status must be supplied together",
                json_path="$.human_input",
                validator="human_input_authority",
            )
        if human_input is not None:
            _validate_human_input_seal_path(
                human_input,
                transaction="advance",
                from_phase=from_phase,
            )
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
        if human_input is not None:
            _validate_human_input_routing_effects(
                update_sets=(
                    result["state_updates"],
                    queued_updates,
                    prepared.control_updates,
                    transaction_updates,
                ),
                removal_sets=(
                    prepared.state_removals,
                    transaction_removals,
                ),
            )

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
            if human_input is not None:
                self._validate_human_input_replaceability_unlocked(state)

            next_state = deepcopy(state)
            logger.debug(
                "squad advance %s → %s verdict=%s run_id=%s",
                from_phase,
                to_phase,
                result["verdict"],
                state.get("run_id", "?"),
            )
            completed_at = datetime.now(timezone.utc).isoformat()
            dispatch_id = decision.dispatch_id
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
            completion_marker = transaction_updates.get(
                PENDING_CONTROLLER_COMPLETION_KEY
            )
            if completion_marker is not None:
                next_state["last_dispatch"].update(
                    {
                        "post_dispatch_complete": False,
                        "completion_intent_sha256": (
                            completion_marker["intent_sha256"]
                        ),
                        "completion_origin": completion_marker["origin"],
                        "completion_publication_binding_sha256": (
                            completion_marker[
                                "publication_binding_sha256"
                            ]
                        ),
                    }
                )
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
            if human_input is None:
                next_state.pop("recovery_instruction", None)
            else:
                self._seal_human_input_decision_unlocked(
                    next_state,
                    human_input,
                    initial_status=str(human_input_initial_status),
                )

            saved_state = self._save_exact_state_unlocked(
                state,
                next_state,
                allow_human_input_authority_update=human_input is not None,
                json_path="$.state",
                error_message="atomic state save failed",
            )
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
            except StateDurabilityError:
                raise
            except Exception as exc:
                raise StateAdvanceError(
                    "atomic external publication marker save failed",
                    json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                    validator="save",
                ) from exc

    def begin_terminal_controller_completion(
        self,
        prepared: PreparedControllerCompletion,
        *,
        snapshot: RoutingStateSnapshot,
        state_updates: dict[str, object] | None = None,
    ) -> None:
        """Atomically install one terminal completion and its publication."""
        (
            completion_marker,
            intent,
            _,
            _,
            prefix_kind,
        ) = _validate_prepared_controller_completion(prepared)
        route = intent["route"]
        publication = intent["publication"]
        if (
            completion_marker["origin"] != "terminal"
            or prefix_kind != "bound"
            or type(route) is not dict
            or route.get("kind") != "terminal"
            or type(publication) is not dict
        ):
            raise StateAdvanceError(
                "terminal completion intent is invalid",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator="completion_binding",
            )
        if not isinstance(snapshot, RoutingStateSnapshot):
            raise StateAdvanceError(
                "terminal completion snapshot is invalid",
                json_path="$.routing_snapshot",
                validator="type",
            )
        updates = deepcopy(state_updates or {})
        if frozenset(updates) - {"published_spec_dir"}:
            raise StateAdvanceError(
                "terminal completion state update is not owned",
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
        publication_marker: dict[str, object] | None
        if publication.get("kind") == "external":
            try:
                publication_marker = validate_pending_external_publication(
                    publication.get("marker")
                )
            except ValueError as exc:
                raise StateAdvanceError(
                    "terminal publication binding is invalid",
                    json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                    validator="completion_binding",
                ) from exc
        elif publication == {"kind": "none"}:
            publication_marker = None
        else:
            raise StateAdvanceError(
                "terminal publication binding is invalid",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator="completion_binding",
            )

        with self._lock(exclusive=True):
            state = self._load_unlocked()
            revision = state.get("state_revision", 0)
            if (
                state.get("phase") != snapshot.phase
                or route.get("terminal_phase") != snapshot.phase
                or type(revision) is not int
                or revision != snapshot.state_revision
                or _last_dispatch_sha256(state)
                != snapshot.previous_dispatch_sha256
                or PENDING_CONTROLLER_COMPLETION_KEY in state
                or PENDING_EXTERNAL_PUBLICATION_KEY in state
            ):
                raise StateAdvanceError(
                    "persisted state changed before terminal completion",
                    json_path="$.routing_snapshot",
                    validator="stale_state",
                )
            desired = deepcopy(state)
            desired.update(updates)
            desired[PENDING_CONTROLLER_COMPLETION_KEY] = (
                completion_marker
            )
            if publication_marker is not None:
                desired[PENDING_EXTERNAL_PUBLICATION_KEY] = (
                    publication_marker
                )
            self._save_exact_completion_state_unlocked(
                state,
                desired,
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            )

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
                except ValueError:
                    resume_status = state.get("status", "running")
                    resume_blocked_reason = state.get("blocked_reason")
                    if (
                        resume_status == "blocked"
                        and resume_blocked_reason
                        == "external_publication_pending"
                    ):
                        resume_status = "running"
                        resume_blocked_reason = None
                    if type(resume_status) is not str:
                        resume_status = "running"
                    if (
                        resume_blocked_reason is not None
                        and type(resume_blocked_reason) is not str
                    ):
                        resume_blocked_reason = None
                    diagnostic = _validate_external_publication_failure(
                        {
                            "schema_version": 1,
                            "code": code,
                            "resume_status": resume_status,
                            "resume_blocked_reason": (
                                resume_blocked_reason
                            ),
                        }
                    )
                else:
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

    def record_malformed_external_publication_failure(
        self,
        marker: object,
    ) -> None:
        """Block on one exact malformed marker without accepting it as valid."""
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            if (
                PENDING_EXTERNAL_PUBLICATION_KEY not in state
                or state[PENDING_EXTERNAL_PUBLICATION_KEY] != marker
            ):
                raise StateAdvanceError(
                    "malformed external publication marker changed",
                    json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                    validator="stale_state",
                )
            try:
                validate_pending_external_publication(
                    state[PENDING_EXTERNAL_PUBLICATION_KEY]
                )
            except ValueError:
                pass
            else:
                raise StateAdvanceError(
                    "external publication marker is not malformed",
                    json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                    validator="state_contract",
                )
            if _EXTERNAL_PUBLICATION_FAILURE_KEY in state:
                try:
                    diagnostic = _validate_external_publication_failure(
                        state[_EXTERNAL_PUBLICATION_FAILURE_KEY]
                    )
                except ValueError:
                    resume_status = state.get("status", "running")
                    resume_blocked_reason = state.get("blocked_reason")
                    if (
                        resume_status == "blocked"
                        and resume_blocked_reason
                        == "external_publication_pending"
                    ):
                        resume_status = "running"
                        resume_blocked_reason = None
                    if type(resume_status) is not str:
                        resume_status = "running"
                    if (
                        resume_blocked_reason is not None
                        and type(resume_blocked_reason) is not str
                    ):
                        resume_blocked_reason = None
                    diagnostic = _validate_external_publication_failure(
                        {
                            "schema_version": 1,
                            "code": "manifest_invalid",
                            "resume_status": resume_status,
                            "resume_blocked_reason": (
                                resume_blocked_reason
                            ),
                        }
                    )
                else:
                    diagnostic["code"] = "manifest_invalid"
            else:
                diagnostic = _validate_external_publication_failure(
                    {
                        "schema_version": 1,
                        "code": "manifest_invalid",
                        "resume_status": state.get("status", "running"),
                        "resume_blocked_reason": state.get("blocked_reason"),
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
            if PENDING_CONTROLLER_COMPLETION_KEY in state:
                raise StateAdvanceError(
                    "coupled publication requires completion handoff",
                    json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                    validator="completion_binding",
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

    def _save_exact_completion_state_unlocked(
        self,
        before: dict[str, Any],
        desired: dict[str, Any],
        *,
        json_path: str,
    ) -> dict[str, Any]:
        return self._save_exact_state_unlocked(
            before,
            desired,
            json_path=json_path,
            error_message="atomic controller completion state save failed",
        )

    @staticmethod
    def _require_controller_completion_marker(
        state: dict[str, Any],
        expected_marker: dict[str, object],
    ) -> None:
        if PENDING_CONTROLLER_COMPLETION_KEY not in state:
            raise StateAdvanceError(
                "controller completion marker is missing",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator="stale_state",
            )
        try:
            current_marker = validate_pending_controller_completion(
                state[PENDING_CONTROLLER_COMPLETION_KEY]
            )
        except ValueError as exc:
            raise StateAdvanceError(
                "persisted controller completion marker is invalid",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator="state_contract",
            ) from exc
        if current_marker != expected_marker:
            raise StateAdvanceError(
                "controller completion marker changed",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator="stale_state",
            )

    @staticmethod
    def _require_controller_completion_provenance(
        state: dict[str, Any],
        marker: dict[str, object],
        intent: dict[str, object],
    ) -> None:
        route = intent["route"]
        if marker["origin"] == "terminal":
            if (
                type(route) is not dict
                or frozenset(dict.keys(route))
                != frozenset({"kind", "terminal_phase"})
                or route["kind"] != "terminal"
                or type(route["terminal_phase"]) is not str
                or not route["terminal_phase"]
                or state.get("phase") != route["terminal_phase"]
            ):
                raise StateAdvanceError(
                    "terminal completion provenance changed",
                    json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                    validator="completion_binding",
                )
            return
        if (
            type(route) is not dict
            or frozenset(dict.keys(route))
            != frozenset(
                {
                    "kind",
                    "from_phase",
                    "to_phase",
                    "manual_phase_run",
                    "record_completion",
                }
            )
            or route["kind"] != "routed"
            or type(route["from_phase"]) is not str
            or not route["from_phase"]
            or type(route["to_phase"]) is not str
            or not route["to_phase"]
            or type(route["manual_phase_run"]) is not bool
            or type(route["record_completion"]) is not bool
            or state.get("phase") != route["to_phase"]
        ):
            raise StateAdvanceError(
                "routed completion provenance changed",
                json_path="$.last_dispatch",
                validator="completion_binding",
            )
        dispatch = state.get("last_dispatch")
        if (
            type(dispatch) is not dict
            or dispatch.get("dispatch_id") != marker["completion_id"]
            or dispatch.get("phase_id") != route["from_phase"]
            or dispatch.get("next_phase") != route["to_phase"]
            or dispatch.get("post_dispatch_complete") is not False
            or dispatch.get("completion_intent_sha256")
            != marker["intent_sha256"]
            or dispatch.get("completion_origin") != "routed"
            or dispatch.get(
                "completion_publication_binding_sha256"
            )
            != marker["publication_binding_sha256"]
            or dispatch.get("record_completion")
            is not route["record_completion"]
            or dispatch.get("manual_phase_run", False)
            is not route["manual_phase_run"]
            or type(dispatch.get("judgment_payload_sha256")) is not list
            or dispatch.get("judgment_payload_sha256")
            != intent["judgment_payload_sha256"]
        ):
            raise StateAdvanceError(
                "routed completion dispatch binding changed",
                json_path="$.last_dispatch",
                validator="completion_binding",
            )

    @staticmethod
    def _restore_failure_lifecycle(
        state: dict[str, Any],
        *,
        diagnostic_key: str,
    ) -> None:
        if diagnostic_key not in state:
            return
        if diagnostic_key == _EXTERNAL_PUBLICATION_FAILURE_KEY:
            validator = _validate_external_publication_failure
        elif diagnostic_key == _CONTROLLER_COMPLETION_FAILURE_KEY:
            validator = _validate_controller_completion_failure
        else:  # pragma: no cover - internal programming error
            raise AssertionError("unknown failure lifecycle")
        try:
            diagnostic = validator(state[diagnostic_key])
        except ValueError as exc:
            raise StateAdvanceError(
                "persisted completion diagnostic is invalid",
                json_path=f"$.{diagnostic_key}",
                validator="state_contract",
            ) from exc
        state["status"] = diagnostic["resume_status"]
        blocked_reason = diagnostic["resume_blocked_reason"]
        if blocked_reason is None:
            state.pop("blocked_reason", None)
        else:
            state["blocked_reason"] = blocked_reason

    def handoff_external_publication(
        self,
        publication_marker: object,
        prepared: PreparedControllerCompletion,
    ) -> None:
        try:
            expected_publication = validate_pending_external_publication(
                publication_marker
            )
        except ValueError as exc:
            raise StateAdvanceError(
                "external publication marker is invalid",
                json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                validator="type",
            ) from exc
        (
            expected_completion,
            intent,
            _,
            _,
            prefix_kind,
        ) = _validate_prepared_controller_completion(prepared)
        publication = intent["publication"]
        if (
            expected_completion["step"] != "awaiting_publication"
            or prefix_kind != "bound"
            or type(publication) is not dict
            or frozenset(dict.keys(publication))
            != frozenset({"kind", "marker"})
            or publication["kind"] != "external"
            or publication["marker"] != expected_publication
        ):
            raise StateAdvanceError(
                "publication handoff is not bound to this completion",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator="completion_binding",
            )
        effect_plan = intent["effect_plan"]
        next_step = effect_plan[0] if effect_plan else "complete"
        next_marker = {
            **expected_completion,
            "step": next_step,
        }
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            self._require_external_publication_marker(
                state,
                expected_publication,
            )
            self._require_controller_completion_marker(
                state,
                expected_completion,
            )
            self._require_controller_completion_provenance(
                state,
                expected_completion,
                intent,
            )
            desired = deepcopy(state)
            self._restore_failure_lifecycle(
                desired,
                diagnostic_key=_EXTERNAL_PUBLICATION_FAILURE_KEY,
            )
            desired.pop(PENDING_EXTERNAL_PUBLICATION_KEY, None)
            desired.pop(_EXTERNAL_PUBLICATION_FAILURE_KEY, None)
            desired[PENDING_CONTROLLER_COMPLETION_KEY] = next_marker
            if _CONTROLLER_COMPLETION_FAILURE_KEY in desired:
                try:
                    _validate_controller_completion_failure(
                        desired[_CONTROLLER_COMPLETION_FAILURE_KEY]
                    )
                except ValueError as exc:
                    raise StateAdvanceError(
                        "persisted completion diagnostic is invalid",
                        json_path=(
                            f"$.{_CONTROLLER_COMPLETION_FAILURE_KEY}"
                        ),
                        validator="state_contract",
                    ) from exc
                desired["status"] = "blocked"
                desired["blocked_reason"] = (
                    "controller_completion_pending"
                )
            self._save_exact_completion_state_unlocked(
                state,
                desired,
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            )

    def advance_controller_completion(
        self,
        prepared: PreparedControllerCompletion,
    ) -> None:
        (
            expected_marker,
            intent,
            _,
            receipts_sha256,
            prefix_kind,
        ) = _validate_prepared_controller_completion(prepared)
        effect_plan = intent["effect_plan"]
        current_step = expected_marker["step"]
        if (
            current_step not in effect_plan
            or prefix_kind != "one_ahead"
        ):
            raise StateAdvanceError(
                "controller completion effect has no exact receipt",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.step",
                validator="completion_step",
            )
        current_index = effect_plan.index(current_step)
        next_step = (
            effect_plan[current_index + 1]
            if current_index + 1 < len(effect_plan)
            else "complete"
        )
        next_marker = {
            **expected_marker,
            "receipts_sha256": receipts_sha256,
            "step": next_step,
        }
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            self._require_controller_completion_marker(
                state,
                expected_marker,
            )
            self._require_controller_completion_provenance(
                state,
                expected_marker,
                intent,
            )
            desired = deepcopy(state)
            desired[PENDING_CONTROLLER_COMPLETION_KEY] = next_marker
            self._save_exact_completion_state_unlocked(
                state,
                desired,
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            )

    def record_controller_completion_failure(
        self,
        marker: object,
        code: object,
    ) -> None:
        if (
            type(code) is not str
            or code not in _CONTROLLER_COMPLETION_FAILURE_CODES
        ):
            raise StateAdvanceError(
                "controller completion failure code is invalid",
                json_path=f"$.{_CONTROLLER_COMPLETION_FAILURE_KEY}.code",
                validator="enum",
            )
        try:
            marker_bytes, _ = _canonical_completion_document(marker)
            expected_raw_marker = json.loads(marker_bytes)
        except (StateAdvanceError, json.JSONDecodeError) as exc:
            raise StateAdvanceError(
                "controller completion raw marker is invalid",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator="type",
            ) from exc
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            if code == "completion_missing":
                if (
                    expected_raw_marker is not None
                    or PENDING_CONTROLLER_COMPLETION_KEY in state
                    or PENDING_EXTERNAL_PUBLICATION_KEY not in state
                ):
                    raise StateAdvanceError(
                        "missing completion authority changed",
                        json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                        validator="stale_state",
                    )
            elif (
                PENDING_CONTROLLER_COMPLETION_KEY not in state
                or state[PENDING_CONTROLLER_COMPLETION_KEY]
                != expected_raw_marker
            ):
                raise StateAdvanceError(
                    "controller completion marker changed",
                    json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                    validator="stale_state",
                )
            existing = state.get(_CONTROLLER_COMPLETION_FAILURE_KEY)
            try:
                diagnostic = _validate_controller_completion_failure(
                    existing
                )
            except ValueError:
                status = state.get("status", "running")
                blocked_reason = state.get("blocked_reason")
                if (
                    status == "blocked"
                    and blocked_reason == "external_publication_pending"
                    and _EXTERNAL_PUBLICATION_FAILURE_KEY in state
                ):
                    try:
                        publication_diagnostic = (
                            _validate_external_publication_failure(
                                state[
                                    _EXTERNAL_PUBLICATION_FAILURE_KEY
                                ]
                            )
                        )
                    except ValueError:
                        status = "running"
                        blocked_reason = None
                    else:
                        status = publication_diagnostic["resume_status"]
                        blocked_reason = publication_diagnostic[
                            "resume_blocked_reason"
                        ]
                elif (
                    status == "blocked"
                    and blocked_reason == "controller_completion_pending"
                ):
                    status = "running"
                    blocked_reason = None
                if status not in VALID_SQUAD_TRANSITIONS:
                    status = "running"
                    blocked_reason = None
                if (
                    blocked_reason is not None
                    and (
                        type(blocked_reason) is not str
                        or len(blocked_reason) > 4_096
                    )
                ):
                    blocked_reason = None
                diagnostic = {
                    "schema_version": 1,
                    "code": code,
                    "resume_status": status,
                    "resume_blocked_reason": blocked_reason,
                }
            else:
                diagnostic["code"] = code
            diagnostic = _validate_controller_completion_failure(
                diagnostic
            )
            desired = deepcopy(state)
            desired[_CONTROLLER_COMPLETION_FAILURE_KEY] = diagnostic
            desired["status"] = "blocked"
            desired["blocked_reason"] = "controller_completion_pending"
            self._save_exact_completion_state_unlocked(
                state,
                desired,
                json_path=f"$.{_CONTROLLER_COMPLETION_FAILURE_KEY}",
            )

    def complete_controller_completion(
        self,
        prepared: PreparedControllerCompletion,
        *,
        phase_a_active_source_sha256: str | None = None,
        phase_a_published_postimage_sha256: str | None = None,
    ) -> None:
        (
            expected_marker,
            intent,
            _,
            receipts_sha256,
            prefix_kind,
        ) = _validate_prepared_controller_completion(prepared)
        if (
            expected_marker["step"] != "complete"
            or prefix_kind != "bound"
            or receipts_sha256 != expected_marker["receipts_sha256"]
        ):
            raise StateAdvanceError(
                "controller completion is not ready to finalize",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}.step",
                validator="completion_step",
            )
        has_active_digest = phase_a_active_source_sha256 is not None
        has_published_digest = (
            phase_a_published_postimage_sha256 is not None
        )
        if (
            has_active_digest != has_published_digest
            or (
                has_active_digest
                and (
                    not _valid_completion_sha256(
                        phase_a_active_source_sha256
                    )
                    or not _valid_completion_sha256(
                        phase_a_published_postimage_sha256
                    )
                )
            )
        ):
            raise StateAdvanceError(
                "Phase A completion inventory digests are invalid",
                json_path="$.phase_a_active_source_sha256",
                validator="type",
            )
        route = intent["route"]
        is_phase4_completion = (
            expected_marker["origin"] == "routed"
            and route["from_phase"] == "phase4-document"
        )
        if (
            (is_phase4_completion and not has_active_digest)
            or (
                expected_marker["origin"] == "routed"
                and not is_phase4_completion
                and has_active_digest
            )
        ):
            raise StateAdvanceError(
                "Phase A inventory digests do not match completion origin",
                json_path="$.phase_a_active_source_sha256",
                validator="completion_binding",
            )
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            self._require_controller_completion_marker(
                state,
                expected_marker,
            )
            self._require_controller_completion_provenance(
                state,
                expected_marker,
                intent,
            )
            desired = deepcopy(state)
            if expected_marker["origin"] == "routed":
                self._restore_failure_lifecycle(
                    desired,
                    diagnostic_key=_CONTROLLER_COMPLETION_FAILURE_KEY,
                )
                dispatch = desired["last_dispatch"]
                dispatch.update(
                    {
                        "post_dispatch_complete": True,
                        "completion_intent_sha256": (
                            expected_marker["intent_sha256"]
                        ),
                        "completion_receipts_sha256": receipts_sha256,
                        "completed_publication_binding_sha256": (
                            expected_marker[
                                "publication_binding_sha256"
                            ]
                        ),
                    }
                )
                if has_active_digest:
                    desired["phase_a_active_source_sha256"] = (
                        phase_a_active_source_sha256
                    )
                    desired[
                        "phase_a_published_postimage_sha256"
                    ] = phase_a_published_postimage_sha256
            else:
                desired["status"] = "done"
                desired.pop("blocked_reason", None)
                terminal_receipt = {
                    "schema_version": 1,
                    "completion_id": expected_marker["completion_id"],
                    "intent_sha256": expected_marker["intent_sha256"],
                    "receipts_sha256": receipts_sha256,
                    "publication_binding_sha256": (
                        expected_marker[
                            "publication_binding_sha256"
                        ]
                    ),
                    "terminal_phase": route["terminal_phase"],
                }
                if has_active_digest:
                    terminal_receipt.update(
                        {
                            "phase_a_active_source_sha256": (
                                phase_a_active_source_sha256
                            ),
                            "phase_a_published_postimage_sha256": (
                                phase_a_published_postimage_sha256
                            ),
                        }
                    )
                desired["last_terminal_completion"] = terminal_receipt
            desired.pop(PENDING_CONTROLLER_COMPLETION_KEY, None)
            desired.pop(_CONTROLLER_COMPLETION_FAILURE_KEY, None)
            self._save_exact_completion_state_unlocked(
                state,
                desired,
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            )

    def set_blocked(self, reason: str) -> None:
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            logger.debug(
                "squad blocked run_id=%s reason=%r",
                state.get("run_id", "?"),
                reason,
            )
            self._transition_status(state, "blocked")
            state["blocked_reason"] = reason
            self._save_unlocked(state)

    def set_cancel_requested(self) -> None:
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            state["cancel_requested"] = True
            self._save_unlocked(state)

    def is_cancel_requested(self) -> bool:
        return bool(self.load().get("cancel_requested", False))

    def token_usage(self) -> int:
        return int(self.load().get("token_usage", 0))

    def increment_token_usage(self, tokens: int) -> None:
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            state["token_usage"] = state.get("token_usage", 0) + tokens
            self._save_unlocked(state)

    def increment_why_fail_count(self) -> int:
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            count = state.get("why_fail_count", 0) + 1
            state["why_fail_count"] = count
            self._save_unlocked(state)
            return int(count)

    def reset_why_fail_count(self) -> None:
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            state["why_fail_count"] = 0
            self._save_unlocked(state)

    def increment_phase_dispatch_count(self, phase: str) -> int:
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            counts = state.get("phase_dispatch_counts") or {}
            counts[phase] = counts.get(phase, 0) + 1
            state["phase_dispatch_counts"] = counts
            self._save_unlocked(state)
            return int(counts[phase])

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
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            count = state.get("convergence_guard_fire_count", 0) + 1
            state["convergence_guard_fire_count"] = count
            self._save_unlocked(state)
            return int(count)

    def reset_convergence_guard_fires(self) -> None:
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            state["convergence_guard_fire_count"] = 0
            self._save_unlocked(state)

    def increment_cost(self, amount: float) -> None:
        if not amount:
            return
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            state["cost_usd"] = round(
                state.get("cost_usd", 0.0) + amount,
                6,
            )
            self._save_unlocked(state)

    def token_budget(self) -> int:
        return int(self.load().get("token_budget", 0))
