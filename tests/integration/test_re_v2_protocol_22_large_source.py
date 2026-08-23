from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.integration.test_re_v2_protocol_22_failures import _request_context
from tests.support.re_v2_layered_workspace import build_and_commit_fixture


def _assert_exact_ratios(coverage: dict[str, object]) -> None:
    for name in ("direct", "projected_domains", "combined"):
        record = coverage[name]
        if record is None:
            continue
        assert record["selected_over_inventory"] == {
            "numerator": record["selected_file_count"],
            "denominator": record["inventory_file_count"],
        }
        assert record["referenced_over_inventory"] == {
            "numerator": record["referenced_file_count"],
            "denominator": record["inventory_file_count"],
        }
        assert record["referenced_over_selected"] == {
            "numerator": record["referenced_file_count"],
            "denominator": record["selected_file_count"],
        }


@pytest.mark.integration
def test_large_pathological_source_is_bounded_debt_explicit_and_restart_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.artifacts import EvidencePackV1
    from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
    from harness.re_v2.protocol_22.inputs import load_protocol_22_inputs
    from harness.re_v2.protocol_22.inventory import InventoryArtifactV1
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.policies import policy_for
    from harness.re_v2.protocol_22.schema import load_canonical_object
    from harness.re_v2.protocol_22.status import protocol_22_status_document
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    fixture = build_and_commit_fixture(tmp_path, "large-source")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)
    runner = CliRunner()

    with fixture.provider:
        shadow = runner.invoke(
            app,
            ["re", "run", "--engine", "v2", "--shadow"],
        )
        assert shadow.exit_code == 0, shadow.output
        assert fixture.provider.requests == []
        assert "deterministic initial dispatches: 8" in shadow.output
        assert "provider initial dispatches: 2" in shadow.output
        assert "maximum shared-retry dispatches: 2" in shadow.output
        assert "context exact:" in shadow.output
        assert "context worst-case bound:" in shadow.output
        assert "whole-run initial reservation:" in shadow.output
        assert "whole-run shared-retry reservation:" in shadow.output
        assert "provider requests issued: 0" in shadow.output

        completed = runner.invoke(app, ["re", "continue"])
        assert completed.exit_code == 0, completed.output
        assert "L1 COMPACT BASELINE COMPLETE" in completed.output
        calls = len(fixture.provider.requests)
        run_dir = fixture.run_directories()[0]
        paths = ReV2Paths.for_run(run_dir)
        before_events = paths.events.read_bytes()
        before_status = protocol_22_status_document(run_dir)
        replayed = runner.invoke(app, ["re", "continue"])

    assert replayed.exit_code == 0, replayed.output
    assert len(fixture.provider.requests) == calls == 2
    assert paths.events.read_bytes() == before_events
    status = protocol_22_status_document(run_dir)
    assert status["status"] == "complete"
    assert [item["depth_debt"] for item in status["baselines"]] == [
        item["depth_debt"] for item in before_status["baselines"]
    ]
    assert status["telemetry"]["result_contract_reconstructed"] == 2
    assert status["telemetry"]["unknown_token_dispatches"] == 2
    assert status["budget"]["tokens"]["trusted_observed"] == 0

    events = EventStore(paths, protocol=PROTOCOL_22_EVENTS).replay()
    reserved_tokens = sum(
        event.payload["billable_token_reservation"]
        for event in events
        if event.type == "dispatch_started"
    )
    assert status["budget"]["tokens"]["charged"] == reserved_tokens > 0

    manifest = load_run_manifest(run_dir)
    inputs = load_protocol_22_inputs(paths, manifest)
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths, objects).replay()
    artifacts = tuple(ledger.accepted_artifacts.values())
    inventories = [
        load_canonical_object(
            objects.read_blob(receipt.artifact_hash),
            InventoryArtifactV1.from_json_dict,
        )
        for receipt in artifacts
        if receipt.artifact_key.artifact_kind == "domain-inventory"
    ]
    assert len(inventories) == 1
    files = {
        item.source_relative_path: item
        for item in inventories[0].files
    }
    assert files["src/huge/binary.bin"].text_status == "contains_nul"
    assert files["src/huge/invalid-utf8.py"].text_status == "invalid_utf8"
    assert files["src/huge/crlf.py"].line_count == 2
    assert files["src/huge/unterminated.py"].line_count == 1

    evidence_packs = [
        (
            receipt,
            load_canonical_object(
                objects.read_blob(receipt.artifact_hash),
                EvidencePackV1.from_json_dict,
            ),
        )
        for receipt in artifacts
        if receipt.artifact_key.artifact_kind.endswith("evidence-pack")
    ]
    assert len(evidence_packs) == 2
    domain_pack = next(
        pack
        for receipt, pack in evidence_packs
        if receipt.artifact_key.artifact_kind == "domain-evidence-pack"
    )
    assert domain_pack.depth_debt.omitted_file_count >= 3
    assert domain_pack.depth_debt.omitted_descriptor_hash is not None
    for receipt, pack in evidence_packs:
        payload = objects.read_blob(receipt.artifact_hash)
        assert len(payload) <= pack.max_canonical_json_bytes
        assert len(payload) <= pack.max_conservative_input_tokens

    for estimate in status["context_estimates"]:
        policy = policy_for(
            inputs.artifact_policy,
            "L1",
            estimate["artifact_kind"],
        )
        assert estimate["canonical_bytes"] <= policy.max_canonical_json_bytes
        assert estimate["canonical_bytes"] <= policy.max_context_bundle_bytes
        assert (
            estimate["conservative_input_tokens"]
            <= policy.max_conservative_input_tokens
        )

    executor = inputs.executor_contract.entry_for("compact-baseline")
    assert executor.execution_mode == "cli"
    assert executor.request_tokenizer is None
    for request in fixture.provider.requests:
        assert (
            len(request.body)
            <= executor.limits.max_billable_tokens_per_dispatch
        )
        assert request.prompt_metadata["model_tier"] == "strong"
        assert request.prompt_metadata["effort"] == "high"

    calls_by_item = Counter(
        (
            context["target_artifact_kind"],
            context["scope"]["source_id"],
            context["scope"]["domain_key"],
        )
        for context in map(_request_context, fixture.provider.requests)
    )
    assert max(calls_by_item.values()) == 1
    assert set(calls_by_item.values()) == {1}
    for baseline in status["baselines"]:
        _assert_exact_ratios(baseline["coverage"])
    assert any(
        baseline["coverage"]["projected_domains"] is not None
        for baseline in status["baselines"]
    )
