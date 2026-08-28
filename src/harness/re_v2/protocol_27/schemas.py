"""Closed response schemas for protocol-2.7 synthesis artifacts."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from harness.re_v2.canonical import canonical_json_bytes

from .policies import SYNTHESIS_GENERATED_KINDS


_SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"

_REQUIRED_SECTIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "source-architecture": (
            "purpose",
            "structure",
            "flows",
            "dependencies",
            "risks",
        ),
        "source-contracts": (
            "interfaces",
            "data-contracts",
            "errors",
            "compatibility",
        ),
        "source-components": (
            "components",
            "responsibilities",
            "dependencies",
        ),
        "workspace-domain-summary": (
            "purpose",
            "participants",
            "interactions",
            "risks",
        ),
        "workspace-overview": (
            "purpose",
            "sources",
            "topology",
            "operations",
        ),
        "workspace-relationships": (
            "relationships",
            "data-flows",
            "dependencies",
            "risks",
        ),
        "workspace-contracts": (
            "interfaces",
            "shared-data",
            "errors",
            "compatibility",
        ),
    }
)

_SCOPE_BY_KIND: Mapping[str, str] = MappingProxyType(
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


class Protocol27SchemaContractError(ValueError):
    """Raised when a synthesis kind has no registered response contract."""


def required_section_ids(artifact_kind: str) -> tuple[str, ...]:
    try:
        return _REQUIRED_SECTIONS[artifact_kind]
    except KeyError as exc:
        raise Protocol27SchemaContractError(
            f"unsupported protocol-2.7 synthesis kind: {artifact_kind!r}"
        ) from exc


def synthesis_response_schema(artifact_kind: str) -> dict[str, object]:
    """Return the exact closed authorial schema for one generated kind."""
    section_ids = required_section_ids(artifact_kind)
    scope_kind = _SCOPE_BY_KIND[artifact_kind]
    nullable_safe_id = {
        "oneOf": [
            {"type": "null"},
            {"type": "string", "pattern": _SAFE_ID_PATTERN},
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "artifact_kind",
            "scope",
            "sections",
            "claims",
            "input_quality",
            "debt_refs",
        ],
        "properties": {
            "schema_version": {"const": 1},
            "artifact_kind": {"const": artifact_kind},
            "scope": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "schema_version",
                    "kind",
                    "source_id",
                    "workspace_domain_id",
                    "participant_ids",
                ],
                "properties": {
                    "schema_version": {"const": 1},
                    "kind": {"const": scope_kind},
                    "source_id": nullable_safe_id,
                    "workspace_domain_id": nullable_safe_id,
                    "participant_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 128,
                        "uniqueItems": True,
                        "items": {"type": "string", "pattern": _SAFE_ID_PATTERN},
                    },
                },
            },
            "sections": {
                "type": "array",
                "minItems": len(section_ids),
                "maxItems": len(section_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["section_id", "heading", "claim_ids"],
                    "properties": {
                        "section_id": {"enum": list(section_ids)},
                        "heading": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 160,
                        },
                        "claim_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 256,
                            "uniqueItems": True,
                            "items": {
                                "type": "string",
                                "pattern": _SAFE_ID_PATTERN,
                            },
                        },
                    },
                },
            },
            "claims": {
                "type": "array",
                "minItems": 1,
                "maxItems": 256,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim_id", "statement", "evidence"],
                    "properties": {
                        "claim_id": {"type": "string", "pattern": _SAFE_ID_PATTERN},
                        "statement": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 32,
                            "uniqueItems": True,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": [
                                    "authority_kind",
                                    "authority_id",
                                    "source_id",
                                ],
                                "properties": {
                                    "authority_kind": {
                                        "enum": [
                                            "authority-object",
                                            "dependency-artifact",
                                        ]
                                    },
                                    "authority_id": {
                                        "type": "string",
                                        "pattern": _DIGEST_PATTERN,
                                    },
                                    "source_id": nullable_safe_id,
                                },
                            },
                        },
                    },
                },
            },
            "input_quality": {"enum": ["complete", "partial"]},
            "debt_refs": {
                "type": "array",
                "maxItems": 128,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": _DIGEST_PATTERN},
            },
        },
    }


def canonical_synthesis_response_schema_bytes(artifact_kind: str) -> bytes:
    return canonical_json_bytes(synthesis_response_schema(artifact_kind))


if set(_REQUIRED_SECTIONS) != SYNTHESIS_GENERATED_KINDS:
    raise RuntimeError("protocol-2.7 response schema registry is incomplete")


__all__ = (
    "Protocol27SchemaContractError",
    "canonical_synthesis_response_schema_bytes",
    "required_section_ids",
    "synthesis_response_schema",
)
