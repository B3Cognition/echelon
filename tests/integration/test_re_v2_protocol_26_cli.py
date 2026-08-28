from __future__ import annotations

from pathlib import Path
import shutil

import pytest
from typer.testing import CliRunner

from tests.support.re_v2_layered_workspace import build_and_commit_fixture


@pytest.mark.integration
def test_completed_protocol_26_l1_is_reconstructed_for_zero_call_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.protocol_26.status import protocol_26_status_document

    fixture = build_and_commit_fixture(tmp_path, "complete")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)
    runner = CliRunner()

    with fixture.provider:
        origin = runner.invoke(app, ["re", "run", "--engine", "v2"])
        assert origin.exit_code == 0, origin.output
        calls_after_origin = len(fixture.provider.requests)
        sibling = runner.invoke(app, ["re", "run", "--engine", "v2"])

    assert sibling.exit_code == 0, sibling.output
    assert len(fixture.provider.requests) == calls_after_origin
    run_dirs = fixture.run_directories()
    assert len(run_dirs) == 2
    status = protocol_26_status_document(run_dirs[-1])
    assert status["status"] == "complete"
    assert status["checkpoints"]["adopted_count"] > 0
    assert status["checkpoints"]["generated_count"] == 0

    origin_run, sibling_run = run_dirs
    shutil.move(str(origin_run), tmp_path / "hidden-origin")
    shutil.rmtree(fixture.root / ".echelon" / "re-v2" / "checkpoints")
    with fixture.provider:
        repeated = runner.invoke(app, ["re", "run", "--engine", "v2"])

    assert repeated.exit_code == 0, repeated.output
    assert len(fixture.provider.requests) == calls_after_origin
    remaining = fixture.run_directories()
    assert len(remaining) == 2
    assert sibling_run in remaining
    repeated_status = protocol_26_status_document(remaining[-1])
    assert repeated_status["checkpoints"]["adopted_count"] > 0
    assert repeated_status["checkpoints"]["generated_count"] == 0


@pytest.mark.integration
def test_new_layered_runs_use_protocol_26_and_exact_l3_reuse_is_no_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from echelon import cli as legacy_cli
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_26.status import protocol_26_status_document
    from harness.re_v2.run_store import load_run_manifest

    fixture = build_and_commit_fixture(tmp_path, "complete")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(fixture.root)
    runner = CliRunner()

    with fixture.provider:
        l1_result = runner.invoke(app, ["re", "run", "--engine", "v2"])
        assert l1_result.exit_code == 0, l1_result.output
        l1 = fixture.run_directories()[-1]
        l2_result = runner.invoke(
            app,
            ["re", "deepen", "--to", "L2", "--all", "--from-run", l1.name],
        )
        assert l2_result.exit_code == 0, l2_result.output
        l2 = fixture.run_directories()[-1]
        # This routing test stops at the established controller boundary; the
        # scripted baseline provider does not synthesize protocol-2.5 payloads.
        monkeypatch.setattr(legacy_cli, "_run_re_v2_live", lambda _context: None)
        command = [
            "re",
            "deepen",
            "--to",
            "L3",
            "--all",
            "--from-run",
            l2.name,
        ]
        l3_result = runner.invoke(app, command)
        assert l3_result.exit_code == 0, l3_result.output
        l3 = fixture.run_directories()[-1]
        calls_before_reuse = len(fixture.provider.requests)
        repeated = runner.invoke(app, command)

    assert repeated.exit_code == 0, repeated.output
    assert len(fixture.provider.requests) == calls_before_reuse
    manifests = [load_run_manifest(path) for path in (l1, l2, l3)]
    assert all(isinstance(manifest, RunManifestV5) for manifest in manifests)
    assert [manifest.target_layer for manifest in manifests] == ["L1", "L2", "L3"]
    assert all(manifest.engine_protocol_version == "2.6" for manifest in manifests)
    assert protocol_26_status_document(l3)["status"] == "in_progress"
