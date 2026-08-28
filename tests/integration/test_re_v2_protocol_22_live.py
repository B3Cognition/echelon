from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from tests.support.re_v2_layered_workspace import build_and_commit_fixture


@pytest.mark.integration
def test_live_cli_completes_multi_source_compact_baseline_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.execution import CandidateInventoryV1
    from harness.re_v2.protocol_22.graph import build_protocol_22_graph
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.model import PersistedCandidateV2
    from harness.re_v2.protocol_22.schema import load_canonical_object
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_26.status import protocol_26_status_document
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    fixture = build_and_commit_fixture(tmp_path, "complete")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)
    runner = CliRunner()
    source_git_before = {
        source_id: _git_state(fixture.root / "sources" / source_id)
        for source_id in fixture.source_domains
    }

    with fixture.provider:
        result = runner.invoke(app, ["re", "run", "--engine", "v2"])
        assert result.exit_code == 0, result.output
        initial_calls = len(fixture.provider.requests)
        continued = runner.invoke(app, ["re", "continue"])

    assert continued.exit_code == 0, continued.output
    assert len(fixture.provider.requests) == initial_calls
    assert "L1 COMPACT BASELINE COMPLETE" in result.output
    assert "semantic audit: not run" in result.output
    assert "workspace synthesis: not run" in result.output
    assert "selective deepening: not run" in result.output
    assert "exhaustive RE: not run" in result.output
    assert not (fixture.root / "re").exists()

    run_dir = fixture.run_directories()[0]
    manifest = load_run_manifest(run_dir)
    assert isinstance(manifest, RunManifestV5)
    assert manifest.engine_protocol_version == "2.6"
    paths = ReV2Paths.for_run(run_dir)
    outer_inputs = load_protocol_26_inputs(paths, manifest)
    inputs = outer_inputs.layer_inputs
    inner_manifest = outer_inputs.layer_execution_contract.layer_manifest
    graph = build_protocol_22_graph(inner_manifest, inputs)
    ledger = Protocol22Ledger(paths, ObjectStore(paths.objects)).replay()
    provider_templates = tuple(
        template
        for template in graph.templates
        if template.producer_family == "compact-baseline"
    )
    assert len(fixture.provider.requests) == len(provider_templates)
    assert len(ledger.accepted_artifacts) == len(graph.templates)
    assert all(
        request.prompt_metadata["model_tier"] == "strong"
        and request.prompt_metadata["effort"] == "high"
        and request.request_metadata["isolated_workspace"] is True
        for request in fixture.provider.requests
    )

    status = protocol_26_status_document(run_dir)
    assert status["status"] == "complete"
    assert status["banner"].startswith("L1 COMPACT BASELINE COMPLETE")
    assert status["checkpoints"]["adopted_count"] == 0
    assert status["telemetry"]["provider_observations"] == [
        {
            "dispatches": len(provider_templates),
            "model": "fixture-shared-model",
            "provider": "opencode",
        }
    ]
    assert len(status["source_roots"]) == len(fixture.source_domains)
    assert all(item["minimum_utility"]["passed"] for item in status["baselines"])
    assert all(item["semantic_status"] == "unaudited" for item in status["baselines"])
    for root in status["source_roots"]:
        materialized = Path(root["materialized_path"])
        assert materialized.is_file()
        assert materialized.name == (
            root["artifact_hash"].removeprefix("sha256:") + ".json"
        )
    materialized_baselines = tuple(
        (paths.root / "materialized").glob("L1/sources/**/baseline.json")
    )
    assert len(materialized_baselines) == len(status["baselines"])
    assert all(path.with_suffix(".md").is_file() for path in materialized_baselines)
    provider_observations = [
        event
        for event in EventStore(paths, protocol=protocol_26_events_for("L1")).replay()
        if event.type == "dispatch_observed"
        and event.payload["reported_token_usage"] != 0
    ]
    assert len(provider_observations) == len(provider_templates)
    assert all(
        event.payload["raw_result_contract_status"] == "valid"
        for event in provider_observations
    )
    for assessment in ledger.candidate_assessments.values():
        candidate = load_canonical_object(
            ObjectStore(paths.objects).read_blob(assessment.candidate_id),
            PersistedCandidateV2.from_json_dict,
        )
        inventory = load_canonical_object(
            ObjectStore(paths.objects).read_blob(candidate.candidate_inventory_hash),
            CandidateInventoryV1.from_json_dict,
        )
        assert [entry.relative_path for entry in inventory.entries] == [
            "baseline.json"
        ]
    assert {
        source_id: _git_state(fixture.root / "sources" / source_id)
        for source_id in fixture.source_domains
    } == source_git_before


def _git_state(source: Path) -> tuple[str, str]:
    head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return head, dirty


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("ECHELON_RUN_LIVE_CODEX") != "1"
    or shutil.which("codex") is None
    or shutil.which("echelon") is None,
    reason="set ECHELON_RUN_LIVE_CODEX=1 with installed codex and echelon CLIs",
)
def test_installed_codex_completes_clean_l0_l1_pilot(tmp_path: Path) -> None:
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.execution import CandidateInventoryV1
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.model import PersistedCandidateV2
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.protocol_22.schema import load_canonical_object
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_26.status import protocol_26_status_document
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    fixture = build_and_commit_fixture(tmp_path, "live-codex")
    source = fixture.root / "sources" / "api"
    source_git_before = _git_state(source)
    env = {
        **os.environ,
        "ECHELON_HOME": str(tmp_path / "echelon-home"),
        "ECHELON_LLM": "codex",
    }

    provisioned = subprocess.run(
        ["echelon", "workspace", "migrate-to-prosaic"],
        cwd=fixture.root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert provisioned.returncode == 0, provisioned.stdout + provisioned.stderr
    installed_agent = ProsaicPromptLoader(fixture.root).load_subagent(
        "echelon.re-baseliner"
    )
    assert installed_agent is not None
    inspected_agent_bytes = canonical_prosaic_agent_bytes(installed_agent)

    result = subprocess.run(
        ["echelon", "re", "run", "--engine", "v2"],
        cwd=fixture.root,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    run_dir = fixture.run_directories()[0]
    manifest = load_run_manifest(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    objects = ObjectStore(paths.objects)
    assert isinstance(manifest, RunManifestV5)
    inputs = load_protocol_26_inputs(paths, manifest).layer_inputs
    renderer = inputs.executor_contract.entry_for(
        "compact-baseline"
    ).request_renderer
    assert renderer is not None
    assert renderer.agent_contract_hash == content_digest(inspected_agent_bytes)
    assert objects.read_blob(renderer.agent_contract_hash) == inspected_agent_bytes
    ledger = Protocol22Ledger(paths, objects).replay()
    status = protocol_26_status_document(run_dir)
    assert manifest.engine_protocol_version == "2.6"
    assert manifest.target_layer == "L1"
    assert status["banner"] == "L1 COMPACT BASELINE COMPLETE"
    assert status["telemetry"]["provider_observations"] == [
        {
            "dispatches": 3,
            "model": "gpt-5.6-sol",
            "provider": "codex",
        }
    ]
    provider_observations = [
        event
        for event in EventStore(
            paths, protocol=protocol_26_events_for("L1")
        ).replay()
        if event.type == "dispatch_observed"
        and event.payload["raw_result_contract_status"] != "not_applicable"
    ]
    assert len(provider_observations) == 3
    assert all(
        event.payload["raw_result_contract_status"] == "valid"
        for event in provider_observations
    )
    assert len(ledger.candidate_assessments) == 3
    for assessment in ledger.candidate_assessments.values():
        candidate = load_canonical_object(
            objects.read_blob(assessment.candidate_id),
            PersistedCandidateV2.from_json_dict,
        )
        inventory = load_canonical_object(
            objects.read_blob(candidate.candidate_inventory_hash),
            CandidateInventoryV1.from_json_dict,
        )
        assert len(inventory.entries) == 1
        entry = inventory.entries[0]
        assert entry.relative_path == "baseline.json"
        assert entry.content_hash is not None
        candidate_bytes = objects.read_blob(entry.content_hash)
        assert content_digest(candidate_bytes) == entry.content_hash
        assert assessment.normalized_authorial_payload_hash is not None
        assert canonical_json_bytes(json.loads(candidate_bytes)) == objects.read_blob(
            assessment.normalized_authorial_payload_hash
        )
    assert _git_state(source) == source_git_before
