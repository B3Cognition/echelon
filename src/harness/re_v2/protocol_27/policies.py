"""Closed synthesis artifact, producer, verifier, and attempt policies."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    safe_id,
)


SYNTHESIS_GENERATED_KINDS = frozenset(
    {
        "source-architecture",
        "source-contracts",
        "source-components",
        "workspace-domain-summary",
        "workspace-overview",
        "workspace-relationships",
        "workspace-contracts",
    }
)

_SCOPE_BY_KIND = MappingProxyType(
    {
        "source-architecture": "source",
        "source-contracts": "source",
        "source-components": "source",
        "workspace-domain-summary": "workspace-domain",
        "workspace-overview": "workspace",
        "workspace-relationships": "workspace",
        "workspace-contracts": "workspace",
    }
)
_DEPENDENCIES_BY_KIND = MappingProxyType(
    {
        "source-architecture": ("source-overview-projection",),
        "source-contracts": ("source-overview-projection",),
        "source-components": ("source-overview-projection",),
        "workspace-domain-summary": (
            "source-architecture",
            "source-components",
            "source-contracts",
        ),
        "workspace-overview": (
            "source-architecture",
            "source-components",
            "source-overview-projection",
            "workspace-domain-summary",
        ),
        "workspace-relationships": (
            "source-architecture",
            "source-contracts",
            "workspace-domain-summary",
        ),
        "workspace-contracts": (
            "source-contracts",
            "workspace-relationships",
        ),
    }
)


class Protocol27PolicyError(Protocol22SchemaError):
    """Raised when synthesis policy broadens the approved closed contract."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol27PolicyError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol27PolicyError(str(exc)) from exc


def _safe_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol27PolicyError(f"{field} must be an array")
    result = tuple(_schema(safe_id, item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise Protocol27PolicyError(f"{field} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class SynthesisImplementationAuthorityV1:
    schema_version: int
    producer_authority_hash: str
    executor_contract_hash: str
    verifier_authority_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "producer_authority_hash",
        "executor_contract_hash",
        "verifier_authority_hash",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "implementation authority schema")
        for field in self.FIELDS[1:]:
            _schema(digest_value, getattr(self, field), field)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisImplementationAuthorityV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisPolicyEntryV1:
    schema_version: int
    artifact_kind: str
    scope_kind: str
    required_artifact_kinds: tuple[str, ...]
    max_provider_attempts: int
    max_generation_attempts: int
    max_result_contract_retries: int
    max_artifact_contract_retries: int
    max_semantic_repair_rounds: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_kind",
        "scope_kind",
        "required_artifact_kinds",
        "max_provider_attempts",
        "max_generation_attempts",
        "max_result_contract_retries",
        "max_artifact_contract_retries",
        "max_semantic_repair_rounds",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis policy schema")
        kind = _schema(
            one_of,
            self.artifact_kind,
            SYNTHESIS_GENERATED_KINDS,
            "synthesis artifact kind",
        )
        expected_scope = _SCOPE_BY_KIND[kind]
        if self.scope_kind != expected_scope:
            raise Protocol27PolicyError(
                f"{kind} scope must be {expected_scope}"
            )
        dependencies = _safe_tuple(
            self.required_artifact_kinds,
            f"{kind} required dependency kinds",
        )
        if dependencies != _DEPENDENCIES_BY_KIND[kind]:
            raise Protocol27PolicyError(
                f"{kind} dependency taxonomy differs from the closed policy"
            )
        if (
            self.max_provider_attempts,
            self.max_generation_attempts,
            self.max_result_contract_retries,
            self.max_artifact_contract_retries,
        ) != (2, 2, 1, 1):
            raise Protocol27PolicyError(
                "synthesis policy requires the fixed bounded attempt policy (2, 2, 1, 1)"
            )
        if self.max_semantic_repair_rounds != 0:
            raise Protocol27PolicyError(
                "synthesis policy does not permit a semantic repair round"
            )
        object.__setattr__(self, "required_artifact_kinds", dependencies)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            field: (
                list(getattr(self, field))
                if field == "required_artifact_kinds"
                else getattr(self, field)
            )
            for field in self.FIELDS
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisPolicyEntryV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisPolicyCatalogV1:
    schema_version: int
    goal: str
    producer_id: str
    producer_protocol_version: str
    verifier_id: str
    verifier_version: str
    implementation_authority: SynthesisImplementationAuthorityV1
    entries: tuple[SynthesisPolicyEntryV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "goal",
        "producer_id",
        "producer_protocol_version",
        "verifier_id",
        "verifier_version",
        "implementation_authority",
        "entries",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis policy catalog schema")
        _schema(literal, self.goal, "workspace-synthesis", "synthesis goal")
        _schema(literal, self.producer_id, "echelon.re-synthesizer", "producer ID")
        _schema(literal, self.producer_protocol_version, "2.7", "producer protocol")
        _schema(literal, self.verifier_id, "re-v2-synthesis-verifier", "verifier ID")
        _schema(literal, self.verifier_version, "1", "verifier version")
        if not isinstance(
            self.implementation_authority, SynthesisImplementationAuthorityV1
        ):
            raise Protocol27PolicyError("synthesis implementation authority is invalid")
        if not isinstance(self.entries, (list, tuple)) or any(
            not isinstance(item, SynthesisPolicyEntryV1) for item in self.entries
        ):
            raise Protocol27PolicyError("synthesis policy entries are invalid")
        entries = tuple(self.entries)
        kinds = tuple(item.artifact_kind for item in entries)
        if kinds != tuple(sorted(SYNTHESIS_GENERATED_KINDS)):
            raise Protocol27PolicyError(
                "synthesis policy catalog must register every generated kind exactly once"
            )
        object.__setattr__(self, "entries", entries)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def entry_for(self, artifact_kind: str) -> SynthesisPolicyEntryV1:
        matches = [item for item in self.entries if item.artifact_kind == artifact_kind]
        if len(matches) != 1:
            raise Protocol27PolicyError(
                f"synthesis policy has no unique entry for {artifact_kind!r}"
            )
        return matches[0]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "goal": self.goal,
            "producer_id": self.producer_id,
            "producer_protocol_version": self.producer_protocol_version,
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "implementation_authority": self.implementation_authority.to_json_dict(),
            "entries": [item.to_json_dict() for item in self.entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisPolicyCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        entries = raw["entries"]
        if not isinstance(entries, (list, tuple)):
            raise Protocol27PolicyError("synthesis policy entries must be an array")
        return cls(
            schema_version=raw["schema_version"],
            goal=raw["goal"],
            producer_id=raw["producer_id"],
            producer_protocol_version=raw["producer_protocol_version"],
            verifier_id=raw["verifier_id"],
            verifier_version=raw["verifier_version"],
            implementation_authority=SynthesisImplementationAuthorityV1.from_json_dict(
                raw["implementation_authority"]
            ),
            entries=tuple(SynthesisPolicyEntryV1.from_json_dict(item) for item in entries),
        )


def build_synthesis_policy_catalog(
    authority: SynthesisImplementationAuthorityV1,
) -> SynthesisPolicyCatalogV1:
    if not isinstance(authority, SynthesisImplementationAuthorityV1):
        raise Protocol27PolicyError("synthesis policy requires implementation authority")
    entries = tuple(
        SynthesisPolicyEntryV1(
            schema_version=1,
            artifact_kind=kind,
            scope_kind=_SCOPE_BY_KIND[kind],
            required_artifact_kinds=_DEPENDENCIES_BY_KIND[kind],
            max_provider_attempts=2,
            max_generation_attempts=2,
            max_result_contract_retries=1,
            max_artifact_contract_retries=1,
            max_semantic_repair_rounds=0,
        )
        for kind in sorted(SYNTHESIS_GENERATED_KINDS)
    )
    return SynthesisPolicyCatalogV1(
        schema_version=1,
        goal="workspace-synthesis",
        producer_id="echelon.re-synthesizer",
        producer_protocol_version="2.7",
        verifier_id="re-v2-synthesis-verifier",
        verifier_version="1",
        implementation_authority=authority,
        entries=entries,
    )


__all__ = (
    "Protocol27PolicyError",
    "SYNTHESIS_GENERATED_KINDS",
    "SynthesisImplementationAuthorityV1",
    "SynthesisPolicyCatalogV1",
    "SynthesisPolicyEntryV1",
    "build_synthesis_policy_catalog",
)

