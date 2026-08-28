from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from tests.integration.test_re_v2_protocol_22_live import _git_state
from tests.support.re_v2_layered_workspace import build_and_commit_fixture


@pytest.mark.integration
def test_live_cli_layers_selective_l2_and_reuses_lineal_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.ledger import Protocol22Ledger
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_26.status import protocol_26_status_document
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    fixture = build_and_commit_fixture(tmp_path, "complete")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)
    source_git_before = {
        source_id: _git_state(fixture.root / "sources" / source_id)
        for source_id in fixture.source_domains
    }
    runner = CliRunner()

    with fixture.provider:
        baseline = runner.invoke(app, ["re", "run", "--engine", "v2"])
        assert baseline.exit_code == 0, baseline.output
        parent_dir = fixture.run_directories()[0]
        parent_manifest = load_run_manifest(parent_dir)
        parent_outer_inputs = load_protocol_26_inputs(
            ReV2Paths.for_run(parent_dir),
            parent_manifest,
        )
        parent_inputs = parent_outer_inputs.layer_inputs
        api = next(
            item
            for item in parent_inputs.workspace_partition.sources
            if item.source_id == "api"
        )
        first_domain, second_domain = api.domains

        first = runner.invoke(
            app,
            [
                "re",
                "deepen",
                "--to",
                "L2",
                "--source",
                "api",
                "--domain",
                first_domain.presentation_domain_id,
            ],
        )
        assert first.exit_code == 0, first.output
        calls_after_first = len(fixture.provider.requests)
        repeated = runner.invoke(
            app,
            [
                "re",
                "deepen",
                "--to",
                "L2",
                "--source",
                "api",
                "--domain",
                first_domain.presentation_domain_id,
            ],
        )
        assert repeated.exit_code == 0, repeated.output
        assert len(fixture.provider.requests) == calls_after_first

        second = runner.invoke(
            app,
            [
                "re",
                "deepen",
                "--to",
                "L2",
                "--source",
                "api",
                "--domain",
                second_domain.presentation_domain_id,
            ],
        )
        assert second.exit_code == 0, second.output

    assert "L2 SELECTED SCOPE COMPLETE" in first.output
    assert "L2 SELECTED SCOPE COMPLETE" in repeated.output
    assert "L2 SELECTED SCOPE COMPLETE" in second.output
    run_dirs = fixture.run_directories()
    assert len(run_dirs) == 3
    children = [
        path
        for path in run_dirs
        if isinstance(load_run_manifest(path), RunManifestV5)
        and load_run_manifest(path).target_layer == "L2"
    ]
    assert len(children) == 2
    latest = next(
        path
        for path in children
        if load_protocol_26_inputs(
            ReV2Paths.for_run(path), load_run_manifest(path)
        ).layer_execution_contract.layer_manifest.selection.domain_keys
        == (second_domain.domain_key,)
    )
    latest_manifest = load_run_manifest(latest)
    assert isinstance(latest_manifest, RunManifestV5)
    latest_inputs = load_protocol_26_inputs(
        ReV2Paths.for_run(latest), latest_manifest
    )
    latest_layer_manifest = latest_inputs.layer_execution_contract.layer_manifest
    assert latest_layer_manifest.parent_lineage.lineage_root_run_id == parent_manifest.run_id
    status = protocol_26_status_document(latest)
    assert status["status"] == "complete"
    assert status["artifact_counts"]["adopted_by_layer"]["L2"] > 0
    assert status["artifact_counts"]["generated_l2"] == 6
    assert status["telemetry"]["provider_observations"] == [
        {
            "dispatches": 2,
            "model": "fixture-shared-model",
            "provider": "opencode",
        }
    ]
    latest_paths = ReV2Paths.for_run(latest)
    latest_ledger = Protocol22Ledger(
        latest_paths,
        ObjectStore(latest_paths.objects),
    ).replay()
    assert any(
        item.output_key.layer == "L2"
        for item in latest_ledger.certification_work_items.values()
    )
    assert {
        source_id: _git_state(fixture.root / "sources" / source_id)
        for source_id in fixture.source_domains
    } == source_git_before


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("ECHELON_RUN_LIVE_CODEX") != "1"
    or shutil.which("codex") is None
    or shutil.which("echelon") is None,
    reason="set ECHELON_RUN_LIVE_CODEX=1 with installed codex and echelon CLIs",
)
def test_installed_codex_completes_and_reuses_clean_l2_pilot(tmp_path: Path) -> None:
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.ledger import ObjectStore
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
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
    installed = ProsaicPromptLoader(fixture.root).load_subagent(
        "echelon.re-deepener"
    )
    assert installed is not None
    deepener_bytes = canonical_prosaic_agent_bytes(installed)

    baseline = subprocess.run(
        ["echelon", "re", "run", "--engine", "v2"],
        cwd=fixture.root,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    deepen = subprocess.run(
        ["echelon", "re", "deepen", "--to", "L2", "--all"],
        cwd=fixture.root,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert deepen.returncode == 0, deepen.stdout + deepen.stderr
    assert "L2 SELECTED SCOPE COMPLETE" in deepen.stdout
    calls_before_repeat = _provider_dispatch_count(fixture.root)
    repeated = subprocess.run(
        ["echelon", "re", "deepen", "--to", "L2", "--all"],
        cwd=fixture.root,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert _provider_dispatch_count(fixture.root) == calls_before_repeat

    child = next(
        path
        for path in fixture.run_directories()
        if isinstance(load_run_manifest(path), RunManifestV5)
        and load_run_manifest(path).target_layer == "L2"
    )
    manifest = load_run_manifest(child)
    paths = ReV2Paths.for_run(child)
    objects = ObjectStore(paths.objects)
    inputs = load_protocol_26_inputs(paths, manifest).layer_inputs
    renderer = inputs.executor_contract.entry_for(
        "compact-deepening"
    ).request_renderer
    assert renderer is not None
    assert renderer.agent_contract_hash == content_digest(deepener_bytes)
    assert objects.read_blob(renderer.agent_contract_hash) == deepener_bytes
    status = protocol_26_status_document(child)
    assert status["status"] == "complete"
    observations = status["telemetry"]["provider_observations"]
    assert len(observations) == 1
    assert observations[0]["provider"] == "codex"
    assert observations[0]["model"] == "gpt-5.6-sol"
    assert observations[0]["dispatches"] in {2, 3}
    assert sum(
        status["budget"]["attempts"]["artifact_contract_retries"].values()
    ) <= 1
    assert _git_state(source) == source_git_before


def _provider_dispatch_count(workspace: Path) -> int:
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_26.events import protocol_26_events_for
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    total = 0
    for run_dir in workspace.joinpath("runs").glob("re-*"):
        manifest = load_run_manifest(run_dir)
        if not isinstance(manifest, RunManifestV5) or manifest.target_layer != "L2":
            continue
        total += sum(
            item.type == "dispatch_observed"
            and item.payload["raw_result_contract_status"] != "not_applicable"
            for item in EventStore(
                ReV2Paths.for_run(run_dir),
                protocol=protocol_26_events_for("L2"),
            ).replay()
        )
    return total
