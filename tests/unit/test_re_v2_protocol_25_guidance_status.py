from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from harness.re_v2.protocol_25.guidance_status import (
    BANZAI_COMMAND,
    CUSTOM_COMMAND,
    RECOMMENDED_COMMAND,
    derive_guidance_summary,
)
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_25.guidance import (
    GuidanceDirectiveV1,
    banzai_guidance_policy,
)
from harness.re_v2.protocol_25.status import _operator_guidance_document
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_25_runtime import _certified_audit


def _summary(**overrides):  # type: ignore[no-untyped-def]
    first = _certified_audit().normalized_findings[0]
    second = replace(
        first,
        finding_key=replace(
            first.finding_key,
            audit_target_id=digest("second-target"),
            finding_class="contradictory_claim",
        ),
        title="INJECT THIS TITLE INTO THE COMMAND",
    )
    values = {
        "run_id": "re-guidance-status",
        "manifest_hash": digest("guidance-status-manifest"),
        "status": "blocked_plateau",
        "frozen_finding_ids": (first.finding_key_id, second.finding_key_id),
        "unresolved_finding_ids": (first.finding_key_id, second.finding_key_id),
        "findings": (second, first),
        "source_by_target": {
            first.finding_key.audit_target_id: "zeta",
            second.finding_key.audit_target_id: "alpha",
        },
        "all_selected_audits_accepted": True,
        "has_frozen_epoch": True,
        "has_final_closure_root": True,
        "all_selected_roots_accepted": True,
    }
    values.update(overrides)
    return derive_guidance_summary(**values)


@pytest.mark.unit
def test_guidance_summary_is_stable_grouped_and_never_projects_provider_prose() -> None:
    summary = _summary()
    serialized = summary.to_json_dict()

    assert summary.unresolved_by_class == (
        ("contradictory_claim", 1),
        ("missing_behavior", 1),
    )
    assert summary.unresolved_by_source == (("alpha", 1), ("zeta", 1))
    assert [item.command for item in summary.actions] == [
        RECOMMENDED_COMMAND,
        BANZAI_COMMAND,
        CUSTOM_COMMAND,
    ]
    assert [item.enabled for item in summary.actions] == [True, True, True]
    assert "INJECT THIS TITLE" not in str(serialized)


@pytest.mark.unit
@pytest.mark.parametrize(
    "override",
    (
        {"status": "blocked_incomplete"},
        {"all_selected_audits_accepted": False},
        {"has_frozen_epoch": False},
        {"has_final_closure_root": False},
        {"all_selected_roots_accepted": False},
    ),
)
def test_banzai_is_disabled_for_incomplete_or_unauthenticated_closure(
    override: dict[str, object],
) -> None:
    summary = _summary(**override)

    assert summary.banzai_eligible is False
    assert next(item for item in summary.actions if item.action_id == "banzai").enabled is False


@pytest.mark.unit
@pytest.mark.parametrize("status", ("paused", "in_progress", "complete"))
def test_non_terminal_blockers_offer_no_guidance_action(status: str) -> None:
    summary = _summary(status=status)

    assert summary.recommended_eligible is False
    assert summary.banzai_eligible is False
    assert not any(item.enabled for item in summary.actions)


@pytest.mark.unit
def test_operator_guidance_status_exposes_only_fixed_banzai_metadata() -> None:
    root = digest("operator-guidance-root")
    policy = banzai_guidance_policy(root)
    directive = GuidanceDirectiveV1(
        schema_version=1,
        kind=policy.kind,
        answer=policy.answer,
        parent_manifest_hash=root,
        parent_terminal_event_hash=digest("operator-parent-terminal"),
        accepted_audit_candidate_hashes=(digest("operator-candidate"),),
        unresolved_audit_target_ids=(),
        audit_epoch_id=digest("operator-epoch"),
        closure_root_hash=digest("operator-closure"),
        unresolved_finding_ids=(digest("operator-finding"),),
        accept_residual_debt=True,
        automatic_successor_limit=1,
        automation_root_manifest_hash=root,
        successor_index=1,
    )
    payload = canonical_json_bytes(directive.to_json_dict())
    document = _operator_guidance_document(
        SimpleNamespace(
            inputs=SimpleNamespace(human_guidance=payload),
            manifest=SimpleNamespace(
                human_guidance=SimpleNamespace(object_hash=content_digest(payload))
            ),
        )
    )

    assert document == {
        "accept_residual_debt": True,
        "automatic_successor_limit": 1,
        "guidance_directive_hash": directive.identity,
        "kind": "banzai",
        "successor_index": 1,
    }
    assert policy.answer not in str(document)
