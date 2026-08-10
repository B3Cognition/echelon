from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "runtime" / "scripts" / "bash" / "echelon-config-get.sh"


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _script_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "specify").write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    (bin_dir / "specify").chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return env


def _run_get(project: Path, key: str, tmp_path: Path) -> str:
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), key],
        cwd=project,
        env=_script_env(tmp_path),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def test_config_get_layers_canonical_local_over_project_config(tmp_path: Path) -> None:
    project = tmp_path / "workspace"
    (project / ".specify").mkdir(parents=True)
    _write_yaml(project / ".echelon" / "config.yml", {
        "re": {
            "output": {"directory": ".specify/echelon/re"},
            "workflow": {"coverage_threshold": 80},
        },
    })
    _write_yaml(project / ".echelon" / "local.yml", {
        "re": {
            "output": {"directory": "runs/spec-001/re"},
        },
    })

    assert _run_get(project, "re.output.directory", tmp_path) == "runs/spec-001/re"
    assert _run_get(project, "re.workflow.coverage_threshold", tmp_path) == "80"


def test_config_get_ignores_retired_speckit_local_config(tmp_path: Path) -> None:
    project = tmp_path / "workspace"
    (project / ".specify").mkdir(parents=True)
    _write_yaml(project / ".echelon" / "config.yml", {
        "re": {
            "analysis": {"max_files": 80},
            "output": {"directory": ".specify/echelon/re"},
        },
    })
    _write_yaml(project / ".specify" / "extensions" / "echelon" / "local-config.yml", {
        "re": {
            "analysis": {"max_files": 25},
            "output": {"directory": "runs/spec-002/re"},
        },
    })

    assert _run_get(project, "re.analysis.max_files", tmp_path) == "80"
    assert _run_get(project, "re.output.directory", tmp_path) == ".specify/echelon/re"
