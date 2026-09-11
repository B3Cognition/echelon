from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from tests.support.temp_storage import copy_package_build_tree, package_checkout_files


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


def test_install_prosaic_bundle_removes_staging_after_deploying_packages(
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

    assert report.prose_root == workspace / ".echelon/prosaic"
    assert report.runtime_root == workspace / ".echelon/runtime"
    assert report.prose_source == report.prose_root
    assert report.runtime_source == report.runtime_root
    assert not (workspace / ".echelon/packages").exists()
    assert commands == [
        (["prosaic", "package", "deploy", "echelon-prose"], workspace),
        (["prosaic", "package", "deploy", "echelon-runtime"], workspace),
    ]
    assert not (workspace / "prosaic.config.yaml").exists()


def test_install_prosaic_bundle_removes_staging_when_deployment_fails(
    tmp_path: Path,
) -> None:
    from echelon.prosaic_packages import (
        ProsaicBundleInstallError,
        install_prosaic_bundle,
    )

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)

    def run(command: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, command, stderr="deployment failed")

    with pytest.raises(ProsaicBundleInstallError, match="installation failed"):
        install_prosaic_bundle(workspace, echelon_root=echelon_root, run=run)

    assert not (workspace / ".echelon/packages").exists()
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
    assert not (workspace / ".echelon/packages").exists()


def test_install_prosaic_bundle_excludes_checkout_only_dependency_trees(
    tmp_path: Path,
) -> None:
    from echelon.prosaic_packages import install_prosaic_bundle

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)
    ignored_dependency = (
        echelon_root
        / "runtime"
        / "scripts"
        / "node"
        / "codegraph"
        / "node_modules"
        / "large.bin"
    )
    ignored_dependency.parent.mkdir(parents=True)
    ignored_dependency.write_bytes(b"checkout-only dependency")

    def deploy(command: list[str], *, cwd: Path, check: bool) -> None:
        assert check is True
        package_id = command[-1]
        source = cwd / ".echelon" / "packages" / package_id
        destination = cwd / ".echelon" / (
            "prosaic" if package_id == "echelon-prose" else "runtime"
        )
        shutil.copytree(source, destination)

    install_prosaic_bundle(workspace, echelon_root=echelon_root, run=deploy)

    assert not (
        workspace
        / ".echelon"
        / "runtime"
        / "scripts"
        / "node"
        / "codegraph"
        / "node_modules"
    ).exists()


def test_install_prosaic_bundle_refreshes_legacy_destinations_without_manifest(
    tmp_path: Path,
) -> None:
    from echelon.prosaic_packages import install_prosaic_bundle

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)
    legacy_prose = workspace / ".echelon/prosaic/commands/echelon.demo.md"
    legacy_runtime = workspace / ".echelon/runtime/workflow/definition.yaml"
    legacy_prose.parent.mkdir(parents=True)
    legacy_runtime.parent.mkdir(parents=True)
    legacy_prose.write_text("legacy prose\n", encoding="utf-8")
    legacy_runtime.write_text("legacy runtime\n", encoding="utf-8")

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        subprocess.run(command, cwd=cwd, check=check)

    install_prosaic_bundle(workspace, echelon_root=echelon_root, run=run)

    assert legacy_prose.read_text(encoding="utf-8").endswith("# Demo\n")
    assert legacy_runtime.read_text(encoding="utf-8") == "phases: []\n"


def test_install_prosaic_bundle_restores_legacy_destinations_when_refresh_fails(
    tmp_path: Path,
) -> None:
    from echelon.prosaic_packages import (
        ProsaicBundleInstallError,
        install_prosaic_bundle,
    )

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)
    legacy_prose = workspace / ".echelon/prosaic/legacy.md"
    legacy_runtime = workspace / ".echelon/runtime/legacy.yaml"
    legacy_prose.parent.mkdir(parents=True)
    legacy_runtime.parent.mkdir(parents=True)
    legacy_prose.write_text("legacy prose\n", encoding="utf-8")
    legacy_runtime.write_text("legacy runtime\n", encoding="utf-8")
    calls = 0

    def run(command: list[str], *, cwd: Path, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        (cwd / ".echelon/prosaic/new.md").parent.mkdir(parents=True, exist_ok=True)
        (cwd / ".echelon/prosaic/new.md").write_text("new\n", encoding="utf-8")
        (cwd / ".prosaic-manifest.json").write_text("{}\n", encoding="utf-8")
        if calls == 2:
            raise subprocess.CalledProcessError(1, command)

    with pytest.raises(ProsaicBundleInstallError, match="installation failed"):
        install_prosaic_bundle(workspace, echelon_root=echelon_root, run=run)

    assert legacy_prose.read_text(encoding="utf-8") == "legacy prose\n"
    assert legacy_runtime.read_text(encoding="utf-8") == "legacy runtime\n"
    assert not (workspace / ".echelon/prosaic/new.md").exists()
    assert not (workspace / ".prosaic-manifest.json").exists()
    assert not (workspace / ".echelon/.prosaic.pre-prosaic-migration").exists()
    assert not (workspace / ".echelon/.runtime.pre-prosaic-migration").exists()


def test_install_prosaic_bundle_rolls_back_partially_quarantined_legacy_trees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.prosaic_packages import (
        ProsaicBundleInstallError,
        install_prosaic_bundle,
    )

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)
    legacy_prose = workspace / ".echelon/prosaic/legacy.md"
    legacy_runtime = workspace / ".echelon/runtime/legacy.yaml"
    legacy_prose.parent.mkdir(parents=True)
    legacy_runtime.parent.mkdir(parents=True)
    legacy_prose.write_text("legacy prose\n", encoding="utf-8")
    legacy_runtime.write_text("legacy runtime\n", encoding="utf-8")
    original_replace = Path.replace

    def fail_second_quarantine(path: Path, target: Path) -> Path:
        if path == workspace / ".echelon/runtime":
            raise OSError("simulated second quarantine failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_second_quarantine)

    with pytest.raises(ProsaicBundleInstallError, match="installation failed"):
        install_prosaic_bundle(
            workspace,
            echelon_root=echelon_root,
            run=lambda *_args, **_kwargs: None,
        )

    assert legacy_prose.read_text(encoding="utf-8") == "legacy prose\n"
    assert legacy_runtime.read_text(encoding="utf-8") == "legacy runtime\n"
    assert not (workspace / ".echelon/.prosaic.pre-prosaic-migration").exists()
    assert not (workspace / ".echelon/.runtime.pre-prosaic-migration").exists()


def test_install_prosaic_bundle_waits_for_protocol_fingerprint_consumer(
    tmp_path: Path,
) -> None:
    """A refresh cannot replace files while a controller owns the shared lock."""
    from echelon.prosaic_packages import install_prosaic_bundle

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".echelon").mkdir()
    _write_bundle_source(echelon_root)
    lock_holder = """
import sys
import time
from pathlib import Path
from harness.banzai_protocol import banzai_default_protocol_bundle_lock

with banzai_default_protocol_bundle_lock(Path(sys.argv[1]), exclusive=False):
    print('locked', flush=True)
    time.sleep(0.4)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", lock_holder, str(workspace)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"
    started = time.monotonic()
    try:
        install_prosaic_bundle(
            workspace,
            echelon_root=echelon_root,
            run=lambda *_args, **_kwargs: None,
        )
    finally:
        holder.wait(timeout=2)

    assert holder.returncode == 0, holder.stderr.read() if holder.stderr else ""
    assert time.monotonic() - started >= 0.25


def test_install_prosaic_bundle_retains_live_lifecycle_state_across_refresh(
    tmp_path: Path,
) -> None:
    """A bundle refresh must not strand a lease an in-flight operation owns."""
    from echelon.prosaic_packages import install_prosaic_bundle
    from echelon.spec_lifecycle import SpecMutationLock

    echelon_root = tmp_path / "echelon"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_bundle_source(echelon_root)
    (workspace / ".echelon/runtime").mkdir(parents=True)
    switch_intent = workspace / ".echelon/runtime/spec-switch-intent.json"
    switch_intent.write_text('{"spec_id": "003-test"}\n', encoding="utf-8")

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        subprocess.run(command, cwd=cwd, check=check)

    with SpecMutationLock.acquire(workspace, "003-test", "delivery-held"):
        install_prosaic_bundle(workspace, echelon_root=echelon_root, run=run)

        lock_dir = workspace / ".echelon/runtime/spec-mutations/003-test.lock"
        assert lock_dir.is_dir(), "live spec mutation lease was dropped by the refresh"
        with pytest.raises(Exception):
            SpecMutationLock.acquire(workspace, "003-test", "second-owner")

    assert switch_intent.read_text(encoding="utf-8") == '{"spec_id": "003-test"}\n'
    # Deployed bundle content still lands alongside the retained state.
    assert (workspace / ".echelon/runtime/workflow/definition.yaml").read_text(
        encoding="utf-8"
    ) == "phases: []\n"


def test_built_wheel_installs_canonical_prosaic_bundles(tmp_path: Path) -> None:
    echelon_root = Path(__file__).resolve().parents[2]
    build_root = tmp_path / 'source'
    def checkout_files():
        roots = [echelon_root / name for name in ('src', 'prosaic', 'runtime', 'build')]
        files = package_checkout_files(*roots)
        files.update(
            {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in echelon_root.iterdir()
                if path.is_file()
            }
        )
        return files
    before = checkout_files()
    build_root.mkdir()
    for name in ('pyproject.toml', 'setup.py', 'MANIFEST.in', 'README.md', 'LICENSE'):
        shutil.copy2(echelon_root / name, build_root / name)
    for name in ('src', 'prosaic', 'runtime'):
        copy_package_build_tree(echelon_root / name, build_root / name)
    checkout_only_dependency = (
        build_root
        / "runtime"
        / "scripts"
        / "node"
        / "codegraph"
        / "node_modules"
        / "checkout-only.txt"
    )
    checkout_only_dependency.parent.mkdir(parents=True)
    checkout_only_dependency.write_text("not package data\n", encoding="utf-8")
    wheel_dir = tmp_path / "wheel"
    installed = tmp_path / "installed"
    workspace = tmp_path / "workspace"
    wheel_dir.mkdir()
    workspace.mkdir()

    # Refuse before invoking a build backend that could refresh live egg-info.
    assert not build_root.is_relative_to(echelon_root), 'build intermediates must not touch the checkout'
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(wheel_dir),
        ],
        cwd=build_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("echelon-*.whl"))
    assert checkout_files() == before
    source_distribution = next(wheel_dir.glob("echelon-*.tar.gz"))
    with tarfile.open(source_distribution) as archive:
        members = {member.name for member in archive.getmembers()}
    assert any(name.endswith("/prosaic/commands/echelon.run.md") for name in members)
    assert any(name.endswith("/runtime/workflow/definition.yaml") for name in members)
    assert not any("/node_modules/" in name for name in members)

    with zipfile.ZipFile(wheel) as archive:
        wheel_members = set(archive.namelist())
        assert "echelon/bundles/prosaic/commands/echelon.run.md" in wheel_members
        assert "echelon/bundles/runtime/workflow/definition.yaml" in wheel_members
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in wheel_members)
        assert not any("/node_modules/" in name for name in wheel_members)
        archive.extractall(installed)

    script = """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from echelon.prosaic_packages import install_prosaic_bundle

workspace = Path(sys.argv[2])
install_prosaic_bundle(workspace, run=lambda *_args, **_kwargs: None)
assert not (workspace / ".echelon/packages").exists()
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
