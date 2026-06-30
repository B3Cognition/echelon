from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{SRC}{os.pathsep}{existing}" if existing else str(SRC)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_workspace_manifest_cli_single_repo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "workspace-manifest.json"

    result = _run(
        [sys.executable, "-m", "echelon.workspace_model", str(tmp_path), str(output)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["workspace"]["git_role"] == "source"
    assert data["sources"][0]["path"] == "."


def test_workspace_manifest_cli_polyrepo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    for name in ["og-platform", "pbg-api"]:
        source = tmp_path / name
        source.mkdir()
        (source / ".git").mkdir()
        (source / "package.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "workspace-manifest.json"

    result = _run(
        [sys.executable, "-m", "echelon.workspace_model", str(tmp_path), str(output)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["workspace"]["git_role"] == "orchestration"
    assert [source["path"] for source in data["sources"]] == [
        "og-platform",
        "pbg-api",
    ]
