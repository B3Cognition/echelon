"""Behavior tests for harness-managed Node runtime resolution."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from harness.node_runtime import (
    NodeRuntimeResolutionError,
    resolve_codegraph_bridge,
    resolve_perlgraph_cli,
)
from harness.re_controller import ReExtractionController
from harness.re_planner import ReExecutionPlan
from tests.unit.test_re_publication import write_valid_re_run


def _write_complete_codegraph(runtime: Path) -> None:
    package = runtime / "node_modules" / "@colbymchenry" / "codegraph" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text("{}\n", encoding="utf-8")
    (runtime / "codegraph-bridge.js").write_text("bridge\n", encoding="utf-8")
    (runtime / "codegraph-adapter.js").write_text("adapter\n", encoding="utf-8")
    (runtime / "package.json").write_text(
        json.dumps(
            {
                "echelon_runtime": {
                    "provider_artifact_schema_version": 2,
                    "exact_relationship_endpoints": True,
                    "uncapped_symbols": True,
                }
            }
        ),
        encoding="utf-8",
    )


def _write_complete_perlgraph(runtime: Path) -> None:
    cli = runtime / "dist" / "cli" / "perlgraph.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    cli.chmod(0o755)
    (runtime / "node_modules").mkdir()


def test_codegraph_uses_shared_runtime_when_deployed_copy_is_source_only(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    local = (
        project_root
        / ".specify/extensions/echelon/scripts/node/codegraph"
    )
    local.mkdir(parents=True)
    (local / "codegraph-bridge.js").write_text("source only\n", encoding="utf-8")
    shared = tmp_path / "echelon-home" / "node" / "codegraph"
    _write_complete_codegraph(shared)

    bridge = resolve_codegraph_bridge(
        project_root,
        env={"ECHELON_HOME": str(tmp_path / "echelon-home")},
    )

    assert bridge == shared / "codegraph-bridge.js"


def test_codegraph_rejects_contract_stale_complete_local_runtime(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    local = project_root / ".specify/extensions/echelon/scripts/node/codegraph"
    shared = tmp_path / "echelon-home" / "node" / "codegraph"
    _write_complete_codegraph(local)
    _write_complete_codegraph(shared)
    (local / "package.json").write_text("{}\n", encoding="utf-8")

    bridge = resolve_codegraph_bridge(
        project_root,
        env={"ECHELON_HOME": str(tmp_path / "echelon-home")},
    )

    assert bridge == shared / "codegraph-bridge.js"


def test_re_analysis_pins_controller_validated_codegraph_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    run_re = run_dir / "re"
    extension = tmp_path / "extension"
    script = extension / "scripts/bash/re/run-analysis.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    shared = tmp_path / "echelon-home/node/codegraph"
    _write_complete_codegraph(shared)
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_re / "re-execution-plan.json").read_text(encoding="utf-8"))
    )
    (run_re / "re-analysis-manifest.json").write_text("{}\n", encoding="utf-8")
    captured: dict[str, str] = {}
    controller = object.__new__(ReExtractionController)
    controller._project_root = tmp_path
    controller._run_re_dir = run_re
    controller._extension_root = extension

    def execute(
        _command: list[str], environment: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        captured.update(environment)
        (run_re / "analysis.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")

    controller._execute_analysis_command = execute
    monkeypatch.setattr(
        "harness.re_controller.resolve_codegraph_bridge",
        lambda _root: shared / "codegraph-bridge.js",
    )

    assert controller._run_analysis_script(plan) is None
    assert captured["ECHELON_CODEGRAPH_RUNTIME_DIR"] == str(shared)


def test_perlgraph_complete_deployed_runtime_wins_over_shared(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    local = project_root / ".specify/extensions/echelon/scripts/node/perlgraph"
    shared = tmp_path / "echelon-home" / "node" / "perlgraph"
    _write_complete_perlgraph(local)
    _write_complete_perlgraph(shared)

    cli = resolve_perlgraph_cli(
        project_root,
        env={"ECHELON_HOME": str(tmp_path / "echelon-home")},
    )

    assert cli == local / "dist" / "cli" / "perlgraph.js"


def test_explicit_incomplete_codegraph_override_is_terminal(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    shared = tmp_path / "echelon-home" / "node" / "codegraph"
    _write_complete_codegraph(shared)

    with pytest.raises(NodeRuntimeResolutionError) as exc_info:
        resolve_codegraph_bridge(
            project_root,
            env={
                "ECHELON_HOME": str(tmp_path / "echelon-home"),
                "ECHELON_CODEGRAPH_RUNTIME_DIR": str(incomplete),
            },
        )

    assert "ECHELON_CODEGRAPH_RUNTIME_DIR" in str(exc_info.value)
    assert str(incomplete) in str(exc_info.value)


def test_missing_perlgraph_runtime_reports_local_and_shared_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    echelon_home = tmp_path / "echelon-home"

    with pytest.raises(NodeRuntimeResolutionError) as exc_info:
        resolve_perlgraph_cli(
            project_root,
            env={"ECHELON_HOME": str(echelon_home)},
        )

    message = str(exc_info.value)
    assert str(project_root / ".specify/extensions/echelon/scripts/node/perlgraph") in message
    assert str(echelon_home / "node/perlgraph") in message
    assert "scripts/install.sh" in message
