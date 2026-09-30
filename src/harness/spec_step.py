"""Sealed durable documents for one Phase A controller step."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping


SpecStepOrigin = Literal["routed", "terminal", "resolution"]
SpecStepEffect = Literal[
    "publication",
    "journal",
    "timing",
    "checkpoint",
    "quality",
    "context",
    "mining",
    "retarget",
    "commit",
]

_SCHEMA_VERSION = 1
_OUTBOX_DIRECTORY = ".spec-step-outbox"
_INTENT_NAME = "intent.json"
_RECEIPTS_NAME = "receipts.json"
_MAX_INTENT_BYTES = 4_194_304
_MAX_RECEIPTS_BYTES = 1_048_576
_STEP_ID = re.compile(r"\A[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_DISPATCH_ID = re.compile(r"\A[0-9a-f]{32}\Z")
_ORIGINS = ("routed", "terminal", "resolution")
_EFFECT_ORDER = (
    "publication",
    "journal",
    "timing",
    "checkpoint",
    "quality",
    "context",
    "mining",
    "retarget",
)
_ERROR_CODES = frozenset(
    {
        "intent_invalid",
        "intent_mismatch",
        "receipts_invalid",
        "receipts_mismatch",
        "stage_corrupt",
        "stage_missing",
        "stage_io",
    }
)


class SpecStepError(Exception):
    """Bounded durable-step failure that never contains filesystem details."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in _ERROR_CODES:
            code = "stage_io"
        self.code = code
        super().__init__(code)


def _raise(code: str) -> None:
    raise SpecStepError(code)


@dataclass(frozen=True)
class SpecStepFailure:
    effect: SpecStepEffect
    code: str
    attempts: int
    resume_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "effect": self.effect,
            "code": self.code,
            "attempts": self.attempts,
            "resume_status": self.resume_status,
        }


@dataclass(frozen=True)
class SpecStepMarker:
    schema_version: int
    step_id: str
    intent_sha256: str
    receipts_sha256: str
    cursor: SpecStepEffect
    origin: SpecStepOrigin
    publication_binding_sha256: str | None
    failure: SpecStepFailure | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "intent_sha256": self.intent_sha256,
            "receipts_sha256": self.receipts_sha256,
            "cursor": self.cursor,
            "origin": self.origin,
            "publication_binding_sha256": self.publication_binding_sha256,
            "failure": None if self.failure is None else self.failure.to_dict(),
        }


@dataclass(frozen=True)
class SpecStepEffectReceipt:
    step_id: str
    effect: SpecStepEffect
    postimage_sha256: str
    _payload_json: bytes = field(repr=False)

    def __init__(
        self,
        step_id: str,
        effect: SpecStepEffect,
        postimage_sha256: str,
        payload: Mapping[str, object],
    ) -> None:
        normalized = _normalize_json(payload, code="receipts_invalid")
        if type(normalized) is not dict:
            _raise("receipts_invalid")
        object.__setattr__(self, "step_id", _valid_step_id(step_id, "receipts_invalid"))
        object.__setattr__(self, "effect", _valid_effect(effect, allow_commit=False, code="receipts_invalid"))
        object.__setattr__(self, "postimage_sha256", _valid_sha256(postimage_sha256, "receipts_invalid"))
        object.__setattr__(self, "_payload_json", _canonical_json(normalized, code="receipts_invalid", newline=False))

    @property
    def payload(self) -> dict[str, object]:
        value = json.loads(self._payload_json)
        if type(value) is not dict:
            raise AssertionError("invalid internal receipt payload")
        return value

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "effect": self.effect,
            "postimage_sha256": self.postimage_sha256,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class SpecStepIntent:
    step_id: str
    origin: SpecStepOrigin
    expected_state_revision: int
    expected_previous_dispatch_sha256: str
    effects: tuple[SpecStepEffect, ...]
    _route_json: bytes = field(repr=False)
    _publication_json: bytes = field(repr=False)
    _final_state_json: bytes = field(repr=False)
    _provenance_json: bytes = field(repr=False)
    _sealed_json: bytes = field(repr=False)

    @property
    def route(self) -> dict[str, object]:
        return _dict_snapshot(self._route_json)

    @property
    def publication(self) -> dict[str, object] | None:
        value = json.loads(self._publication_json)
        if value is None:
            return None
        if type(value) is not dict:
            raise AssertionError("invalid internal publication snapshot")
        return value

    @property
    def final_state(self) -> dict[str, object]:
        return _dict_snapshot(self._final_state_json)

    @property
    def provenance(self) -> dict[str, object]:
        return _dict_snapshot(self._provenance_json)

    def to_dict(self) -> dict[str, object]:
        return _dict_snapshot(self._sealed_json)


@dataclass(frozen=True)
class PreparedSpecStep:
    marker: SpecStepMarker
    intent: SpecStepIntent
    _squad_dir: Path = field(repr=False)
    _transaction_root: Path = field(repr=False)
    _transaction_identity: tuple[int, int, int] = field(repr=False)
    _receipts_json: bytes = field(repr=False)

    @property
    def receipts(self) -> tuple[SpecStepEffectReceipt, ...]:
        document = json.loads(self._receipts_json)
        return tuple(_receipt_from(item) for item in document["receipts"])

    def discard(self) -> None:
        _discard_exact(
            self._transaction_root.parent,
            self.marker.step_id,
            self._transaction_identity,
            missing_ok=True,
        )


def _dict_snapshot(content: bytes) -> dict[str, object]:
    value = json.loads(content)
    if type(value) is not dict:
        raise AssertionError("invalid internal spec-step snapshot")
    return value


def _normalize_json(value: Any, *, code: str, depth: int = 0) -> Any:
    if depth > 64:
        _raise(code)
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            _raise(code)
        return value
    if type(value) in (list, tuple):
        return [_normalize_json(item, code=code, depth=depth + 1) for item in value]
    if type(value) is dict:
        result: dict[str, object] = {}
        for key, item in dict.items(value):
            if type(key) is not str:
                _raise(code)
            result[key] = _normalize_json(item, code=code, depth=depth + 1)
        return result
    _raise(code)


def _canonical_json(value: object, *, code: str, newline: bool = True) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _raise(code)
    if newline:
        encoded += "\n"
    return encoded.encode("utf-8")


def _decode_canonical(content: bytes, *, code: str) -> object:
    def exact_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                _raise(code)
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=exact_object)
    except SpecStepError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        _raise(code)
    normalized = _normalize_json(value, code=code)
    if _canonical_json(normalized, code=code) != content:
        _raise(code)
    return normalized


def _valid_step_id(value: object, code: str = "intent_invalid") -> str:
    if type(value) is not str or _STEP_ID.fullmatch(value) is None:
        _raise(code)
    return value


def _valid_sha256(value: object, code: str = "intent_invalid") -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _raise(code)
    return value


def _bounded_provider_text(value: object, *, maximum: int) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum
    ):
        _raise("intent_invalid")
    return value


def _provider_artifact_path(value: object) -> str:
    path = _bounded_provider_text(value, maximum=2048)
    parts = path.split("/")
    if (
        path.startswith("/")
        or path.endswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in parts)
    ):
        _raise("intent_invalid")
    return path


def _provider_occurrence_order_key(occurrence_id: str) -> tuple[object, ...]:
    fixed = {
        "ordinary": (10, 0),
        "why3/initial": (20, 0),
        "sage/work-assessment": (40, 0),
        "why3/final-revalidation": (70, 0),
    }
    if occurrence_id in fixed:
        group, index = fixed[occurrence_id]
        return (group, index, occurrence_id)
    match = re.fullmatch(
        r"(pre-dispatch|stage1|stage2|specialist)/(\d+)",
        occurrence_id,
    )
    if match:
        group = {
            "pre-dispatch": 0,
            "stage1": 20,
            "specialist": 20,
            "stage2": 60,
        }[match.group(1)]
        return (group, int(match.group(2)), occurrence_id)
    # Runtime-only controller occurrences use stable semantic names. Their
    # lexical order is the graph-independent canonical order.
    return (80, 0, occurrence_id)


def _validate_provider_output_evidence(value: object) -> dict[str, object]:
    keys = {
        "root",
        "path",
        "kind",
        "requirement",
        "sha256",
        "preimage_identity_sha256",
        "postimage_identity_sha256",
        "evidence_kind",
        "members",
    }
    if type(value) is not dict or frozenset(value) != frozenset(keys):
        _raise("intent_invalid")
    root = _bounded_provider_text(value["root"], maximum=64)
    if root not in {"active_spec", "squad", "proposal"}:
        _raise("intent_invalid")
    path = _provider_artifact_path(value["path"])
    if value["kind"] not in {"file", "directory"}:
        _raise("intent_invalid")
    if value["requirement"] not in {"required", "optional"}:
        _raise("intent_invalid")
    if value["evidence_kind"] not in {
        "created",
        "replaced",
        "shadow_promoted",
        "retained",
    }:
        _raise("intent_invalid")
    preimage = value["preimage_identity_sha256"]
    if preimage is not None:
        preimage = _valid_sha256(preimage)
    members = value["members"]
    if type(members) is not list or len(members) > 4096:
        _raise("intent_invalid")
    normalized_members: list[dict[str, object]] = []
    previous_path: str | None = None
    for member in members:
        if type(member) is not dict or frozenset(member) != frozenset(
            {"path", "sha256", "identity_sha256"}
        ):
            _raise("intent_invalid")
        member_path = _provider_artifact_path(member["path"])
        if previous_path is not None and member_path <= previous_path:
            _raise("intent_invalid")
        previous_path = member_path
        normalized_members.append(
            {
                "path": member_path,
                "sha256": _valid_sha256(member["sha256"]),
                "identity_sha256": _valid_sha256(member["identity_sha256"]),
            }
        )
    if value["kind"] == "file" and normalized_members:
        _raise("intent_invalid")
    if value["kind"] == "directory" and not normalized_members:
        _raise("intent_invalid")
    return {
        "root": root,
        "path": path,
        "kind": value["kind"],
        "requirement": value["requirement"],
        "sha256": _valid_sha256(value["sha256"]),
        "preimage_identity_sha256": preimage,
        "postimage_identity_sha256": _valid_sha256(
            value["postimage_identity_sha256"]
        ),
        "evidence_kind": value["evidence_kind"],
        "members": normalized_members,
    }


def _validate_provider_receipt(value: object) -> dict[str, object]:
    keys = {
        "schema_version",
        "dispatch_id",
        "phase_id",
        "assignment_id",
        "occurrence_id",
        "state_revision",
        "contract_sha256",
        "prompt_sha256",
        "prompt_metadata_sha256",
        "outcome",
        "outputs",
        "semantic_validator_id",
        "semantic_result_sha256",
        "provider_attempts_sha256",
        "validated_result_sha256",
    }
    if type(value) is not dict or frozenset(value) != frozenset(keys):
        _raise("intent_invalid")
    if value["schema_version"] != 2 or type(value["schema_version"]) is not int:
        _raise("intent_invalid")
    dispatch_id = value["dispatch_id"]
    if type(dispatch_id) is not str or _DISPATCH_ID.fullmatch(dispatch_id) is None:
        _raise("intent_invalid")
    revision = value["state_revision"]
    if type(revision) is not int or revision < 0:
        _raise("intent_invalid")
    if value["outcome"] not in {"published", "domain_blocked", "invalid"}:
        _raise("intent_invalid")
    outputs = value["outputs"]
    if type(outputs) is not list or len(outputs) > 4096:
        _raise("intent_invalid")
    semantic_id = value["semantic_validator_id"]
    semantic_sha = value["semantic_result_sha256"]
    if (semantic_id is None) != (semantic_sha is None):
        _raise("intent_invalid")
    if semantic_id is not None:
        semantic_id = _bounded_provider_text(semantic_id, maximum=256)
        semantic_sha = _valid_sha256(semantic_sha)
    return {
        "schema_version": 2,
        "dispatch_id": dispatch_id,
        "phase_id": _bounded_provider_text(value["phase_id"], maximum=256),
        "assignment_id": _bounded_provider_text(
            value["assignment_id"], maximum=512
        ),
        "occurrence_id": _bounded_provider_text(
            value["occurrence_id"], maximum=256
        ),
        "state_revision": revision,
        "contract_sha256": _valid_sha256(value["contract_sha256"]),
        "prompt_sha256": _valid_sha256(value["prompt_sha256"]),
        "prompt_metadata_sha256": _valid_sha256(
            value["prompt_metadata_sha256"]
        ),
        "outcome": value["outcome"],
        "outputs": [_validate_provider_output_evidence(item) for item in outputs],
        "semantic_validator_id": semantic_id,
        "semantic_result_sha256": semantic_sha,
        "provider_attempts_sha256": _valid_sha256(
            value["provider_attempts_sha256"]
        ),
        "validated_result_sha256": _valid_sha256(
            value["validated_result_sha256"]
        ),
    }


def validate_provider_execution_provenance(value: object) -> dict[str, object]:
    """Authenticate one closed provider manifest without graph imports."""
    keys = {
        "schema_version",
        "manifest_sha256",
        "manifest",
        "receipts",
        "cost_usd_delta",
    }
    if type(value) is not dict or frozenset(value) != frozenset(keys):
        _raise("intent_invalid")
    if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
        _raise("intent_invalid")
    manifest = value["manifest"]
    receipts = value["receipts"]
    if (
        type(manifest) is not list
        or type(receipts) is not list
        or len(manifest) > 512
        or len(receipts) > 512
    ):
        _raise("intent_invalid")
    normalized_manifest: list[dict[str, object]] = []
    occurrences: set[str] = set()
    prior_order: tuple[object, ...] | None = None
    for row in manifest:
        row_keys = {
            "assignment_id",
            "occurrence_id",
            "contract_sha256",
            "status",
            "reason",
            "receipt_sha256",
            "reused_step_id",
            "reused_dispatch_id",
        }
        if type(row) is not dict or frozenset(row) != frozenset(row_keys):
            _raise("intent_invalid")
        assignment_id = _bounded_provider_text(row["assignment_id"], maximum=512)
        occurrence_id = _bounded_provider_text(row["occurrence_id"], maximum=256)
        if occurrence_id in occurrences:
            _raise("intent_invalid")
        occurrences.add(occurrence_id)
        order = _provider_occurrence_order_key(occurrence_id)
        if prior_order is not None and order <= prior_order:
            _raise("intent_invalid")
        prior_order = order
        status = row["status"]
        reason = row["reason"]
        receipt_sha = row["receipt_sha256"]
        reused_step = row["reused_step_id"]
        reused_dispatch = row["reused_dispatch_id"]
        if status == "executed":
            if reason != "" or reused_step is not None or reused_dispatch is not None:
                _raise("intent_invalid")
            receipt_sha = _valid_sha256(receipt_sha)
        elif status in {"skipped", "deferred"}:
            _bounded_provider_text(reason, maximum=1024)
            if receipt_sha is not None or reused_step is not None or reused_dispatch is not None:
                _raise("intent_invalid")
        elif status == "reused":
            _bounded_provider_text(reason, maximum=1024)
            if receipt_sha is not None:
                _raise("intent_invalid")
            reused_step = _valid_step_id(reused_step)
            if (
                type(reused_dispatch) is not str
                or _DISPATCH_ID.fullmatch(reused_dispatch) is None
            ):
                _raise("intent_invalid")
        else:
            _raise("intent_invalid")
        normalized_manifest.append(
            {
                "assignment_id": assignment_id,
                "occurrence_id": occurrence_id,
                "contract_sha256": _valid_sha256(row["contract_sha256"]),
                "status": status,
                "reason": reason,
                "receipt_sha256": receipt_sha,
                "reused_step_id": reused_step,
                "reused_dispatch_id": reused_dispatch,
            }
        )
    manifest_sha = _valid_sha256(value["manifest_sha256"])
    if hashlib.sha256(
        _canonical_json(
            normalized_manifest,
            code="intent_invalid",
            newline=False,
        )
    ).hexdigest() != manifest_sha:
        _raise("intent_invalid")
    executed = [row for row in normalized_manifest if row["status"] == "executed"]
    if len(executed) != len(receipts):
        _raise("intent_invalid")
    normalized_receipts: list[dict[str, object]] = []
    for row, raw_receipt in zip(executed, receipts, strict=True):
        receipt = _validate_provider_receipt(raw_receipt)
        receipt_sha = hashlib.sha256(
            _canonical_json(receipt, code="intent_invalid", newline=False)
        ).hexdigest()
        if (
            receipt_sha != row["receipt_sha256"]
            or receipt["assignment_id"] != row["assignment_id"]
            or receipt["occurrence_id"] != row["occurrence_id"]
            or receipt["contract_sha256"] != row["contract_sha256"]
        ):
            _raise("intent_invalid")
        normalized_receipts.append(receipt)
    output_targets = [
        (output["root"], output["path"])
        for receipt in normalized_receipts
        for output in receipt["outputs"]
    ]
    if len(output_targets) != len(set(output_targets)):
        _raise("intent_invalid")
    cost = value["cost_usd_delta"]
    if (
        type(cost) not in (int, float)
        or not math.isfinite(float(cost))
        or not 0 <= float(cost) <= 1_000_000_000
    ):
        _raise("intent_invalid")
    return {
        "schema_version": 1,
        "manifest_sha256": manifest_sha,
        "manifest": normalized_manifest,
        "receipts": normalized_receipts,
        "cost_usd_delta": float(cost),
    }


def _valid_origin(value: object) -> SpecStepOrigin:
    if type(value) is not str or value not in _ORIGINS:
        _raise("intent_invalid")
    return value  # type: ignore[return-value]


def _valid_effect(value: object, *, allow_commit: bool, code: str) -> SpecStepEffect:
    allowed = _EFFECT_ORDER + (("commit",) if allow_commit else ())
    if type(value) is not str or value not in allowed:
        _raise(code)
    return value  # type: ignore[return-value]


def _valid_effects(value: object) -> tuple[SpecStepEffect, ...]:
    if type(value) not in (list, tuple):
        _raise("intent_invalid")
    result: list[SpecStepEffect] = []
    previous = -1
    for raw in value:
        effect = _valid_effect(raw, allow_commit=False, code="intent_invalid")
        index = _EFFECT_ORDER.index(effect)
        if index <= previous:
            _raise("intent_invalid")
        result.append(effect)
        previous = index
    return tuple(result)


def _valid_failure(value: object, *, cursor: SpecStepEffect) -> SpecStepFailure | None:
    if value is None:
        return None
    if type(value) is not dict or frozenset(value) != frozenset(
        {"effect", "code", "attempts", "resume_status"}
    ):
        _raise("intent_invalid")
    effect = _valid_effect(value["effect"], allow_commit=True, code="intent_invalid")
    attempts = value["attempts"]
    if effect != cursor or type(attempts) is not int or not 0 <= attempts <= 1_000_000:
        _raise("intent_invalid")
    code = value["code"]
    resume_status = value["resume_status"]
    if type(code) is not str or not code or len(code) > 128:
        _raise("intent_invalid")
    if type(resume_status) is not str or resume_status not in {"running", "blocked"}:
        _raise("intent_invalid")
    return SpecStepFailure(effect, code, attempts, resume_status)


def _marker_from(value: object) -> SpecStepMarker:
    if type(value) is SpecStepMarker:
        raw = value.to_dict()
    elif type(value) is dict:
        raw = value
    else:
        _raise("intent_invalid")
    keys = {
        "schema_version",
        "step_id",
        "intent_sha256",
        "receipts_sha256",
        "cursor",
        "origin",
        "publication_binding_sha256",
        "failure",
    }
    if frozenset(raw) != frozenset(keys) or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        _raise("intent_invalid")
    cursor = _valid_effect(raw["cursor"], allow_commit=True, code="intent_invalid")
    binding = raw["publication_binding_sha256"]
    if binding is not None:
        binding = _valid_sha256(binding)
    return SpecStepMarker(
        1,
        _valid_step_id(raw["step_id"]),
        _valid_sha256(raw["intent_sha256"]),
        _valid_sha256(raw["receipts_sha256"]),
        cursor,
        _valid_origin(raw["origin"]),
        binding,
        _valid_failure(raw["failure"], cursor=cursor),
    )


def validate_spec_step_marker(value: object) -> SpecStepMarker:
    """Return one detached exact-schema marker for state-store ownership."""
    return _marker_from(value)


def _validate_publication(value: object, *, step_id: str) -> dict[str, object] | None:
    if value is None:
        return None
    if type(value) is not dict or type(value.get("kind")) is not str:
        _raise("intent_invalid")

    def external(marker: object) -> dict[str, object]:
        if type(marker) is not dict or frozenset(marker) != frozenset(
            {"schema_version", "transaction_id", "manifest_sha256"}
        ):
            _raise("intent_invalid")
        if type(marker["schema_version"]) is not int or marker["schema_version"] != 1:
            _raise("intent_invalid")
        transaction_id = _valid_step_id(marker["transaction_id"])
        if transaction_id != step_id:
            _raise("intent_invalid")
        return {
            "schema_version": 1,
            "transaction_id": transaction_id,
            "manifest_sha256": _valid_sha256(marker["manifest_sha256"]),
        }

    def constitution(request: object) -> dict[str, object]:
        try:
            from harness.constitution_publication import (
                ConstitutionPublicationError,
                validate_constitution_publication_request,
            )

            return validate_constitution_publication_request(request)
        except ConstitutionPublicationError:
            _raise("intent_invalid")

    kind = value["kind"]
    if kind == "external" and set(value) == {"kind", "marker"}:
        return {"kind": "external", "marker": external(value["marker"])}
    if kind == "constitution" and set(value) == {"kind", "request"}:
        return {
            "kind": "constitution",
            "request": constitution(value["request"]),
        }
    if kind == "both" and set(value) == {"kind", "external", "constitution"}:
        return {
            "kind": "both",
            "external": external(value["external"]),
            "constitution": constitution(value["constitution"]),
        }
    _raise("intent_invalid")


def _validate_intent(value: object) -> dict[str, object]:
    keys = {
        "schema_version",
        "step_id",
        "origin",
        "expected_state_revision",
        "expected_previous_dispatch_sha256",
        "route",
        "effects",
        "publication",
        "final_state",
        "provenance",
    }
    if type(value) is not dict or frozenset(value) != frozenset(keys):
        _raise("intent_invalid")
    step_id = _valid_step_id(value["step_id"])
    revision = value["expected_state_revision"]
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        _raise("intent_invalid")
    if type(revision) is not int or revision < 0:
        _raise("intent_invalid")
    route = _normalize_json(value["route"], code="intent_invalid")
    final_state = _normalize_json(value["final_state"], code="intent_invalid")
    provenance = _normalize_json(value["provenance"], code="intent_invalid")
    if type(route) is not dict or type(final_state) is not dict or type(provenance) is not dict:
        _raise("intent_invalid")
    if "provider_execution" in provenance:
        provenance["provider_execution"] = (
            validate_provider_execution_provenance(
                provenance["provider_execution"]
            )
        )
        from_phase = route.get("from_phase")
        if type(from_phase) is str and any(
            receipt["phase_id"] != from_phase
            for receipt in provenance["provider_execution"]["receipts"]
        ):
            _raise("intent_invalid")
    effects = _valid_effects(value["effects"])
    publication = _validate_publication(value["publication"], step_id=step_id)
    if ("publication" in effects) != (publication is not None):
        _raise("intent_invalid")
    return {
        "schema_version": 1,
        "step_id": step_id,
        "origin": _valid_origin(value["origin"]),
        "expected_state_revision": revision,
        "expected_previous_dispatch_sha256": _valid_sha256(value["expected_previous_dispatch_sha256"]),
        "route": route,
        "effects": list(effects),
        "publication": publication,
        "final_state": final_state,
        "provenance": provenance,
    }


def _intent_view(value: dict[str, object], sealed: bytes) -> SpecStepIntent:
    return SpecStepIntent(
        step_id=str(value["step_id"]),
        origin=value["origin"],  # type: ignore[arg-type]
        expected_state_revision=int(value["expected_state_revision"]),
        expected_previous_dispatch_sha256=str(value["expected_previous_dispatch_sha256"]),
        effects=tuple(value["effects"]),  # type: ignore[arg-type]
        _route_json=_canonical_json(value["route"], code="intent_invalid", newline=False),
        _publication_json=_canonical_json(value["publication"], code="intent_invalid", newline=False),
        _final_state_json=_canonical_json(value["final_state"], code="intent_invalid", newline=False),
        _provenance_json=_canonical_json(value["provenance"], code="intent_invalid", newline=False),
        _sealed_json=_canonical_json(value, code="intent_invalid", newline=False),
    )


def _receipt_from(value: object) -> SpecStepEffectReceipt:
    if type(value) is not dict or frozenset(value) != frozenset(
        {"step_id", "effect", "postimage_sha256", "payload"}
    ):
        _raise("receipts_invalid")
    return SpecStepEffectReceipt(
        value["step_id"],  # type: ignore[arg-type]
        value["effect"],  # type: ignore[arg-type]
        value["postimage_sha256"],  # type: ignore[arg-type]
        value["payload"],  # type: ignore[arg-type]
    )


def _validate_receipts(value: object, *, intent: dict[str, object]) -> tuple[dict[str, object], tuple[SpecStepEffectReceipt, ...]]:
    if type(value) is not dict or frozenset(value) != frozenset(
        {"schema_version", "step_id", "receipts"}
    ):
        _raise("receipts_invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["step_id"] != intent["step_id"]:
        _raise("receipts_invalid")
    raw_receipts = value["receipts"]
    if type(raw_receipts) is not list:
        _raise("receipts_invalid")
    receipts = tuple(_receipt_from(item) for item in raw_receipts)
    effects = tuple(intent["effects"])
    if len(receipts) > len(effects):
        _raise("receipts_invalid")
    for index, receipt in enumerate(receipts):
        if receipt.step_id != intent["step_id"] or receipt.effect != effects[index]:
            _raise("receipts_invalid")
    return {
        "schema_version": 1,
        "step_id": intent["step_id"],
        "receipts": [receipt.to_dict() for receipt in receipts],
    }, receipts


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _real_directory(path: Path, *, missing_code: str) -> Path:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        _raise(missing_code)
    except OSError:
        _raise("stage_io")
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        _raise("stage_corrupt")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        _raise("stage_corrupt")
    if resolved != path.absolute():
        _raise("stage_corrupt")
    return resolved


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        _raise("stage_io")
    try:
        os.fsync(fd)
    except OSError:
        _raise("stage_io")
    finally:
        os.close(fd)


def _ensure_outbox(squad_dir: Path) -> Path:
    outbox = squad_dir / _OUTBOX_DIRECTORY
    try:
        os.mkdir(outbox, 0o700)
    except FileExistsError:
        pass
    except OSError:
        _raise("stage_io")
    else:
        _fsync_directory(outbox)
        _fsync_directory(squad_dir)
    return _real_directory(outbox, missing_code="stage_missing")


def _atomic_write(directory: Path, name: str, content: bytes, *, identity: tuple[int, int, int], replace: bool) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(directory, flags)
    except OSError:
        _raise("stage_io")
    temporary = f".{name}-{secrets.token_hex(12)}.tmp"
    temporary_fd: int | None = None
    try:
        if _directory_identity(os.fstat(directory_fd)) != identity:
            _raise("stage_corrupt")
        try:
            existing = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        except OSError:
            _raise("stage_io")
        if replace:
            if existing is None or not stat.S_ISREG(existing.st_mode) or stat.S_ISLNK(existing.st_mode):
                _raise("stage_corrupt")
        elif existing is not None:
            _raise("stage_corrupt")
        temporary_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(content)
        while view:
            written = os.write(temporary_fd, view)
            if written <= 0:
                _raise("stage_io")
            view = view[written:]
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    except SpecStepError:
        raise
    except OSError:
        _raise("stage_io")
    finally:
        if temporary_fd is not None:
            try:
                os.close(temporary_fd)
            except OSError:
                pass
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
        os.close(directory_fd)


def _read_regular(path: Path, *, maximum: int, code: str) -> bytes:
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise("stage_io")
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_size > maximum:
        _raise(code)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise(code)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            _raise(code)
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(fd)
        if len(content) > maximum or (after.st_dev, after.st_ino, after.st_size) != (opened.st_dev, opened.st_ino, opened.st_size):
            _raise(code)
        return content
    except SpecStepError:
        raise
    except OSError:
        _raise(code)
    finally:
        os.close(fd)


def _assert_root_identity(prepared: PreparedSpecStep) -> None:
    try:
        metadata = os.lstat(prepared._transaction_root)
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise("stage_corrupt")
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or _directory_identity(metadata) != prepared._transaction_identity:
        _raise("stage_corrupt")


def prepare_spec_step(
    squad_dir: Path,
    *,
    step_id: str,
    origin: SpecStepOrigin,
    expected_state_revision: int,
    expected_previous_dispatch_sha256: str,
    route: Mapping[str, object],
    effects: tuple[SpecStepEffect, ...],
    publication: Mapping[str, object] | None,
    final_state: Mapping[str, object],
    provenance: Mapping[str, object],
) -> PreparedSpecStep:
    """Detach, validate, durably seal, and reread one step intent."""
    candidate = _validate_intent(
        _normalize_json(
            {
                "schema_version": 1,
                "step_id": step_id,
                "origin": origin,
                "expected_state_revision": expected_state_revision,
                "expected_previous_dispatch_sha256": expected_previous_dispatch_sha256,
                "route": route,
                "effects": effects,
                "publication": publication,
                "final_state": final_state,
                "provenance": provenance,
            },
            code="intent_invalid",
        )
    )
    intent_bytes = _canonical_json(candidate, code="intent_invalid")
    if len(intent_bytes) > _MAX_INTENT_BYTES:
        _raise("intent_invalid")
    receipts_document = {"schema_version": 1, "step_id": step_id, "receipts": []}
    receipts_bytes = _canonical_json(receipts_document, code="receipts_invalid")
    squad = _real_directory(squad_dir, missing_code="stage_missing")
    outbox = _ensure_outbox(squad)
    root = outbox / step_id
    try:
        os.mkdir(root, 0o700)
    except FileExistsError:
        _raise("stage_corrupt")
    except OSError:
        _raise("stage_io")
    metadata = os.lstat(root)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        _raise("stage_corrupt")
    identity = _directory_identity(metadata)
    try:
        _atomic_write(root, _INTENT_NAME, intent_bytes, identity=identity, replace=False)
        _atomic_write(root, _RECEIPTS_NAME, receipts_bytes, identity=identity, replace=False)
        _fsync_directory(outbox)
        publication_bytes = _canonical_json(candidate["publication"], code="intent_invalid")
        effect_values = tuple(candidate["effects"])
        marker = SpecStepMarker(
            1,
            step_id,
            hashlib.sha256(intent_bytes).hexdigest(),
            hashlib.sha256(receipts_bytes).hexdigest(),
            effect_values[0] if effect_values else "commit",  # type: ignore[arg-type]
            candidate["origin"],  # type: ignore[arg-type]
            hashlib.sha256(publication_bytes).hexdigest() if candidate["publication"] is not None else None,
            None,
        )
        loaded = load_prepared_spec_step(squad, marker)
        if loaded._transaction_identity != identity:
            _raise("stage_corrupt")
        return loaded
    except BaseException:
        try:
            _discard_exact(outbox, step_id, identity, missing_ok=True)
        except SpecStepError:
            pass
        raise


def load_prepared_spec_step(squad_dir: Path, marker: object) -> PreparedSpecStep:
    """Load one exact state-authorized step without regenerating evidence."""
    expected = _marker_from(marker)
    squad = _real_directory(squad_dir, missing_code="stage_missing")
    outbox = _real_directory(squad / _OUTBOX_DIRECTORY, missing_code="stage_missing")
    root = _real_directory(outbox / expected.step_id, missing_code="stage_missing")
    before = os.lstat(root)
    identity = _directory_identity(before)
    intent_bytes = _read_regular(root / _INTENT_NAME, maximum=_MAX_INTENT_BYTES, code="intent_invalid")
    receipts_bytes = _read_regular(root / _RECEIPTS_NAME, maximum=_MAX_RECEIPTS_BYTES, code="receipts_invalid")
    if hashlib.sha256(intent_bytes).hexdigest() != expected.intent_sha256:
        _raise("intent_mismatch")
    intent = _validate_intent(_decode_canonical(intent_bytes, code="intent_invalid"))
    receipts_document, receipts = _validate_receipts(
        _decode_canonical(receipts_bytes, code="receipts_invalid"),
        intent=intent,
    )
    publication_bytes = _canonical_json(intent["publication"], code="intent_invalid")
    binding = hashlib.sha256(publication_bytes).hexdigest() if intent["publication"] is not None else None
    if intent["step_id"] != expected.step_id or intent["origin"] != expected.origin or binding != expected.publication_binding_sha256:
        _raise("intent_mismatch")
    effects = tuple(intent["effects"])
    if expected.cursor != "commit" and expected.cursor not in effects:
        _raise("intent_mismatch")
    cursor_index = len(effects) if expected.cursor == "commit" else effects.index(expected.cursor)
    if len(receipts) not in {cursor_index, cursor_index + 1}:
        _raise("receipts_mismatch")
    digest = hashlib.sha256(receipts_bytes).hexdigest()
    if len(receipts) == cursor_index:
        if digest != expected.receipts_sha256:
            _raise("receipts_mismatch")
    else:
        if expected.cursor == "commit":
            _raise("receipts_mismatch")
        prior = {"schema_version": 1, "step_id": expected.step_id, "receipts": receipts_document["receipts"][:-1]}
        if hashlib.sha256(_canonical_json(prior, code="receipts_invalid")).hexdigest() != expected.receipts_sha256:
            _raise("receipts_mismatch")
    after = os.lstat(root)
    if _directory_identity(after) != identity:
        _raise("stage_corrupt")
    return PreparedSpecStep(
        marker=expected,
        intent=_intent_view(intent, _canonical_json(intent, code="intent_invalid", newline=False)),
        _squad_dir=squad,
        _transaction_root=root,
        _transaction_identity=identity,
        _receipts_json=_canonical_json(receipts_document, code="receipts_invalid", newline=False),
    )


def append_spec_step_receipt(prepared: PreparedSpecStep, receipt: SpecStepEffectReceipt) -> PreparedSpecStep:
    """Append or adopt the receipt for exactly the marker's current cursor."""
    if type(prepared) is not PreparedSpecStep or type(receipt) is not SpecStepEffectReceipt:
        _raise("receipts_invalid")
    _assert_root_identity(prepared)
    current = load_prepared_spec_step(prepared._squad_dir, prepared.marker)
    if receipt.step_id != current.marker.step_id or receipt.effect != current.marker.cursor or current.marker.cursor == "commit":
        _raise("receipts_invalid")
    receipts = list(current.receipts)
    effects = current.intent.effects
    cursor_index = effects.index(current.marker.cursor)
    if len(receipts) == cursor_index + 1:
        if receipts[-1] != receipt:
            _raise("receipts_mismatch")
    elif len(receipts) == cursor_index:
        receipts.append(receipt)
        document = {"schema_version": 1, "step_id": current.marker.step_id, "receipts": [item.to_dict() for item in receipts]}
        content = _canonical_json(document, code="receipts_invalid")
        if len(content) > _MAX_RECEIPTS_BYTES:
            _raise("receipts_invalid")
        _atomic_write(current._transaction_root, _RECEIPTS_NAME, content, identity=current._transaction_identity, replace=True)
    else:
        _raise("receipts_mismatch")
    content = _read_regular(current._transaction_root / _RECEIPTS_NAME, maximum=_MAX_RECEIPTS_BYTES, code="receipts_invalid")
    next_cursor: SpecStepEffect = effects[cursor_index + 1] if cursor_index + 1 < len(effects) else "commit"
    advanced = SpecStepMarker(
        1,
        current.marker.step_id,
        current.marker.intent_sha256,
        hashlib.sha256(content).hexdigest(),
        next_cursor,
        current.marker.origin,
        current.marker.publication_binding_sha256,
        None,
    )
    return load_prepared_spec_step(current._squad_dir, advanced)


def _discard_exact(outbox: Path, step_id: str, identity: tuple[int, int, int], *, missing_ok: bool) -> None:
    try:
        outbox_fd = os.open(outbox, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        if missing_ok:
            return
        _raise("stage_missing")
    except OSError:
        _raise("stage_corrupt")
    root_fd: int | None = None
    try:
        try:
            root_fd = os.open(step_id, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=outbox_fd)
        except FileNotFoundError:
            if missing_ok:
                return
            _raise("stage_missing")
        except OSError:
            _raise("stage_corrupt")
        if _directory_identity(os.fstat(root_fd)) != identity:
            _raise("stage_corrupt")
        names = os.listdir(root_fd)
        if set(names) - {_INTENT_NAME, _RECEIPTS_NAME}:
            _raise("stage_corrupt")
        for name in names:
            metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                _raise("stage_corrupt")
            os.unlink(name, dir_fd=root_fd)
        os.fsync(root_fd)
        current = os.stat(step_id, dir_fd=outbox_fd, follow_symlinks=False)
        if _directory_identity(current) != identity:
            _raise("stage_corrupt")
        os.rmdir(step_id, dir_fd=outbox_fd)
        os.fsync(outbox_fd)
    except SpecStepError:
        raise
    except OSError:
        _raise("stage_io")
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(outbox_fd)


def discard_unreferenced_spec_step(squad_dir: Path, marker: object) -> bool:
    """Discard one exact valid stage; missing repeated discards are harmless."""
    expected = _marker_from(marker)
    squad = _real_directory(squad_dir, missing_code="stage_missing")
    outbox_path = squad / _OUTBOX_DIRECTORY
    if not outbox_path.exists():
        return False
    outbox = _real_directory(outbox_path, missing_code="stage_missing")
    root_path = outbox / expected.step_id
    if not root_path.exists():
        return False
    prepared = load_prepared_spec_step(squad, expected)
    _discard_exact(outbox, expected.step_id, prepared._transaction_identity, missing_ok=True)
    return True


def discard_unreferenced_spec_step_by_id(
    squad_dir: Path,
    step_id: str,
) -> bool:
    """Validate and discard one orphan stage when no state marker exists."""
    identifier = _valid_step_id(step_id, "stage_corrupt")
    squad = _real_directory(squad_dir, missing_code="stage_missing")
    outbox_path = squad / _OUTBOX_DIRECTORY
    if not outbox_path.exists():
        return False
    outbox = _real_directory(outbox_path, missing_code="stage_missing")
    root_path = outbox / identifier
    if not root_path.exists():
        return False
    root = _real_directory(root_path, missing_code="stage_missing")
    intent_bytes = _read_regular(
        root / _INTENT_NAME,
        maximum=_MAX_INTENT_BYTES,
        code="intent_invalid",
    )
    receipts_bytes = _read_regular(
        root / _RECEIPTS_NAME,
        maximum=_MAX_RECEIPTS_BYTES,
        code="receipts_invalid",
    )
    intent = _validate_intent(
        _decode_canonical(intent_bytes, code="intent_invalid")
    )
    _, receipts = _validate_receipts(
        _decode_canonical(receipts_bytes, code="receipts_invalid"),
        intent=intent,
    )
    if intent["step_id"] != identifier:
        _raise("intent_mismatch")
    effects = tuple(intent["effects"])
    cursor: SpecStepEffect = (
        effects[len(receipts)]
        if len(receipts) < len(effects)
        else "commit"
    )
    publication_bytes = _canonical_json(
        intent["publication"],
        code="intent_invalid",
    )
    marker = SpecStepMarker(
        1,
        identifier,
        hashlib.sha256(intent_bytes).hexdigest(),
        hashlib.sha256(receipts_bytes).hexdigest(),
        cursor,
        intent["origin"],
        (
            hashlib.sha256(publication_bytes).hexdigest()
            if intent["publication"] is not None
            else None
        ),
        None,
    )
    prepared = load_prepared_spec_step(squad, marker)
    _discard_exact(
        outbox,
        identifier,
        prepared._transaction_identity,
        missing_ok=True,
    )
    return True
