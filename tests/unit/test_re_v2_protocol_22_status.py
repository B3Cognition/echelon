from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.re_v2.protocol_22.controller import Protocol22Controller
from harness.re_v2.protocol_22.materialization import materialize_accepted_l1
from harness.re_v2.protocol_22.status import (
    protocol_22_status_document,
    render_protocol_22_status,
)
from tests.unit.test_re_v2_protocol_22_controller import _baseline_context


def _completed(
    tmp_path: Path,
    *,
    provider_mode: str = "api",
    engine_protocol_version: str = "2.2",
):
    context, provider = _baseline_context(
        tmp_path,
        malformed_result=True,
        provider_mode=provider_mode,
        engine_protocol_version=engine_protocol_version,
    )
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "completed"
    materialize_accepted_l1(context)
    return context, provider


@pytest.mark.unit
def test_cli_status_reports_observed_provider_and_model_from_captures(
    tmp_path: Path,
) -> None:
    context, provider = _completed(tmp_path, provider_mode="cli")

    document = protocol_22_status_document(
        context.paths.root.parent,
        context=context,
    )
    human = render_protocol_22_status(
        context.paths.root.parent,
        context=context,
    )

    assert document["telemetry"]["provider_observations"] == [
        {
            "dispatches": provider.calls,
            "model": "gpt-5.6-codex",
            "provider": "codex",
        }
    ]
    assert (
        "provider observation: provider=codex model=gpt-5.6-codex "
        f"dispatches={provider.calls}"
    ) in human


@pytest.mark.unit
def test_complete_status_exposes_exact_layered_authority_and_not_run_boundaries(
    tmp_path: Path,
) -> None:
    context, provider = _completed(tmp_path)

    document = protocol_22_status_document(
        context.paths.root.parent,
        context=context,
    )
    human = render_protocol_22_status(
        context.paths.root.parent,
        context=context,
    )
    rendered_json = json.loads(
        render_protocol_22_status(
            context.paths.root.parent,
            as_json=True,
            context=context,
        )
    )

    assert rendered_json == document
    assert document["status"] == "complete"
    assert document["banner"] == "L1 COMPACT BASELINE COMPLETE"
    assert human.rstrip().endswith("L1 COMPACT BASELINE COMPLETE")
    assert document["artifact_counts"]["total"] == {
        "accepted": len(context.graph.templates),
        "required": len(context.graph.templates),
    }
    assert document["artifact_counts"]["by_kind"]["domain-baseline"] == {
        "accepted": 1,
        "required": 1,
    }
    source = document["sources"][0]
    assert source["source_id"] == "api"
    assert source["domains"] == {"accepted": 1, "required": 1}
    assert source["source_roots"] == {"accepted": 1, "required": 1}
    assert document["domains"][0]["presentation_domain_id"] == "001-re-src"
    root = document["source_roots"][0]
    assert Path(root["materialized_path"]).is_file()
    assert Path(root["materialized_path"]).name == (
        root["artifact_hash"].removeprefix("sha256:") + ".json"
    )
    baseline = document["baselines"][0]
    assert baseline["semantic_status"] == "unaudited"
    assert baseline["minimum_utility"]["passed"] is True
    combined = baseline["coverage"]["combined"]
    assert combined["selected_over_inventory"] == {
        "denominator": combined["inventory_file_count"],
        "numerator": combined["selected_file_count"],
    }
    assert document["context_estimates"]
    assert all(
        value["canonical_bytes"] == value["conservative_input_tokens"]
        for value in document["context_estimates"]
    )
    assert document["budget"]["tokens"]["charged"] >= 0
    assert document["budget"]["active_ms"]["charged"] >= 0
    assert document["telemetry"]["result_contract_reconstructed"] == provider.calls
    assert document["telemetry"]["unknown_token_dispatches"] == provider.calls
    assert document["budget"]["tokens"]["trusted_observed"] == 0
    assert document["not_run"] == {
        "exhaustive_re": "not run",
        "selective_deepening": "not run",
        "semantic_audit": "not run",
        "workspace_synthesis": "not run",
    }
    assert "full quality" not in human.lower()
    assert "full re complete" not in human.lower()


@pytest.mark.unit
def test_budget_pause_banner_names_next_item_and_exact_reservation(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(tmp_path, active_ms_limit=1)
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "paused"
    before_paths = tuple(
        sorted(
            path.relative_to(context.paths.root).as_posix()
            for path in context.paths.root.rglob("*")
        )
    )

    document = protocol_22_status_document(
        context.paths.root.parent,
        context=context,
    )
    human = render_protocol_22_status(
        context.paths.root.parent,
        context=context,
    )

    assert provider.calls == 0
    assert document["status"] == "paused"
    assert document["continuable"] is True
    assert document["banner"] == (
        "L1 COMPACT BASELINE PAUSED — BUDGET AUTHORIZATION REQUIRED"
    )
    assert human.rstrip().endswith(document["banner"])
    assert document["next_work"]["work_item_id"]
    assert document["next_work"]["reservation"]["active_ms"] > 1
    assert document["next_work"]["reservation"]["billable_tokens"] == 0
    after_paths = tuple(
        sorted(
            path.relative_to(context.paths.root).as_posix()
            for path in context.paths.root.rglob("*")
        )
    )
    assert after_paths == before_paths


@pytest.mark.unit
def test_budget_pause_status_reconstructs_reservation_from_run_dir_alone(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(tmp_path, active_ms_limit=1)
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "paused"

    document = protocol_22_status_document(context.paths.root.parent)
    with_context = protocol_22_status_document(
        context.paths.root.parent,
        context=context,
    )

    assert provider.calls == 0
    assert document["next_work"]["attempt_kind"] == "initial_generation"
    assert document["next_work"]["dispatch_id"].startswith("dispatch-")
    assert (
        document["next_work"]["reservation"] == with_context["next_work"]["reservation"]
    )


@pytest.mark.unit
def test_pristine_status_is_read_only_and_does_not_create_ledger_lock(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(tmp_path)
    before = tuple(
        sorted(
            path.relative_to(context.paths.root).as_posix()
            for path in context.paths.root.rglob("*")
        )
    )

    document = protocol_22_status_document(context.paths.root.parent)

    after = tuple(
        sorted(
            path.relative_to(context.paths.root).as_posix()
            for path in context.paths.root.rglob("*")
        )
    )
    assert provider.calls == 0
    assert document["status"] == "in_progress"
    assert document["next_work"]["reservation"]["billable_tokens"] == 0
    assert after == before


@pytest.mark.parametrize("provider_mode", ["api", "cli"])
@pytest.mark.unit
def test_provider_budget_pause_status_reconstructs_conservative_reservation(
    tmp_path: Path,
    provider_mode: str,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        token_limit=1,
        provider_mode=provider_mode,
    )
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "paused"

    document = protocol_22_status_document(context.paths.root.parent)
    next_work = document["next_work"]

    assert provider.calls == 0
    assert next_work["artifact_kind"] in {"domain-baseline", "source-overview"}
    assert next_work["attempt_kind"] == "initial_generation"
    assert next_work["dispatch_id"].startswith("dispatch-")
    assert next_work["reservation"]["billable_tokens"] > 1
    assert next_work["reservation"]["active_ms"] > 0


@pytest.mark.unit
def test_unresolved_authority_mismatch_is_unavailable_without_event_writes(
    tmp_path: Path,
) -> None:
    context, _provider = _baseline_context(tmp_path)
    wrong = replace(
        context.installed_authorities,
        executor_implementations={"wrong": "sha256:" + "0" * 64},
    )
    unavailable_context = replace(context, installed_authorities=wrong)
    events_lock = context.paths.events.with_name("events.lock")
    assert not context.paths.events.exists()
    assert not events_lock.exists()

    document = protocol_22_status_document(
        context.paths.root.parent,
        context=unavailable_context,
    )
    human = render_protocol_22_status(
        context.paths.root.parent,
        context=unavailable_context,
    )

    assert document["status"] == "pinned_authority_unavailable"
    assert document["banner"] == (
        "L1 COMPACT BASELINE UNAVAILABLE — PINNED AUTHORITY REQUIRED"
    )
    assert human.rstrip().endswith(document["banner"])
    assert document["authority"]["mismatches"]
    assert not context.paths.events.exists()
    assert not events_lock.exists()


@pytest.mark.unit
def test_terminal_failure_banner_reports_receipts_blocked_fanout_and_siblings(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        source_domains={"api": ("orders",), "web": ("ui",)},
        scripts={"domain-baseline:api": ["invalid_candidate", "invalid_candidate"]},
    )
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "failed"

    document = protocol_22_status_document(
        context.paths.root.parent,
        context=context,
    )
    human = render_protocol_22_status(
        context.paths.root.parent,
        context=context,
    )

    assert document["status"] == "failed"
    assert document["continuable"] is False
    assert document["banner"] == (
        "L1 COMPACT BASELINE INCOMPLETE — TERMINAL WORK-ITEM FAILURES"
    )
    assert human.rstrip().endswith(document["banner"])
    assert document["failures"]["work_items"][0]["failure_class"] == (
        "artifact_contract"
    )
    assert document["failures"]["work_items"][0]["receipt_id"].startswith("sha256:")
    assert document["plan_counts"]["blocked_dependency"] > 0
    assert document["accepted_siblings"]
    assert provider.calls_by_kind["domain-baseline"] == 3


@pytest.mark.unit
def test_terminal_outcome_survives_later_installed_authority_drift(
    tmp_path: Path,
) -> None:
    context, _provider = _completed(tmp_path)
    wrong = replace(
        context.installed_authorities,
        verifier_implementations={"compact-verifier-v1": "sha256:" + "0" * 64},
    )
    drifted = replace(context, installed_authorities=wrong)

    document = protocol_22_status_document(
        context.paths.root.parent,
        context=drifted,
    )

    assert document["status"] == "complete"
    assert document["banner"] == "L1 COMPACT BASELINE COMPLETE"
    assert document["authority"]["status"] == "drift_warning"
    assert document["authority"]["mismatches"]


@pytest.mark.unit
def test_executor_failure_status_names_exact_receipt_and_blocked_contract_fanout(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(
        tmp_path,
        source_domains={"api": ("orders",), "web": ("ui",)},
        scripts={"domain-baseline:api": ["usage_overflow"]},
    )
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "failed"

    document = protocol_22_status_document(
        context.paths.root.parent,
        context=context,
    )

    failure = document["failures"]["executors"][0]
    assert failure["reason_code"] == "usage_exceeded_reservation"
    assert failure["receipt_id"].startswith("sha256:")
    assert document["plan_counts"]["blocked_executor"] > 0
    assert provider.calls == 1


@pytest.mark.unit
@pytest.mark.parametrize("engine_protocol_version", ("2.2", "2.3"))
def test_legacy_status_entrypoint_selects_protocol_22_from_immutable_manifest(
    tmp_path: Path,
    engine_protocol_version: str,
) -> None:
    from harness.re_v2.status import render_v2_status

    context, _provider = _completed(
        tmp_path,
        engine_protocol_version=engine_protocol_version,
    )

    document = json.loads(render_v2_status(context.paths.root.parent, as_json=True))

    assert document["engine_protocol_version"] == engine_protocol_version
    assert document["status"] == "complete"
    assert document["banner"] == "L1 COMPACT BASELINE COMPLETE"
