from __future__ import annotations

from pathlib import Path

from hormone_calc.cli import _find_current_run_dir


def test_current_run_directory_uses_runs_current_pointer(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "spec-001"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-001\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert _find_current_run_dir() == run_dir


def test_current_run_directory_falls_back_to_runs_root(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert _find_current_run_dir() == Path("runs")
