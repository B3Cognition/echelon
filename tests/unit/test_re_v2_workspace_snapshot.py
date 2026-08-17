from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

import pytest

from echelon.workspace_model import SourceRoot
from harness.re_v2.snapshot import ReV2SnapshotError, load_snapshot_manifest
from harness.re_v2.workspace_snapshot import (
    ReV2WorkspaceSourceError,
    capture_workspace_snapshot,
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
    for phrase in (
        "RE v2 requires clean Git sources",
        "Commit",
        "stash",
        "including untracked files",
        "revert or remove",
        "echelon re run --engine v2",
    ):
        assert phrase in message


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


@pytest.mark.unit
def test_composite_capture_uses_declared_repositories_not_orchestration_root(
    tmp_path: Path,
) -> None:
    workspace = _clean_repo(
        tmp_path / "workspace",
        {
            ".gitignore": "/sources/*\n!/sources/README.md\n",
            "sources/README.md": "repos\n",
        },
    )
    tooling_link = workspace / ".claude" / "skills" / "tool" / "SKILL.md"
    tooling_link.parent.mkdir(parents=True)
    tooling_link.symlink_to("../../../../outside-skill.md")
    first = _clean_repo(workspace / "sources" / "first", {"src/a.py": "a\n"})
    second = _clean_repo(workspace / "sources" / "second", {"src/b.py": "b\n"})
    ignored_link = second / "node_modules" / ".bin" / "tool"
    (second / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _git(second, "add", ".gitignore")
    _git(second, "commit", "-m", "ignore dependencies")
    ignored_link.parent.mkdir(parents=True)
    ignored_link.symlink_to("../tool.js")

    snapshot = capture_workspace_snapshot(
        workspace,
        (_source("first", "sources/first"), _source("second", "sources/second")),
        tmp_path / "snapshots",
    )

    assert (snapshot.read_root / "sources/first/src/a.py").read_text() == "a\n"
    assert (snapshot.read_root / "sources/second/src/b.py").read_text() == "b\n"
    assert not (snapshot.read_root / ".claude").exists()
    assert not (snapshot.read_root / "sources/README.md").exists()
    assert not (snapshot.read_root / "sources/second/node_modules").exists()


@pytest.mark.unit
def test_composite_capture_materializes_shared_repository_subtrees_once(
    tmp_path: Path,
) -> None:
    workspace = _clean_repo(
        tmp_path / "workspace",
        {"apps/a/a.py": "a\n", "apps/b/b.py": "b\n", "outside.txt": "no\n"},
    )

    snapshot = capture_workspace_snapshot(
        workspace,
        (_source("a", "apps/a"), _source("b", "apps/b")),
        tmp_path / "snapshots",
    )

    assert (snapshot.read_root / "apps/a/a.py").read_text() == "a\n"
    assert (snapshot.read_root / "apps/b/b.py").read_text() == "b\n"
    assert not (snapshot.read_root / "outside.txt").exists()
    assert len(load_snapshot_manifest(snapshot).components or ()) == 2


@pytest.mark.unit
def test_composite_capture_materializes_recursive_submodule_identity_and_bytes(
    tmp_path: Path,
) -> None:
    child = _clean_repo(tmp_path / "child", {"child.py": "child\n"})
    workspace = _clean_repo(tmp_path / "workspace", {"parent.py": "parent\n"})
    _git(
        workspace,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(child),
        "modules/child",
    )
    _git(workspace, "commit", "-am", "add child")

    snapshot = capture_workspace_snapshot(
        workspace,
        (_source("workspace", "."),),
        tmp_path / "snapshots",
    )
    component = (load_snapshot_manifest(snapshot).components or ())[0]

    assert (snapshot.read_root / "modules/child/child.py").read_text() == "child\n"
    assert component.submodules == (
        ("modules/child", _git(child, "rev-parse", "HEAD").strip()),
    )


@pytest.mark.unit
def test_composite_capture_rejects_tracked_symlink_and_cleans_worktree(
    tmp_path: Path,
) -> None:
    workspace = _clean_repo(tmp_path / "workspace", {"app.py": "pass\n"})
    (workspace / "linked.py").symlink_to("app.py")
    _git(workspace, "add", "linked.py")
    _git(workspace, "commit", "-m", "track link")

    with pytest.raises(ReV2SnapshotError, match="symlink"):
        capture_workspace_snapshot(
            workspace,
            (_source("workspace", "."),),
            tmp_path / "snapshots",
        )

    assert ".snapshot-stage-worktree-" not in _git(
        workspace, "worktree", "list", "--porcelain"
    )


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ("untracked", "head"))
def test_composite_capture_rejects_source_mutation_before_publish(
    tmp_path: Path,
    mutation: str,
) -> None:
    workspace = _clean_repo(tmp_path / "workspace", {"app.py": "pass\n"})

    def mutate(point: str) -> None:
        if point != "before_publish":
            return
        (workspace / "late.py").write_text("late\n", encoding="utf-8")
        if mutation == "head":
            _git(workspace, "add", "late.py")
            _git(workspace, "commit", "-m", "late")

    with pytest.raises(ReV2WorkspaceSourceError, match="changed during capture"):
        capture_workspace_snapshot(
            workspace,
            (_source("workspace", "."),),
            tmp_path / "snapshots",
            fault_hook=mutate,
        )

    assert ".snapshot-stage-worktree-" not in _git(
        workspace, "worktree", "list", "--porcelain"
    )


COMPOSITE_FAULTS = (
    "source_worktree_added",
    "source_tree_copied",
    "before_publish",
    "source_installed",
    "manifest_installed",
    "permissions_normalized",
    "bundle_fsynced",
    "final_promoted",
    "marker_linked",
    "marker_root_fsynced",
    "marker_destination_fsynced",
    "marker_temporary_cleaned",
    "final_validated",
)


@pytest.mark.unit
@pytest.mark.parametrize("boundary", COMPOSITE_FAULTS)
def test_composite_capture_recovers_every_publication_fault(
    tmp_path: Path,
    boundary: str,
) -> None:
    first = _clean_repo(tmp_path / "first", {"a.py": "a\n"})
    second = _clean_repo(tmp_path / "second", {"b.py": "b\n"})
    sources = _sources(tmp_path, first, second)
    destination = tmp_path.parent / f"{tmp_path.name}-snapshots"
    fired = False

    def crash_once(point: str) -> None:
        nonlocal fired
        if point == boundary and not fired:
            fired = True
            raise RuntimeError(f"crash at {point}")

    with pytest.raises(Exception, match="crash at"):
        capture_workspace_snapshot(
            tmp_path,
            sources,
            destination,
            fault_hook=crash_once,
        )
    assert fired

    snapshot = capture_workspace_snapshot(tmp_path, sources, destination)
    manifest = load_snapshot_manifest(snapshot)

    assert [component.source_id for component in manifest.components or ()] == [
        "first",
        "second",
    ]
    assert len(
        [
            path
            for path in destination.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]
    ) == 1
    assert len(list((destination / ".snapshot-commits").glob("*.json"))) == 1
    assert not list(destination.glob(".snapshot-stage-*"))
    assert not list(destination.glob(".workspace-prepare-*"))
    for repository in (first, second):
        assert ".snapshot-stage-worktree-" not in _git(
            repository, "worktree", "list", "--porcelain"
        )


@pytest.mark.unit
def test_composite_capture_converges_for_concurrent_writers(tmp_path: Path) -> None:
    first = _clean_repo(tmp_path / "first", {"a.py": "a\n"})
    second = _clean_repo(tmp_path / "second", {"b.py": "b\n"})
    destination = tmp_path.parent / f"{tmp_path.name}-snapshots"
    script = """
from pathlib import Path
from types import SimpleNamespace
import sys
from harness.re_v2.workspace_snapshot import capture_workspace_snapshot

workspace = Path(sys.argv[1])
destination = Path(sys.argv[2])
sources = tuple(
    SimpleNamespace(id=name, path=name, git_role="source")
    for name in ("first", "second")
)
print(capture_workspace_snapshot(workspace, sources, destination).snapshot_id)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), str(destination)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        )
        for _ in range(2)
    ]
    results = [process.communicate(timeout=30) for process in processes]

    assert all(process.returncode == 0 for process in processes), results
    snapshot_ids = [stdout.strip().splitlines()[-1] for stdout, _stderr in results]
    assert len(set(snapshot_ids)) == 1
    assert len(
        [
            path
            for path in destination.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]
    ) == 1
    assert len(list((destination / ".snapshot-commits").glob("*.json"))) == 1
    for repository in (first, second):
        assert ".snapshot-stage-worktree-" not in _git(
            repository, "worktree", "list", "--porcelain"
        )
