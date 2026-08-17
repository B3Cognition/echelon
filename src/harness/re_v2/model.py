"""Validated immutable model contracts for the RE v2 execution kernel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping

from .canonical import canonical_json_bytes, content_digest

RE_V2_ENGINE = "re-v2"
RE_V2_PROTOCOL = "2.1"
RE_V2_SUPPORTED_PROTOCOLS = ("2.0", "2.1")

SnapshotKind = Literal[
    "git-worktree",
    "content-snapshot",
    "workspace-git-composite",
]

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")


class ReV2ModelError(ValueError):
    """Raised when untrusted RE v2 model data violates its canonical schema."""


def _error(message: str) -> None:
    raise ReV2ModelError(message)


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        _error(f"{field} must be a nonempty safe ID")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        _error(f"{field} must be a nonempty string")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        _error(f"{field} must be a lowercase sha256 digest")
    return value


def _nonnegative(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _error(f"{field} must be a nonnegative integer")
    return value


def _positive_or_none(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _error(f"{field} must be a positive integer or null")
    return value


def _utc_timestamp(value: object, field: str) -> str:
    text = _string(value, field)
    if not text.endswith("Z"):
        _error(f"{field} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        _error(f"{field} must be an RFC3339 UTC timestamp")
    if parsed.tzinfo != timezone.utc:
        _error(f"{field} must be an RFC3339 UTC timestamp")
    return text


def _sorted_unique_ids(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        _error(f"{field} must be an array")
    result = tuple(_safe_id(value, field) for value in values)
    if result != tuple(sorted(set(result))):
        _error(f"{field} must be unique and sorted")
    return result


def _sorted_unique_digests(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        _error(f"{field} must be an array")
    result = tuple(_digest(value, field) for value in values)
    if result != tuple(sorted(set(result))):
        _error(f"{field} must be unique and sorted")
    return result


def _canonical_object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _error(f"{field} must be a JSON object")
    try:
        return json.loads(canonical_json_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ReV2ModelError(f"{field} must contain JSON values") from exc


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _fields(value: object, required: set[str], name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _error(f"{name} must be a JSON object")
    present = set(value)
    unknown = present - required
    missing = required - present
    if unknown:
        _error(f"{name} has unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        _error(f"{name} is missing fields: {', '.join(sorted(missing))}")
    return value


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    token_limit: int | None
    active_ms_limit: int | None
    provider_attempt_limit: int
    artifact_generation_attempt_limit: int
    semantic_repair_round_limit: int
    result_contract_retry_limit: int

    def __post_init__(self) -> None:
        _positive_or_none(self.token_limit, "token_limit")
        _positive_or_none(self.active_ms_limit, "active_ms_limit")
        for field in self._COUNTERS:
            _nonnegative(getattr(self, field), field)

    _COUNTERS: ClassVar[tuple[str, ...]] = (
        "provider_attempt_limit", "artifact_generation_attempt_limit",
        "semantic_repair_round_limit", "result_contract_retry_limit",
    )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self._FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "BudgetPolicy":
        raw = _fields(value, set(cls._FIELDS), "BudgetPolicy")
        return cls(**{field: raw[field] for field in cls._FIELDS})

    _FIELDS: ClassVar[tuple[str, ...]] = ("token_limit", "active_ms_limit", *_COUNTERS)


@dataclass(frozen=True, slots=True)
class ArtifactKey:
    source_snapshot_id: str
    partition_manifest_id: str
    artifact_kind: str
    layer: str
    producer_protocol_version: str
    layer_policy_hash: str
    dependency_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.source_snapshot_id, "source_snapshot_id")
        _digest(self.partition_manifest_id, "partition_manifest_id")
        _safe_id(self.artifact_kind, "artifact_kind")
        _safe_id(self.layer, "layer")
        _safe_id(self.producer_protocol_version, "producer_protocol_version")
        _digest(self.layer_policy_hash, "layer_policy_hash")
        object.__setattr__(self, "dependency_hashes", _sorted_unique_digests(self.dependency_hashes, "dependency_hashes"))

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: list(getattr(self, field)) if field == "dependency_hashes" else getattr(self, field) for field in self._FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactKey":
        raw = _fields(value, set(cls._FIELDS), "ArtifactKey")
        return cls(**{field: raw[field] for field in cls._FIELDS})

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "source_snapshot_id", "partition_manifest_id", "artifact_kind", "layer",
        "producer_protocol_version", "layer_policy_hash", "dependency_hashes",
    )


@dataclass(frozen=True, slots=True)
class CertificationKey:
    artifact_hash: str
    verifier_id: str
    verifier_version: str
    source_snapshot_id: str
    audit_epoch_id: str | None

    def __post_init__(self) -> None:
        _digest(self.artifact_hash, "artifact_hash")
        _safe_id(self.verifier_id, "verifier_id")
        _safe_id(self.verifier_version, "verifier_version")
        _digest(self.source_snapshot_id, "source_snapshot_id")
        if self.audit_epoch_id is not None:
            _safe_id(self.audit_epoch_id, "audit_epoch_id")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self._FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "CertificationKey":
        raw = _fields(value, set(cls._FIELDS), "CertificationKey")
        return cls(**{field: raw[field] for field in cls._FIELDS})

    _FIELDS: ClassVar[tuple[str, ...]] = ("artifact_hash", "verifier_id", "verifier_version", "source_snapshot_id", "audit_epoch_id")


@dataclass(frozen=True, slots=True)
class WorkTemplate:
    goal_id: str
    artifact_kind: str
    layer: str
    producer_id: str
    producer_protocol_version: str
    layer_policy_hash: str
    required_template_ids: tuple[str, ...]
    verifier_id: str
    verifier_version: str
    result_contract_id: str
    max_provider_attempts: int
    max_generation_attempts: int
    max_semantic_rounds: int
    max_result_contract_retries: int

    def __post_init__(self) -> None:
        for field in self._IDS:
            _safe_id(getattr(self, field), field)
        _digest(self.layer_policy_hash, "layer_policy_hash")
        object.__setattr__(self, "required_template_ids", _sorted_unique_ids(self.required_template_ids, "required_template_ids"))
        for field in self._COUNTERS:
            _nonnegative(getattr(self, field), field)

    @property
    def template_id(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: list(getattr(self, field)) if field == "required_template_ids" else getattr(self, field) for field in self._FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkTemplate":
        raw = _fields(value, set(cls._FIELDS), "WorkTemplate")
        return cls(**{field: raw[field] for field in cls._FIELDS})

    _IDS: ClassVar[tuple[str, ...]] = ("goal_id", "artifact_kind", "layer", "producer_id", "producer_protocol_version", "verifier_id", "verifier_version", "result_contract_id")
    _COUNTERS: ClassVar[tuple[str, ...]] = ("max_provider_attempts", "max_generation_attempts", "max_semantic_rounds", "max_result_contract_retries")
    _FIELDS: ClassVar[tuple[str, ...]] = (*_IDS[:5], "layer_policy_hash", "required_template_ids", *_IDS[5:], *_COUNTERS)


@dataclass(frozen=True, slots=True)
class WorkItem:
    template_id: str
    goal_id: str
    output_key: ArtifactKey
    required_artifact_hashes: tuple[str, ...]
    producer_id: str
    producer_protocol_version: str
    verifier_id: str
    verifier_version: str
    result_contract_id: str
    max_provider_attempts: int
    max_generation_attempts: int
    max_semantic_rounds: int
    max_result_contract_retries: int

    def __post_init__(self) -> None:
        for field in self._IDS:
            _safe_id(getattr(self, field), field)
        if not isinstance(self.output_key, ArtifactKey):
            _error("output_key must be an ArtifactKey")
        object.__setattr__(self, "required_artifact_hashes", _sorted_unique_digests(self.required_artifact_hashes, "required_artifact_hashes"))
        if self.required_artifact_hashes != self.output_key.dependency_hashes:
            _error("required_artifact_hashes must exactly equal output_key.dependency_hashes")
        for field in self._COUNTERS:
            _nonnegative(getattr(self, field), field)

    @property
    def work_item_id(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self._FIELDS}
        result["output_key"] = self.output_key.to_json_dict()
        result["required_artifact_hashes"] = list(self.required_artifact_hashes)
        return result

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkItem":
        raw = _fields(value, set(cls._FIELDS), "WorkItem")
        data = {field: raw[field] for field in cls._FIELDS}
        data["output_key"] = ArtifactKey.from_json_dict(data["output_key"])
        return cls(**data)

    _IDS: ClassVar[tuple[str, ...]] = ("template_id", "goal_id", "producer_id", "producer_protocol_version", "verifier_id", "verifier_version", "result_contract_id")
    _COUNTERS: ClassVar[tuple[str, ...]] = ("max_provider_attempts", "max_generation_attempts", "max_semantic_rounds", "max_result_contract_retries")
    _FIELDS: ClassVar[tuple[str, ...]] = ("template_id", "goal_id", "output_key", "required_artifact_hashes", *_IDS[2:], *_COUNTERS)


@dataclass(frozen=True, slots=True)
class ExecutionObservation:
    started_at: str
    ended_at: str
    duration_ms: int
    exit_code: int | None
    timed_out: bool
    output_truncated: bool
    result_contract_valid: bool
    token_usage: int | None
    provider_name: str
    model_name: str
    stderr_digest: str | None

    def __post_init__(self) -> None:
        _utc_timestamp(self.started_at, "started_at")
        _utc_timestamp(self.ended_at, "ended_at")
        _nonnegative(self.duration_ms, "duration_ms")
        if self.exit_code is not None and (not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)):
            _error("exit_code must be an integer or null")
        for field in ("timed_out", "output_truncated", "result_contract_valid"):
            if not isinstance(getattr(self, field), bool):
                _error(f"{field} must be a boolean")
        if self.token_usage is not None:
            _nonnegative(self.token_usage, "token_usage")
        _safe_id(self.provider_name, "provider_name")
        _safe_id(self.model_name, "model_name")
        if self.stderr_digest is not None:
            _digest(self.stderr_digest, "stderr_digest")

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self._FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ExecutionObservation":
        raw = _fields(value, set(cls._FIELDS), "ExecutionObservation")
        return cls(**{field: raw[field] for field in cls._FIELDS})

    _FIELDS: ClassVar[tuple[str, ...]] = ("started_at", "ended_at", "duration_ms", "exit_code", "timed_out", "output_truncated", "result_contract_valid", "token_usage", "provider_name", "model_name", "stderr_digest")


@dataclass(frozen=True, slots=True)
class CertificationReceipt:
    certification_key: CertificationKey
    candidate_id: str
    work_item_id: str
    verdict: Literal["accepted", "rejected"]
    normalized_diagnostics: tuple[str, ...]
    evidence_references: tuple[str, ...]
    scope_verified: bool
    certified_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.certification_key, CertificationKey):
            _error("certification_key must be a CertificationKey")
        _safe_id(self.candidate_id, "candidate_id")
        _safe_id(self.work_item_id, "work_item_id")
        if self.verdict not in ("accepted", "rejected"):
            _error("verdict must be accepted or rejected")
        object.__setattr__(self, "normalized_diagnostics", _sorted_unique_ids(self.normalized_diagnostics, "normalized_diagnostics"))
        object.__setattr__(self, "evidence_references", _sorted_unique_ids(self.evidence_references, "evidence_references"))
        if not isinstance(self.scope_verified, bool):
            _error("scope_verified must be a boolean")
        _utc_timestamp(self.certified_at, "certified_at")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{field: getattr(self, field) for field in self._FIELDS if field not in {"certification_key", "normalized_diagnostics", "evidence_references"}},
            "certification_key": self.certification_key.to_json_dict(),
            "normalized_diagnostics": list(self.normalized_diagnostics),
            "evidence_references": list(self.evidence_references),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CertificationReceipt":
        raw = _fields(value, set(cls._FIELDS), "CertificationReceipt")
        data = {field: raw[field] for field in cls._FIELDS}
        data["certification_key"] = CertificationKey.from_json_dict(data["certification_key"])
        return cls(**data)

    _FIELDS: ClassVar[tuple[str, ...]] = ("certification_key", "candidate_id", "work_item_id", "verdict", "normalized_diagnostics", "evidence_references", "scope_verified", "certified_at")


@dataclass(frozen=True, slots=True)
class ArtifactReceipt:
    artifact_key: ArtifactKey
    artifact_hash: str
    certification_id: str
    candidate_id: str
    work_item_id: str
    accepted_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_key, ArtifactKey):
            _error("artifact_key must be an ArtifactKey")
        _digest(self.artifact_hash, "artifact_hash")
        _digest(self.certification_id, "certification_id")
        _safe_id(self.candidate_id, "candidate_id")
        _safe_id(self.work_item_id, "work_item_id")
        _utc_timestamp(self.accepted_at, "accepted_at")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {"artifact_key": self.artifact_key.to_json_dict(), **{field: getattr(self, field) for field in self._FIELDS if field != "artifact_key"}}

    @classmethod
    def from_json_dict(cls, value: object) -> "ArtifactReceipt":
        raw = _fields(value, set(cls._FIELDS), "ArtifactReceipt")
        data = {field: raw[field] for field in cls._FIELDS}
        data["artifact_key"] = ArtifactKey.from_json_dict(data["artifact_key"])
        return cls(**data)

    _FIELDS: ClassVar[tuple[str, ...]] = ("artifact_key", "artifact_hash", "certification_id", "candidate_id", "work_item_id", "accepted_at")


@dataclass(frozen=True, slots=True)
class RunManifest:
    schema_version: int
    engine: str
    engine_protocol_version: str
    run_id: str
    created_at: str
    source_snapshot_id: str
    source_snapshot_kind: SnapshotKind
    partition_manifest_id: str
    requested_goals: tuple[str, ...]
    initial_budget_policy: BudgetPolicy
    provider_contract: Mapping[str, object]
    artifact_policy_versions: Mapping[str, str]
    parent_run_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool) or self.schema_version != 1:
            _error("unsupported schema version")
        if self.engine != RE_V2_ENGINE:
            _error("unsupported engine")
        if self.engine_protocol_version not in RE_V2_SUPPORTED_PROTOCOLS:
            _error("unsupported engine protocol version")
        _safe_id(self.run_id, "run_id")
        _utc_timestamp(self.created_at, "created_at")
        _digest(self.source_snapshot_id, "source_snapshot_id")
        legacy_kinds = {"git-worktree", "content-snapshot"}
        if self.engine_protocol_version == "2.0":
            if self.source_snapshot_kind not in legacy_kinds:
                _error("protocol 2.0 requires a legacy source snapshot kind")
        elif self.source_snapshot_kind != "workspace-git-composite":
            _error("protocol 2.1 requires workspace-git-composite")
        _digest(self.partition_manifest_id, "partition_manifest_id")
        object.__setattr__(self, "requested_goals", _sorted_unique_ids(self.requested_goals, "requested_goals"))
        if not isinstance(self.initial_budget_policy, BudgetPolicy):
            _error("initial_budget_policy must be a BudgetPolicy")
        provider_contract = _canonical_object(
            self.provider_contract, "provider_contract"
        )
        _safe_id(
            provider_contract.get("provider"),
            "provider_contract.provider",
        )
        object.__setattr__(
            self, "provider_contract", _freeze_json(provider_contract)
        )
        policies = _canonical_object(self.artifact_policy_versions, "artifact_policy_versions")
        if not policies or any(not _safe_id(key, "artifact_policy_versions key") or not _safe_id(item, "artifact_policy_versions value") for key, item in policies.items()):
            _error("artifact_policy_versions must have nonempty safe keys and values")
        object.__setattr__(self, "artifact_policy_versions", _freeze_json(policies))
        if self.parent_run_id is not None:
            _safe_id(self.parent_run_id, "parent_run_id")

    @property
    def run_manifest_id(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{field: getattr(self, field) for field in self._FIELDS if field not in {"requested_goals", "initial_budget_policy", "provider_contract", "artifact_policy_versions"}},
            "requested_goals": list(self.requested_goals),
            "initial_budget_policy": self.initial_budget_policy.to_json_dict(),
            "provider_contract": _thaw_json(self.provider_contract),
            "artifact_policy_versions": _thaw_json(self.artifact_policy_versions),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "RunManifest":
        raw = _fields(value, set(cls._FIELDS), "RunManifest")
        data = {field: raw[field] for field in cls._FIELDS}
        data["initial_budget_policy"] = BudgetPolicy.from_json_dict(data["initial_budget_policy"])
        return cls(**data)

    _FIELDS: ClassVar[tuple[str, ...]] = ("schema_version", "engine", "engine_protocol_version", "run_id", "created_at", "source_snapshot_id", "source_snapshot_kind", "partition_manifest_id", "requested_goals", "initial_budget_policy", "provider_contract", "artifact_policy_versions", "parent_run_id")
