"""Unit tests for harness.spec_frontmatter.find_spec_dir — walk-up discovery."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.spec_frontmatter import find_spec_dir


def _make_spec(parent: Path, spec_name: str) -> Path:
    spec_dir = parent / "specs" / spec_name
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return spec_dir


@pytest.mark.unit
class TestFindSpecDir:
    def test_found_locally(self, tmp_path: Path) -> None:
        spec = _make_spec(tmp_path, "024-test")
        result = find_spec_dir("024", tmp_path)
        assert result == spec

    def test_found_one_level_up(self, tmp_path: Path) -> None:
        spec = _make_spec(tmp_path, "024-test")
        child = tmp_path / "repo-a"
        child.mkdir()
        result = find_spec_dir("024", child)
        assert result == spec

    def test_found_two_levels_up(self, tmp_path: Path) -> None:
        spec = _make_spec(tmp_path, "024-test")
        child = tmp_path / "org" / "repo-a"
        child.mkdir(parents=True)
        result = find_spec_dir("024", child)
        assert result == spec

    def test_local_takes_precedence_over_parent(self, tmp_path: Path) -> None:
        _make_spec(tmp_path, "024-parent")
        child = tmp_path / "repo-a"
        local_spec = _make_spec(child, "024-local")
        result = find_spec_dir("024", child)
        assert result == local_spec

    def test_stops_at_git_boundary_in_parent(self, tmp_path: Path) -> None:
        # P has .git — walk-up from P/A should not find P/specs/
        _make_spec(tmp_path, "024-test")
        (tmp_path / ".git").mkdir()
        child = tmp_path / "repo-a"
        child.mkdir()
        result = find_spec_dir("024", child)
        assert result is None

    def test_starts_in_git_repo_walks_up_to_non_git_parent(self, tmp_path: Path) -> None:
        # P (no .git) has specs. A (has .git) is child of P.
        spec = _make_spec(tmp_path, "024-test")
        child = tmp_path / "repo-a"
        child.mkdir()
        (child / ".git").mkdir()  # A is a git repo
        result = find_spec_dir("024", child)
        assert result == spec

    def test_not_found_returns_none(self, tmp_path: Path) -> None:
        child = tmp_path / "repo-a"
        child.mkdir()
        result = find_spec_dir("999", child)
        assert result is None

    def test_returns_first_alphabetically_when_multiple(self, tmp_path: Path) -> None:
        _make_spec(tmp_path, "024-beta")
        spec_a = _make_spec(tmp_path, "024-alpha")
        result = find_spec_dir("024", tmp_path)
        assert result == spec_a  # alpha < beta
