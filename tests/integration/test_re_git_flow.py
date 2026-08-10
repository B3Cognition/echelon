from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FINALIZE = ROOT / "runtime/scripts/bash/finalize-run.sh"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_index(root: Path, generation: int) -> None:
    path = root / "re/index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generation": generation}) + "\n", encoding="utf-8")


def test_finalize_commits_durable_re_on_feature_and_restores_main(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Echelon Tests")
    (tmp_path / "README.md").write_text("# Workspace\n", encoding="utf-8")
    re_root = tmp_path / "re"
    re_root.mkdir()
    (re_root / ".gitignore").write_text(
        ".cache/\n.staging/\n.locks/\n",
        encoding="utf-8",
    )
    _write_index(tmp_path, 0)
    _git(tmp_path, "add", "README.md", "re/.gitignore", "re/index.json")
    _git(tmp_path, "commit", "-m", "initial")
    _git(tmp_path, "checkout", "-b", "001-demo")

    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo spec\n", encoding="utf-8")
    constitution = tmp_path / ".echelon/constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReal rules.\n", encoding="utf-8")
    _write_index(tmp_path, 2)
    source = re_root / "sources/api"
    source.mkdir(parents=True)
    (source / "overview.md").write_text("# API\n", encoding="utf-8")
    workspace = re_root / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "overview.md").write_text("# Workspace\n", encoding="utf-8")
    (workspace / "relationships.md").write_text("# Relationships\n", encoding="utf-8")
    (workspace / "contracts.md").write_text("# Contracts\n", encoding="utf-8")
    for runtime in (".cache", ".staging", ".locks"):
        runtime_dir = re_root / runtime
        runtime_dir.mkdir()
        (runtime_dir / "sentinel.txt").write_text("runtime\n", encoding="utf-8")

    subprocess.run(
        ["bash", str(FINALIZE), str(tmp_path), "001", "demo", "run-1"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert _git(tmp_path, "branch", "--show-current").stdout.strip() == "main"
    main_index = json.loads((tmp_path / "re/index.json").read_text(encoding="utf-8"))
    assert main_index["generation"] == 0
    committed = _git(
        tmp_path,
        "show",
        "--format=",
        "--name-only",
        "001-demo",
    ).stdout.splitlines()
    assert "specs/001-demo/spec.md" in committed
    assert "re/index.json" in committed
    assert "re/sources/api/overview.md" in committed
    assert "re/workspace/contracts.md" in committed
    assert not any(
        path.startswith(("re/.cache/", "re/.staging/", "re/.locks/"))
        for path in committed
    )
