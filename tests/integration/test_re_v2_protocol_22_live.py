from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.support.re_v2_layered_workspace import build_and_commit_fixture


@pytest.mark.integration
def test_live_cli_completes_multi_source_compact_baseline_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.graph import build_protocol_22_graph
    from harness.re_v2.protocol_22.inputs import load_protocol_22_inputs
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_22.status import protocol_22_status_document
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    fixture = build_and_commit_fixture(tmp_path, "complete")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.setenv("ECHELON_TEST_API_KEY", "fixture-secret")
    monkeypatch.chdir(fixture.root)
    runner = CliRunner()

    with fixture.api:
        result = runner.invoke(app, ["re", "run", "--engine", "v2"])
        assert result.exit_code == 0, result.output
        initial_calls = len(fixture.api.requests)
        continued = runner.invoke(app, ["re", "continue"])

    assert continued.exit_code == 0, continued.output
    assert len(fixture.api.requests) == initial_calls
    assert "L1 COMPACT BASELINE COMPLETE" in result.output
    assert "semantic audit: not run" in result.output
    assert "workspace synthesis: not run" in result.output
    assert "selective deepening: not run" in result.output
    assert "exhaustive RE: not run" in result.output
    assert not (fixture.root / "re").exists()

    run_dir = fixture.run_directories()[0]
    manifest = load_run_manifest(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    inputs = load_protocol_22_inputs(paths, manifest)
    graph = build_protocol_22_graph(manifest, inputs)
    ledger = Protocol22Ledger(paths, ObjectStore(paths.objects)).replay()
    provider_templates = tuple(
        template
        for template in graph.templates
        if template.producer_family == "compact-baseline"
    )
    assert len(fixture.api.requests) == len(provider_templates)
    assert len(ledger.accepted_artifacts) == len(graph.templates)
    assert all(
        request.json["tools"] == []
        and request.json["tool_choice"] == "none"
        and request.json["stream"] is False
        for request in fixture.api.requests
    )

    status = protocol_22_status_document(run_dir)
    assert status["status"] == "complete"
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
