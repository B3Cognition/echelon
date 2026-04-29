"""Unit tests for harness.spec_frontmatter — frontmatter parse and write."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.spec_frontmatter import read_frontmatter, write_targets


def _make_spec_dir(tmp_path: Path, content: str, filename: str = "spec.md") -> Path:
    spec_dir = tmp_path / "specs" / "024-test"
    spec_dir.mkdir(parents=True)
    (spec_dir / filename).write_text(content, encoding="utf-8")
    return spec_dir


@pytest.mark.unit
class TestReadFrontmatter:
    def test_reads_targets(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - og-platform\n---\n# Body\n")
        result = read_frontmatter(spec_dir)
        assert result["targets"] == ["og-platform"]

    def test_reads_multiple_targets(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - repo-a\n  - repo-b\n---\n")
        assert read_frontmatter(spec_dir)["targets"] == ["repo-a", "repo-b"]

    def test_no_frontmatter_returns_empty(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# Just a spec\nNo frontmatter here.\n")
        assert read_frontmatter(spec_dir) == {}

    def test_malformed_yaml_returns_empty(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\n: bad: yaml: [\n---\n# body\n")
        assert read_frontmatter(spec_dir) == {}

    def test_no_md_file_returns_empty(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "024-empty"
        spec_dir.mkdir(parents=True)
        assert read_frontmatter(spec_dir) == {}

    def test_preserves_other_keys(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\nid: '024'\ntargets:\n  - repo-a\n---\n")
        data = read_frontmatter(spec_dir)
        assert data["id"] == "024"
        assert data["targets"] == ["repo-a"]


@pytest.mark.unit
class TestWriteTargets:
    def test_creates_frontmatter_when_absent(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# Spec body\n")
        write_targets(spec_dir, ["og-platform"])
        data = read_frontmatter(spec_dir)
        assert data["targets"] == ["og-platform"]

    def test_replaces_existing_targets(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - old-repo\n---\n# Body\n")
        write_targets(spec_dir, ["new-repo"])
        assert read_frontmatter(spec_dir)["targets"] == ["new-repo"]

    def test_preserves_body_content(self, tmp_path: Path) -> None:
        body = "# My Spec\n\nSome content.\n"
        spec_dir = _make_spec_dir(tmp_path, f"---\ntargets:\n  - r\n---\n{body}")
        write_targets(spec_dir, ["other"])
        md = next(spec_dir.glob("*.md"))
        assert "# My Spec" in md.read_text(encoding="utf-8")

    def test_preserves_other_frontmatter_keys(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\nid: '024'\ntargets:\n  - old\n---\n")
        write_targets(spec_dir, ["new"])
        data = read_frontmatter(spec_dir)
        assert data["id"] == "024"
        assert data["targets"] == ["new"]

    def test_no_duplication_on_rewrite(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - r\n---\n# body\n")
        write_targets(spec_dir, ["a", "b"])
        write_targets(spec_dir, ["c"])
        md = next(spec_dir.glob("*.md"))
        text = md.read_text(encoding="utf-8")
        assert text.count("targets:") == 1

    def test_no_md_file_raises(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "024-empty"
        spec_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            write_targets(spec_dir, ["repo"])

    def test_returns_modified_path(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# body\n")
        result = write_targets(spec_dir, ["r"])
        assert result.exists()
        assert result.suffix == ".md"
