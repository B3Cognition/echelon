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
    digest = {"pattern": "^sha256:[0-9a-f]{64}$", "type": "string"}
    digest_array = {
        "items": digest,
        "type": "array",
        "uniqueItems": True,
    }

    def closed_object(
        fields: tuple[str, ...], properties: dict[str, object]
    ) -> dict[str, object]:
        return {
            "additionalProperties": False,
            "properties": properties,
            "required": list(fields),
            "type": "object",
        }

    if role == "producer":
        title = "ExhaustiveEvidenceSliceV1"
        fields = (
            "schema_version", "slice_spec_id", "plan_entry_id", "target_kind",
            "source_id", "target_id", "category_id",
            "covered_primary_subject_ids", "covered_primary_source_record_ids",
            "covered_primary_evidence_ids", "evidence_anchors", "claims",
            "observations", "addressed_finding_ids", "unresolved_finding_ids",
            "rendered_markdown",
        )
        anchor_fields = (
            "schema_version", "evidence_id", "source_id", "source_relative_path",
            "byte_start", "byte_end", "raw_hash",
        )
        claim_fields = (
            "schema_version", "claim_kind", "subject_ids", "evidence_anchor_ids",
            "statement",
        )
        observation_fields = (
            "schema_version", "disposition", "category_id", "subject_ids",
            "evidence_ids", "finding_ids", "detail",
        )
        definitions = {
            "EvidenceAnchorV1": closed_object(
                anchor_fields,
                {
                    "schema_version": {"const": 1},
                    "evidence_id": digest,
                    "source_id": {"minLength": 1, "type": "string"},
                    "source_relative_path": {"minLength": 1, "type": "string"},
                    "byte_start": {"minimum": 0, "type": "integer"},
                    "byte_end": {"minimum": 0, "type": "integer"},
                    "raw_hash": digest,
                },
            ),
            "ExhaustiveClaimV1": closed_object(
                claim_fields,
                {
                    "schema_version": {"const": 1},
                    "claim_kind": {
                        "enum": [
                            "behavioral", "boundary", "failure", "invariant",
                            "configuration", "security", "operational",
                            "negative-space",
                        ]
                    },
                    "subject_ids": digest_array,
                    "evidence_anchor_ids": digest_array,
                    "statement": {"maxLength": 4096, "type": "string"},
                },
            ),
            "ExhaustiveObservationV1": closed_object(
                observation_fields,
                {
                    "schema_version": {"const": 1},
                    "disposition": {
                        "enum": [
                            "applicable", "not-applicable", "unknown", "unresolved"
                        ]
                    },
                    "category_id": {"minLength": 1, "type": "string"},
                    "subject_ids": digest_array,
                    "evidence_ids": digest_array,
                    "finding_ids": digest_array,
                    "detail": {"maxLength": 4096, "type": "string"},
                },
            ),
        }
        properties = {
            "schema_version": {"const": 1},
            "slice_spec_id": {
                **digest,
                "description": "Copy top-level frozen-context slice_spec_id exactly.",
            },
            "plan_entry_id": {
                **digest,
                "description": "Copy top-level frozen-context plan_entry_id exactly.",
            },
            "target_kind": {"enum": ["domain", "source"]},
            "source_id": {"minLength": 1, "type": "string"},
            "target_id": {"minLength": 1, "type": "string"},
            "category_id": {"minLength": 1, "type": "string"},
            "covered_primary_subject_ids": digest_array,
            "covered_primary_source_record_ids": digest_array,
            "covered_primary_evidence_ids": digest_array,
            "evidence_anchors": {
                "items": {"$ref": "#/$defs/EvidenceAnchorV1"},
                "type": "array",
                "uniqueItems": True,
            },
            "claims": {
                "items": {"$ref": "#/$defs/ExhaustiveClaimV1"},
                "type": "array",
                "uniqueItems": True,
            },
            "observations": {
                "items": {"$ref": "#/$defs/ExhaustiveObservationV1"},
                "type": "array",
                "uniqueItems": True,
            },
            "addressed_finding_ids": digest_array,
            "unresolved_finding_ids": digest_array,
            "rendered_markdown": {"maxLength": 98_304, "type": "string"},
        }
    elif role == "verifier":
        title = "ExhaustiveVerificationV1"
        fields = (
            "schema_version", "slice_spec_id", "candidate_id",
            "verifier_policy_id", "verdict", "diagnostics",
            "verified_primary_evidence_ids", "assessed_finding_ids",
        )
        diagnostic_fields = (
            "schema_version", "candidate_id", "verifier_policy_id",
            "diagnostic_class", "subject_ids", "evidence_ids", "finding_ids",
            "detail",
        )
        definitions = {
            "ExhaustiveDiagnosticV1": closed_object(
                diagnostic_fields,
                {
                    "schema_version": {"const": 1},
                    "candidate_id": digest,
                    "verifier_policy_id": digest,
                    "diagnostic_class": {
                        "enum": [
                            "missing-planned-coverage", "unsupported-claim",
                            "contradictory-claim", "invalid-or-insufficient-evidence",
                            "incomplete-boundary-behavior",
                            "incomplete-failure-recovery-behavior",
                            "incomplete-negative-space",
                            "unresolved-assigned-l3-finding",
                            "malformed-result-contract",
                        ]
                    },
                    "subject_ids": digest_array,
                    "evidence_ids": digest_array,
                    "finding_ids": digest_array,
                    "detail": {"maxLength": 4096, "type": "string"},
                },
            )
        }
        properties = {
            "schema_version": {"const": 1},
            "slice_spec_id": {
                **digest,
                "description": "Copy top-level frozen-context slice_spec_id exactly.",
            },
            "candidate_id": {
                **digest,
                "description": "Copy top-level frozen-context candidate_id exactly.",
            },
            "verifier_policy_id": {
                **digest,
                "description": "Copy plan_entry.verifier_contract_hash exactly.",
            },
            "verdict": {"enum": ["PASS", "REPAIR"]},
            "diagnostics": {
                "items": {"$ref": "#/$defs/ExhaustiveDiagnosticV1"},
                "type": "array",
                "uniqueItems": True,
            },
            "verified_primary_evidence_ids": digest_array,
            "assessed_finding_ids": digest_array,
        }
    else:
        raise Protocol28ExecutorError(f"unknown L4 response role: {role!r}")
    schema = closed_object(fields, properties)
    schema.update(
        {
            "$defs": definitions,
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "schema_version": 1,
            "title": title,
            "x-echelon-contract": (
                "Exact closed object. Copy all scope and coverage identities exactly "
                "from the frozen context. Copy permitted evidence anchor objects and "
                "their anchor IDs exactly; an evidence ID is not an anchor ID. Digest "
                "arrays must be sorted and unique; the controller canonicalizes nested "
                "object collection order."
            ),
        }
    )
    return canonical_json_bytes(schema)


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
