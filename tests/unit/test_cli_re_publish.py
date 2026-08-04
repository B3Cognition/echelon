from __future__ import annotations

import subprocess
from pathlib import Path
import json

import pytest

from echelon.cli import _cmd_re_publish
from tests.unit.test_re_publication import write_valid_re_run


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_workspace(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Echelon Tests")
    (root / "README.md").write_text("# Workspace\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "initial")


def test_publish_without_commit_leaves_re_changes_uncommitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _git_workspace(tmp_path)
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    monkeypatch.chdir(tmp_path)

    _cmd_re_publish([run_dir.name])

    assert _git(tmp_path, "status", "--short", "--", "re").stdout.strip()
    assert _git(tmp_path, "log", "-1", "--format=%s").stdout.strip() == "initial"


def test_publish_commit_stages_only_durable_re_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _git_workspace(tmp_path)
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    monkeypatch.chdir(tmp_path)

    _cmd_re_publish([run_dir.name, "--commit"])

    assert (
        _git(tmp_path, "log", "-1", "--format=%s").stdout.strip()
        == "docs(re): publish workspace reverse engineering generation 1"
    )
    committed = _git(tmp_path, "show", "--format=", "--name-only", "HEAD").stdout.splitlines()
    assert "re/index.json" in committed
    assert "re/sources/api/overview.md" in committed
    assert "re/workspace/contracts.md" in committed
    assert not any(
        path.startswith(("re/.cache/", "re/.staging/", "re/.locks/"))
        for path in committed
    )


def test_partial_publish_requires_explicit_override(tmp_path: Path, monkeypatch) -> None:
    run_dir = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-partial",
        status="partial",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_re_publish([run_dir.name])
    assert exc_info.value.code == 1

    _cmd_re_publish([run_dir.name, "--allow-partial"])
    assert (tmp_path / "re/index.json").is_file()


def test_publish_republishes_the_run_that_owns_current_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    monkeypatch.chdir(tmp_path)

    _cmd_re_publish([run_dir.name])
    _cmd_re_publish([run_dir.name])

    index = json.loads((tmp_path / "re/index.json").read_text(encoding="utf-8"))
    assert index["generation"] == 2
    assert index["published_from_run"] == run_dir.name


@pytest.mark.parametrize("run_id", ["../outside", "a/b", ".", ""])
def test_publish_rejects_unsafe_run_ids(tmp_path: Path, monkeypatch, run_id: str) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_re_publish([run_id])

    assert exc_info.value.code == 1
