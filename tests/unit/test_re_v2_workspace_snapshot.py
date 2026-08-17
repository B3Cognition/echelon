from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping

import pytest

from echelon.workspace_model import SourceRoot
from harness.re_v2.workspace_snapshot import (
    ReV2WorkspaceSourceError,
    plan_clean_workspace_sources,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        },
    ).stdout


def _clean_repo(path: Path, tracked: Mapping[str, str]) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    for relative, payload in tracked.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "fixture")
    return path


def _source(source_id: str, path: str, *, git_role: str = "source") -> SourceRoot:
    return SourceRoot(
        id=source_id,
        path=path,
        git_present=True,
        git_role=git_role,  # type: ignore[arg-type]
    )


def _sources(workspace: Path, *repositories: Path) -> tuple[SourceRoot, ...]:
    return tuple(
        _source(repository.name, repository.relative_to(workspace).as_posix())
        for repository in repositories
    )


@pytest.mark.unit
def test_preflight_pins_two_clean_child_repositories(tmp_path: Path) -> None:
    first = _clean_repo(tmp_path / "sources" / "first", {"a.py": "a\n"})
    second = _clean_repo(tmp_path / "sources" / "second", {"b.py": "b\n"})

    plan = plan_clean_workspace_sources(tmp_path, _sources(tmp_path, first, second))

    assert [proof.source_id for proof in plan.sources] == ["first", "second"]
    assert [proof.workspace_path for proof in plan.sources] == [
        "sources/first",
        "sources/second",
    ]
    assert [proof.repository_path for proof in plan.sources] == [".", "."]
    assert [proof.commit for proof in plan.sources] == [
        _git(first, "rev-parse", "HEAD").strip(),
        _git(second, "rev-parse", "HEAD").strip(),
    ]
    assert plan.repositories == (first.resolve(), second.resolve())


@pytest.mark.unit
def test_preflight_aggregates_dirty_sources_and_remediation(tmp_path: Path) -> None:
    first = _clean_repo(tmp_path / "sources" / "first", {"a.py": "a\n"})
    second = _clean_repo(tmp_path / "sources" / "second", {"b.py": "b\n"})
    third = _clean_repo(tmp_path / "sources" / "third", {"c.py": "c\n"})
    (first / "a.py").write_text("changed\n", encoding="utf-8")
    (second / "new.py").write_text("new\n", encoding="utf-8")
    (third / "staged.py").write_text("staged\n", encoding="utf-8")
    _git(third, "add", "staged.py")

    with pytest.raises(ReV2WorkspaceSourceError) as exc:
        plan_clean_workspace_sources(
            tmp_path,
            _sources(tmp_path, first, second, third),
        )

    message = str(exc.value)
    assert all(source_id in message for source_id in ("first", "second", "third"))
    assert "modified" in message and "untracked" in message and "staged" in message
    assert "commit" in message.lower()
    assert "stash" in message.lower() and "untracked" in message.lower()
    assert "revert" in message.lower()


@pytest.mark.unit
def test_preflight_ignores_git_ignored_dependency_symlinks(tmp_path: Path) -> None:
    repo = _clean_repo(
        tmp_path / "repo",
        {".gitignore": "node_modules/\n", "src/app.py": "pass\n"},
    )
    binary = repo / "node_modules" / ".bin" / "tool"
    binary.parent.mkdir(parents=True)
    binary.symlink_to("../tool.js")

    plan = plan_clean_workspace_sources(tmp_path, _sources(tmp_path, repo))

    assert plan.sources[0].commit == _git(repo, "rev-parse", "HEAD").strip()


@pytest.mark.unit
def test_preflight_allows_nonoverlapping_subtrees_in_one_clean_repo(
    tmp_path: Path,
) -> None:
    repo = _clean_repo(
        tmp_path / "mono",
        {"apps/a/a.py": "a\n", "apps/b/b.py": "b\n"},
    )
    sources = (_source("a", "mono/apps/a"), _source("b", "mono/apps/b"))

    plan = plan_clean_workspace_sources(tmp_path, sources)

    assert len(plan.repositories) == 1
    assert [proof.repository_path for proof in plan.sources] == ["apps/a", "apps/b"]


@pytest.mark.unit
def test_preflight_rejects_non_git_source_with_other_dirty_sources(
    tmp_path: Path,
) -> None:
    dirty = _clean_repo(tmp_path / "dirty", {"app.py": "pass\n"})
    (dirty / "app.py").write_text("changed\n", encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "note.txt").write_text("not Git\n", encoding="utf-8")

    with pytest.raises(ReV2WorkspaceSourceError) as exc:
        plan_clean_workspace_sources(
            tmp_path,
            (_source("dirty", "dirty"), _source("plain", "plain")),
        )

    message = str(exc.value)
    assert "dirty" in message and "modified" in message
    assert "plain" in message and "Git" in message


@pytest.mark.unit
def test_preflight_rejects_overlapping_declared_source_paths(tmp_path: Path) -> None:
    _clean_repo(tmp_path / "mono", {"apps/a.py": "a\n"})

    with pytest.raises(ReV2WorkspaceSourceError, match="overlap"):
        plan_clean_workspace_sources(
            tmp_path,
            (_source("mono", "mono"), _source("apps", "mono/apps")),
        )


@pytest.mark.unit
def test_preflight_rejects_uninitialized_submodule(tmp_path: Path) -> None:
    child = _clean_repo(tmp_path / "child", {"child.py": "pass\n"})
    parent = _clean_repo(tmp_path / "parent", {"parent.py": "pass\n"})
    _git(
        parent,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(child),
        "modules/child",
    )
    _git(parent, "commit", "-am", "add submodule")
    _git(parent, "submodule", "deinit", "-f", "modules/child")

    with pytest.raises(ReV2WorkspaceSourceError, match="submodule"):
        plan_clean_workspace_sources(tmp_path, (_source("parent", "parent"),))
