"""Deterministic strict authorial response schemas for compact baselines."""

from __future__ import annotations

from typing import Literal, Mapping

from jsonschema import Draft202012Validator

from harness.re_v2.canonical import canonical_json_bytes, content_digest

from .policies import (
    CompactBaselinePolicyParametersV1,
    build_compact_v1_policy_catalog,
    policy_for,
)


BaselineKind = Literal["domain-baseline", "source-overview"]


def _evidence_reference_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence_authority_id", "path", "start_line", "end_line"],
        "properties": {
            "evidence_authority_id": {
                "type": "string",
                "pattern": r"^sha256:[0-9a-f]{64}$",
            },
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
    }


def _claim_schema(policy: CompactBaselinePolicyParametersV1) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["statement", "evidence"],
        "properties": {
            "statement": {
                "type": "string",
                "minLength": policy.min_statement_utf8_bytes,
                "maxLength": policy.max_statement_utf8_bytes,
            },
            "evidence": {
                "type": "array",
                "minItems": 1,
                "maxItems": policy.max_evidence_refs_per_claim,
                "uniqueItems": True,
                "items": _evidence_reference_schema(),
            },
        },
    }


def _surface_schema(policy: CompactBaselinePolicyParametersV1) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "items", "not_established_reason_code"],
        "properties": {
            "status": {"enum": ["observed", "not_established"]},
            "items": {
                "type": "array",
                "maxItems": policy.max_claims_per_observed_surface,
                "uniqueItems": True,
                "items": _claim_schema(policy),
            },
            "not_established_reason_code": {
                "enum": [
                    "not_in_bounded_context",
                    "requires_deeper_analysis",
                    None,
                ]
            },
        },
        "allOf": [
            {
                "if": {
                    "properties": {"status": {"const": "observed"}},
                    "required": ["status"],
                },
                "then": {
                    "properties": {
                        "items": {"minItems": 1},
                        "not_established_reason_code": {"const": None},
                    }
                },
                "else": {
                    "properties": {
                        "items": {"maxItems": 0},
                        "not_established_reason_code": {
                            "enum": [
                                "not_in_bounded_context",
                                "requires_deeper_analysis",
                            ]
                        },
                    }
                },
            }
        ],
    }


def _unknown_schema(policy: CompactBaselinePolicyParametersV1) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["question", "reason_code", "inspected_evidence"],
        "properties": {
            "question": {
                "type": "string",
                "minLength": policy.min_question_utf8_bytes,
                "maxLength": policy.max_question_utf8_bytes,
            },
            "reason_code": {
                "enum": [
                    "not_in_bounded_context",
                    "conflicting_evidence",
                    "requires_deeper_analysis",
                ]
            },
            "inspected_evidence": {
                "type": "array",
                "maxItems": policy.max_inspected_refs_per_unknown,
                "uniqueItems": True,
                "items": _evidence_reference_schema(),
            },
        },
        "allOf": [
            {
                "if": {
                    "properties": {"reason_code": {"const": "conflicting_evidence"}},
                    "required": ["reason_code"],
                },
                "then": {
                    "properties": {
                        "inspected_evidence": {
                            "minItems": policy.min_conflicting_evidence_refs
                        }
                    }
                },
            }
        ],
    }


def authorial_response_schema(artifact_kind: BaselineKind | str) -> Mapping[str, object]:
    if artifact_kind not in {"domain-baseline", "source-overview"}:
        raise ValueError(f"unsupported authorial artifact kind: {artifact_kind!r}")
    entry = policy_for(build_compact_v1_policy_catalog(), "L1", artifact_kind)
    policy = entry.policy_parameters
    if not isinstance(policy, CompactBaselinePolicyParametersV1):  # pragma: no cover
        raise ValueError(f"artifact kind has no compact authorial policy: {artifact_kind}")
    surface = _surface_schema(policy)
    schema: dict[str, object] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "surfaces", "unknowns"],
        "properties": {
            "schema_version": {"const": 1},
            "surfaces": {
                "type": "object",
                "additionalProperties": False,
                "required": list(policy.surface_order),
                "properties": {
                    name: surface for name in policy.surface_order
                },
            },
            "unknowns": {
                "type": "array",
                "maxItems": policy.max_unknowns,
                "uniqueItems": True,
                "items": _unknown_schema(policy),
            },
        },
    }
    Draft202012Validator.check_schema(schema)
    return schema


def canonical_response_schema_bytes(artifact_kind: BaselineKind | str) -> bytes:
    return canonical_json_bytes(authorial_response_schema(artifact_kind))


def response_schema_hash(artifact_kind: BaselineKind | str) -> str:
    return content_digest(canonical_response_schema_bytes(artifact_kind))


__all__ = (
    "BaselineKind",
    "authorial_response_schema",
    "canonical_response_schema_bytes",
    "response_schema_hash",
)
