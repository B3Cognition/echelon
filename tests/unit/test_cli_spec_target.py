"""Regression tests for retired post-hoc spec target mutation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.spec_frontmatter import read_targets, write_targets


def _run_spec_target(tmp_path: Path, args: list[str]) -> int:
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        from echelon.cli import _cmd_spec_target

        try:
            _cmd_spec_target(args)
            return 0
        except SystemExit as exc:
            return int(exc.code) if exc.code is not None else 0
    finally:
        os.chdir(original)


@pytest.mark.unit
def test_spec_target_refuses_post_hoc_mutation_without_changing_metadata(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec_dir = tmp_path / "specs" / "001-dashboard"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Dashboard\n", encoding="utf-8")
    write_targets(spec_dir, ["sources/web"])

    rc = _run_spec_target(tmp_path, ["001", "sources/api"])

    assert rc == 2
    assert read_targets(spec_dir) == ["sources/web"]
    err = capsys.readouterr().err
    assert "no longer mutates generated specifications" in err
    assert "echelon spec run" in err
    assert "target-dependent artifacts" in err


@pytest.mark.unit
def test_spec_target_init_does_not_create_repository(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-dashboard"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Dashboard\n", encoding="utf-8")

    rc = _run_spec_target(
        tmp_path,
        ["001", "sources/api", "--init"],
    )

    assert rc == 2
    assert not (tmp_path / "sources" / "api").exists()
    assert not (spec_dir / "targets.yml").exists()
