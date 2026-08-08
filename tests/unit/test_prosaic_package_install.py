from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


def _write_bundle_source(root: Path) -> None:
    (root / "prosaic" / "commands").mkdir(parents=True)
    (root / "prosaic" / "commands" / "echelon.demo.md").write_text(
        "---\ntype: command\nname: demo\n---\n# Demo\n",
        encoding="utf-8",
    )
    (root / "runtime" / "workflow").mkdir(parents=True)
    (root / "runtime" / "workflow" / "definition.yaml").write_text(
        "phases: []\n",
        encoding="utf-8",
    )


def test_install_prosaic_bundle_stages_sources_and_deploys_packages(
    tmp_path: Path,
) -> None:
    from echelon.prosaic_packages import install_prosaic_bundle

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)
    commands: list[tuple[list[str], Path]] = []

    def run(command: list[str], *, cwd: Path, **_kwargs: object) -> None:
        commands.append((command, cwd))

    report = install_prosaic_bundle(
        workspace,
        echelon_root=echelon_root,
        run=run,
    )

    assert report.prose_source == workspace / ".echelon/packages/echelon-prose"
    assert report.runtime_source == workspace / ".echelon/packages/echelon-runtime"
    assert (report.prose_source / "commands/echelon.demo.md").read_text(encoding="utf-8").endswith(
        "# Demo\n"
    )
    assert (report.runtime_source / "workflow/definition.yaml").read_text(encoding="utf-8") == "phases: []\n"
    assert commands == [
        (["prosaic", "package", "deploy", "echelon-prose"], workspace),
        (["prosaic", "package", "deploy", "echelon-runtime"], workspace),
    ]
    assert not (workspace / "prosaic.config.yaml").exists()


def test_install_prosaic_bundle_refuses_to_overwrite_workspace_prosaic_config(
    tmp_path: Path,
) -> None:
    from echelon.prosaic_packages import ProsaicBundleInstallError, install_prosaic_bundle

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)
    (workspace / "prosaic.config.yaml").write_text("source: .prosaic\n", encoding="utf-8")

    with pytest.raises(ProsaicBundleInstallError, match="existing Prosaic configuration"):
        install_prosaic_bundle(workspace, echelon_root=echelon_root, run=lambda *_args, **_kwargs: None)

    assert not (workspace / ".echelon/packages").exists()


def test_install_prosaic_bundle_deploys_staged_content_with_prosaic(
    tmp_path: Path,
) -> None:
    from echelon.prosaic_packages import install_prosaic_bundle

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        subprocess.run(command, cwd=cwd, check=check)

    install_prosaic_bundle(workspace, echelon_root=echelon_root, run=run)

    assert (workspace / ".echelon/prosaic/commands/echelon.demo.md").read_text(
        encoding="utf-8"
    ).endswith("# Demo\n")
    assert (workspace / ".echelon/runtime/workflow/definition.yaml").read_text(
        encoding="utf-8"
    ) == "phases: []\n"


def test_committed_prosaic_runtime_does_not_reference_legacy_squad_layout() -> None:
    echelon_root = Path(__file__).resolve().parents[2]
    legacy_references = [
        path
        for path in (echelon_root / "runtime").rglob("*")
        if path.is_file()
        and ".specify/squad" in path.read_text(encoding="utf-8", errors="ignore")
    ]

    assert legacy_references == []


def test_runtime_workflow_dispatches_only_neutral_prosaic_subagents() -> None:
    echelon_root = Path(__file__).resolve().parents[2]
    runtime = echelon_root / "runtime"
    workflow = (runtime / "workflow/definition.yaml").read_text(encoding="utf-8")
    prosaic_agents = {
        path.stem for path in (echelon_root / "prosaic/subagents").glob("*.md")
    }
    dispatched_agents = set(
        re.findall(r"^\s+agent:\s*(echelon\.[a-z0-9-]+)\s*$", workflow, flags=re.MULTILINE)
    )
    staged_agents = set(
        re.findall(r"^\s+- id:\s*(echelon\.[a-z0-9-]+)\s*$", workflow, flags=re.MULTILINE)
    )

    assert "speckit-echelon-" not in "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in runtime.rglob("*")
        if path.is_file()
    )
    assert dispatched_agents <= prosaic_agents
    assert staged_agents <= prosaic_agents
