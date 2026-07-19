from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from echelon.spec_publish import (
    SpecPublishError,
    discover_publication_sources,
    publish_specs,
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


def _create_spec_branch(
    repo: Path,
    branch: str,
    spec_text: str,
    *,
    extra_files: dict[str, str] | None = None,
) -> str:
    _git(repo, "switch", "main")
    _git(repo, "switch", "-c", branch)
    spec_dir = repo / "specs" / branch
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
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


@pytest.mark.unit
def test_publish_one_copies_only_matching_committed_spec_and_retains_branch(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    source_commit = _create_spec_branch(
        repo,
        "001-first",
        "# First\n",
        extra_files={
            "specs/001-first/plan.md": "# Plan\n",
            "src/implementation.py": "do_not_publish = True\n",
        },
    )
    source_ref_before = _git(repo, "rev-parse", "refs/heads/001-first")

    result = publish_specs(repo, identity="001")

    assert result.created_commit is True
    assert result.default_branch == "main"
    assert result.published[0].source_commit == source_commit
    assert result.published[0].changed is True
    assert (repo / "specs/001-first/spec.md").read_text(encoding="utf-8") == "# First\n"
    assert (repo / "specs/001-first/plan.md").is_file()
    assert not (repo / "src/implementation.py").exists()
    manifest = json.loads(
        (repo / "specs/001-first/.echelon-publication.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest == {
        "schema_version": 1,
        "source_branch": "001-first",
        "source_commit": source_commit,
        "spec_id": "001-first",
    }
    assert _git(repo, "rev-parse", "refs/heads/001-first") == source_ref_before
    assert _git(repo, "status", "--short") == ""


@pytest.mark.unit
def test_publish_all_is_one_commit_and_republish_is_noop(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _create_spec_branch(repo, "001-first", "# First\n")
    _create_spec_branch(repo, "002-second", "# Second\n")
    before = int(_git(repo, "rev-list", "--count", "main"))

    first = publish_specs(repo, publish_all=True)
    second = publish_specs(repo, publish_all=True)

    assert int(_git(repo, "rev-list", "--count", "main")) == before + 1
    assert first.created_commit is True
    assert [item.spec_id for item in first.published] == ["001-first", "002-second"]
    assert second.created_commit is False
    assert second.default_commit == first.default_commit
    assert all(item.changed is False for item in second.published)
    assert _git(repo, "status", "--short") == ""


@pytest.mark.unit
def test_republish_replaces_snapshot_exactly_and_removes_stale_files(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _create_spec_branch(
        repo,
        "001-first",
        "# First\n",
        extra_files={"specs/001-first/obsolete.md": "old\n"},
    )
    publish_specs(repo, identity="001")
    _git(repo, "switch", "001-first")
    (repo / "specs/001-first/obsolete.md").unlink()
    (repo / "specs/001-first/spec.md").write_text("# Updated\n", encoding="utf-8")
    _git(repo, "add", "-A", "specs/001-first")
    _git(repo, "commit", "-m", "docs: update first")
    _git(repo, "switch", "main")

    result = publish_specs(repo, identity="001")

    assert result.created_commit is True
    assert not (repo / "specs/001-first/obsolete.md").exists()
    assert (repo / "specs/001-first/spec.md").read_text() == "# Updated\n"


@pytest.mark.unit
def test_publish_rejects_same_number_destination_collision_before_mutation(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _create_spec_branch(repo, "001-new", "# New\n")
    old = repo / "specs/001-old"
    old.mkdir(parents=True)
    (old / "spec.md").write_text("# Old\n", encoding="utf-8")
    _git(repo, "add", "specs/001-old")
    _git(repo, "commit", "-m", "docs: publish old")
    main_before = _git(repo, "rev-parse", "main")

    with pytest.raises(SpecPublishError, match="collision.*001-old.*001-new"):
        publish_specs(repo, identity="001-new")

    assert _git(repo, "rev-parse", "main") == main_before
    assert (old / "spec.md").read_text() == "# Old\n"
    assert not (repo / "specs/001-new").exists()
    assert _git(repo, "status", "--short") == ""
