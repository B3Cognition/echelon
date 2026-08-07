from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_re_run_help_exposes_clean_reconstruction_switch() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["re", "run", "--help"])

    assert result.exit_code == 0
    assert "--no-reuse" in result.output


@pytest.mark.unit
def test_re_refresh_help_requires_one_source_selector() -> None:
    from echelon.cli_app import app

    help_result = CliRunner().invoke(app, ["re", "refresh", "--help"])
    missing_result = CliRunner().invoke(app, ["re", "refresh"])

    assert help_result.exit_code == 0
    assert "--source" in help_result.output
    assert missing_result.exit_code == 2


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
        def continue_run(
            self,
            re_max_inner: int | None = None,
            *,
            hard_token_limit: int | None = None,
            hard_active_minutes: int | None = None,
        ) -> SimpleNamespace:
            assert re_max_inner == 8
            assert hard_token_limit == 6_000_000
            assert hard_active_minutes == 240
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

    _cmd_re_continue(
        [
            "--re-max-inner",
            "8",
            "--re-token-limit",
            "6000000",
            "--re-time-limit-minutes",
            "240",
        ]
    )

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
    monkeypatch.setattr(
        "echelon.cli._cmd_re_refresh", lambda args: calls.append(("refresh", args))
    )
    runner = CliRunner()

    assert runner.invoke(
        app,
        ["re", "run", "--re-policy", "refresh-all", "--re-max-inner", "9", "--reset"],
    ).exit_code == 0
    assert runner.invoke(
        app,
        [
            "re",
            "continue",
            "--re-max-inner",
            "10",
            "--re-token-limit",
            "6000000",
            "--re-time-limit-minutes",
            "240",
        ],
    ).exit_code == 0
    assert runner.invoke(
        app,
        [
            "re",
            "resume",
            "Use v2",
            "--re-max-inner",
            "11",
            "--re-token-limit",
            "7000000",
        ],
    ).exit_code == 0
    assert runner.invoke(app, ["re", "refresh", "--source", "api"]).exit_code == 0

    assert calls == [
        ("run", ["--re-policy", "refresh-all", "--re-max-inner", "9", "--reset"]),
        (
            "continue",
            [
                "--re-max-inner",
                "10",
                "--re-token-limit",
                "6000000",
                "--re-time-limit-minutes",
                "240",
            ],
        ),
        (
            "resume",
            ["Use v2", "--re-max-inner", "11", "--re-token-limit", "7000000"],
        ),
        ("refresh", ["--source", "api"]),
    ]


@pytest.mark.unit
def test_re_refresh_runs_target_only_and_publishes_completed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_re_refresh

    observed: dict[str, object] = {}

    class FakeController:
        def run(self, **kwargs: object) -> SimpleNamespace:
            observed.update(kwargs)
            return SimpleNamespace(
                status="done",
                run_id="re-20260804-120000-000001",
                generation=4,
                no_work=False,
            )

    published: list[list[str]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli._re_lifecycle_controller", lambda _root: FakeController()
    )
    monkeypatch.setattr(
        "echelon.cli._cmd_re_publish", lambda args: published.append(args)
    )

    _cmd_re_refresh(["--source", "api"])

    assert observed == {
        "policy": "target-only",
        "target_source": "api",
        "force_selected_refresh": True,
    }
    assert published == [["re-20260804-120000-000001"]]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source_id", "source_path"),
    (("-api", "sources/api"),),
)
def test_re_refresh_cli_rejects_topology_incompatible_source_declarations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source_id: str,
    source_path: str,
) -> None:
    from echelon.cli import _cmd_re_refresh
    from harness.re_lifecycle import ReLifecycleController

    source = tmp_path if source_path == "." else tmp_path / source_path
    source.mkdir(parents=True, exist_ok=True)
    (source / "app.py").write_text("pass\n", encoding="utf-8")
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        f"workspace:\n  sources:\n    - id: {source_id}\n      path: {source_path}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli._re_lifecycle_controller",
        lambda root: ReLifecycleController(
            project_root=root,
            extension_root=tmp_path / "extension",
            provider_factory=lambda: pytest.fail(
                "unpublishable declaration must not construct provider"
            ),
        ),
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_re_refresh(["--source", source_id])

    assert exc.value.code == 2
    assert "not publishable as topology" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "re").exists()


@pytest.mark.unit
@pytest.mark.parametrize("provenance", ("canonical", "legacy"))
def test_re_refresh_cli_exits_two_for_malformed_workspace_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provenance: str,
) -> None:
    from echelon.cli import _cmd_re_refresh
    from harness.re_lifecycle import ReLifecycleController

    config = (
        tmp_path / ".echelon/config.yml"
        if provenance == "canonical"
        else tmp_path / ".specify/extensions/echelon/echelon-config.yml"
    )
    config.parent.mkdir(parents=True)
    config.write_text("workspace:\n  sources: [api\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli._re_lifecycle_controller",
        lambda root: ReLifecycleController(
            project_root=root,
            extension_root=tmp_path / "extension",
            provider_factory=lambda: pytest.fail(
                "malformed config must not construct provider"
            ),
        ),
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_re_refresh(["--source", "api"])

    assert exc.value.code == 2
    assert "cannot parse workspace config" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "re").exists()


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
