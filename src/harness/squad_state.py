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
from typing import Any, Callable, Iterable, Iterator, Literal, Mapping

from harness.blocked_decision import (
    BlockedDecisionError,
    build_blocked_decision_v3,
    ensure_blocked_decision,
    normalize_escalation_options,
    validate_blocked_decision,
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
from harness.human_input import AppliedHumanInputResolution, PreparedHumanInput
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
    PRODUCT_INPUT_MUTATION_KEY,
    PROVIDER_CONTROL_INTENT_KEYS,
    require_product_input_mutation_publication_binding,
    store_owned_update_keys,
    validate_pending_controller_completion,
    validate_pending_external_publication,
    validate_product_input_mutation,
)
from harness.proportional_quality import initialize_repair_state
from echelon.spec_authoring import normalize_spec_authoring_mode
from echelon.strict_json import loads_strict_json

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
    "quality",
    "context",
    "mining",
    "retarget",
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
    {
        "consecutive_why_fails",
        "why2_metric_stagnation",
        "proportional_quality_budget_exhausted",
        "proportional_quality_extension_exhausted",
    }
)
_SETTER_SAFEGUARD_PRODUCERS = frozenset(
    {
        "phase_dispatch_limit",
        "agent_blocked",
    }
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
    current_intent_keys = frozenset(
        {
            "schema_version",
            "completion_id",
            "origin",
            "publication",
            "route",
            "effect_plan",
            "checkpoint_prestate",
            "quality_effect",
            "context_reason",
            "mine_phase_a",
            "judgment_payload_sha256",
            "judgments",
        }
    )
    legacy_intent_keys = current_intent_keys - {"quality_effect"}
    intent_keys = frozenset(dict.keys(intent)) if type(intent) is dict else frozenset()
    if (
        type(intent) is not dict
        or intent_keys not in {current_intent_keys, legacy_intent_keys}
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
    if intent_keys == legacy_intent_keys and "quality" in plan:
        raise StateAdvanceError(
            "legacy controller completion cannot contain a quality effect",
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


_QUALITY_DEBT_EFFECT_POSTIMAGE_KEYS = frozenset(
    {
        "operation",
        "debt_path",
        "debt",
        "authorization",
        "previous_debt_artifact_sha256",
    }
)
_QUALITY_DEBT_AUTHORIZATION_POSTIMAGE_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "source_path",
        "source_sha256",
        "understanding_evidence",
        "understanding_evidence_sha256",
        "candidate_manifest",
        "candidate_manifest_sha256",
        "debt_artifact",
        "debt_artifact_sha256",
        "selected_candidate_id",
        "failed_gates",
        "qualitative_debt",
        "decision_id",
        "resolved_by",
        "accepted_at",
        "resolved_decision",
        "resolved_decision_sha256",
        "understanding_state_sha256",
        "candidate_evidence_state_sha256",
        "resolution_completion",
        "previous_debt_artifact_sha256",
    }
)
_QUALITY_DEBT_ARTIFACT_POSTIMAGE_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "source_path",
        "source_sha256",
        "understanding_evidence",
        "understanding_evidence_sha256",
        "candidate_manifest",
        "candidate_manifest_sha256",
        "selected_candidate_id",
        "failed_gates",
        "qualitative_debt",
        "repair_accounting",
        "selection_rationale",
        "decision_id",
        "resolved_by",
        "accepted_at",
        "resolved_decision",
        "resolved_decision_sha256",
        "understanding_state_sha256",
        "candidate_evidence_state_sha256",
        "resolution_completion",
        "previous_debt_artifact_sha256",
    }
)
_QUALITY_DEBT_SHARED_POSTIMAGE_KEYS = (
    _QUALITY_DEBT_AUTHORIZATION_POSTIMAGE_KEYS
    - {"debt_artifact", "debt_artifact_sha256"}
)


def _validate_quality_debt_resolution_postimage(
    resolved: Mapping[str, object],
    updates: Mapping[str, Any],
    completion_intent: Mapping[str, object],
) -> None:
    """Require one canonical debt decision across state and staged effect."""
    if set(updates) != {"spec_quality_debt_authorization"}:
        raise StateAdvanceError(
            "quality-debt resolution postimage updates are invalid",
            json_path="$.spec_quality_debt_authorization",
            validator="resolution_postimage",
        )
    authorization = updates.get("spec_quality_debt_authorization")
    quality_effect = completion_intent.get("quality_effect")
    payload = (
        quality_effect.get("payload")
        if isinstance(quality_effect, Mapping)
        else None
    )
    debt = payload.get("debt") if isinstance(payload, Mapping) else None
    effect_authorization = (
        payload.get("authorization")
        if isinstance(payload, Mapping)
        else None
    )
    if (
        not isinstance(authorization, Mapping)
        or not isinstance(debt, Mapping)
        or not isinstance(effect_authorization, Mapping)
        or not isinstance(quality_effect, Mapping)
        or set(quality_effect) != {"kind", "operation", "payload"}
        or not isinstance(payload, Mapping)
        or set(payload) != _QUALITY_DEBT_EFFECT_POSTIMAGE_KEYS
        or set(authorization)
        != _QUALITY_DEBT_AUTHORIZATION_POSTIMAGE_KEYS
        or set(effect_authorization)
        != _QUALITY_DEBT_AUTHORIZATION_POSTIMAGE_KEYS
        or set(debt) != _QUALITY_DEBT_ARTIFACT_POSTIMAGE_KEYS
        or authorization.get("schema_version") != 1
        or debt.get("schema_version") != 1
        or quality_effect.get("kind") != "proportional_quality"
        or quality_effect.get("operation") != "debt_write"
        or payload.get("operation") != "debt_write"
        or payload.get("debt_path")
        != authorization.get("debt_artifact")
        or payload.get("previous_debt_artifact_sha256")
        != authorization.get("previous_debt_artifact_sha256")
        or dict(effect_authorization) != dict(authorization)
        or authorization.get("resolved_decision") != dict(resolved)
        or debt.get("resolved_decision") != dict(resolved)
        or authorization.get("resolved_decision_sha256")
        != debt.get("resolved_decision_sha256")
        or authorization.get("decision_id") != resolved.get("id")
        or authorization.get("resolved_by") != resolved.get("resolved_by")
    ):
        raise StateAdvanceError(
            "quality-debt resolved postimage diverged",
            json_path="$.spec_quality_debt_authorization.resolved_decision",
            validator="resolution_postimage",
        )
    if any(
        debt.get(key) != authorization.get(key)
        for key in _QUALITY_DEBT_SHARED_POSTIMAGE_KEYS
    ):
        raise StateAdvanceError(
            "quality-debt authorization and artifact postimages diverged",
            json_path="$.spec_quality_debt_authorization",
            validator="resolution_postimage",
        )
    route = completion_intent.get("route")
    expected_completion = {
        "schema_version": 1,
        "completion_id": completion_intent.get("completion_id"),
        "from_phase": (
            route.get("from_phase") if isinstance(route, Mapping) else None
        ),
        "to_phase": (
            route.get("to_phase") if isinstance(route, Mapping) else None
        ),
    }
    if authorization.get("resolution_completion") != expected_completion:
        raise StateAdvanceError(
            "quality-debt completion postimage diverged",
            json_path=(
                "$.spec_quality_debt_authorization.resolution_completion"
            ),
            validator="resolution_postimage",
        )
    _, resolved_digest = _canonical_completion_document(dict(resolved))
    if authorization.get("resolved_decision_sha256") != resolved_digest:
        raise StateAdvanceError(
            "quality-debt resolved postimage digest changed",
            json_path=(
                "$.spec_quality_debt_authorization."
                "resolved_decision_sha256"
            ),
            validator="resolution_postimage",
        )
    try:
        debt_content = (
            json.dumps(dict(debt), indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise StateAdvanceError(
            "quality-debt artifact postimage is invalid",
            json_path="$.spec_quality_debt_authorization",
            validator="resolution_postimage",
        ) from exc
    if hashlib.sha256(debt_content).hexdigest() != authorization.get(
        "debt_artifact_sha256"
    ):
        raise StateAdvanceError(
            "quality-debt artifact postimage digest changed",
            json_path="$.spec_quality_debt_authorization.debt_artifact_sha256",
            validator="resolution_postimage",
        )


def _is_human_input_decision(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and type(value.get("schema_version")) is int
        and value.get("schema_version") in {2, 3}
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
    current_is_authority = _is_human_input_decision(current_decision)
    candidate_is_authority = _is_human_input_decision(candidate_decision)

    if candidate_is_authority:
        try:
            validate_decision_recovery_pair(
                candidate_decision,
                candidate.get("recovery_instruction"),
            )
        except BlockedDecisionError as exc:
            raise StateAdvanceError(
                f"invalid versioned decision authority: {exc}",
                json_path="$.blocked_decision",
                validator="human_input_authority",
            ) from exc
        except RecoveryInstructionError as exc:
            raise StateAdvanceError(
                f"invalid versioned recovery authority: {exc}",
                json_path="$.recovery_instruction",
                validator="human_input_authority",
            ) from exc
    if allow_update:
        return
    if current_is_authority != candidate_is_authority:
        raise StateAdvanceError(
            "generic state writes cannot create or clear versioned decision authority",
            json_path="$.blocked_decision",
            validator="human_input_authority",
        )
    if not current_is_authority:
        return
    if current_decision != candidate_decision:
        raise StateAdvanceError(
            "generic state writes cannot replace versioned decision authority",
            json_path="$.blocked_decision",
            validator="human_input_authority",
        )
    if current.get("recovery_instruction") != candidate.get(
        "recovery_instruction"
    ):
        raise StateAdvanceError(
            "generic state writes cannot mutate versioned recovery authority",
            json_path="$.recovery_instruction",
            validator="human_input_authority",
        )
    validated = validate_blocked_decision(current_decision)
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


def _canonicalize_resolved_human_input_audit_for_diagnostic(
    state: dict[str, Any],
) -> bool:
    decision = state.get("blocked_decision")
    if not (
        _is_human_input_decision(decision)
        and decision.get("status") == "resolved"
    ):
        return False
    instruction = state.get("recovery_instruction")
    if instruction is None:
        return False
    if (
        isinstance(instruction, Mapping)
        and instruction.get("schema_version") == 2
        and instruction.get("decision_id") == decision.get("id")
    ):
        state.pop("recovery_instruction", None)
        return True

    state.pop("blocked_decision", None)
    for key in _HUMAN_INPUT_DISPLAY_AUTHORITY_KEYS:
        state.pop(key, None)
    return True


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
    if type(request) is not PreparedHumanInput or request.schema_version != 2:
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
        source_matches = request.phase_id == from_phase or (
            request.source_kind == "controller_safeguard"
            and request.producer_id
            == "proportional_quality_budget_exhausted"
            and from_phase == "phase1-what"
            and request.phase_id == "phase1-why2"
        )
        if not source_matches:
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
                and request.producer_id in _SETTER_SAFEGUARD_PRODUCERS
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
    mutation_value = verified.transaction_state_updates.get(
        PRODUCT_INPUT_MUTATION_KEY
    )
    product_inputs_update = verified.transaction_state_updates.get(
        "product_inputs"
    )
    if mutation_value is not None:
        try:
            mutation = require_product_input_mutation_publication_binding(
                mutation_value,
                verified.transaction_state_updates.get(
                    PENDING_EXTERNAL_PUBLICATION_KEY
                ),
            )
        except ValueError as exc:
            raise _prepared_result_error(
                "product input mutation receipt is invalid",
                json_path=(
                    "$.transaction_state_updates."
                    f"{PRODUCT_INPUT_MUTATION_KEY}"
                ),
                validator="type",
            ) from exc
        if (
            type(product_inputs_update) is not dict
            or product_inputs_update.get("tree_hash")
            != mutation["new_tree_hash"]
            or product_inputs_update.get("inputs_dir")
            != mutation["inputs_dir"]
        ):
            raise _prepared_result_error(
                "product input mutation state postimage is invalid",
                json_path="$.transaction_state_updates.product_inputs",
                validator="transaction_binding",
            )
        verified.transaction_state_updates[
            PRODUCT_INPUT_MUTATION_KEY
        ] = mutation
    elif product_inputs_update is not None:
        raise _prepared_result_error(
            "product input state update has no mutation receipt",
            json_path="$.transaction_state_updates.product_inputs",
            validator="transaction_binding",
        )
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
        self._manual_phase_replay_authority: tuple[str, str, int, bool] | None = None
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
        value = loads_strict_json(self._path.read_text())
        if type(value) is not dict:
            raise ValueError("squad state must be a JSON object")
        return value

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
                observed = loads_strict_json(content.decode("utf-8"))
            except (
                UnicodeDecodeError,
                ValueError,
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
                old_state = loads_strict_json(old_text)
                if type(old_state) is dict:
                    current_state = old_state
                self._check_monotonics(old_state, next_state)
                old_revision = old_state.get("state_revision", 0)
                if type(old_revision) is int and old_revision >= 0:
                    previous_revision = old_revision
            except ValueError:
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
        if type(request) is not PreparedHumanInput or request.schema_version != 2:
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
        decision = build_blocked_decision_v3(
            prepared=request,
            decision_id=f"dec-{secrets.token_hex(16)}",
            status=initial_status,
            autonomy_mode=str(autonomy_mode),
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
        state["escalation_options"] = normalize_escalation_options(
            decision["options"]
        )
        return decision

    @staticmethod
    def _validate_human_input_replaceability_unlocked(
        state: Mapping[str, Any],
    ) -> None:
        existing = state.get("blocked_decision")
        if _is_human_input_decision(existing):
            validated_existing = validate_blocked_decision(existing)
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
        if not _is_human_input_decision(decision):
            raise StateAdvanceError(
                "versioned human-input decision is missing",
                json_path="$.blocked_decision",
                validator="human_input_authority",
            )
        validated = validate_blocked_decision(decision)
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
        validated = validate_blocked_decision(decision)
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
            if (
                type(decision.get("attempts")) is not int
                or int(decision["attempts"]) >= 2
            ):
                raise StateAdvanceError(
                    "human-input decision attempt limit is exhausted",
                    json_path="$.blocked_decision.attempts",
                    validator="human_input_authority",
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

    def migrate_pending_v2_banzai_human_input_decision(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
        prepared: PreparedHumanInput,
    ) -> dict[str, Any]:
        """Replace one exact pending v2 Banzai authority with canonical v3."""
        if (
            type(prepared) is not PreparedHumanInput
            or prepared.schema_version != 2
        ):
            raise StateAdvanceError(
                "human-input migration requires a prepared request",
                json_path="$.human_input",
                validator="type",
            )
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._human_input_decision_for_cas_unlocked(
                before,
                decision_id,
                expected_state_revision=expected_state_revision,
                allowed_statuses=frozenset({"pending"}),
            )
            if (
                decision["schema_version"] != 2
                or decision["autonomy_mode"] != "banzai"
            ):
                raise StateAdvanceError(
                    "only pending schema-v2 Banzai decisions may migrate",
                    json_path="$.blocked_decision",
                    validator="human_input_authority",
                )
            if prepared.source_state_revision != expected_state_revision:
                raise StateAdvanceError(
                    "human-input migration preparation is stale",
                    json_path="$.state_revision",
                    validator="stale_state",
                )

            status = (
                "pending" if prepared.automatic_eligible else "awaiting_human"
            )
            migrated = build_blocked_decision_v3(
                prepared=prepared,
                decision_id=str(decision["id"]),
                status=status,
                autonomy_mode="banzai",
                attempts=int(decision["attempts"]),
                created_at=str(decision["created_at"]),
            )
            identity_fields = (
                "source_kind",
                "producer_id",
                "source_phase",
                "reason_code",
                "classification",
                "question",
                "recommended_answer",
                "risk_level",
                "resolution_handler",
                "autonomy_mode",
            )
            if any(migrated[field] != decision[field] for field in identity_fields):
                raise StateAdvanceError(
                    "human-input migration changed the sealed decision contract",
                    json_path="$.blocked_decision",
                    validator="human_input_authority",
                )
            legacy_options = [
                {**dict(option), "recommended": False}
                for option in decision["options"]
            ]
            migrated_options = [
                {**dict(option), "recommended": False}
                for option in migrated["options"]
            ]
            if migrated_options != legacy_options:
                raise StateAdvanceError(
                    "human-input migration changed the sealed option contract",
                    json_path="$.blocked_decision.options",
                    validator="human_input_authority",
                )

            desired = deepcopy(before)
            desired["status"] = "blocked"
            desired["blocked_reason"] = decision["reason_code"]
            desired["escalation_question"] = decision["question"]
            desired["escalation_options"] = normalize_escalation_options(
                migrated["options"]
            )
            self._replace_human_input_decision_unlocked(desired, migrated)
            return self._commit_human_input_state_unlocked(before, desired)

    def fail_pending_v2_banzai_human_input_migration(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
    ) -> dict[str, Any]:
        """Seal the one canonical terminal failure for unsafe v2 migration."""
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._human_input_decision_for_cas_unlocked(
                before,
                decision_id,
                expected_state_revision=expected_state_revision,
                allowed_statuses=frozenset({"pending"}),
            )
            if (
                decision["schema_version"] != 2
                or decision["autonomy_mode"] != "banzai"
            ):
                raise StateAdvanceError(
                    "only pending schema-v2 Banzai decisions may fail migration",
                    json_path="$.blocked_decision",
                    validator="human_input_authority",
                )
            failed = {
                **decision,
                "status": "failed",
                "failure_code": "decision_recommendation_unavailable",
            }
            desired = deepcopy(before)
            desired["status"] = "blocked"
            desired["blocked_reason"] = "decision_recommendation_unavailable"
            desired.pop("escalation_question", None)
            self._replace_human_input_decision_unlocked(desired, failed)
            return self._commit_human_input_state_unlocked(before, desired)

    def fail_pending_human_input_decision(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
        failure_code: str,
    ) -> dict[str, Any]:
        """Fail deterministic pre-claim setup without consuming an attempt."""
        if not isinstance(failure_code, str) or not failure_code.strip():
            raise StateAdvanceError(
                "human-input setup failure code is invalid",
                json_path="$.blocked_decision.failure_code",
                validator="type",
            )
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._human_input_decision_for_cas_unlocked(
                before,
                decision_id,
                expected_state_revision=expected_state_revision,
                allowed_statuses=frozenset({"pending"}),
            )
            desired = deepcopy(before)
            failed = {
                **decision,
                "status": "failed",
                "failure_code": failure_code.strip(),
            }
            desired.pop("escalation_question", None)
            self._replace_human_input_decision_unlocked(desired, failed)
            return self._commit_human_input_state_unlocked(before, desired)

    def block_unresolvable_dispatch_cap(
        self,
        *,
        from_phase: str,
        expected_state_revision: int,
        reason_code: str,
    ) -> bool:
        """Install manual diagnosis without retaining unrelated terminal authority."""
        if (
            not isinstance(from_phase, str)
            or not from_phase.strip()
            or not isinstance(reason_code, str)
            or not reason_code.strip()
        ):
            raise StateAdvanceError(
                "dispatch-cap diagnosis identity is invalid",
                json_path="$.blocked_reason",
                validator="type",
            )
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            if (
                before.get("phase") != from_phase
                or type(expected_state_revision) is not int
                or before.get("state_revision", 0)
                != expected_state_revision
            ):
                return False
            raw_decision = before.get("blocked_decision")
            if raw_decision is not None:
                if not _is_human_input_decision(raw_decision):
                    raise StateAdvanceError(
                        "dispatch-cap diagnosis cannot replace malformed authority",
                        json_path="$.blocked_decision",
                        validator="human_input_authority",
                    )
                decision = validate_blocked_decision(raw_decision)
                validate_decision_recovery_pair(
                    decision,
                    before.get("recovery_instruction"),
                )
                if decision["status"] != "resolved":
                    raise StateAdvanceError(
                        "dispatch-cap diagnosis cannot replace unresolved authority",
                        json_path="$.blocked_decision.status",
                        validator="human_input_authority",
                    )

            desired = deepcopy(before)
            desired.pop("blocked_decision", None)
            desired.pop("recovery_instruction", None)
            for key in _HUMAN_INPUT_DISPLAY_AUTHORITY_KEYS:
                desired.pop(key, None)
            desired["status"] = "blocked"
            desired["blocked_reason"] = reason_code.strip()
            desired["recovery_instruction"] = RecoveryInstruction(
                kind=RecoveryKind.MANUAL_DIAGNOSIS,
                reason_code=reason_code.strip(),
                phase="",
                requires_human_input=False,
            ).to_dict()
            self._save_exact_state_unlocked(
                before,
                desired,
                allow_human_input_authority_update=True,
                json_path="$.recovery_instruction",
                error_message="atomic dispatch-cap diagnosis save failed",
            )
            return True

    def block_checkpoint_recommendation_unavailable(
        self,
        snapshot: RoutingStateSnapshot,
    ) -> bool:
        """Install checkpoint retry recovery after retiring terminal authority."""
        if (
            type(snapshot) is not RoutingStateSnapshot
            or snapshot.phase != "checkpoint-assess"
        ):
            raise StateAdvanceError(
                "checkpoint recommendation snapshot is invalid",
                json_path="$.routing_snapshot",
                validator="type",
            )
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            if (
                before.get("phase") != snapshot.phase
                or before.get("state_revision", 0)
                != snapshot.state_revision
                or _last_dispatch_sha256(before)
                != snapshot.previous_dispatch_sha256
            ):
                return False
            raw_decision = before.get("blocked_decision")
            if raw_decision is not None:
                if not _is_human_input_decision(raw_decision):
                    raise StateAdvanceError(
                        "checkpoint recommendation cannot replace malformed authority",
                        json_path="$.blocked_decision",
                        validator="human_input_authority",
                    )
                decision = validate_blocked_decision(raw_decision)
                validate_decision_recovery_pair(
                    decision,
                    before.get("recovery_instruction"),
                )
                if decision["status"] != "resolved":
                    raise StateAdvanceError(
                        "checkpoint recommendation cannot replace unresolved authority",
                        json_path="$.blocked_decision.status",
                        validator="human_input_authority",
                    )

            desired = deepcopy(before)
            desired.pop("blocked_decision", None)
            desired.pop("recovery_instruction", None)
            for key in _HUMAN_INPUT_DISPLAY_AUTHORITY_KEYS:
                desired.pop(key, None)
            desired["status"] = "blocked"
            desired["phase"] = "checkpoint-assess"
            desired["blocked_reason"] = (
                "decision_recommendation_unavailable"
            )
            desired["recovery_instruction"] = RecoveryInstruction(
                kind=RecoveryKind.RETRY_PHASE,
                reason_code="decision_recommendation_unavailable",
                phase="checkpoint-assess",
                requires_human_input=False,
            ).to_dict()
            self._save_exact_state_unlocked(
                before,
                desired,
                allow_human_input_authority_update=True,
                json_path="$.recovery_instruction",
                error_message=(
                    "atomic checkpoint recommendation failure save failed"
                ),
            )
            return True

    def recover_interrupted_human_input_decision(self) -> dict[str, Any]:
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            raw_decision = before.get("blocked_decision")
            if not _is_human_input_decision(raw_decision):
                return deepcopy(before)
            decision = validate_blocked_decision(raw_decision)
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

    def _failed_automatic_replay_decision_unlocked(
        self,
        before: dict[str, Any],
        phase_id: str,
        decision_id: str,
        *,
        expected_state_revision: int,
        v2_automatic_eligible: bool,
    ) -> dict[str, object] | None:
        decision = self._human_input_decision_for_cas_unlocked(
            before,
            decision_id,
            expected_state_revision=expected_state_revision,
            allowed_statuses=frozenset({"failed"}),
        )
        if (
            decision["source_kind"]
            not in {"provider_escalation", "controller_safeguard"}
            or decision["autonomy_mode"] != "banzai"
            or decision["source_phase"] != phase_id
            or before.get("autonomy_mode") != "banzai"
            or before.get("status") != "blocked"
            or (
                decision["schema_version"] == 3
                and decision.get("automatic_eligible") is not True
            )
            or (
                decision["schema_version"] == 2
                and v2_automatic_eligible is not True
            )
        ):
            return None
        return decision

    def authorize_failed_automatic_decision_for_manual_phase_replay(
        self,
        phase_id: str,
        *,
        decision_id: str,
        expected_state_revision: int,
        v2_automatic_eligible: bool = False,
    ) -> bool:
        """Arm a one-shot exact CAS for the controller's execution lease."""
        if not isinstance(phase_id, str) or not phase_id.strip():
            raise StateAdvanceError(
                "manual replay phase identity is invalid",
                json_path="$.phase",
                validator="type",
            )
        if not isinstance(decision_id, str) or not decision_id.strip():
            return False
        if type(expected_state_revision) is not int:
            return False
        normalized_phase = phase_id.strip()
        normalized_id = decision_id.strip()
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._failed_automatic_replay_decision_unlocked(
                before,
                normalized_phase,
                normalized_id,
                expected_state_revision=expected_state_revision,
                v2_automatic_eligible=v2_automatic_eligible,
            )
            if decision is None:
                return False
            self._manual_phase_replay_authority = (
                normalized_phase,
                normalized_id,
                expected_state_revision,
                v2_automatic_eligible,
            )
            return True

    def discard_failed_automatic_decision_for_manual_phase_replay(
        self,
        phase_id: str,
        *,
        decision_id: str | None = None,
        expected_state_revision: int | None = None,
        v2_automatic_eligible: bool = False,
    ) -> bool:
        """Clear one exact failed automatic decision before replaying its phase.

        The CLI authenticates v2 eligibility against the active workflow graph
        and passes that result into this CAS.  V3 eligibility remains sealed in
        the decision itself.  Omitting the exact revision and decision ID is a
        no-op unless the CLI armed the one-shot authority for the controller's
        execution lease, so other internal callers cannot retire it.
        """
        if not isinstance(phase_id, str) or not phase_id.strip():
            raise StateAdvanceError(
                "manual replay phase identity is invalid",
                json_path="$.phase",
                validator="type",
            )
        normalized_phase = phase_id.strip()
        with self._lock(exclusive=True):
            if decision_id is None and expected_state_revision is None:
                authority = self._manual_phase_replay_authority
                self._manual_phase_replay_authority = None
                if authority is None or authority[0] != normalized_phase:
                    return False
                _, decision_id, expected_state_revision, v2_automatic_eligible = (
                    authority
                )
            if not isinstance(decision_id, str) or not decision_id.strip():
                return False
            if type(expected_state_revision) is not int:
                return False
            before = self._load_unlocked()
            decision = self._failed_automatic_replay_decision_unlocked(
                before,
                normalized_phase,
                decision_id.strip(),
                expected_state_revision=expected_state_revision,
                v2_automatic_eligible=v2_automatic_eligible,
            )
            if decision is None:
                return False

            desired = deepcopy(before)
            desired.pop("blocked_decision", None)
            desired.pop("recovery_instruction", None)
            for key in _HUMAN_INPUT_DISPLAY_AUTHORITY_KEYS:
                desired.pop(key, None)
            desired["status"] = "running"
            desired["phase"] = normalized_phase
            desired["blocked_reason"] = None
            return bool(
                self._commit_human_input_state_unlocked(before, desired)
            )

    def rewind_failed_banzai_human_gate(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
        source_phase: str,
        predecessor_phase: str,
        rewound_state: Mapping[str, Any],
        v2_automatic_eligible: bool = False,
    ) -> dict[str, Any]:
        """Atomically reset one exact failed Banzai gate and retire authority."""
        if not isinstance(source_phase, str) or not source_phase.strip():
            raise StateAdvanceError(
                "failed gate source phase is invalid",
                json_path="$.blocked_decision.source_phase",
                validator="type",
            )
        if not isinstance(predecessor_phase, str) or not predecessor_phase.strip():
            raise StateAdvanceError(
                "failed gate predecessor phase is invalid",
                json_path="$.phase",
                validator="type",
            )
        if not isinstance(rewound_state, Mapping):
            raise StateAdvanceError(
                "failed gate rewind postimage is invalid",
                json_path="$",
                validator="type",
            )
        normalized_source = source_phase.strip()
        normalized_predecessor = predecessor_phase.strip()
        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._human_input_decision_for_cas_unlocked(
                before,
                decision_id,
                expected_state_revision=expected_state_revision,
                allowed_statuses=frozenset({"failed"}),
            )
            if (
                decision["source_kind"] != "human_gate"
                or decision["source_phase"] != normalized_source
                or decision["autonomy_mode"] != "banzai"
                or before.get("autonomy_mode") != "banzai"
                or before.get("status") != "blocked"
                or before.get("phase") != normalized_source
                or (
                    decision["schema_version"] == 3
                    and decision.get("automatic_eligible") is not True
                )
                or (
                    decision["schema_version"] == 2
                    and v2_automatic_eligible is not True
                )
            ):
                raise StateAdvanceError(
                    "failed gate authority does not permit rewind",
                    json_path="$.blocked_decision",
                    validator="human_input_authority",
                )

            desired = deepcopy(dict(rewound_state))
            if (
                desired.get("state_revision") != expected_state_revision
                or desired.get("status") != "running"
                or desired.get("phase") != normalized_predecessor
                or desired.get("blocked_reason") is not None
                or desired.get("iteration") != 0
                or desired.get("blocked_decision")
                != before.get("blocked_decision")
                or desired.get("recovery_instruction")
                != before.get("recovery_instruction")
                or any(
                    desired.get(key) != before.get(key)
                    for key in _HUMAN_INPUT_DISPLAY_AUTHORITY_KEYS
                )
            ):
                raise StateAdvanceError(
                    "failed gate rewind postimage does not match checked authority",
                    json_path="$",
                    validator="human_input_authority",
                )

            desired.pop("blocked_decision", None)
            desired.pop("recovery_instruction", None)
            for key in _HUMAN_INPUT_DISPLAY_AUTHORITY_KEYS:
                desired.pop(key, None)
            return self._commit_human_input_state_unlocked(before, desired)

    def apply_human_input_state_resolution(
        self,
        decision_id: str,
        *,
        expected_state_revision: int,
        resolution: AppliedHumanInputResolution,
        state_updates: Mapping[str, Any],
        state_removals: Iterable[str],
        token_usage_delta: int = 0,
        prepared_completion: PreparedControllerCompletion | None = None,
        resolved_at: str | None = None,
        resolved_postimage_builder: Callable[
            [Mapping[str, object]],
            tuple[Mapping[str, Any], PreparedControllerCompletion],
        ]
        | None = None,
    ) -> dict[str, Any]:
        if type(resolution) is not AppliedHumanInputResolution:
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
        if resolved_at is not None and (
            type(resolved_at) is not str or not resolved_at
        ):
            raise StateAdvanceError(
                "human-input resolution timestamp is invalid",
                json_path="$.resolved_at",
                validator="type",
            )
        if resolved_postimage_builder is not None and not callable(
            resolved_postimage_builder
        ):
            raise StateAdvanceError(
                "human-input resolution postimage builder is invalid",
                json_path="$.resolution_postimage",
                validator="type",
            )
        if (
            resolved_postimage_builder is not None
            and prepared_completion is not None
        ):
            raise StateAdvanceError(
                "human-input resolution completion is ambiguous",
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                validator="completion_binding",
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

        def validate_resolution_completion(
            prepared: PreparedControllerCompletion,
        ) -> tuple[dict[str, object], dict[str, object]]:
            (
                marker,
                intent,
                _,
                _,
                prefix_kind,
            ) = _validate_prepared_controller_completion(prepared)
            route = intent["route"]
            if (
                marker["origin"] != "resolution"
                or prefix_kind != "bound"
                or marker["step"] != "quality"
                or type(route) is not dict
                or route.get("kind") != "resolution"
                or route.get("decision_id") != decision_id
            ):
                raise StateAdvanceError(
                    "human-input completion binding is invalid",
                    json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                    validator="completion_binding",
                )
            return marker, intent

        completion_marker: dict[str, object] | None = None
        completion_intent: dict[str, object] | None = None
        if prepared_completion is not None:
            completion_marker, completion_intent = (
                validate_resolution_completion(prepared_completion)
            )

        with self._lock(exclusive=True):
            before = self._load_unlocked()
            decision = self._human_input_decision_for_cas_unlocked(
                before,
                decision_id,
                expected_state_revision=expected_state_revision,
                allowed_statuses=_ACTIVE_HUMAN_INPUT_DECISION_STATUSES,
            )
            selected_option_id = resolution.selected_option_id
            if isinstance(selected_option_id, str):
                selected_option_id = selected_option_id.strip()
            answer_text = resolution.answer_text
            if isinstance(answer_text, str):
                answer_text = answer_text.strip()
            resolution_postimage = {
                **decision,
                "status": "resolved",
                "selected_option_id": selected_option_id,
                "answer_text": answer_text,
                "resolved_by": resolution.resolved_by,
                "failure_code": None,
                "resolved_at": (
                    datetime.now(timezone.utc).isoformat()
                    if resolved_at is None
                    else resolved_at
                ),
            }
            if decision["schema_version"] == 3:
                recommended_target = (
                    decision.get("recommended_option_id")
                    or decision.get("recommended_answer")
                )
                selected_target = (
                    selected_option_id or answer_text
                )
                followed = (
                    None
                    if decision.get("recommended_action") is not None
                    else selected_target == recommended_target
                )
                resolution_postimage.update(
                    {
                        "resolution_rationale": resolution.rationale,
                        "resolution_confidence": resolution.confidence,
                        "recommendation_followed": followed,
                        "override_reason": (
                            resolution.rationale
                            if resolution.resolved_by in {"semi", "COMMANDER"}
                            and followed is False
                            else None
                        ),
                    }
                )
            resolved = validate_blocked_decision(resolution_postimage)
            dynamic_completion: PreparedControllerCompletion | None = None
            try:
                if resolved_postimage_builder is not None:
                    built = resolved_postimage_builder(deepcopy(resolved))
                    if type(built) is not tuple or len(built) != 2:
                        raise StateAdvanceError(
                            "human-input resolution postimage is invalid",
                            json_path="$.resolution_postimage",
                            validator="resolution_postimage",
                        )
                    raw_updates, dynamic_completion = built
                    if not isinstance(raw_updates, Mapping):
                        raise StateAdvanceError(
                            "human-input resolution postimage is invalid",
                            json_path="$.resolution_postimage",
                            validator="resolution_postimage",
                        )
                    try:
                        dynamic_updates = deepcopy(dict(raw_updates))
                    except Exception as exc:
                        raise StateAdvanceError(
                            "human-input resolution postimage is invalid",
                            json_path="$.resolution_postimage",
                            validator="resolution_postimage",
                        ) from exc
                    if (
                        not all(
                            isinstance(key, str) for key in dynamic_updates
                        )
                        or set(dynamic_updates) & set(detached_updates)
                        or set(dynamic_updates)
                        & _HUMAN_INPUT_STATE_EFFECT_RESERVED_KEYS
                    ):
                        raise StateAdvanceError(
                            "human-input resolution postimage updates are invalid",
                            json_path="$.resolution_postimage",
                            validator="resolution_postimage",
                        )
                    completion_marker, completion_intent = (
                        validate_resolution_completion(dynamic_completion)
                    )
                    _validate_quality_debt_resolution_postimage(
                        resolved,
                        dynamic_updates,
                        completion_intent,
                    )
                    detached_updates.update(dynamic_updates)

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
                    int(desired.get("token_usage") or 0)
                    + token_usage_delta
                )
                self._replace_human_input_decision_unlocked(
                    desired,
                    resolved,
                )
                if (
                    completion_marker is not None
                    and completion_intent is not None
                ):
                    route = completion_intent["route"]
                    if (
                        route["from_phase"] != before.get("phase")
                        or route["to_phase"] != desired.get("phase")
                        or PENDING_CONTROLLER_COMPLETION_KEY in before
                    ):
                        raise StateAdvanceError(
                            "human-input completion route changed",
                            json_path=(
                                f"$.{PENDING_CONTROLLER_COMPLETION_KEY}"
                            ),
                            validator="completion_binding",
                        )
                    desired[PENDING_CONTROLLER_COMPLETION_KEY] = (
                        completion_marker
                    )
                return self._commit_human_input_state_unlocked(
                    before,
                    desired,
                )
            except BaseException:
                if dynamic_completion is not None:
                    try:
                        current = self._load_unlocked()
                        if current.get(
                            PENDING_CONTROLLER_COMPLETION_KEY
                        ) != dynamic_completion.marker.to_dict():
                            dynamic_completion.discard()
                    except Exception:
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
        ignore_re: bool = False,
        requested_re_sources: list[str] | None = None,
        spec_authoring_mode: str = "proportional",
        stack_contract: dict[str, object] | None = None,
    ) -> None:
        if autonomy_mode == "semi" and mode in AUTONOMY_MODES and mode not in PROJECT_MODES:
            autonomy_mode = mode
            mode = "greenfield"
        logger.debug("squad init run_id=%s mode=%s entry_phase=%s", run_id, mode, entry_phase)
        ts = datetime.now(timezone.utc).isoformat()
        authoring_mode = normalize_spec_authoring_mode(spec_authoring_mode)
        initial_state = {
            "run_id": run_id,
            "status": "running",
            "phase": entry_phase,
            "mode": mode,
            "autonomy_mode": autonomy_mode,
            "spec_authoring_mode": authoring_mode,
            "iteration": 0,
            "max_iterations": max_iterations,
            "token_usage": 0,
            "token_budget": token_budget,
            "cost_usd": 0.0,
            "user_message": user_message,
            "implementation_targets": list(implementation_targets or []),
            "product_inputs": dict(product_inputs or {}),
            "ignore_re": ignore_re,
            "requested_re_sources": list(requested_re_sources or []),
            "stack_contract": dict(stack_contract or {}),
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
        repair_state = initialize_repair_state(
            {"spec_authoring_mode": authoring_mode}
        )
        if repair_state is not None:
            initial_state["phase1_quality_repair"] = repair_state
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
        checkpoint_policy: str = "none",
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
        if checkpoint_policy not in {"required", "none"}:
            raise StateAdvanceError(
                "checkpoint policy must be required or none",
                json_path="$.checkpoint_policy",
                validator="enum",
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
                checkpoint_policy=checkpoint_policy,
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
                if next_state.get("checkpoint_policy_version") == 2:
                    if not isinstance(completion_marker, Mapping):
                        raise StateAdvanceError(
                            "versioned completion requires a completion marker",
                            json_path=(
                                "$.transaction_state_updates."
                                f"{PENDING_CONTROLLER_COMPLETION_KEY}"
                            ),
                            validator="completion_binding",
                        )
                    outcomes = next_state.get("phase_completion_outcomes")
                    if type(outcomes) is not list:
                        raise StateAdvanceError(
                            "phase completion outcomes must be a list",
                            json_path="$.phase_completion_outcomes",
                            validator="type",
                        )
                    outcome = {
                        "completion_id": completion_marker["completion_id"],
                        "phase": from_phase,
                        "next_phase": to_phase,
                        "outcome": (
                            "skipped" if decision.conditional_skip else "executed"
                        ),
                        "checkpoint": decision.checkpoint_policy,
                    }
                    matching = [
                        row
                        for row in outcomes
                        if isinstance(row, Mapping)
                        and row.get("completion_id") == outcome["completion_id"]
                    ]
                    if matching and matching != [outcome]:
                        raise StateAdvanceError(
                            "completion outcome conflicts with an existing completion ID",
                            json_path="$.phase_completion_outcomes",
                            validator="completion_binding",
                        )
                    if not matching:
                        next_state["phase_completion_outcomes"] = [
                            *outcomes,
                            outcome,
                        ]
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
            authority_changed = (
                _canonicalize_resolved_human_input_audit_for_diagnostic(
                    next_state
                )
            )
            next_state["token_usage"] = (
                int(next_state.get("token_usage") or 0)
                + token_usage_delta
            )
            self._save_unlocked(
                next_state,
                allow_human_input_authority_update=authority_changed,
            )
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

    def begin_product_input_publication(
        self,
        marker: object,
        mutation: object,
        *,
        snapshot: RoutingStateSnapshot,
        state_updates: dict[str, object],
    ) -> None:
        """Persist one exact add-input post-state and write-ahead receipt."""
        try:
            expected_marker = validate_pending_external_publication(marker)
            expected_mutation = require_product_input_mutation_publication_binding(
                mutation,
                expected_marker,
            )
        except ValueError as exc:
            raise StateAdvanceError(
                "product input publication receipt is invalid",
                json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}",
                validator="type",
            ) from exc
        if expected_mutation["kind"] != "add_input":
            raise StateAdvanceError(
                "product input publication kind is invalid",
                json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}.kind",
                validator="enum",
            )
        if not isinstance(snapshot, RoutingStateSnapshot):
            raise StateAdvanceError(
                "product input publication snapshot is invalid",
                json_path="$.routing_snapshot",
                validator="type",
            )
        updates = deepcopy(state_updates)
        expected_keys = frozenset(
            {
                "product_inputs",
                "product_input_attachments",
                "phase_dispatch_counts",
                "status",
                "phase",
                "blocked_reason",
                "escalation_question",
                "escalation_resolved",
                "escalation_resolver",
                "add_input_recovery",
            }
        )
        if type(updates) is not dict or frozenset(updates) != expected_keys:
            raise StateAdvanceError(
                "product input publication state update is not exact",
                json_path="$.state_updates",
                validator="ownership",
            )
        updated_product_inputs = updates["product_inputs"]
        updated_attachments = updates["product_input_attachments"]
        recovery = updates["add_input_recovery"]
        recovery_keys = frozenset(
            {
                "schema_version",
                "request_sha256",
                "product_input_tree_hash",
                "command",
                "operation_id",
                "attachment_ids",
                "attachment_id",
                "added_count",
                "duplicate_count",
                "original_declaration_count",
                "attached_declaration_count",
                "original_declarations",
                "attached_declarations",
                "attachment_ledger_entry",
                "attachment_ledger_entry_sha256",
                "product_input_attachments_sha256",
                "previous_blocked_reason",
                "previous_phase1_investigate_dispatch_count",
            }
        )
        try:
            entry_digest = hashlib.sha256(
                json.dumps(
                    recovery.get("attachment_ledger_entry"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            attachments_digest = hashlib.sha256(
                json.dumps(
                    updated_attachments,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        except (AttributeError, TypeError, UnicodeError):
            entry_digest = ""
            attachments_digest = ""
        if (
            type(updated_product_inputs) is not dict
            or updated_product_inputs.get("tree_hash")
            != expected_mutation["new_tree_hash"]
            or updated_product_inputs.get("inputs_dir")
            != expected_mutation["inputs_dir"]
            or type(recovery) is not dict
            or frozenset(recovery) != recovery_keys
            or recovery.get("schema_version") != 3
            or recovery.get("request_sha256")
            != expected_mutation["request_sha256"]
            or recovery.get("product_input_tree_hash")
            != expected_mutation["new_tree_hash"]
            or recovery.get("attachment_id")
            != expected_mutation["attachment_id"]
            or recovery.get("added_count")
            != expected_mutation["added_count"]
            or recovery.get("duplicate_count")
            != expected_mutation["duplicate_count"]
            or recovery.get("operation_id")
            != expected_mutation["operation_id"]
            or recovery.get("attachment_ids")
            != [expected_mutation["attachment_id"]]
            or type(recovery.get("original_declarations")) is not list
            or recovery.get("original_declaration_count")
            != len(recovery["original_declarations"])
            or type(recovery.get("attached_declarations")) is not list
            or recovery.get("attached_declaration_count")
            != len(recovery["attached_declarations"])
            or type(recovery.get("attachment_ledger_entry")) is not dict
            or recovery["attachment_ledger_entry"].get("id")
            != expected_mutation["attachment_id"]
            or recovery["attachment_ledger_entry"].get("operation_id")
            != expected_mutation["operation_id"]
            or recovery.get("attachment_ledger_entry_sha256") != entry_digest
            or type(updated_attachments) is not list
            or recovery.get("product_input_attachments_sha256")
            != attachments_digest
        ):
            raise StateAdvanceError(
                "product input publication post-state is not receipt-bound",
                json_path="$.state_updates.product_inputs",
                validator="transaction_binding",
            )
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            revision = state.get("state_revision", 0)
            current_product_inputs = state.get("product_inputs")
            if (
                state.get("phase") != snapshot.phase
                or type(revision) is not int
                or revision != snapshot.state_revision
                or _last_dispatch_sha256(state)
                != snapshot.previous_dispatch_sha256
                or PENDING_EXTERNAL_PUBLICATION_KEY in state
                or PRODUCT_INPUT_MUTATION_KEY in state
                or type(current_product_inputs) is not dict
                or current_product_inputs.get("tree_hash")
                != expected_mutation["old_tree_hash"]
            ):
                raise StateAdvanceError(
                    "persisted state changed before product input publication",
                    json_path="$.routing_snapshot",
                    validator="stale_state",
                )
            desired = deepcopy(state)
            desired.update(updates)
            desired[PENDING_EXTERNAL_PUBLICATION_KEY] = expected_marker
            desired[PRODUCT_INPUT_MUTATION_KEY] = expected_mutation
            self._save_exact_state_unlocked(
                state,
                desired,
                json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}",
                error_message="atomic product input publication state save failed",
            )

    def begin_traceability_repair_publication(
        self,
        marker: object,
        mutation: object,
        *,
        snapshot: RoutingStateSnapshot,
        desired_state: dict[str, object],
    ) -> None:
        """Persist the exact repair post-state before any package write."""
        try:
            expected_marker = validate_pending_external_publication(marker)
            expected_mutation = require_product_input_mutation_publication_binding(
                mutation,
                expected_marker,
            )
        except ValueError as exc:
            raise StateAdvanceError(
                "traceability repair publication receipt is invalid",
                json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}",
                validator="type",
            ) from exc
        if expected_mutation["kind"] != "traceability_repair":
            raise StateAdvanceError(
                "traceability repair publication kind is invalid",
                json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}.kind",
                validator="enum",
            )
        if not isinstance(snapshot, RoutingStateSnapshot) or type(desired_state) is not dict:
            raise StateAdvanceError(
                "traceability repair state is invalid",
                json_path="$.state_updates",
                validator="type",
            )
        desired_input = deepcopy(desired_state)
        allowed_updates = frozenset(
            {
                "phase",
                "status",
                "iteration",
                "spec_dir",
                "blocked_reason",
                "escalation_question",
                "escalation_resolved",
                "escalation_resolver",
                "product_inputs",
            }
        )
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            revision = state.get("state_revision", 0)
            changed = {
                key
                for key in set(state) | set(desired_input)
                if key in desired_input and state.get(key) != desired_input.get(key)
            }
            removed = set(state) - set(desired_input)
            current_product_inputs = state.get("product_inputs")
            repaired_product_inputs = desired_input.get("product_inputs")
            current_without_hash = (
                {key: value for key, value in current_product_inputs.items() if key != "tree_hash"}
                if type(current_product_inputs) is dict
                else None
            )
            repaired_without_hash = (
                {key: value for key, value in repaired_product_inputs.items() if key != "tree_hash"}
                if type(repaired_product_inputs) is dict
                else None
            )
            if (
                state.get("phase") != snapshot.phase
                or type(revision) is not int
                or revision != snapshot.state_revision
                or _last_dispatch_sha256(state) != snapshot.previous_dispatch_sha256
                or PENDING_EXTERNAL_PUBLICATION_KEY in state
                or PRODUCT_INPUT_MUTATION_KEY in state
                or changed - allowed_updates
                or removed - {"phase_a_readiness_blockers"}
                or desired_input.get("phase") != "phase4-document"
                or desired_input.get("status") != "running"
                or desired_input.get("iteration") != 0
                or desired_input.get("spec_dir") != state.get("spec_dir")
                or desired_input.get("blocked_reason") is not None
                or desired_input.get("escalation_question") is not None
                or desired_input.get("escalation_resolved") is not False
                or desired_input.get("escalation_resolver") is not None
                or current_without_hash != repaired_without_hash
                or type(current_product_inputs) is not dict
                or current_product_inputs.get("tree_hash")
                != expected_mutation["old_tree_hash"]
                or type(repaired_product_inputs) is not dict
                or repaired_product_inputs.get("tree_hash")
                != expected_mutation["new_tree_hash"]
                or repaired_product_inputs.get("inputs_dir")
                != expected_mutation["inputs_dir"]
            ):
                raise StateAdvanceError(
                    "traceability repair post-state is not exact",
                    json_path="$.state_updates",
                    validator="transaction_binding",
                )
            desired = deepcopy(desired_input)
            desired[PENDING_EXTERNAL_PUBLICATION_KEY] = expected_marker
            desired[PRODUCT_INPUT_MUTATION_KEY] = expected_mutation
            self._save_exact_state_unlocked(
                state,
                desired,
                json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}",
                error_message="atomic traceability repair state save failed",
            )

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

    @staticmethod
    def _complete_product_input_mutation(
        state: dict[str, Any],
        desired: dict[str, Any],
        marker: dict[str, object],
        verified_tree_hash: object,
    ) -> None:
        raw = state.get(PRODUCT_INPUT_MUTATION_KEY)
        if raw is None:
            if verified_tree_hash is not None:
                raise StateAdvanceError(
                    "unexpected product input postimage proof",
                    json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}",
                    validator="transaction_binding",
                )
            return
        try:
            mutation = require_product_input_mutation_publication_binding(
                raw,
                marker,
            )
        except ValueError as exc:
            raise StateAdvanceError(
                "persisted product input mutation is invalid",
                json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}",
                validator="state_contract",
            ) from exc
        product_inputs = state.get("product_inputs")
        if (
            type(verified_tree_hash) is not str
            or verified_tree_hash != mutation["new_tree_hash"]
            or type(product_inputs) is not dict
            or product_inputs.get("tree_hash") != verified_tree_hash
            or product_inputs.get("inputs_dir") != mutation["inputs_dir"]
        ):
            raise StateAdvanceError(
                "product input mutation postimage is not verified",
                json_path=f"$.{PRODUCT_INPUT_MUTATION_KEY}",
                validator="transaction_binding",
            )
        desired.pop(PRODUCT_INPUT_MUTATION_KEY, None)

    def complete_external_publication(
        self,
        marker: object,
        *,
        verified_product_input_tree_hash: str | None = None,
    ) -> None:
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
            desired = deepcopy(state)
            self._complete_product_input_mutation(
                state,
                desired,
                expected_marker,
                verified_product_input_tree_hash,
            )
            if _EXTERNAL_PUBLICATION_FAILURE_KEY in desired:
                try:
                    diagnostic = _validate_external_publication_failure(
                        desired[_EXTERNAL_PUBLICATION_FAILURE_KEY]
                    )
                except ValueError as exc:
                    raise StateAdvanceError(
                        "persisted external publication failure is invalid",
                        json_path=f"$.{_EXTERNAL_PUBLICATION_FAILURE_KEY}",
                        validator="state_contract",
                    ) from exc
                desired["status"] = diagnostic["resume_status"]
                resume_blocked_reason = diagnostic[
                    "resume_blocked_reason"
                ]
                if resume_blocked_reason is None:
                    desired.pop("blocked_reason", None)
                else:
                    desired["blocked_reason"] = resume_blocked_reason
            desired.pop(PENDING_EXTERNAL_PUBLICATION_KEY, None)
            desired.pop(_EXTERNAL_PUBLICATION_FAILURE_KEY, None)
            self._save_exact_state_unlocked(
                state,
                desired,
                json_path=f"$.{PENDING_EXTERNAL_PUBLICATION_KEY}",
                error_message="atomic external publication completion failed",
            )

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
        if marker["origin"] == "resolution":
            decision = state.get("blocked_decision")
            if (
                type(route) is not dict
                or frozenset(dict.keys(route))
                != frozenset(
                    {"kind", "decision_id", "from_phase", "to_phase"}
                )
                or route.get("kind") != "resolution"
                or state.get("phase") != route.get("to_phase")
                or not isinstance(decision, Mapping)
                or decision.get("id") != route.get("decision_id")
                or decision.get("status") != "resolved"
            ):
                raise StateAdvanceError(
                    "human-input completion provenance changed",
                    json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
                    validator="completion_binding",
                )
            return
        routed_keys = {
            "kind",
            "from_phase",
            "to_phase",
            "manual_phase_run",
            "record_completion",
        }
        versioned_route = (
            type(route) is dict
            and "checkpoint_policy_version" in route
        )
        if versioned_route:
            routed_keys.update({
                "checkpoint_policy_version",
                "checkpoint_policy",
                "rewind_policy",
            })
        if (
            type(route) is not dict
            or frozenset(dict.keys(route)) != frozenset(routed_keys)
            or route["kind"] != "routed"
            or type(route["from_phase"]) is not str
            or not route["from_phase"]
            or type(route["to_phase"]) is not str
            or not route["to_phase"]
            or type(route["manual_phase_run"]) is not bool
            or type(route["record_completion"]) is not bool
            or state.get("phase") != route["to_phase"]
            or (
                versioned_route
                and state.get("checkpoint_policy_version")
                != route["checkpoint_policy_version"]
            )
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
        *,
        verified_product_input_tree_hash: str | None = None,
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
            self._complete_product_input_mutation(
                state,
                desired,
                expected_publication,
                verified_product_input_tree_hash,
            )
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
            active_decision = state.get("blocked_decision")
            if not (
                _is_human_input_decision(active_decision)
                and active_decision.get("status")
                in _ACTIVE_HUMAN_INPUT_DECISION_STATUSES
            ):
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
                if "quality" in intent["effect_plan"]:
                    quality_receipt = prepared.receipts["effects"].get(
                        "quality"
                    )
                    candidate_receipt = (
                        quality_receipt.get("candidate")
                        if isinstance(quality_receipt, Mapping)
                        else None
                    )
                    evidence = desired.get(
                        "proportional_quality_candidate_evidence"
                    )
                    if (
                        isinstance(candidate_receipt, Mapping)
                        and isinstance(evidence, Mapping)
                        and candidate_receipt.get("candidate_id")
                        == evidence.get("current_candidate_id")
                        and evidence.get("selected_candidate_id")
                        in {None, evidence.get("current_candidate_id")}
                        and _valid_completion_sha256(
                            candidate_receipt.get("manifest_sha256")
                        )
                    ):
                        updated_evidence = deepcopy(dict(evidence))
                        updated_evidence["candidate_manifest_sha256"] = (
                            candidate_receipt["manifest_sha256"]
                        )
                        desired[
                            "proportional_quality_candidate_evidence"
                        ] = updated_evidence
            elif expected_marker["origin"] == "terminal":
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
            else:
                self._restore_failure_lifecycle(
                    desired,
                    diagnostic_key=_CONTROLLER_COMPLETION_FAILURE_KEY,
                )
                desired["last_human_input_completion"] = {
                    "schema_version": 1,
                    "completion_id": expected_marker["completion_id"],
                    "intent_sha256": expected_marker["intent_sha256"],
                    "receipts_sha256": receipts_sha256,
                    "decision_id": route["decision_id"],
                }
            if "retarget" in intent["effect_plan"]:
                from echelon.spec_retarget_finalization import (
                    verify_retarget_finalization_receipt,
                )

                receipt = prepared.receipts["effects"].get("retarget")
                if (
                    type(receipt) is not dict
                    or receipt.get("completion_id")
                    != expected_marker["completion_id"]
                ):
                    raise StateAdvanceError(
                        "retarget completion receipt identity is invalid",
                        json_path="$.retarget.finalization_receipt",
                        validator="completion_binding",
                    )
                checked = verify_retarget_finalization_receipt(
                    prepared._project_root,
                    desired,
                    receipt,
                )
                retarget = desired.get("retarget")
                if type(retarget) is not dict or retarget.get("status") != "finalizing":
                    raise StateAdvanceError(
                        "retarget completion state is invalid",
                        json_path="$.retarget.status",
                        validator="completion_binding",
                    )
                updated_retarget = deepcopy(retarget)
                updated_retarget["status"] = "complete"
                updated_retarget["replacement_commit"] = checked["replacement_commit"]
                updated_retarget["finalization_receipt"] = checked
                updated_retarget["comparison_pending_completion_id"] = (
                    expected_marker["completion_id"]
                )
                updated_retarget["comparison_event_id"] = (
                    "retarget-comparison-" + expected_marker["completion_id"]
                )
                updated_retarget["comparison_command"] = (
                    "Compare old and replacement artifacts:\n"
                    f"  git diff {retarget['checkpoint_commit']}.."
                    f"{checked['replacement_commit']} -- specs/{desired['spec_id']}"
                )
                updated_retarget.pop("memory_excluded", None)
                desired["retarget"] = updated_retarget
            desired.pop(PENDING_CONTROLLER_COMPLETION_KEY, None)
            desired.pop(_CONTROLLER_COMPLETION_FAILURE_KEY, None)
            self._save_exact_completion_state_unlocked(
                state,
                desired,
                json_path=f"$.{PENDING_CONTROLLER_COMPLETION_KEY}",
            )

    def mark_retarget_comparison_emitted(self, completion_id: str) -> bool:
        """Durably consume one post-adoption retarget comparison event."""
        with self._lock(exclusive=True):
            state = self._load_unlocked()
            retarget = state.get("retarget")
            if (
                type(retarget) is not dict
                or retarget.get("comparison_pending_completion_id") != completion_id
            ):
                return False
            desired = deepcopy(state)
            updated = deepcopy(retarget)
            updated.pop("comparison_pending_completion_id", None)
            updated["comparison_emitted_completion_id"] = completion_id
            desired["retarget"] = updated
            self._save_exact_completion_state_unlocked(
                state,
                desired,
                json_path="$.retarget.comparison_pending_completion_id",
            )
            return True

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
