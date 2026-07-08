"""CLI tests for the delivery namespace and top-level help."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.unit
def test_help_command_prints_usage_without_unknown_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "echelon: unknown command" not in captured.err
    assert "Usage: echelon <command>" in captured.out
    assert "delivery init" in captured.out
    assert "delivery run <spec_id> [--mode <m>] [--strategy <s>]" in captured.out
    assert "--max-outer <n>" in captured.out
    assert "--auto-merge|--no-auto-merge" in captured.out
    assert "Legacy key=value options remain accepted for compatibility." in captured.out
    assert "workspace migrate [--write] [--commit] [--message <msg>]" in captured.out
    assert "spec run <description> [--mode semi|banzai|guided] [--reset]" in captured.out
    assert "[--message <text>] [--next-phase <id>]" in captured.out
    assert "phase run <phase-id> [--spec <id>] [--mode semi|banzai|guided]" in captured.out
    assert "[--message <text>]" in captured.out
    assert "checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]" in captured.out
    assert "benchmark show [latest|<summary-path-or-run-dir>]" in captured.out
    assert "[--baseline-ref <ref>] [--dry-run]" in captured.out


@pytest.mark.unit
def test_phase_help_does_not_require_installed_extension(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "phase", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Echelon extension not installed" not in captured.err
    assert "echelon phase run <phase-id>" in captured.out
    assert "--message <text>" in captured.out


@pytest.mark.unit
def test_checkpoint_help_documents_subcommands_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "checkpoint", "--help"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "echelon checkpoint list" in captured.out
    assert "echelon checkpoint accept --phase <phase-id>" in captured.out
    assert "echelon checkpoint commit --phase <phase-id>" in captured.out
    assert "--run-id <id>" in captured.out
    assert "--message <msg>" in captured.out


@pytest.mark.unit
def test_delivery_init_routes_to_harness_init(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "init"])

    with patch("echelon.cli._cmd_harness_init") as mock_init:
        main()

    mock_init.assert_called_once_with([], command_prefix="echelon delivery init")


@pytest.mark.unit
def test_delivery_init_rejects_target_argument(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from echelon.cli import main

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "init", "sources/app"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "no longer accepts a target repository" in captured.err
    assert "echelon spec target <spec_id> <source-path>" in captured.err


@pytest.mark.unit
def test_delivery_init_non_git_workspace_fails_before_mirror_clone(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from harness.init import InitError
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "init"])
    monkeypatch.chdir(tmp_path)

    def fail_if_called(*_args, **_kwargs):
        raise InitError("Failed to clone mirror: should not be reached")

    monkeypatch.setattr("harness.init.init_harness", fail_if_called)

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "workspace root is not a Git repo" in captured.err
    assert "Failed to clone mirror" not in captured.err
    assert "Then rerun:\n  echelon delivery init" in captured.err


@pytest.mark.unit
def test_delivery_run_routes_to_harness_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "run", "001", "strategy=codegen"])

    with patch("echelon.cli._cmd_harness_run") as mock_run:
        main()

    mock_run.assert_called_once_with(
        ["001", "strategy=codegen"],
        command_prefix="echelon delivery run",
        display_args=["001", "strategy=codegen"],
    )


@pytest.mark.unit
def test_delivery_run_multiple_source_roots_reports_delivery_rerun_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from echelon.cli import main

    (tmp_path / ".git").mkdir()
    spec_dir = tmp_path / "specs" / "001-feature"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Feature\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n",
        encoding="utf-8",
    )
    for name in ["ruler", "spec-kit-skills-agents"]:
        source = tmp_path / "sources" / name
        (source / ".git").mkdir(parents=True)
        (source / "package.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["echelon", "delivery", "run", "--mode=banzai", "001-feature"],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Multiple source roots found; choose one before running delivery" in err
    assert "For a new implementation repo:" in err
    assert "echelon spec target 001-feature sources/<new-repo> --init" in err
    assert "echelon spec target 001-feature <source-path>" in err
    assert "Then rerun:  echelon delivery run 001-feature --mode=banzai" in err
    assert "echelon harness run" not in err


@pytest.mark.unit
def test_delivery_resume_routes_to_harness_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "resume", "001"])

    with patch("echelon.cli._cmd_harness_resume") as mock_resume:
        main()

    mock_resume.assert_called_once_with(["001"])


@pytest.mark.unit
def test_delivery_land_routes_to_land(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "land", "001", "--continue"])

    with patch("echelon.cli._cmd_land") as mock_land:
        main()

    mock_land.assert_called_once_with(["001", "--continue"])


@pytest.mark.unit
def test_harness_namespace_remains_compatibility_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "harness", "run", "001"])

    with patch("echelon.cli._cmd_harness_run") as mock_run:
        main()

    mock_run.assert_called_once_with(
        ["001"],
        command_prefix="echelon harness run",
        display_args=["001"],
    )


@pytest.mark.unit
def test_delivery_unknown_subcommand_exits_without_traceback(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import main

    monkeypatch.setattr("sys.argv", ["echelon", "delivery", "bogus"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "No such command 'bogus'" in captured.err
    assert "Traceback" not in captured.err
