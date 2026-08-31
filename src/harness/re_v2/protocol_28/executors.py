"""Closed protocol-2.8 producer/verifier execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
)


RoleV1 = Literal["producer", "verifier"]
_ROLES = frozenset({"producer", "verifier"})


class Protocol28ExecutorError(Protocol22SchemaError):
    """Raised when L4 executor authority is incomplete or inconsistent."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol28ExecutorError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol28ExecutorError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class L4ExecutorEntryV1:
    schema_version: int
    role: RoleV1
    inherited_executor_contract_hash: str
    agent_contract_hash: str
    response_schema_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "role",
        "inherited_executor_contract_hash",
        "agent_contract_hash",
        "response_schema_hash",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4ExecutorEntryV1.schema_version")
        _schema(one_of, self.role, _ROLES, "L4ExecutorEntryV1.role")
        for field in self.FIELDS[2:]:
            _schema(
                digest_value,
                getattr(self, field),
                f"L4ExecutorEntryV1.{field}",
            )

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "L4ExecutorEntryV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class L4ExecutorCatalogV1:
    schema_version: int
    entries: tuple[L4ExecutorEntryV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("schema_version", "entries")

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "L4ExecutorCatalogV1.schema_version")
        if not isinstance(self.entries, (list, tuple)) or any(
            not isinstance(item, L4ExecutorEntryV1) for item in self.entries
        ):
            raise Protocol28ExecutorError(
                "L4ExecutorCatalogV1.entries must contain executor entries"
            )
        entries = tuple(self.entries)
        if tuple(item.role for item in entries) != ("producer", "verifier"):
            raise Protocol28ExecutorError(
                "L4 executor catalog must contain producer then verifier"
            )
        if entries[0].agent_contract_hash == entries[1].agent_contract_hash:
            raise Protocol28ExecutorError(
                "producer and verifier require independent agent contracts"
            )
        object.__setattr__(self, "entries", entries)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def entry(self, role: RoleV1) -> L4ExecutorEntryV1:
        if role not in _ROLES:
            raise Protocol28ExecutorError(f"unknown L4 executor role: {role!r}")
        return next(item for item in self.entries if item.role == role)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "entries": [item.to_json_dict() for item in self.entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "L4ExecutorCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        entries = raw["entries"]
        if not isinstance(entries, (list, tuple)):
            raise Protocol28ExecutorError("L4ExecutorCatalogV1.entries must be an array")
        return cls(1, tuple(L4ExecutorEntryV1.from_json_dict(item) for item in entries))


def canonical_exhaustive_response_schema_bytes(role: RoleV1) -> bytes:
    """Return closed human- and machine-readable result authority for one role."""
    if role == "producer":
        title = "ExhaustiveEvidenceSliceV1"
        fields = (
            "schema_version", "slice_spec_id", "plan_entry_id", "target_kind",
            "source_id", "target_id", "category_id",
            "covered_primary_subject_ids", "covered_primary_source_record_ids",
            "covered_primary_evidence_ids", "evidence_anchors", "claims",
            "observations", "addressed_finding_ids", "unresolved_finding_ids",
            "rendered_explanation",
        )
    elif role == "verifier":
        title = "ExhaustiveVerificationV1"
        fields = (
            "schema_version", "slice_spec_id", "candidate_id",
            "verifier_policy_id", "verdict", "diagnostics",
            "assessed_primary_evidence_ids", "assessed_finding_ids",
        )
    else:
        raise Protocol28ExecutorError(f"unknown L4 response role: {role!r}")
    return canonical_json_bytes(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "required": list(fields),
            "schema_version": 1,
            "title": title,
            "type": "object",
            "x-echelon-contract": (
                "Exact closed object. Nested evidence, claim, observation, and "
                "diagnostic objects must match their named protocol-2.8 V1 schemas."
            ),
        }
    )


def build_l4_executor_catalog(
    *,
    inherited_executor_contract_hash: str,
    producer_agent_contract_hash: str,
    verifier_agent_contract_hash: str,
) -> L4ExecutorCatalogV1:
    return L4ExecutorCatalogV1(
        1,
        (
            L4ExecutorEntryV1(
                1,
                "producer",
                inherited_executor_contract_hash,
                producer_agent_contract_hash,
                content_digest(canonical_exhaustive_response_schema_bytes("producer")),
            ),
            L4ExecutorEntryV1(
                1,
                "verifier",
                inherited_executor_contract_hash,
                verifier_agent_contract_hash,
                content_digest(canonical_exhaustive_response_schema_bytes("verifier")),
            ),
        ),
    )


__all__ = (
    "L4ExecutorCatalogV1",
    "L4ExecutorEntryV1",
    "Protocol28ExecutorError",
    "RoleV1",
    "build_l4_executor_catalog",
    "canonical_exhaustive_response_schema_bytes",
)
