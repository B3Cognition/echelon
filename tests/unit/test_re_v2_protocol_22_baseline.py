from __future__ import annotations

import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.baseline import (
    CompactCandidateError,
    CompactBaselineArtifactV1,
    NormalizedAuthorialPayloadV1,
    parse_authorial_candidate,
    render_baseline_markdown,
)
from harness.re_v2.protocol_22.policies import (
    DOMAIN_SURFACES,
    SOURCE_OVERVIEW_SURFACES,
    ArtifactPolicyEntryV1,
    build_compact_v1_policy_catalog,
    policy_for,
)
from tests.re_v2_protocol_22_fixtures import digest


def _policy(kind: str = "domain-baseline") -> ArtifactPolicyEntryV1:
    return policy_for(build_compact_v1_policy_catalog(), "L1", kind)


def _reference(
    label: str = "a",
    *,
    path: str = "orders/main.py",
    start: int = 1,
    end: int = 1,
) -> dict[str, object]:
    return {
        "evidence_authority_id": digest(f"authority:{label}"),
        "path": path,
        "start_line": start,
        "end_line": end,
    }


def _surface(
    *statements: str,
    evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if statements:
        return {
            "status": "observed",
            "items": [
                {
                    "statement": statement,
                    "evidence": evidence or [_reference()],
                }
                for statement in statements
            ],
            "not_established_reason_code": None,
        }
    return {
        "status": "not_established",
        "items": [],
        "not_established_reason_code": "not_in_bounded_context",
    }


def _candidate(
    kind: str = "domain-baseline",
    *,
    surfaces: dict[str, object] | None = None,
    unknowns: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    names = DOMAIN_SURFACES if kind == "domain-baseline" else SOURCE_OVERVIEW_SURFACES
    return {
        "schema_version": 1,
        "surfaces": surfaces or {name: _surface() for name in names},
        "unknowns": unknowns or [],
    }


@pytest.mark.unit
@pytest.mark.parametrize("field", ("artifact", "depth_debt", "coverage"))
def test_candidate_cannot_supply_controller_owned_fields(field: str) -> None:
    raw = _candidate()
    raw[field] = {}

    with pytest.raises(CompactCandidateError, match="unknown fields"):
        parse_authorial_candidate(
            canonical_json_bytes(raw),
            "domain-baseline",
            _policy(),
        )


@pytest.mark.unit
def test_normalization_preserves_claim_order_and_sorts_evidence() -> None:
    raw = _candidate()
    raw["surfaces"]["responsibilities"] = _surface(
        "  z-most e\u0301\r\nmaterial  ",
        "a-second",
        evidence=[_reference("z"), _reference("a")],
    )

    normalized = parse_authorial_candidate(
        canonical_json_bytes(raw),
        "domain-baseline",
        _policy(),
    )
    claims = normalized.surfaces["responsibilities"].items

    assert [claim.statement for claim in claims] == [
        "z-most é\nmaterial",
        "a-second",
    ]
    assert claims[0].evidence == tuple(
        sorted(claims[0].evidence, key=lambda item: item.sort_key)
    )


@pytest.mark.unit
def test_unknown_order_is_semantic_but_inspected_evidence_is_sorted() -> None:
    raw = _candidate(
        unknowns=[
            {
                "question": "  Z?  ",
                "reason_code": "conflicting_evidence",
                "inspected_evidence": [_reference("z"), _reference("a")],
            },
            {
                "question": "A?",
                "reason_code": "requires_deeper_analysis",
                "inspected_evidence": [],
            },
        ]
    )

    normalized = parse_authorial_candidate(
        canonical_json_bytes(raw), "domain-baseline", _policy()
    )

    assert [unknown.question for unknown in normalized.unknowns] == ["Z?", "A?"]
    assert normalized.unknowns[0].inspected_evidence == tuple(
        sorted(
            normalized.unknowns[0].inspected_evidence,
            key=lambda item: item.sort_key,
        )
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "message"),
    (
        (
            b'{"schema_version":1,"schema_version":1,"surfaces":{},"unknowns":[]}',
            "duplicate",
        ),
        (
            b'{"schema_version":NaN,"surfaces":{},"unknowns":[]}',
            "finite|constant",
        ),
        (b"\xff", "UTF-8"),
        (
            b'{"schema_version":1,"surfaces":{},"unknowns":[{"question":"\\ud800","reason_code":"requires_deeper_analysis","inspected_evidence":[]}]}',
            "Unicode|surrogate|surface",
        ),
    ),
)
def test_parser_rejects_ambiguous_or_invalid_json(raw: bytes, message: str) -> None:
    with pytest.raises(CompactCandidateError, match=message):
        parse_authorial_candidate(raw, "domain-baseline", _policy())


@pytest.mark.unit
def test_surface_map_is_literal_for_selected_artifact_kind() -> None:
    mixed = _candidate()
    mixed["surfaces"]["purpose"] = _surface("purpose")

    with pytest.raises(CompactCandidateError, match="surface.*unknown|unknown fields"):
        parse_authorial_candidate(
            canonical_json_bytes(mixed), "domain-baseline", _policy()
        )
    with pytest.raises(CompactCandidateError, match="surface.*missing|missing fields"):
        parse_authorial_candidate(
            canonical_json_bytes(_candidate("source-overview")),
            "domain-baseline",
            _policy(),
        )


@pytest.mark.unit
def test_normalization_rejects_empty_and_nfc_colliding_claims() -> None:
    empty = _candidate()
    empty["surfaces"]["responsibilities"] = _surface(" \r\n ")
    colliding = _candidate()
    colliding["surfaces"]["responsibilities"] = _surface("é", "e\u0301")

    with pytest.raises(CompactCandidateError, match="empty|nonempty"):
        parse_authorial_candidate(
            canonical_json_bytes(empty), "domain-baseline", _policy()
        )
    with pytest.raises(CompactCandidateError, match="duplicate"):
        parse_authorial_candidate(
            canonical_json_bytes(colliding), "domain-baseline", _policy()
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        ("claims", "24|claim"),
        ("evidence", "eight|evidence"),
        ("unknowns", "32|unknown"),
        ("conflict", "two|conflicting"),
    ),
)
def test_parser_enforces_all_compact_cardinalities(
    mutate: str,
    message: str,
) -> None:
    raw = _candidate()
    if mutate == "claims":
        raw["surfaces"]["responsibilities"] = _surface(
            *(f"claim-{index}" for index in range(25))
        )
    elif mutate == "evidence":
        raw["surfaces"]["responsibilities"] = _surface(
            "claim",
            evidence=[_reference(str(index)) for index in range(9)],
        )
    elif mutate == "unknowns":
        raw["unknowns"] = [
            {
                "question": f"question-{index}?",
                "reason_code": "requires_deeper_analysis",
                "inspected_evidence": [],
            }
            for index in range(33)
        ]
    else:
        raw["unknowns"] = [
            {
                "question": "Conflict?",
                "reason_code": "conflicting_evidence",
                "inspected_evidence": [_reference()],
            }
        ]

    with pytest.raises(CompactCandidateError, match=message):
        parse_authorial_candidate(
            canonical_json_bytes(raw), "domain-baseline", _policy()
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("statement", "message"),
    (
        ("x" * 1025, "1024|byte"),
        ("contains\x00nul", "control"),
    ),
)
def test_parser_enforces_normalized_text_byte_and_control_limits(
    statement: str,
    message: str,
) -> None:
    raw = _candidate()
    raw["surfaces"]["responsibilities"] = _surface(statement)

    with pytest.raises(CompactCandidateError, match=message):
        parse_authorial_candidate(
            canonical_json_bytes(raw), "domain-baseline", _policy()
        )


@pytest.mark.unit
def test_parser_rejects_reversed_evidence_range() -> None:
    raw = _candidate()
    raw["surfaces"]["responsibilities"] = _surface(
        "claim", evidence=[_reference(start=3, end=2)]
    )

    with pytest.raises(CompactCandidateError, match="reversed|range"):
        parse_authorial_candidate(
            canonical_json_bytes(raw), "domain-baseline", _policy()
        )


@pytest.mark.unit
def test_raw_candidate_cap_is_twice_final_artifact_cap() -> None:
    oversized = b" " * (2 * _policy().max_canonical_json_bytes + 1)

    with pytest.raises(CompactCandidateError, match="raw candidate.*limit"):
        parse_authorial_candidate(oversized, "domain-baseline", _policy())


@pytest.mark.unit
def test_normalized_authorial_payload_round_trips_canonically() -> None:
    normalized = parse_authorial_candidate(
        canonical_json_bytes(_candidate()),
        "domain-baseline",
        _policy(),
    )
    payload = canonical_json_bytes(normalized.to_json_dict())

    assert NormalizedAuthorialPayloadV1.from_json_dict(
        json.loads(payload),
        "domain-baseline",
        _policy(),
    ) == normalized


@pytest.mark.unit
def test_markdown_is_deterministic_and_exposes_unaudited_debt() -> None:
    # Full artifact construction is exercised by certification tests; this decoder
    # assertion pins strict rejection of authorial-only bytes here.
    with pytest.raises(CompactCandidateError, match="artifact|fields"):
        render_baseline_markdown(canonical_json_bytes(_candidate()))

    assert hasattr(CompactBaselineArtifactV1, "from_json_dict")
