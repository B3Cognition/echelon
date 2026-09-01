"""Closed zero-dispatch authority for protocol-2.5 audit-context preflight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    nonnegative_int,
    one_of,
    positive_int,
    safe_id,
)


PreflightReasonV1 = Literal[
    "semantic_context_byte_ceiling_exceeded",
    "audit_target_authority_invalid",
    "immutable_object_missing",
    "immutable_object_hash_mismatch",
    "snapshot_evidence_invalid",
    "response_schema_authority_invalid",
    "semantic_context_projection_invalid",
]
PreflightScopeKindV1 = Literal["domain", "source"]

_REASONS = frozenset(
    {
        "semantic_context_byte_ceiling_exceeded",
        "audit_target_authority_invalid",
        "immutable_object_missing",
        "immutable_object_hash_mismatch",
        "snapshot_evidence_invalid",
        "response_schema_authority_invalid",
        "semantic_context_projection_invalid",
    }
)
_SCOPE_KINDS = frozenset({"domain", "source"})


class Protocol25PreflightError(Protocol22SchemaError):
    """Raised when zero-dispatch preflight authority is not closed."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol25PreflightError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol25PreflightError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class AuditContextPreflightEntryV1:
    schema_version: int
    audit_target_id: str
    work_item_id: str
    context_hash: str
    canonical_json_bytes: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_target_id",
        "work_item_id",
        "context_hash",
        "canonical_json_bytes",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "preflight entry schema_version")
        _schema(digest_value, self.audit_target_id, "preflight audit_target_id")
        _schema(digest_value, self.work_item_id, "preflight work_item_id")
        _schema(digest_value, self.context_hash, "preflight context_hash")
        _schema(
            positive_int,
            self.canonical_json_bytes,
            "preflight canonical_json_bytes",
        )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditContextPreflightEntryV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class AuditContextPreflightFailureV1:
    schema_version: int
    audit_target_id: str
    work_item_id: str
    scope_kind: PreflightScopeKindV1
    source_id: str
    domain_key: str | None
    reason_code: PreflightReasonV1
    projection_class: Literal["semantic-audit-context"]
    measured_canonical_json_bytes: int | None
    max_canonical_json_bytes: int
    provider_dispatch_count: Literal[0]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "audit_target_id",
        "work_item_id",
        "scope_kind",
        "source_id",
        "domain_key",
        "reason_code",
        "projection_class",
        "measured_canonical_json_bytes",
        "max_canonical_json_bytes",
        "provider_dispatch_count",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "preflight failure schema_version")
        _schema(digest_value, self.audit_target_id, "preflight audit_target_id")
        _schema(digest_value, self.work_item_id, "preflight work_item_id")
        _schema(one_of, self.scope_kind, _SCOPE_KINDS, "preflight scope_kind")
        _schema(safe_id, self.source_id, "preflight source_id")
        if self.scope_kind == "domain":
            if self.domain_key is None:
                raise Protocol25PreflightError(
                    "domain preflight failure requires domain_key"
                )
            _schema(digest_value, self.domain_key, "preflight domain_key")
        elif self.domain_key is not None:
            raise Protocol25PreflightError(
                "source preflight failure requires null domain_key"
            )
        _schema(one_of, self.reason_code, _REASONS, "preflight reason_code")
        _schema(
            literal,
            self.projection_class,
            "semantic-audit-context",
            "preflight projection_class",
        )
        if self.measured_canonical_json_bytes is not None:
            _schema(
                positive_int,
                self.measured_canonical_json_bytes,
                "preflight measured_canonical_json_bytes",
            )
        _schema(
            positive_int,
            self.max_canonical_json_bytes,
            "preflight max_canonical_json_bytes",
        )
        if self.provider_dispatch_count != 0:
            raise Protocol25PreflightError(
                "preflight failure requires zero provider dispatches"
            )
        if self.reason_code == "semantic_context_byte_ceiling_exceeded" and (
            self.measured_canonical_json_bytes is None
            or self.measured_canonical_json_bytes <= self.max_canonical_json_bytes
        ):
            raise Protocol25PreflightError(
                "semantic context bytes must exceed the preflight ceiling"
            )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditContextPreflightFailureV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class AuditContextPreflightResultV1:
    schema_version: int
    entries: tuple[AuditContextPreflightEntryV1, ...]
    failure: AuditContextPreflightFailureV1 | None
    max_canonical_json_bytes: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "entries",
        "failure",
        "max_canonical_json_bytes",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "preflight result schema_version")
        entries = tuple(self.entries)
        if any(not isinstance(item, AuditContextPreflightEntryV1) for item in entries):
            raise Protocol25PreflightError("preflight result entries are invalid")
        target_ids = tuple(item.audit_target_id for item in entries)
        if len(target_ids) != len(set(target_ids)):
            raise Protocol25PreflightError(
                "preflight result entries must have unique targets"
            )
        if (bool(entries)) == (self.failure is not None):
            raise Protocol25PreflightError(
                "preflight result must contain exactly success or failure"
            )
        if self.failure is not None and not isinstance(
            self.failure, AuditContextPreflightFailureV1
        ):
            raise Protocol25PreflightError("preflight result failure is invalid")
        _schema(
            positive_int,
            self.max_canonical_json_bytes,
            "preflight result max_canonical_json_bytes",
        )
        if any(
            item.canonical_json_bytes > self.max_canonical_json_bytes
            for item in entries
        ):
            raise Protocol25PreflightError("preflight success exceeds its byte ceiling")
        if (
            self.failure is not None
            and self.failure.max_canonical_json_bytes
            != self.max_canonical_json_bytes
        ):
            raise Protocol25PreflightError(
                "preflight failure and result byte ceilings disagree"
            )
        object.__setattr__(self, "entries", entries)

    @property
    def passed(self) -> bool:
        return self.failure is None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "entries": [item.to_json_dict() for item in self.entries],
            "failure": None if self.failure is None else self.failure.to_json_dict(),
            "max_canonical_json_bytes": self.max_canonical_json_bytes,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "AuditContextPreflightResultV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        entries = raw["entries"]
        if not isinstance(entries, list):
            raise Protocol25PreflightError("preflight result entries must be an array")
        failure = raw["failure"]
        return cls(
            schema_version=raw["schema_version"],
            entries=tuple(
                AuditContextPreflightEntryV1.from_json_dict(item) for item in entries
            ),
            failure=(
                None
                if failure is None
                else AuditContextPreflightFailureV1.from_json_dict(failure)
            ),
            max_canonical_json_bytes=raw["max_canonical_json_bytes"],
        )


__all__ = (
    "AuditContextPreflightEntryV1",
    "AuditContextPreflightFailureV1",
    "AuditContextPreflightResultV1",
    "PreflightReasonV1",
    "Protocol25PreflightError",
)
