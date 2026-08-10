"""Tests for project config compatibility guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from echelon.cli import (
    _cmd_resume,
    _cmd_run,
    _cmd_status,
    _project_config_compatibility_issues,
)


def _write_config(
    project_root: Path,
    spec_ref: str,
    *,
    spec_path: str = "requirements.lexicon.md",
) -> Path:
    cfg = project_root / ".echelon" / "config.yml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "lexicon_gate:\n"
        "  enabled: true\n"
        "  artifacts:\n"
        "    spec:\n"
        "      enabled: true\n"
        "      type: spec\n"
        f"      path: {spec_path}\n"
        "      source_ref: spec.md\n"
        "      mode: derived\n"
        "    tasks:\n"
        "      enabled: true\n"
        "      type: tasks\n"
        f"      spec_ref: {spec_ref}\n",
        encoding="utf-8",
    )
    return cfg


def test_detects_stale_lexicon_tasks_spec_ref(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "spec.md")

    issues = _project_config_compatibility_issues(tmp_path)

    assert len(issues) == 1
    assert issues[0].path == "lexicon_gate.artifacts.tasks.spec_ref"
    assert issues[0].current == "spec.md"
    assert issues[0].expected == "requirements.lexicon.md"
    assert issues[0].config_file == cfg


def test_accepts_tasks_spec_ref_matching_custom_derived_spec_path(tmp_path: Path) -> None:
    _write_config(tmp_path, "requirements.controlled.md", spec_path="requirements.controlled.md")

    assert _project_config_compatibility_issues(tmp_path) == []


def test_status_warns_for_stale_lexicon_tasks_spec_ref(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(tmp_path, "spec.md")

    _cmd_status(tmp_path)

    captured = capsys.readouterr()
    assert "CONFIG COMPATIBILITY" in captured.out
    assert "lexicon_gate.artifacts.tasks.spec_ref" in captured.out
    assert "spec.md" in captured.out
    assert "requirements.lexicon.md" in captured.out


def test_run_blocks_before_dispatch_when_lexicon_tasks_spec_ref_is_stale(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(tmp_path, "spec.md")
    runtime_dir = tmp_path / ".echelon" / "runtime"

    with pytest.raises(SystemExit) as exc:
        _cmd_run(["build a thing"], project_root=tmp_path, ext_dir=runtime_dir)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "CONFIG BLOCKED" in captured.err
    assert "lexicon_gate.artifacts.tasks.spec_ref" in captured.err
    assert "spec.md" in captured.err
    assert "requirements.lexicon.md" in captured.err
    assert not (tmp_path / "runs").exists()


def test_resume_blocks_before_mutating_state_when_lexicon_tasks_spec_ref_is_stale(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(tmp_path, "spec.md")
    runtime_dir = tmp_path / ".echelon" / "runtime"
    run_dir = tmp_path / "runs" / "spec-test"
    staging_dir = run_dir / "staging"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        "{\n"
        '  "status": "blocked",\n'
        '  "phase": "phase3-plan",\n'
        '  "run_id": "squad-1",\n'
        '  "user_message": "build a thing",\n'
        '  "staging_dir": "' + str(staging_dir) + '",\n'
        '  "escalation_question": "Proceed?",\n'
        '  "blocked_reason": "test"\n'
        "}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_resume(["yes"], project_root=tmp_path, ext_dir=runtime_dir)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "CONFIG BLOCKED" in captured.err
    assert "lexicon_gate.artifacts.tasks.spec_ref" in captured.err
    assert not (staging_dir / "user-clarifications.md").exists()
