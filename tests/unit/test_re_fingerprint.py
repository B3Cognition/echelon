from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.re_fingerprint import ReFingerprintProfile, fingerprint_source


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> str:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    (repo / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "index.ts").write_text("export const value = 1;\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return _git(repo, "rev-parse", "HEAD")


def test_clean_git_source_fingerprint_uses_head_and_profile_inputs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = _init_repo(repo)
    profile = ReFingerprintProfile(
        profile="deep",
        depth="signatures",
        max_lines_per_file=400,
        git_history_limit=20,
        codegraph_version="cg-1",
    )

    first = fingerprint_source(repo, profile)
    second = fingerprint_source(repo, profile)
    changed_profile = fingerprint_source(
        repo,
        ReFingerprintProfile(
            profile="deep",
            depth="full",
            max_lines_per_file=400,
            git_history_limit=20,
            codegraph_version="cg-1",
        ),
    )

    assert first.kind == "git"
    assert first.git_head == head
    assert first.dirty is False
    assert first.value == second.value
    assert first.value != changed_profile.value


def test_dirty_git_source_fingerprint_includes_tracked_and_untracked_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    profile = ReFingerprintProfile()
    clean = fingerprint_source(repo, profile)

    (repo / "src" / "index.ts").write_text("export const value = 2;\n", encoding="utf-8")
    tracked_dirty = fingerprint_source(repo, profile)
    (repo / "notes.md").write_text("untracked context\n", encoding="utf-8")
    untracked_dirty = fingerprint_source(repo, profile)

    assert tracked_dirty.dirty is True
    assert tracked_dirty.value != clean.value
    assert untracked_dirty.dirty is True
    assert untracked_dirty.value != tracked_dirty.value


def test_non_git_source_fingerprint_hashes_relevant_files_and_profile_inputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "package.json").write_text('{"name":"plain"}\n', encoding="utf-8")
    (source / "node_modules").mkdir()
    (source / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")
    (source / "README.md").write_text("# Plain\n", encoding="utf-8")

    profile = ReFingerprintProfile(profile="survey", depth="structure")
    first = fingerprint_source(source, profile)
    (source / "node_modules" / "ignored.js").write_text("ignored changed\n", encoding="utf-8")
    ignored_change = fingerprint_source(source, profile)
    (source / "README.md").write_text("# Plain changed\n", encoding="utf-8")
    relevant_change = fingerprint_source(source, profile)

    assert first.kind == "file-tree"
    assert first.git_head is None
    assert first.dirty is False
    assert ignored_change.value == first.value
    assert relevant_change.value != first.value


def test_re_fingerprint_profile_round_trips_and_hashes_stable_json() -> None:
    profile = ReFingerprintProfile(
        profile="deep",
        depth="full",
        max_lines_per_file=3200,
        git_history_limit=1400,
        codegraph_version="cg-2",
    )

    restored = ReFingerprintProfile.from_json_dict(profile.to_json_dict())

    assert restored == profile
    assert restored.profile_hash() == profile.profile_hash()


def test_re_fingerprint_profile_rejects_invalid_numeric_fields() -> None:
    with pytest.raises(ValueError, match="max_lines_per_file"):
        ReFingerprintProfile.from_json_dict(
            {
                "profile": "full",
                "depth": "full",
                "max_lines_per_file": True,
                "git_history_limit": 2500,
                "codegraph_version": None,
            }
        )
