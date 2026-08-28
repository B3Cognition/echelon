from __future__ import annotations

from copy import deepcopy
from typing import Mapping

import pytest
from jsonschema import Draft202012Validator, ValidationError

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.response_schemas import (
    authorial_response_schema,
    canonical_response_schema_bytes,
    response_schema_hash,
)


DOMAIN_SURFACES = (
    "responsibilities",
    "entry_points",
    "core_behavior",
    "failure_paths",
    "state_and_data",
    "external_contracts",
    "tests",
    "operational_constraints",
)

SOURCE_SURFACES = (
    "purpose",
    "runtime_shape",
    "major_entry_points",
    "intra_source_boundaries",
    "domain_relationships",
)


def evidence_ref(*, suffix: str = "1") -> dict[str, object]:
    return {
        "evidence_authority_id": "sha256:" + suffix * 64,
        "path": "src/orders.py",
        "start_line": 1,
        "end_line": 2,
    }


def not_established_surface() -> dict[str, object]:
    return {
        "status": "not_established",
        "items": [],
        "not_established_reason_code": "not_in_bounded_context",
    }


def observed_surface() -> dict[str, object]:
    return {
        "status": "observed",
        "items": [
            {
                "statement": "Handles order submission.",
                "evidence": [evidence_ref()],
            }
        ],
        "not_established_reason_code": None,
    }


def valid_candidate(artifact_kind: str) -> dict[str, object]:
    names = DOMAIN_SURFACES if artifact_kind == "domain-baseline" else SOURCE_SURFACES
    surfaces = {name: not_established_surface() for name in names}
    surfaces[names[0]] = observed_surface()
    return {"schema_version": 1, "surfaces": surfaces, "unknowns": []}


def _walk_objects(schema: object) -> list[Mapping[str, object]]:
    found: list[Mapping[str, object]] = []
    if isinstance(schema, Mapping):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            found.extend(_walk_objects(value))
    elif isinstance(schema, list):
        for value in schema:
            found.extend(_walk_objects(value))
    return found


@pytest.mark.parametrize(
    ("artifact_kind", "expected_surfaces"),
    (("domain-baseline", DOMAIN_SURFACES), ("source-overview", SOURCE_SURFACES)),
)
def test_response_schema_has_exact_authorial_fields_and_surface_map(
    artifact_kind: str,
    expected_surfaces: tuple[str, ...],
) -> None:
    schema = authorial_response_schema(artifact_kind)
    properties = schema["properties"]
    assert isinstance(properties, dict)

    assert set(properties) == {"schema_version", "surfaces", "unknowns"}
    surfaces = properties["surfaces"]
    assert isinstance(surfaces, dict)
    assert tuple(surfaces["required"]) == expected_surfaces
    assert tuple(surfaces["properties"]) == expected_surfaces
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("artifact_kind", ("domain-baseline", "source-overview"))
def test_every_response_schema_object_is_closed(artifact_kind: str) -> None:
    schema = authorial_response_schema(artifact_kind)

    objects = _walk_objects(schema)

    assert objects
    assert all(value.get("additionalProperties") is False for value in objects)


@pytest.mark.parametrize("artifact_kind", ("domain-baseline", "source-overview"))
def test_generated_schema_is_draft_2020_12_and_accepts_literal_candidate(
    artifact_kind: str,
) -> None:
    schema = authorial_response_schema(artifact_kind)
    Draft202012Validator.check_schema(schema)

    Draft202012Validator(schema).validate(valid_candidate(artifact_kind))


def test_domain_schema_rejects_source_or_mixed_surface_maps() -> None:
    validator = Draft202012Validator(authorial_response_schema("domain-baseline"))
    source = valid_candidate("source-overview")
    mixed = valid_candidate("domain-baseline")
    surfaces = mixed["surfaces"]
    assert isinstance(surfaces, dict)
    surfaces["purpose"] = not_established_surface()

    with pytest.raises(ValidationError):
        validator.validate(source)
    with pytest.raises(ValidationError):
        validator.validate(mixed)


def test_candidate_cannot_supply_controller_owned_fields() -> None:
    candidate = valid_candidate("domain-baseline")
    candidate["artifact"] = {"layer": "L1"}

    with pytest.raises(ValidationError):
        Draft202012Validator(authorial_response_schema("domain-baseline")).validate(candidate)


def test_surface_status_controls_claims_and_reason_nullability() -> None:
    validator = Draft202012Validator(authorial_response_schema("domain-baseline"))
    observed_without_claim = valid_candidate("domain-baseline")
    observed_without_claim["surfaces"]["responsibilities"] = {
        "status": "observed",
        "items": [],
        "not_established_reason_code": None,
    }
    not_established_with_claim = valid_candidate("domain-baseline")
    not_established_with_claim["surfaces"]["entry_points"] = {
        "status": "not_established",
        "items": observed_surface()["items"],
        "not_established_reason_code": "requires_deeper_analysis",
    }

    with pytest.raises(ValidationError):
        validator.validate(observed_without_claim)
    with pytest.raises(ValidationError):
        validator.validate(not_established_with_claim)


def test_conflicting_unknown_requires_two_inspected_evidence_refs() -> None:
    validator = Draft202012Validator(authorial_response_schema("domain-baseline"))
    candidate = valid_candidate("domain-baseline")
    candidate["unknowns"] = [
        {
            "question": "Which retry policy is authoritative?",
            "reason_code": "conflicting_evidence",
            "inspected_evidence": [evidence_ref()],
        }
    ]

    with pytest.raises(ValidationError):
        validator.validate(candidate)

    candidate["unknowns"][0]["inspected_evidence"].append(evidence_ref(suffix="2"))
    validator.validate(candidate)


def test_evidence_ranges_are_positive_and_references_unique() -> None:
    validator = Draft202012Validator(authorial_response_schema("domain-baseline"))
    candidate = valid_candidate("domain-baseline")
    claim = candidate["surfaces"]["responsibilities"]["items"][0]
    claim["evidence"] = [evidence_ref(), deepcopy(evidence_ref())]

    with pytest.raises(ValidationError):
        validator.validate(candidate)

    claim["evidence"] = [evidence_ref()]
    claim["evidence"][0]["start_line"] = 0
    with pytest.raises(ValidationError):
        validator.validate(candidate)


def test_response_schema_bytes_and_hash_are_restart_stable() -> None:
    for kind in ("domain-baseline", "source-overview"):
        first = canonical_response_schema_bytes(kind)
        second = canonical_response_schema_bytes(kind)
        assert first == second
        assert response_schema_hash(kind) == content_digest(first)


def test_unknown_artifact_kind_has_no_authorial_schema() -> None:
    with pytest.raises(ValueError, match="unsupported authorial artifact kind"):
        authorial_response_schema("workspace-synthesis")
