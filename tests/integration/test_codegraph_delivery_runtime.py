"""Integration coverage for CodeGraph preparation in delivery worktrees."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from echelon.cli import _sync_polyrepo_runtime_extension
from harness.config import HarnessConfig
from harness.gitops import GitOpsManager


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_delivery_worktree_installs_and_runs_codegraph_from_locked_source(tmp_path: Path) -> None:
    """Staging excludes packages; a prepared worktree installs and uses the SDK."""
    if shutil.which("node") is None or shutil.which("npm") is None:
        pytest.skip("CodeGraph delivery runtime requires node and npm")

    workspace = tmp_path / "workspace"
    source_runtime = workspace / ".echelon" / "runtime"
    source_prose = workspace / ".echelon" / "prosaic"
    shutil.copytree(
        REPO_ROOT / "runtime",
        source_runtime,
        ignore=shutil.ignore_patterns("node_modules"),
    )
    shutil.copytree(REPO_ROOT / "prosaic", source_prose)
    staging_root = workspace / "runs" / "targets" / "prosaic"
    _sync_polyrepo_runtime_extension(workspace, staging_root)

    staging_runtime = (
        staging_root
        / ".echelon"
        / "runtime"
        / "scripts"
        / "node"
        / "codegraph"
    )
    assert (staging_runtime / "package-lock.json").is_file()
    assert not (staging_runtime / "node_modules").exists()

    worktree = tmp_path / "delivery-worktree"
    worktree.mkdir()
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
    )
    gitops = GitOpsManager(config, base_dir=str(staging_root))
    git_exclude = tmp_path / "git-exclude"
    with patch("harness.gitops._run_git") as run_git:
        run_git.return_value = SimpleNamespace(stdout=f"{git_exclude}\n")
        gitops.sync_runtime_extension(worktree, prepare_codegraph=True)

    runtime = worktree / ".echelon" / "runtime" / "scripts" / "node" / "codegraph"
    assert (runtime / "node_modules" / "@colbymchenry" / "codegraph" / "package.json").is_file()

    project = tmp_path / "typescript-fixture"
    project.mkdir()
    (project / "example.ts").write_text(
        "export function greet(name: string): string { return `hello ${name}`; }\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "codegraph-analysis.json"
    subprocess.run(
        [
            "node",
            str(runtime / "codegraph-bridge.js"),
            "analyze",
            "--repo-path",
            str(project),
            "--output-path",
            str(output_path),
            "--languages",
            "typescript",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    analysis = json.loads(output_path.read_text(encoding="utf-8"))
    assert analysis["repo_path"] == str(project.resolve())
    assert any(symbol["name"] == "greet" for symbol in analysis["symbols"])
    assert analysis["index_stats"]["index_state"] == "ready"
