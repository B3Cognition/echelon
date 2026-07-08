from __future__ import annotations

from pathlib import Path

import pytest

from echelon.cli import _workspace_git_preflight


def test_branchless_polyrepo_workspace_blocks_with_init_recipe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _workspace_git_preflight(tmp_path, command_name="echelon delivery run")

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "workspace root is not a Git repo" in err
    assert "git init" in err
    assert "/og-platform/" in err
    assert "/.specify/" in err
    assert "/runs/" in err
    assert "git add .gitignore specs" in err
    assert "git add .gitignore .specify specs" not in err
    assert "echelon delivery run" in err


def test_git_backed_polyrepo_workspace_passes(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")

    _workspace_git_preflight(tmp_path, command_name="echelon delivery run")


def test_single_repo_workspace_passes(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    _workspace_git_preflight(tmp_path, command_name="echelon spec run")
