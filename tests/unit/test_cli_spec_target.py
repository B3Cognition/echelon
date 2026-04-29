"""Unit tests for 'echelon spec target' CLI command."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.spec_frontmatter import read_frontmatter


def _setup_spec(tmp_path: Path, spec_name: str, content: str = "# spec\n") -> Path:
    spec_dir = tmp_path / "specs" / spec_name
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(content, encoding="utf-8")
    return spec_dir


@pytest.mark.unit
class TestCliSpecTarget:
    def _run_spec_target(self, tmp_path: Path, args: list[str]) -> int:
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            from echelon.cli import _cmd_spec_target
            try:
                _cmd_spec_target(args)
                return 0
            except SystemExit as e:
                return int(e.code) if e.code is not None else 0
        finally:
            os.chdir(orig)

    def test_single_target_written(self, tmp_path: Path) -> None:
        _setup_spec(tmp_path, "024-psd-import")
        rc = self._run_spec_target(tmp_path, ["024", "og-platform"])
        assert rc == 0
        spec_dir = tmp_path / "specs" / "024-psd-import"
        assert read_frontmatter(spec_dir)["targets"] == ["og-platform"]

    def test_multiple_targets_written(self, tmp_path: Path) -> None:
        _setup_spec(tmp_path, "024-psd-import")
        rc = self._run_spec_target(tmp_path, ["024", "og-platform", "fet-libs"])
        assert rc == 0
        spec_dir = tmp_path / "specs" / "024-psd-import"
        assert read_frontmatter(spec_dir)["targets"] == ["og-platform", "fet-libs"]

    def test_in_place_replacement_no_duplication(self, tmp_path: Path) -> None:
        _setup_spec(tmp_path, "024-psd-import", "---\ntargets:\n  - old\n---\n# body\n")
        self._run_spec_target(tmp_path, ["024", "new-repo"])
        spec_dir = tmp_path / "specs" / "024-psd-import"
        md = next(spec_dir.glob("*.md"))
        assert md.read_text(encoding="utf-8").count("targets:") == 1

    def test_spec_not_found_exits_one(self, tmp_path: Path) -> None:
        rc = self._run_spec_target(tmp_path, ["999", "og-platform"])
        assert rc == 1

    def test_missing_repo_arg_exits_one(self, tmp_path: Path) -> None:
        rc = self._run_spec_target(tmp_path, ["024"])
        assert rc == 1

    def test_ambiguous_spec_id_exits_one(self, tmp_path: Path) -> None:
        _setup_spec(tmp_path, "024-alpha")
        _setup_spec(tmp_path, "024-beta")
        rc = self._run_spec_target(tmp_path, ["024", "og-platform"])
        assert rc == 1
        # Neither spec should have been modified
        for name in ("024-alpha", "024-beta"):
            data = read_frontmatter(tmp_path / "specs" / name)
            assert "targets" not in data
