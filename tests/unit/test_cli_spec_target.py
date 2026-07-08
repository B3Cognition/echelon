"""Unit tests for 'echelon spec target' CLI command."""
from __future__ import annotations

import os
import subprocess
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

    def test_init_creates_missing_target_repo_initial_commit_and_feature_branch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _setup_spec(tmp_path, "001-prose-distribution-engine")

        rc = self._run_spec_target(
            tmp_path,
            ["001-prose-distribution-engine", "sources/prosaic", "--init"],
        )

        assert rc == 0
        spec_dir = tmp_path / "specs" / "001-prose-distribution-engine"
        target = tmp_path / "sources" / "prosaic"
        assert read_frontmatter(spec_dir)["targets"] == ["sources/prosaic"]
        assert (target / ".git").exists()
        head = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert head.stdout.strip()
        branches = subprocess.run(
            ["git", "-C", str(target), "branch", "--list", "001-prose-distribution-engine"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "001-prose-distribution-engine" in branches.stdout
        out = capsys.readouterr().out
        assert "Initialized target repo: sources/prosaic" in out
        assert "Created feature branch: 001-prose-distribution-engine" in out
        assert "echelon delivery run 001-prose-distribution-engine --mode=banzai" in out

    def test_init_inside_workspace_git_creates_nested_source_repo(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _setup_spec(tmp_path, "001-prose-distribution-engine")
        subprocess.run(
            ["git", "init", "-b", "main", str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        for name in ("ruler", "spec-kit-skills-agents"):
            repo = tmp_path / "sources" / name
            subprocess.run(
                ["git", "init", "-b", "main", str(repo)],
                capture_output=True,
                text=True,
                check=True,
            )

        rc = self._run_spec_target(
            tmp_path,
            ["001-prose-distribution-engine", "sources/prosaic", "--init"],
        )

        assert rc == 0
        target = tmp_path / "sources" / "prosaic"
        assert (target / ".git").exists()
        top_level = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert Path(top_level.stdout.strip()) == target
        from echelon.workspace_model import discover_workspace

        manifest = discover_workspace(tmp_path)
        assert "sources/prosaic" in {source.path for source in manifest.sources}
        out = capsys.readouterr().out
        assert "Initialized target repo: sources/prosaic" in out
        assert "Created initial target commit" in out
        assert "Created feature branch: 001-prose-distribution-engine" in out

    def test_init_existing_empty_git_repo_creates_initial_commit_and_feature_branch(
        self, tmp_path: Path
    ) -> None:
        _setup_spec(tmp_path, "001-prose-distribution-engine")
        target = tmp_path / "sources" / "prosaic"
        subprocess.run(
            ["git", "init", "-b", "main", str(target)],
            capture_output=True,
            text=True,
            check=True,
        )

        rc = self._run_spec_target(
            tmp_path,
            ["001", "sources/prosaic", "--init"],
        )

        assert rc == 0
        commit_count = subprocess.run(
            ["git", "-C", str(target), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert commit_count.stdout.strip() == "1"
        branches = subprocess.run(
            ["git", "-C", str(target), "branch", "--list", "001-prose-distribution-engine"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "001-prose-distribution-engine" in branches.stdout

    def test_init_existing_repo_keeps_existing_history_and_adds_feature_branch(
        self, tmp_path: Path
    ) -> None:
        _setup_spec(tmp_path, "001-prose-distribution-engine")
        target = tmp_path / "sources" / "prosaic"
        subprocess.run(
            ["git", "init", "-b", "main", str(target)],
            capture_output=True,
            text=True,
            check=True,
        )
        (target / "README.md").write_text("# Prosaic\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(target), "add", "README.md"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(target),
                "-c",
                "user.name=Echelon Test",
                "-c",
                "user.email=echelon-test@example.invalid",
                "commit",
                "-m",
                "Initial commit",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        rc = self._run_spec_target(
            tmp_path,
            ["001", "sources/prosaic", "--init"],
        )

        assert rc == 0
        commit_count = subprocess.run(
            ["git", "-C", str(target), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert commit_count.stdout.strip() == "1"
        branches = subprocess.run(
            ["git", "-C", str(target), "branch", "--list", "001-prose-distribution-engine"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "001-prose-distribution-engine" in branches.stdout
