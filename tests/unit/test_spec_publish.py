from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from echelon.spec_publish import (
    SpecPublishError,
    discover_publication_sources,
    resolve_publication_sources,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Echelon Tests")
    _git(repo, "config", "user.email", "echelon@example.test")
    (repo / "README.md").write_text("# Test repository\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _create_spec_branch(repo: Path, branch: str, spec_text: str) -> str:
    _git(repo, "switch", "main")
    _git(repo, "switch", "-c", branch)
    spec_dir = repo / "specs" / branch
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    _git(repo, "add", str(spec_dir.relative_to(repo)))
    _git(repo, "commit", "-m", f"docs: author {branch}")
    commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "main")
    return commit


@pytest.mark.unit
def test_discovery_uses_only_canonical_local_branches(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    first_commit = _create_spec_branch(repo, "001-first", "# First\n")
    second_commit = _create_spec_branch(repo, "002-second", "# Second\n")
    _git(repo, "branch", "backup/003-third")
    _git(repo, "branch", "codex/004-fourth")
    _git(repo, "update-ref", "refs/remotes/origin/005-remote", "HEAD")
    _git(repo, "branch", "006-missing-spec")

    sources = discover_publication_sources(repo, "main")

    assert [(source.spec_id, source.commit) for source in sources] == [
        ("001-first", first_commit),
        ("002-second", second_commit),
    ]
    assert all(source.branch == source.spec_id for source in sources)
    assert [source.source_path for source in sources] == [
        "specs/001-first",
        "specs/002-second",
    ]


@pytest.mark.unit
def test_numeric_resolution_rejects_ambiguous_canonical_branches(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _create_spec_branch(repo, "003-first", "# First\n")
    _create_spec_branch(repo, "003-second", "# Second\n")

    with pytest.raises(SpecPublishError, match="ambiguous.*003-first.*003-second"):
        resolve_publication_sources(
            repo,
            identity="003",
            publish_all=False,
            default_branch="main",
        )


@pytest.mark.unit
def test_full_identity_resolves_exact_canonical_local_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    expected_commit = _create_spec_branch(repo, "012-search", "# Search\n")

    sources = resolve_publication_sources(
        repo,
        identity="012-search",
        publish_all=False,
        default_branch="main",
    )

    assert len(sources) == 1
    assert sources[0].spec_id == "012-search"
    assert sources[0].commit == expected_commit


@pytest.mark.unit
def test_resolution_requires_exactly_one_command_form(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    with pytest.raises(SpecPublishError, match="exactly one"):
        resolve_publication_sources(
            repo,
            identity=None,
            publish_all=False,
            default_branch="main",
        )
    with pytest.raises(SpecPublishError, match="exactly one"):
        resolve_publication_sources(
            repo,
            identity="001",
            publish_all=True,
            default_branch="main",
        )
