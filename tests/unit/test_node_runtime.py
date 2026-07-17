"""Behavior tests for harness-managed Node runtime resolution."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.node_runtime import (
    NodeRuntimeResolutionError,
    resolve_codegraph_bridge,
    resolve_perlgraph_cli,
)


def _write_complete_codegraph(runtime: Path) -> None:
    package = runtime / "node_modules" / "@colbymchenry" / "codegraph" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text("{}\n", encoding="utf-8")
    (runtime / "codegraph-bridge.js").write_text("bridge\n", encoding="utf-8")
    (runtime / "codegraph-adapter.js").write_text("adapter\n", encoding="utf-8")


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
