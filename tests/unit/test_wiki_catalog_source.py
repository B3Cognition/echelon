from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

import pytest

from echelon.wiki.catalog_source import WikiCatalogError, wiki_catalog_source


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path, *, branch: str = "master") -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.name", "Echelon Tests")
    _git(path, "config", "user.email", "echelon@example.test")
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")
    return path


@pytest.mark.unit
def test_non_git_workspace_uses_caller_root(tmp_path: Path) -> None:
    with wiki_catalog_source(tmp_path) as source:
        assert source.workspace_root == tmp_path.resolve()
        assert source.source_root == tmp_path.resolve()
        assert source.branch is None
        assert source.revision is None
        assert source.dirty is False
        assert source.temporary is False


@pytest.mark.unit
def test_default_branch_caller_uses_live_workspace(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")

    with wiki_catalog_source(repo) as source:
        assert source.workspace_root == repo.resolve()
        assert source.source_root == repo.resolve()
        assert source.branch == "master"
        assert source.revision == _git(repo, "rev-parse", "master")
        assert source.dirty is False
        assert source.temporary is False


@pytest.mark.unit
def test_unconfigured_nonstandard_branch_falls_back_to_live_workspace(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo", branch="trunk")

    with wiki_catalog_source(repo) as source:
        assert source.workspace_root == repo.resolve()
        assert source.source_root == repo.resolve()
        assert source.branch is None
        assert source.revision == _git(repo, "rev-parse", "HEAD")
        assert source.dirty is False
        assert source.temporary is False


@pytest.mark.unit
def test_explicit_missing_default_branch_is_an_error(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", branch="trunk")
    config_dir = repo / ".echelon"
    config_dir.mkdir()
    (config_dir / "config.yml").write_text(
        "target_default_branch: missing\n", encoding="utf-8"
    )

    with pytest.raises(WikiCatalogError, match="missing locally"):
        with wiki_catalog_source(repo):
            pass


@pytest.mark.unit
def test_feature_branch_uses_pinned_temporary_default_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    master_commit = _git(repo, "rev-parse", "master")
    _git(repo, "switch", "-c", "004-feature")
    caller_head = _git(repo, "rev-parse", "HEAD")

    with wiki_catalog_source(repo) as source:
        temporary_path = source.source_root
        assert source.workspace_root == repo.resolve()
        assert source.branch == "master"
        assert source.revision == master_commit
        assert source.dirty is False
        assert source.temporary is True
        assert _git(source.source_root, "rev-parse", "HEAD") == master_commit

    assert not temporary_path.exists()
    assert _git(repo, "branch", "--show-current") == "004-feature"
    assert _git(repo, "rev-parse", "HEAD") == caller_head


@pytest.mark.unit
def test_local_config_overrides_committed_default_and_is_available_in_source(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    config_dir = repo / ".echelon"
    config_dir.mkdir()
    (config_dir / "config.yml").write_text(
        "target_default_branch: main\n", encoding="utf-8"
    )
    _git(repo, "add", ".echelon/config.yml")
    _git(repo, "commit", "-m", "configure wrong committed default")
    _git(repo, "switch", "-c", "004-feature")
    (config_dir / "local.yml").write_text(
        "target_default_branch: master\nwiki:\n  auto_refresh: false\n",
        encoding="utf-8",
    )

    with wiki_catalog_source(repo) as source:
        assert source.branch == "master"
        assert source.temporary is True
        assert (source.source_root / ".echelon/local.yml").read_text(
            encoding="utf-8"
        ) == (config_dir / "local.yml").read_text(encoding="utf-8")

    assert (config_dir / "local.yml").is_file()


@pytest.mark.unit
def test_temporary_parent_cleanup_failure_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "switch", "-c", "004-feature")
    retained_parent: Path | None = None

    def fail_cleanup(path: Path) -> None:
        raise OSError(f"cannot remove {path}")

    with pytest.raises(WikiCatalogError, match="retained at"):
        with wiki_catalog_source(repo) as source:
            retained_parent = source.source_root.parent
            monkeypatch.setattr(
                "echelon.wiki.catalog_source._remove_temporary_parent",
                fail_cleanup,
            )

    assert retained_parent is not None
    assert retained_parent.exists()
    monkeypatch.undo()
    shutil.rmtree(retained_parent)


@pytest.mark.unit
def test_setup_and_cleanup_failures_report_retained_temporary_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "switch", "-c", "004-feature")
    config_dir = repo / ".echelon"
    config_dir.mkdir()
    (config_dir / "local.yml").write_text("wiki: {}\n", encoding="utf-8")
    retained: list[Path] = []

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("cannot copy local override")

    def fail_cleanup(path: Path) -> None:
        retained.append(path)
        raise OSError(f"cannot remove {path}")

    monkeypatch.setattr("echelon.wiki.catalog_source.shutil.copy2", fail_copy)
    monkeypatch.setattr(
        "echelon.wiki.catalog_source._remove_temporary_parent", fail_cleanup
    )

    with pytest.raises(WikiCatalogError, match="retained at"):
        with wiki_catalog_source(repo):
            pass

    assert len(retained) == 1
    assert retained[0].exists()
    monkeypatch.undo()
    shutil.rmtree(retained[0])
