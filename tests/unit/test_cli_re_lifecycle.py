from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_re_lifecycle_typed_commands_route_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli_app import app

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_re_run", lambda args: calls.append(("run", args))
    )
    monkeypatch.setattr(
        "echelon.cli._cmd_re_continue", lambda args: calls.append(("continue", args))
    )
    monkeypatch.setattr(
        "echelon.cli._cmd_re_resume", lambda args: calls.append(("resume", args))
    )
    runner = CliRunner()

    assert runner.invoke(
        app,
        ["re", "run", "--re-policy", "refresh-all", "--re-max-inner", "9", "--reset"],
    ).exit_code == 0
    assert runner.invoke(app, ["re", "continue", "--re-max-inner", "10"]).exit_code == 0
    assert runner.invoke(
        app,
        ["re", "resume", "Use v2", "--re-max-inner", "11"],
    ).exit_code == 0

    assert calls == [
        ("run", ["--re-policy", "refresh-all", "--re-max-inner", "9", "--reset"]),
        ("continue", ["--re-max-inner", "10"]),
        ("resume", ["Use v2", "--re-max-inner", "11"]),
    ]


@pytest.mark.unit
def test_spec_run_help_moves_re_options_and_exposes_ignore_re() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "run", "--help"])

    assert result.exit_code == 0
    assert "--ignore-re" in result.output
    assert "--re-policy" not in result.output
    assert "--re-max-inner" not in result.output


@pytest.mark.unit
def test_spec_run_ignore_re_routes_to_legacy_command(monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli_app import app

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_spec_run", lambda args: calls.append(args))

    result = CliRunner().invoke(app, ["spec", "run", "Build dashboards", "--ignore-re"])

    assert result.exit_code == 0
    assert calls == [["Build dashboards", "--ignore-re"]]


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["--re-policy", "--re-max-inner"])
def test_legacy_spec_parser_rejects_moved_re_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: str,
) -> None:
    from echelon.cli import _cmd_run

    monkeypatch.setattr("echelon.cli._print_extension_drift_warning", lambda *a, **k: None)
    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", lambda *a, **k: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight", lambda *a, **k: None)
    value = "changed" if flag == "--re-policy" else "9"

    with pytest.raises(SystemExit) as exc:
        _cmd_run(["Build dashboards", flag, value], project_root=tmp_path, ext_dir=tmp_path)

    assert exc.value.code == 2
    assert "moved to 'echelon re run'" in capsys.readouterr().err


@pytest.mark.unit
def test_spec_continue_rejects_moved_re_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_continue

    monkeypatch.setattr("echelon.cli._print_extension_drift_warning", lambda *a, **k: None)

    with pytest.raises(SystemExit) as exc:
        _cmd_continue(
            ["--re-max-inner", "9"],
            project_root=tmp_path,
            ext_dir=tmp_path,
        )

    assert exc.value.code == 2
    assert "moved to 'echelon re continue'" in capsys.readouterr().err
