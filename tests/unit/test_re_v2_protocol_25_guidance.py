from __future__ import annotations

from dataclasses import replace
import unicodedata

import pytest

from tests.re_v2_protocol_22_fixtures import digest


def _bindings() -> dict[str, object]:
    return {
        "parent_manifest_hash": digest("parent-manifest"),
        "parent_terminal_event_hash": digest("parent-terminal"),
        "accepted_audit_candidate_hashes": (digest("candidate"),),
        "unresolved_audit_target_ids": (digest("target"),),
        "audit_epoch_id": None,
        "closure_root_hash": None,
        "unresolved_finding_ids": (),
    }


@pytest.mark.unit
def test_custom_guidance_normalizes_text_and_disables_automation() -> None:
    from harness.re_v2.protocol_25.guidance import custom_guidance_policy

    composed = "  Cafe\u0301 decision\r\n"
    policy = custom_guidance_policy(composed)

    assert policy.kind == "custom"
    assert policy.answer == unicodedata.normalize("NFC", composed).strip()
    assert policy.accept_residual_debt is False
    assert policy.automatic_successor_limit == 0
    assert policy.automation_root_manifest_hash is None
    assert policy.successor_index == 0


@pytest.mark.unit
def test_recommended_guidance_is_fixed_and_nonautomatic() -> None:
    from harness.re_v2.protocol_25.guidance import (
        RECOMMENDED_GUIDANCE_TEXT,
        recommended_guidance_policy,
    )

    policy = recommended_guidance_policy()

    assert policy.answer == RECOMMENDED_GUIDANCE_TEXT
    assert policy.kind == "recommended"
    assert policy.accept_residual_debt is False
    assert policy.automatic_successor_limit == 0
    assert policy.automation_root_manifest_hash is None
    assert policy.successor_index == 0


@pytest.mark.unit
def test_banzai_guidance_binds_exactly_one_successor_to_root() -> None:
    from harness.re_v2.protocol_25.guidance import banzai_guidance_policy

    root = digest("automation-root")
    policy = banzai_guidance_policy(root)

    assert policy.kind == "banzai"
    assert policy.accept_residual_debt is True
    assert policy.automatic_successor_limit == 1
    assert policy.automation_root_manifest_hash == root
    assert policy.successor_index == 1


@pytest.mark.unit
def test_guidance_policy_rejects_broadened_custom_or_banzai_authority() -> None:
    from harness.re_v2.protocol_25.guidance import (
        GuidancePolicyV1,
        RECOMMENDED_GUIDANCE_TEXT,
        custom_guidance_policy,
    )

    with pytest.raises(ValueError, match="custom guidance cannot"):
        replace(custom_guidance_policy("decision"), accept_residual_debt=True)
    with pytest.raises(ValueError, match="exactly one"):
        GuidancePolicyV1(
            kind="banzai",
            answer=RECOMMENDED_GUIDANCE_TEXT,
            accept_residual_debt=True,
            automatic_successor_limit=2,
            automation_root_manifest_hash=digest("root"),
            successor_index=1,
        )


@pytest.mark.unit
def test_guidance_directive_round_trips_exact_authority() -> None:
    from harness.re_v2.protocol_25.guidance import (
        GuidanceDirectiveV1,
        build_guidance_directive,
        recommended_guidance_policy,
    )

    directive = build_guidance_directive(
        policy=recommended_guidance_policy(),
        **_bindings(),
    )

    assert GuidanceDirectiveV1.from_json_dict(directive.to_json_dict()) == directive
    assert directive.identity.startswith("sha256:")
    assert directive.parent_manifest_hash == digest("parent-manifest")
    assert directive.unresolved_audit_target_ids == (digest("target"),)


@pytest.mark.unit
def test_legacy_full_guidance_decodes_as_nonautomatic_custom() -> None:
    from harness.re_v2.protocol_25.guidance import GuidanceDirectiveV1

    legacy = {
        "accepted_audit_candidate_hashes": [digest("candidate")],
        "answer": "Use the authenticated bounded context.",
        "audit_epoch_id": None,
        "closure_root_hash": None,
        "parent_manifest_hash": digest("parent-manifest"),
        "parent_terminal_event_hash": digest("parent-terminal"),
        "schema_version": 1,
        "unresolved_audit_target_ids": [digest("target")],
        "unresolved_finding_ids": [],
    }

    directive = GuidanceDirectiveV1.from_json_dict(legacy)

    assert directive.kind == "custom"
    assert directive.accept_residual_debt is False
    assert directive.automatic_successor_limit == 0
    assert directive.automation_root_manifest_hash is None
    assert directive.successor_index == 0
    assert directive.to_json_dict()["kind"] == "custom"


@pytest.mark.unit
def test_guidance_rejects_unbound_text_unknown_fields_and_unsorted_authority() -> None:
    from harness.re_v2.protocol_25.guidance import (
        GuidanceDirectiveV1,
        build_guidance_directive,
        custom_guidance_policy,
    )

    with pytest.raises(ValueError, match="fields"):
        GuidanceDirectiveV1.from_json_dict(
            {"answer": "text only", "schema_version": 1}
        )

    directive = build_guidance_directive(
        policy=custom_guidance_policy("decision"),
        **_bindings(),
    )
    with pytest.raises(ValueError, match="fields"):
        GuidanceDirectiveV1.from_json_dict(
            {**directive.to_json_dict(), "unexpected": True}
        )

    ordered = tuple(sorted((digest("candidate-a"), digest("candidate-b"))))
    with pytest.raises(ValueError, match="sorted"):
        replace(directive, accepted_audit_candidate_hashes=tuple(reversed(ordered)))
