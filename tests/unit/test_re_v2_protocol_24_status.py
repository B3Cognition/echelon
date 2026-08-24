from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from harness.re_v2.protocol_22.controller import Protocol22ControllerResult
from harness.re_v2.protocol_24.controller import Protocol24Controller
from harness.re_v2.protocol_24.status import (
    protocol_24_status_document,
    render_protocol_24_status,
)
from harness.re_v2.status import render_v2_status
from tests.integration.test_re_v2_protocol_24_controller import _child_context
from tests.unit.test_re_v2_protocol_22_controller import _ScriptedProvider


@pytest.mark.unit
def test_complete_l2_status_reports_selected_scope_without_full_quality_claim(
    tmp_path: Path,
) -> None:
    context, provider = _child_context(
        tmp_path,
        paused=False,
        provider_mode="cli",
        source_domains={"api": ("orders", "users")},
    )
    result = Protocol24Controller(context).run_until_stopped()
    assert isinstance(result, Protocol22ControllerResult)
    assert result.status == "completed"

    document = protocol_24_status_document(
        context.paths.root.parent,
        context=context,
    )
    human = render_protocol_24_status(
        context.paths.root.parent,
        context=context,
    )

    assert provider is not None
    assert document["status"] == "complete"
    assert document["banner"] == "L2 SELECTED SCOPE COMPLETE"
    assert document["completion_scope"] == "selected L2 scope only"
    assert document["lineage"]["direct_parent_run_id"] == (
        context.inputs.parent_authority_bundle.direct_parent_run_id
    )
    assert document["selection"]["target_layer"] == "L2"
    assert document["selection"]["selected_domains"] == 1
    assert document["artifact_counts"]["adopted"] == len(
        context.inputs.parent_authority_bundle.artifacts
    )
    assert document["artifact_counts"]["generated_l2"] == 6
    assert document["artifact_counts"]["selected_l2"]["accepted"] == 6
    assert document["artifact_counts"]["selected_l2"]["required"] == 6
    assert document["domains"][0]["state"] == "complete"
    assert document["domains"][0]["coverage"] is not None
    assert document["sources"][0]["domains"]["intentionally_unselected"] == 1
    assert [item["state"] for item in document["domains"]] == [
        "complete",
        "not_requested",
    ]
    assert document["source_roots"][0]["projection_status"] == "present"
    assert document["not_run"] == {
        "exhaustive_re": "not run",
        "semantic_audit": "not run",
        "workspace_synthesis": "not run",
    }
    assert document["next_action"] == "none — selected L2 scope is complete"
    assert document["telemetry"]["provider_observations"][0]["provider"] == "codex"
    assert document["telemetry"]["adoption_validation_duration_ms"] >= 0
    assert document["telemetry"]["dispatches_by_attempt_kind"]["initial_generation"] > 0
    assert document["budget"]["tokens"]["trusted_observed"] > 0
    assert "full quality" not in human.lower()
    assert human.endswith("L2 SELECTED SCOPE COMPLETE\n")


@pytest.mark.unit
def test_paused_l2_status_is_explicitly_continuable(tmp_path: Path) -> None:
    context, _provider = _child_context(tmp_path, paused=True, provider_mode="cli")

    document = protocol_24_status_document(
        context.paths.root.parent,
        context=context,
    )
    human = render_protocol_24_status(
        context.paths.root.parent,
        context=context,
    )

    assert document["status"] == "paused"
    assert document["continuable"] is True
    assert document["banner"] == "L2 PAUSED - CONTINUABLE"
    assert document["next_action"] == (
        "increase the child run resource authorization, then run "
        "`echelon re continue`"
    )
    assert human.endswith("L2 PAUSED - CONTINUABLE\n")


@pytest.mark.unit
def test_failed_requested_l2_output_reports_blocked_not_partial_success(
    tmp_path: Path,
) -> None:
    context, _provider = _child_context(tmp_path, paused=False, provider_mode="cli")
    executor = context.inputs.executor_contract.entry_for("compact-deepening")
    failing = _ScriptedProvider(
        scripts={
            "domain-baseline": ["invalid_candidate", "invalid_candidate"],
        }
    )
    context = replace(
        context,
        executors=MappingProxyType({executor.adapter_id: failing}),
    )

    result = Protocol24Controller(context).run_until_stopped()
    document = protocol_24_status_document(
        context.paths.root.parent,
        context=context,
    )

    assert result.status == "failed"
    assert document["status"] == "blocked"
    assert document["continuable"] is False
    assert document["banner"] == "L2 BLOCKED - REQUESTED OUTPUTS INCOMPLETE"
    assert document["artifact_counts"]["selected_l2"]["accepted"] < (
        document["artifact_counts"]["selected_l2"]["required"]
    )
    assert document["failures"]["work_items"]
    assert render_protocol_24_status(
        context.paths.root.parent,
        context=context,
    ).endswith("L2 BLOCKED - REQUESTED OUTPUTS INCOMPLETE\n")


@pytest.mark.unit
def test_root_status_router_dispatches_schema_3_without_mutation(tmp_path: Path) -> None:
    context, _provider = _child_context(tmp_path, paused=True, provider_mode="cli")
    before = {
        path.relative_to(context.paths.root.parent): path.stat().st_mtime_ns
        for path in context.paths.root.parent.rglob("*")
    }

    routed = json.loads(render_v2_status(context.paths.root.parent, as_json=True))
    direct = protocol_24_status_document(context.paths.root.parent)

    after = {
        path.relative_to(context.paths.root.parent): path.stat().st_mtime_ns
        for path in context.paths.root.parent.rglob("*")
    }
    assert routed == direct
    assert after == before
