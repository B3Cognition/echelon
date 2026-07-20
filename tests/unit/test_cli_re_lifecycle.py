from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_re_continue_prints_controller_summary_before_provider_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_continue

    run_dir = tmp_path / "runs" / "re-20260718-063615-364321"
    re_dir = run_dir / "re"
    (re_dir / "workspace").mkdir(parents=True)
    (tmp_path / "runs" / ".current-re").write_text(
        run_dir.name + "\n",
        encoding="utf-8",
    )
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "run_kind": "re",
                "status": "blocked",
                "phase": "re-extract-2-specify",
                "re_policy": "changed",
                "expected_generation": 4,
                "extraction_complete": False,
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "re-extract-5-validate",
                "coverage_threshold": 99,
                "resolution_threshold": 99,
                "re_workspace_synthesis_complete": True,
                "re_source_budgets": {"max_source_cycles": 10},
                "re_source_order": ["api", "cli", "registry", "starter"],
                "re_source_states": {
                    source_id: {"status": "passed"}
                    for source_id in ("api", "cli", "registry", "starter")
                },
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "workspace" / "architecture-map.json").write_text(
        json.dumps(
            {
                "domains": [
                    {"domain_id": f"domain-{index}"}
                    for index in range(1, 20)
                ]
            }
        ),
        encoding="utf-8",
    )

    class FakeController:
        def continue_run(self, re_max_inner: int | None = None) -> SimpleNamespace:
            assert re_max_inner == 8
            print("PROVIDER STARTED")
            return SimpleNamespace(
                status="done",
                run_id=run_dir.name,
                generation=5,
                no_work=False,
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli._re_lifecycle_controller",
        lambda _root: FakeController(),
    )

    _cmd_re_continue(["--re-max-inner", "8"])

    output = capsys.readouterr().out
    assert "RE CONTINUE" in output
    assert run_dir.name in output
    assert "blocked → continuing" in output
    assert "re-extract-5-validate — semantic validation" in output
    assert "4/4 passed" in output
    assert "19" in output
    assert "complete" in output
    assert "coverage 99% · resolution 99%" in output
    assert "10 source-local attempts" in output
    assert str(re_dir) in output
    assert output.index("RE CONTINUE") < output.index("PROVIDER STARTED")


@pytest.mark.unit
def test_re_lifecycle_block_prints_precise_controller_detail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _print_re_lifecycle_result

    with pytest.raises(SystemExit) as exc:
        _print_re_lifecycle_result(
            SimpleNamespace(
                status="blocked",
                run_id="re-1",
                blocked_reason="re_agent_result_invalid",
                blocked_detail="state_updates key was rejected",
            )
        )

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "re_agent_result_invalid" in error
    assert "state_updates key was rejected" in error


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
        (
            "run",
            [
                "--re-policy",
                "refresh-all",
                "--profile",
                "balanced",
                "--re-max-inner",
                "9",
                "--reset",
            ],
        ),
        ("continue", ["--re-max-inner", "10"]),
        ("resume", ["Use v2", "--re-max-inner", "11"]),
    ]


@pytest.mark.unit
def test_re_run_routes_profile_and_hard_limit_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_re_run", lambda args: calls.append(args))

    result = CliRunner().invoke(
        app,
        [
            "re",
            "run",
            "--profile",
            "fast",
            "--re-token-limit",
            "2000000",
            "--re-time-limit-minutes",
            "90",
        ],
    )

    assert result.exit_code == 0
    assert calls == [[
        "--re-policy",
        "changed",
        "--profile",
        "fast",
        "--re-token-limit",
        "2000000",
        "--re-time-limit-minutes",
        "90",
    ]]


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
