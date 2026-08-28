from __future__ import annotations

from pathlib import Path
import json

import pytest
from typer.testing import CliRunner

from tests.support.re_v2_cli_workspace import create_cli_workspace


@pytest.mark.unit
def test_new_v2_l1_run_uses_protocol_26(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.protocol_26.inputs import load_protocol_26_inputs
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)

    result = CliRunner().invoke(
        app,
        ["re", "run", "--engine", "v2", "--goal", "inventory", "--shadow"],
    )

    assert result.exit_code == 0, result.output
    run_dir = probe.run_directories()[0]
    manifest = load_run_manifest(run_dir)
    assert isinstance(manifest, RunManifestV5)
    assert (manifest.schema_version, manifest.engine_protocol_version) == (5, "2.6")
    assert manifest.target_layer == "L1"
    inputs = load_protocol_26_inputs(ReV2Paths.for_run(run_dir), manifest)
    assert inputs.layer_execution_contract.layer_manifest.engine_protocol_version == (
        "2.3"
    )
    assert inputs.layer_inputs.workspace_partition.sources
    assert "provider requests issued: 0" in result.output


@pytest.mark.unit
def test_dirty_source_blocks_before_checkpoint_cache_or_run_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)
    (probe.root / "untracked.py").write_text("print('dirty')\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["re", "run", "--engine", "v2", "--goal", "inventory", "--shadow"],
    )

    assert result.exit_code != 0
    assert not probe.run_directories()
    assert not (probe.root / ".echelon" / "re-v2" / "checkpoints").exists()


@pytest.mark.unit
def test_protocol_26_status_json_uses_frozen_child_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)
    runner = CliRunner()
    created = runner.invoke(
        app,
        ["re", "run", "--engine", "v2", "--goal", "inventory", "--shadow"],
    )
    assert created.exit_code == 0, created.output

    result = runner.invoke(app, ["re", "status", "--json"])

    assert result.exit_code == 0, result.output
    status = json.loads(result.output)
    assert status["engine_protocol_version"] == "2.6"
    assert status["target_layer"] == "L1"
    assert status["checkpoints"]["reconstruction_state"] == "frozen_self_contained"
