"""Unit tests for harness.spec_frontmatter — frontmatter parse and write."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.spec_frontmatter import (
    read_frontmatter,
    read_target_entries,
    read_targets,
    write_target_delivery,
    write_status,
    write_targets,
)


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
        assert data["targets_file"] == "targets.yml"
        assert read_targets(spec_dir) == ["og-platform"]
        assert (spec_dir / "targets.yml").exists()

    def test_replaces_existing_targets(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - old-repo\n---\n# Body\n")
        write_targets(spec_dir, ["new-repo"])
        assert read_frontmatter(spec_dir)["targets"] == ["new-repo"]
        content = (spec_dir / "spec.md").read_text(encoding="utf-8")
        assert "\ntargets:\n" not in content
        assert "targets_file: targets.yml" in content
        assert read_target_entries(spec_dir)[0]["path"] == "new-repo"

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
        assert text.count("targets:") == 0
        assert text.count("targets_file: targets.yml") == 1
        assert read_targets(spec_dir) == ["c"]

    def test_no_md_file_raises(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "024-empty"
        spec_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            write_targets(spec_dir, ["repo"])

    def test_returns_modified_path(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# body\n")
        result = write_targets(spec_dir, ["r"])
        assert result.exists()
        assert result.name == "targets.yml"

    def test_preserves_delivery_metadata_for_matching_target(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# body\n")
        write_targets(spec_dir, ["sources/app"])
        targets_file = spec_dir / "targets.yml"
        targets_file.write_text(
            "schema_version: 1\n"
            "targets:\n"
            "  - id: app\n"
            "    path: sources/app\n"
            "    role: primary\n"
            "    branch: 024-test\n"
            "    delivery:\n"
            "      verify_command: npm test\n",
            encoding="utf-8",
        )

        write_targets(spec_dir, ["sources/app", "sources/api"])

        entries = read_target_entries(spec_dir)
        assert entries[0]["delivery"]["verify_command"] == "npm test"
        assert entries[1]["path"] == "sources/api"

    def test_write_target_delivery_updates_matching_entry(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# body\n")
        write_targets(spec_dir, ["sources/app"])

        write_target_delivery(
            spec_dir,
            "sources/app",
            {
                "verify_command": "npm test",
                "verify_detection": "high",
                "verify_evidence": ["package.json scripts.test"],
            },
        )

        entry = read_target_entries(spec_dir)[0]
        assert entry["delivery"]["verify_command"] == "npm test"
        assert entry["delivery"]["verify_detection"] == "high"


@pytest.mark.unit
class TestWriteStatus:
    def test_adds_status_field(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets: []\n---\n# Body\n")
        write_status(spec_dir, "landed")
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_creates_frontmatter_when_absent(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# No frontmatter\n")
        write_status(spec_dir, "landed")
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_overwrites_existing_status(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\nstatus: running\n---\n# Body\n")
        write_status(spec_dir, "landed")
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_preserves_other_frontmatter_keys(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - repo-a\n---\n# Body\n")
        write_status(spec_dir, "landed")
        fm = read_frontmatter(spec_dir)
        assert fm["targets"] == ["repo-a"]
        assert fm["status"] == "landed"

    def test_returns_modified_file_path(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\n---\n")
        result = write_status(spec_dir, "landed")
        assert result == spec_dir / "spec.md"

    def test_raises_when_no_md_file(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "specs" / "042-empty"
        empty_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            write_status(empty_dir, "landed")

    def test_updates_body_status_line_when_present(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(
            tmp_path,
            "---\nstatus: Planned\n---\n\n**Status**: Planned\n\n# Body\n",
        )
        write_status(spec_dir, "In Progress")
        content = (spec_dir / "spec.md").read_text(encoding="utf-8")
        assert "**Status**: In Progress" in content
        assert "**Status**: Planned" not in content
        assert read_frontmatter(spec_dir)["status"] == "In Progress"

    def test_body_status_line_absent_does_not_error(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\nstatus: Draft\n---\n# No status line\n")
        write_status(spec_dir, "Implemented")
        assert read_frontmatter(spec_dir)["status"] == "Implemented"

    def test_body_status_line_update_is_idempotent(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(
            tmp_path,
            "---\nstatus: In Progress\n---\n\n**Status**: In Progress\n",
        )
        write_status(spec_dir, "Implemented")
        write_status(spec_dir, "Implemented")
        content = (spec_dir / "spec.md").read_text(encoding="utf-8")
        assert content.count("**Status**: Implemented") == 1


@pytest.mark.unit
class TestWriteStatusIntegration:
    def test_multiple_writes_are_idempotent(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - repo-a\n---\n# Spec body\n")
        write_status(spec_dir, "landed")
        write_status(spec_dir, "landed")  # second write must not corrupt
        fm = read_frontmatter(spec_dir)
        assert fm["status"] == "landed"
        assert fm["targets"] == ["repo-a"]
        # body must survive both writes
        content = (spec_dir / "spec.md").read_text(encoding="utf-8")
        assert "# Spec body" in content

    def test_status_survives_write_targets_roundtrip(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets: []\n---\n# Body\n")
        write_status(spec_dir, "landed")
        write_targets(spec_dir, ["repo-b"])
        fm = read_frontmatter(spec_dir)
        assert fm["status"] == "landed"
        assert fm["targets"] == ["repo-b"]
