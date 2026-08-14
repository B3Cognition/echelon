from __future__ import annotations

import re
import subprocess
import sys
import tarfile
import zipfile
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


def test_built_wheel_installs_canonical_prosaic_bundles(tmp_path: Path) -> None:
    echelon_root = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "wheel"
    installed = tmp_path / "installed"
    workspace = tmp_path / "workspace"
    wheel_dir.mkdir()
    workspace.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(wheel_dir),
        ],
        cwd=echelon_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("echelon-*.whl"))
    source_distribution = next(wheel_dir.glob("echelon-*.tar.gz"))
    with tarfile.open(source_distribution) as archive:
        members = {member.name for member in archive.getmembers()}
    assert any(name.endswith("/prosaic/commands/echelon.run.md") for name in members)
    assert any(name.endswith("/runtime/workflow/definition.yaml") for name in members)

    with zipfile.ZipFile(wheel) as archive:
        wheel_members = set(archive.namelist())
        assert "echelon/bundles/prosaic/commands/echelon.run.md" in wheel_members
        assert "echelon/bundles/runtime/workflow/definition.yaml" in wheel_members
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in wheel_members)
        archive.extractall(installed)

    script = """
import sys
from pathlib import Path

import yaml

sys.path.insert(0, sys.argv[1])
from echelon.prosaic_packages import install_prosaic_bundle

workspace = Path(sys.argv[2])
install_prosaic_bundle(workspace, run=lambda *_args, **_kwargs: None)
assert (workspace / ".echelon/packages/echelon-prose/commands").is_dir()
runtime = workspace / ".echelon/packages/echelon-runtime"
workflow_path = runtime / "workflow/definition.yaml"
assert workflow_path.is_file()
why2_instructions = (runtime / "workflow/phases/phase1-why2.md").read_text(encoding="utf-8")
assert "Controller-Owned Proportional Quality Policy" in why2_instructions
assert "Never authorize quality debt" in why2_instructions
workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
why2 = next(phase for phase in workflow["phases"] if phase["id"] == "phase1-why2")
assert why2["controller_policy"]["proportional_quality"] == {
    "owner": "controller",
    "responsibilities": [
        "repair_accounting",
        "exhaustion_routing",
        "decision_options",
        "debt_authorization",
    ],
}
"""
    subprocess.run(
        [sys.executable, "-c", script, str(installed), str(workspace)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )


def test_committed_prosaic_runtime_does_not_reference_legacy_squad_layout() -> None:
    echelon_root = Path(__file__).resolve().parents[2]
    legacy_references = [
        path
        for path in (echelon_root / "runtime").rglob("*")
        if path.is_file()
        and ".specify/squad" in path.read_text(encoding="utf-8", errors="ignore")
    ]

    assert legacy_references == []


def test_canonical_prosaic_does_not_instruct_providers_to_use_speckit() -> None:
    echelon_root = Path(__file__).resolve().parents[2]
    prose = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (echelon_root / "prosaic").rglob("*.md")
    )

    for legacy_reference in (
        "speckit.plan",
        "speckit.tasks",
        "speckit.analyze",
        "extension.yml",
        "echelon-config.yml",
    ):
        assert legacy_reference not in prose


def test_canonical_prosaic_companion_markdown_references_resolve() -> None:
    prosaic_root = Path(__file__).resolve().parents[2] / "prosaic"
    missing: set[str] = set()

    for artifact in prosaic_root.rglob("*.md"):
        text = artifact.read_text(encoding="utf-8")
        for reference in re.findall(
            r"`((?:agents|commands|subagents)/[^`\s]+\.md)`",
            text,
        ):
            if not (prosaic_root / reference).is_file():
                missing.add(reference)

    assert missing == set()


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


def test_runtime_architect_context_carries_commander_clarifications() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / "runtime"
        / "workflow"
        / "definition.yaml"
    ).read_text(encoding="utf-8")
    phase3_how = workflow.split("  - id: phase3-how", 1)[1].split(
        "  - id: phase3-specialists", 1
    )[0]

    assert "{staging_dir}/user-clarifications.md" in phase3_how


def test_runtime_diagnostics_and_kb_validation_use_echelon_artifacts() -> None:
    echelon_root = Path(__file__).resolve().parents[2]
    workflow = (echelon_root / "runtime" / "workflow" / "definition.yaml").read_text(
        encoding="utf-8"
    )
    validator = (
        echelon_root / "runtime" / "scripts" / "bash" / "kb-validate-evolution.sh"
    ).read_text(encoding="utf-8")

    assert "agent: echelon.investigator" in workflow
    assert "speckit.diagnostic.run" not in workflow
    assert ".echelon/prosaic/subagents" in validator
    assert "extension/extension.yml" not in validator


def test_runtime_light_gates_do_not_probe_legacy_harness_installations() -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "runtime"
        / "scripts"
        / "bash"
        / "build-light-gates.sh"
    ).read_text(encoding="utf-8")

    assert ".specify/extensions/harness" not in script
    assert "sandbox-exec.sh" not in script


def test_prosaic_agents_do_not_reference_removed_sandbox_shim() -> None:
    root = Path(__file__).resolve().parents[2]
    offenders = [
        path
        for path in (root / "prosaic" / "subagents").glob("*.md")
        if "sandbox-exec.sh" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_repository_does_not_ship_legacy_shell_sandbox_helpers() -> None:
    scripts = Path(__file__).resolve().parents[2] / "scripts"

    assert not (scripts / "sandbox-exec.sh").exists()
    assert not (scripts / "docker-sandbox.sh").exists()
    assert not (scripts / "docker-network.sh").exists()
    assert not (scripts / "docker-gc.sh").exists()


def test_runtime_bundle_does_not_ship_legacy_startup_banner() -> None:
    assert not (
        Path(__file__).resolve().parents[2]
        / "runtime"
        / "scripts"
        / "bash"
        / "startup-banner.sh"
    ).exists()
