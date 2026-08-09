"""Executable contract for the Prosaic runtime configuration resolver."""

import os
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "runtime" / "scripts" / "bash" / "echelon-config-get.sh"


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_runtime_config_resolver_uses_echelon_project_and_local_config(
    tmp_path: Path,
) -> None:
    project = tmp_path / "workspace"
    _write_yaml(project / ".echelon" / "config.yml", {"re": {"profile": "full"}})
    _write_yaml(project / ".echelon" / "local.yml", {"re": {"profile": "survey"}})

    completed = subprocess.run(
        ["bash", str(SCRIPT), "re.profile"],
        cwd=project,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "survey"


def test_runtime_config_resolver_has_no_speckit_dependency() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "specify extension config resolve" not in text
    assert ".specify/extensions/echelon" not in text


def test_runtime_workflow_uses_echelon_commands_and_runtime_paths() -> None:
    forbidden = (
        ".specify/extensions/echelon",
        "speckit.echelon.",
        "specify extension add",
        "specify extension config resolve",
    )
    stale = [
        f"{path.relative_to(ROOT)}: {marker}"
        for bundle in (ROOT / "runtime", ROOT / "prosaic")
        for path in bundle.rglob("*")
        if path.is_file()
        for marker in forbidden
        if marker in path.read_text(encoding="utf-8", errors="ignore")
    ]

    assert stale == []


def test_prosaic_harness_operations_use_echelon_owned_state() -> None:
    command_names = (
        "echelon.harness-status.md",
        "echelon.harness-resume.md",
        "echelon.harness-run.md",
        "echelon.deploy.md",
    )
    stale = [
        path.name
        for name in command_names
        if ".specify" in (path := ROOT / "prosaic" / "commands" / name).read_text(
            encoding="utf-8"
        )
    ]

    assert stale == []


def test_runtime_workspace_helpers_anchor_on_echelon_paths() -> None:
    helper_paths = (
        ROOT / "runtime" / "scripts" / "bash" / "kb-read-init.sh",
        ROOT / "runtime" / "scripts" / "bash" / "detect-project.sh",
        ROOT / "runtime" / "scripts" / "bash" / "cicd-fingerprint.sh",
        ROOT / "runtime" / "scripts" / "bash" / "re" / "discover-repos.sh",
        ROOT / "runtime" / "workflow" / "phases" / "codegen-A-preamble.md",
    )

    stale = [
        path.relative_to(ROOT).as_posix()
        for path in helper_paths
        if ".specify" in path.read_text(encoding="utf-8")
    ]

    assert stale == []
