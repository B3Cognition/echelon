"""State-location contracts for the deployed Prosaic/runtime bundle."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
PROSAIC = ROOT / "prosaic"


def test_prosaic_bundle_does_not_reference_legacy_extension_installation() -> None:
    findings = []
    for prose_file in PROSAIC.rglob("*.md"):
        for line_number, line in enumerate(
            prose_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ".specify/extensions/echelon" in line:
                findings.append(
                    f"{prose_file.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_prosaic_bundle_does_not_invoke_spec_kit_commands() -> None:
    legacy_command = re.compile(r"/?speckit\.[A-Za-z0-9_.-]+")
    findings = []
    for prose_file in PROSAIC.rglob("*.md"):
        for line_number, line in enumerate(
            prose_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if legacy_command.search(line):
                findings.append(
                    f"{prose_file.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_prosaic_bundle_does_not_describe_spec_kit_storage_or_runtime() -> None:
    legacy_reference = re.compile(r"\.specify|speckit", re.IGNORECASE)
    findings = []
    for prose_file in PROSAIC.rglob("*.md"):
        for line_number, line in enumerate(
            prose_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if legacy_reference.search(line):
                findings.append(
                    f"{prose_file.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_runtime_workflow_does_not_describe_spec_kit_fallbacks() -> None:
    legacy_reference = re.compile(r"\.specify|speckit|spec-kit", re.IGNORECASE)
    findings = []
    for workflow_file in (RUNTIME / "workflow").rglob("*"):
        if workflow_file.suffix not in {".md", ".yaml", ".yml"}:
            continue
        for line_number, line in enumerate(
            workflow_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if legacy_reference.search(line):
                findings.append(
                    f"{workflow_file.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_active_harness_config_resolution_does_not_use_legacy_extension_config() -> None:
    findings = []
    active_modules = (
        ROOT / "src" / "harness" / "config.py",
        ROOT / "src" / "harness" / "quality_scores.py",
        ROOT / "src" / "harness" / "squad.py",
        ROOT / "src" / "harness" / "squad_executors.py",
    )
    for module in active_modules:
        for line_number, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "echelon-config.yml" in line:
                findings.append(
                    f"{module.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_active_prompt_assembly_does_not_rewrite_legacy_squad_paths() -> None:
    findings = []
    active_modules = (
        ROOT / "src" / "echelon" / "cli.py",
        ROOT / "src" / "harness" / "squad_executors.py",
    )
    for module in active_modules:
        for line_number, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if ".specify/squad" in line:
                findings.append(
                    f"{module.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )

    assert not findings, "\n".join(findings)


def test_runtime_uses_echelon_owned_standalone_re_state() -> None:
    config = (RUNTIME / "config-template.yml").read_text(encoding="utf-8")
    discovery = (RUNTIME / "scripts" / "bash" / "re" / "discover-repos.sh").read_text(
        encoding="utf-8"
    )
    analysis = (RUNTIME / "scripts" / "bash" / "re" / "run-analysis.sh").read_text(
        encoding="utf-8"
    )
    bridge = (RUNTIME / "scripts" / "node" / "codegraph" / "codegraph-bridge.js").read_text(
        encoding="utf-8"
    )

    for text in (config, discovery, analysis, bridge):
        assert ".echelon/re" in text
        assert ".specify/echelon/re" not in text


def test_prosaic_re_commands_describe_echelon_owned_standalone_state() -> None:
    command = (PROSAIC / "commands" / "echelon.re-extract.md").read_text(
        encoding="utf-8"
    )

    assert "standalone `re-*`: `.echelon/re/state.json`" in command
    assert ".specify/echelon/re" not in command


def test_prosaic_runtime_does_not_direct_agents_to_legacy_squad_storage() -> None:
    commander = (PROSAIC / "subagents" / "echelon.commander.md").read_text(
        encoding="utf-8"
    )
    init = (PROSAIC / "commands" / "echelon.init.md").read_text(encoding="utf-8")
    veteran = (PROSAIC / "subagents" / "echelon.veteran.md").read_text(
        encoding="utf-8"
    )

    assert ".specify/squad" not in commander
    assert ".specify/squad" not in init
    assert ".specify/squad-global" not in veteran
    assert "~/.echelon/knowledge-base/" in veteran


def _run_cli_deploy_init(project: Path, home: Path, install_path: Path | None = None) -> dict:
    fake_bin = home / "bin"
    fake_bin.mkdir(parents=True)
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    docker.chmod(0o755)

    config = project / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "deploy:\n"
        "  type: cli\n"
        "  health_check: 'true'\n"
        f"  install_path: '{install_path or ''}'\n",
        encoding="utf-8",
    )
    environment = os.environ | {
        "HOME": str(home),
        "PATH": f"{fake_bin}:{Path(sys.executable).parent}:{os.environ['PATH']}",
    }
    subprocess.run(
        ["bash", str(RUNTIME / "scripts" / "bash" / "deploy-init.sh"), str(project)],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )
    return json.loads((project / "runs" / "deploy-state.json").read_text(encoding="utf-8"))


def test_fresh_cli_deploy_init_uses_echelon_infrastructure(tmp_path: Path) -> None:
    project = tmp_path / "fresh-project"
    state = _run_cli_deploy_init(project, tmp_path / "home")

    assert state["global_state_dir"] == str(tmp_path / "home" / ".echelon" / "deploy")
    assert state["traefik_name"] == "echelon-traefik"
    assert state["deploy_network"] == "echelon-deploy"
    assert (tmp_path / "home" / ".echelon" / "deploy" / "fresh-project.json").exists()


def test_fresh_cli_deploy_init_ignores_unmigrated_legacy_global_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "legacy-project"
    home = tmp_path / "home"
    legacy_state = home / ".speckit-deploy" / "legacy-project.json"
    legacy_state.parent.mkdir(parents=True)
    legacy_state.write_text("{}", encoding="utf-8")

    state = _run_cli_deploy_init(project, home)

    assert state["global_state_dir"] == str(home / ".echelon" / "deploy")
    assert state["traefik_name"] == "echelon-traefik"
    assert state["deploy_network"] == "echelon-deploy"


def test_deploy_runtime_does_not_discover_or_default_to_speckit_resources() -> None:
    findings = []
    for script in (RUNTIME / "scripts" / "bash").glob("deploy*.sh"):
        for line_number, line in enumerate(
            script.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "speckit" in line.lower():
                findings.append(
                    f"{script.relative_to(ROOT)}:{line_number}: {line.strip()}"
                )
    validate = RUNTIME / "scripts" / "bash" / "validate-deploy.sh"
    for line_number, line in enumerate(
        validate.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if "speckit" in line.lower():
            findings.append(
                f"{validate.relative_to(ROOT)}:{line_number}: {line.strip()}"
            )

    assert not findings, "\n".join(findings)


def test_cli_deploy_wrapper_reads_the_selected_global_state_directory(tmp_path: Path) -> None:
    project = tmp_path / "wrapper-project"
    home = tmp_path / "home"
    install_path = tmp_path / "bin"

    state = _run_cli_deploy_init(project, home, install_path)

    wrapper = (install_path / "wrapper-project").read_text(encoding="utf-8")
    assert f'_state_file="{state["global_state_dir"]}/wrapper-project.json"' in wrapper
