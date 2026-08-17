from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner


def _init_clean_v2_source(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'fixture'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(project), "add", "pyproject.toml"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.unit
def test_re_runtime_resolution_prefers_deployed_prosaic_bundle(tmp_path: Path) -> None:
    from echelon.cli import _installed_re_runtime_or_exit

    runtime = tmp_path / ".echelon" / "runtime"
    (runtime / "workflow").mkdir(parents=True)
    (runtime / "workflow" / "definition.yaml").write_text("phases: {}\n")
    prose = tmp_path / ".echelon" / "prosaic" / "subagents"
    prose.mkdir(parents=True)
    (tmp_path / ".specify" / "extensions" / "echelon").mkdir(parents=True)

    resolved_runtime, resolved_prose = _installed_re_runtime_or_exit(tmp_path)

    assert resolved_runtime == runtime
    assert resolved_prose == prose


@pytest.mark.unit
def test_re_runtime_resolution_rejects_legacy_extension_only_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _installed_re_runtime_or_exit

    (tmp_path / ".specify" / "extensions" / "echelon").mkdir(parents=True)

    with pytest.raises(SystemExit) as exc:
        _installed_re_runtime_or_exit(tmp_path)

    assert exc.value.code == 1
    assert "echelon workspace migrate-to-prosaic" in capsys.readouterr().err


@pytest.mark.unit
def test_re_run_help_exposes_clean_reconstruction_switch() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["re", "run", "--help"])

    assert result.exit_code == 0
    assert "--no-reuse" in result.output


@pytest.mark.unit
def test_re_finalize_allow_partial_transitions_active_blocked_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    run_dir = tmp_path / "runs" / "re-20260814-100000-000001"
    re_dir = run_dir / "re"
    (re_dir / "quality").mkdir(parents=True)
    (tmp_path / "runs" / ".current-re").write_text(
        run_dir.name + "\n", encoding="utf-8"
    )
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "run_kind": "re",
                "status": "blocked",
                "phase": "re-extract-2-specify",
                "blocked_reason": "re_token_budget_exhausted",
                "extraction_complete": False,
                "publication_pending": True,
                "publication_complete": False,
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "re-extract-2-specify",
                "blocked_reason": "re_token_budget_exhausted",
                "re_workspace_synthesis_complete": False,
                "re_source_states": {
                    "api": {
                        "status": "passed",
                        "re_quality_debt_semantic_failures": [
                            {
                                "domain_id": "001-re-domain",
                                "reason": "semantic_quality_incomplete",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "quality" / "semantic-quality-review.json").write_text(
        json.dumps(
            {
                "quality_contract_version": 2,
                "passed": False,
                "failures": [
                    {
                        "source_id": "api",
                        "domain_id": "001-re-domain",
                        "reason": "semantic_quality_incomplete",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    import harness.re_finalization as re_finalization

    monkeypatch.setattr(
        re_finalization,
        "validate_re_run",
        lambda *_args, **_kwargs: SimpleNamespace(status="partial"),
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["re", "finalize", "--allow-partial"])

    assert result.exit_code == 0, result.output
    assert "FINAL STATE — PARTIAL" in result.output
    assert f"echelon re publish {run_dir.name} --allow-partial" in result.output
    outer = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    inner = json.loads((re_dir / "state.json").read_text(encoding="utf-8"))
    debt = json.loads(
        (re_dir / "quality" / "partial-finalization.json").read_text(
            encoding="utf-8"
        )
    )
    assert outer["status"] == "done"
    assert outer["golddigger_status"] == "partial"
    assert outer["finalized_partial"] is True
    assert "blocked_reason" not in outer
    assert inner["status"] == "done"
    assert inner["publication_status"] == "partial"
    assert inner["re_workspace_synthesis_complete"] is False
    assert debt["finalized_from"]["blocked_reason"] == "re_token_budget_exhausted"
    assert debt["debt"]["semantic_failure_sources"] == {
        "api": ["001-re-domain"]
    }

    outer["publication_pending"] = False
    outer["publication_complete"] = True
    outer["generation"] = 2
    (run_dir / "state.json").write_text(json.dumps(outer), encoding="utf-8")
    status_result = CliRunner().invoke(app, ["re", "status"])
    assert status_result.exit_code == 0
    assert "finalized and published as partial" in status_result.output
    assert "No continuation is required" in status_result.output
    assert "semantic debt" in status_result.output
    assert "1 finding across api" in status_result.output
    assert "Raise --re-max-inner" not in status_result.output


@pytest.mark.unit
def test_re_finalize_requires_explicit_partial_acknowledgement() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["re", "finalize"])

    assert result.exit_code == 2
    assert "--allow-partial is required" in result.output


@pytest.mark.unit
def test_re_finalize_rejects_a_running_controller_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    run_dir = tmp_path / "runs" / "re-20260814-100000-000002"
    re_dir = run_dir / "re"
    re_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current-re").write_text(
        run_dir.name + "\n", encoding="utf-8"
    )
    outer = {
        "run_id": run_dir.name,
        "run_kind": "re",
        "status": "running",
    }
    inner = {"status": "in_progress"}
    (run_dir / "state.json").write_text(json.dumps(outer), encoding="utf-8")
    (re_dir / "state.json").write_text(json.dumps(inner), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["re", "finalize", "--allow-partial"])

    assert result.exit_code == 1
    assert "not blocked" in result.output
    assert json.loads((run_dir / "state.json").read_text()) == outer
    assert json.loads((re_dir / "state.json").read_text()) == inner
    assert not (re_dir / "quality" / "partial-finalization.json").exists()


@pytest.mark.unit
def test_re_refresh_help_requires_one_source_selector() -> None:
    from echelon.cli_app import app

    help_result = CliRunner().invoke(app, ["re", "refresh", "--help"])
    missing_result = CliRunner().invoke(app, ["re", "refresh"])

    assert help_result.exit_code == 0
    assert "--source" in help_result.output
    assert missing_result.exit_code == 2


@pytest.mark.unit
def test_re_status_reports_live_state_and_source_quality_debt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    run_dir = tmp_path / "runs" / "re-20260808-100000-000001"
    re_dir = run_dir / "re"
    quality_dir = re_dir / "quality" / "sources"
    quality_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current-re").write_text(
        run_dir.name + "\n", encoding="utf-8"
    )
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "blocked_reason": "re_workspace_synthesis_incomplete",
                "re_policy": "refresh-all",
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "in_progress",
                "phase": "re-extract-5-validate",
                "coverage_threshold": 99,
                "resolution_threshold": 99,
                "re_token_usage": 172_000_000,
                "re_execution_profile": {"hard_token_limit": 210_000_000},
                "re_workspace_synthesis_complete": True,
                "re_source_order": ["api", "web"],
                "re_source_states": {
                    "api": {"status": "passed", "coverage_pct": 100.0},
                    "web": {
                        "status": "partial_quality_debt",
                        "coverage_pct": 12.0,
                    },
                },
                "re_source_budgets": {"max_source_cycles": 10},
            }
        ),
        encoding="utf-8",
    )
    (quality_dir / "web.json").write_text(
        json.dumps(
            {
                "source_id": "web",
                "passed": False,
                "coverage_pct": 46.2,
                "orphan_paths": ["src/a.ts", "src/b.ts"],
                "domain_failures": [{"domain_id": "001-re-src"}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["re", "status"])

    assert result.exit_code == 0
    assert "RE STATUS" in result.output
    assert "in_progress" in result.output
    assert "outer lifecycle state is blocked" in result.output
    assert "api" in result.output
    assert "passed" in result.output
    assert "100.0%" in result.output
    assert "web" in result.output
    assert "partial quality debt" in result.output
    assert "46.2%" in result.output
    assert "2 uncovered" in result.output
    assert "1 incomplete domain" in result.output
    assert "Do not start another continuation" in result.output


@pytest.mark.unit
def test_re_status_does_not_claim_all_sources_passed_when_controller_status_is_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    run_dir = tmp_path / "runs" / "re-20260808-100000-000002"
    re_dir = run_dir / "re"
    re_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current-re").write_text(
        run_dir.name + "\n", encoding="utf-8"
    )
    (run_dir / "state.json").write_text(
        json.dumps({"status": "blocked", "re_policy": "refresh-all"}),
        encoding="utf-8",
    )
    (re_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "done",
                "phase": "re-extract-2-specify",
                "re_source_order": ["passed", "active", "pending"],
                "re_source_states": {
                    "passed": {"status": "passed", "coverage_pct": 100.0},
                    "active": {"status": "active", "coverage_pct": 24.1},
                    "pending": {"status": "pending", "coverage_pct": 35.9},
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["re", "status"])

    assert result.exit_code == 0
    assert "Do not start another continuation" in result.output
    assert "All sources have passed" not in result.output


@pytest.mark.unit
def test_re_status_renders_stale_active_source_as_blocked_when_controller_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    run_dir = tmp_path / "runs" / "re-20260808-100000-000003"
    re_dir = run_dir / "re"
    re_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current-re").write_text(
        run_dir.name + "\n", encoding="utf-8"
    )
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "blocked_reason": "re_agent_dispatch_failed",
                "re_policy": "refresh-all",
            }
        ),
        encoding="utf-8",
    )
    (re_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "re-extract-2-specify",
                "blocked_reason": "re_agent_dispatch_failed",
                "re_agent_result_detail": "API Error: 500 Internal server error",
                "re_source_order": ["soccer-api"],
                "re_source_states": {
                    "soccer-api": {"status": "active", "coverage_pct": 35.9}
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["re", "status"])

    assert result.exit_code == 0
    assert "1 blocked" in result.output
    assert "soccer-api" in result.output
    assert "blocked" in result.output
    assert "API Error: 500 Internal server error" in result.output
    assert "echelon re continue" in result.output
    assert "Do not start another continuation" not in result.output


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
    assert "RE FINAL STATE — BLOCKED" in error
    assert "re_agent_result_invalid" in error
    assert "state_updates key was rejected" in error


@pytest.mark.unit
def test_re_lifecycle_banner_explains_workspace_synthesis_contradiction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _print_re_lifecycle_result

    missing = [
        "workspace/domains/002-re-src.md",
        "workspace/domains/004-re-scripts.md",
        "workspace/domains/006-re-tests.md",
        "workspace/domains/007-re-typings.md",
        "workspace/domains/010-re-src-models-types.md",
    ]
    with pytest.raises(SystemExit):
        _print_re_lifecycle_result(
            SimpleNamespace(
                status="blocked",
                run_id="re-1",
                blocked_reason="re_workspace_synthesis_incomplete",
                blocked_detail=(
                    "workspace synthesis has missing or empty artifacts: "
                    + ", ".join(missing)
                ),
            )
        )

    error = capsys.readouterr().err
    assert "Agent reported DONE, but deterministic artifact validation failed." in error
    assert "5 required artifacts are absent." in error
    for path in missing:
        assert path in error
    assert "echelon re continue" in error


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
def test_re_refresh_cli_exits_two_for_malformed_workspace_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_refresh
    from harness.re_lifecycle import ReLifecycleController

    config = tmp_path / ".echelon/config.yml"
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


    with pytest.raises(SystemExit) as exc:
        _cmd_continue(
            ["--re-max-inner", "9"],
            project_root=tmp_path,
            ext_dir=tmp_path,
        )

    assert exc.value.code == 2
    assert "moved to 'echelon re continue'" in capsys.readouterr().err


def _create_pinned_v2_run(project_root: Path) -> Path:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.model import BudgetPolicy, RunManifest
    from harness.re_v2.run_store import create_run_store

    run_dir = project_root / "runs" / "re-20260814-120000-000001"
    manifest = RunManifest(
        schema_version=1,
        engine="re-v2",
        engine_protocol_version="2.0",
        run_id=run_dir.name,
        created_at="2026-08-14T12:00:00Z",
        source_snapshot_id=content_digest(b"snapshot"),
        source_snapshot_kind="content-snapshot",
        partition_manifest_id=content_digest(b"partitions"),
        requested_goals=("inventory",),
        initial_budget_policy=BudgetPolicy(
            token_limit=5_000_000,
            active_ms_limit=10_800_000,
            provider_attempt_limit=1,
            artifact_generation_attempt_limit=1,
            semantic_repair_round_limit=0,
            result_contract_retry_limit=0,
        ),
        provider_contract={"provider": "deterministic-inventory"},
        artifact_policy_versions={"L0": "egr-164-v1"},
        parent_run_id=None,
    )
    create_run_store(run_dir, manifest)
    (project_root / "runs" / ".current-re").write_text(
        run_dir.name + "\n", encoding="utf-8"
    )
    return run_dir


@pytest.mark.unit
def test_re_continue_routes_from_pinned_manifest_before_v1_state_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_re_continue

    run_dir = _create_pinned_v2_run(tmp_path)
    calls: list[tuple[Path, int | None, int | None]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli._run_re_v2_continue",
        lambda selected, *, token_limit, time_limit_minutes: calls.append(
            (selected, token_limit, time_limit_minutes)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.cli._re_lifecycle_controller",
        lambda *_args: pytest.fail("v1 controller was constructed"),
    )

    _cmd_re_continue([])

    assert calls == [(run_dir.resolve(), None, None)]


@pytest.mark.unit
def test_re_v2_continue_rejects_v1_attempt_budget_option_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_continue

    _create_pinned_v2_run(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli._run_re_v2_continue",
        lambda *_args, **_kwargs: pytest.fail("v2 continuation must not start"),
        raising=False,
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_re_continue(["--re-max-inner", "2"])

    assert exc.value.code == 2
    assert (
        "v2 has independent attempt budgets; this option is valid only for v1"
        in capsys.readouterr().err
    )


@pytest.mark.unit
def test_re_status_routes_pinned_v2_without_reading_outer_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_status

    run_dir = _create_pinned_v2_run(tmp_path)
    (run_dir / "state.json").write_text("not-json", encoding="utf-8")
    calls: list[tuple[Path, bool]] = []
    monkeypatch.chdir(tmp_path)

    def fake_render(selected: Path, *, as_json: bool = False) -> str:
        calls.append((selected, as_json))
        return '{"engine":"re-v2"}\n'

    monkeypatch.setattr(
        "harness.re_v2.status.render_v2_status",
        fake_render,
    )

    _cmd_re_status(["--json"])

    assert calls == [(run_dir.resolve(), True)]
    assert capsys.readouterr().out == '{"engine":"re-v2"}\n'


@pytest.mark.unit
def test_re_run_defaults_to_v1_without_constructing_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_run

    calls: list[dict[str, object]] = []

    class FakeV1Controller:
        def run(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                status="done",
                run_id="re-v1",
                generation=3,
                no_work=False,
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli._re_lifecycle_controller", lambda _root: FakeV1Controller()
    )
    monkeypatch.setattr(
        "echelon.cli._run_re_v2_create",
        lambda *_args, **_kwargs: pytest.fail("v2 creation was invoked"),
        raising=False,
    )

    _cmd_re_run([])

    assert calls == [
        {
            "policy": "changed",
            "re_max_inner": None,
            "reset": False,
            "reuse_published": True,
            "profile_name": None,
            "hard_token_limit": None,
            "hard_active_minutes": None,
        }
    ]
    assert "RE run re-v1 complete; publication is pending." in capsys.readouterr().out


@pytest.mark.unit
def test_re_v2_shadow_creation_pins_l0_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_run, _load_re_v2_snapshot
    from harness.re_v2.events import EventStore
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    _init_clean_v2_source(tmp_path)
    external_home = tmp_path.parent / f"{tmp_path.name}-echelon-home"
    monkeypatch.setenv("ECHELON_HOME", str(external_home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "harness.re_v2.controller.ReV2Controller",
        lambda *_args, **_kwargs: pytest.fail("shadow constructed a controller"),
    )

    _cmd_re_run(["--engine", "v2", "--shadow"])

    run_id = (tmp_path / "runs" / ".current-re").read_text(encoding="utf-8").strip()
    run_dir = tmp_path / "runs" / run_id
    manifest = load_run_manifest(run_dir)
    events = EventStore(ReV2Paths.for_run(run_dir)).replay()
    assert manifest.engine == "re-v2"
    assert manifest.engine_protocol_version == "2.1"
    assert manifest.source_snapshot_kind == "workspace-git-composite"
    from harness.re_v2.snapshot import load_snapshot_manifest

    snapshot = _load_re_v2_snapshot(tmp_path, manifest)
    components = load_snapshot_manifest(snapshot).components or ()
    assert [(component.source_id, component.workspace_path) for component in components] == [
        (".", ".")
    ]
    assert manifest.requested_goals == ("inventory",)
    assert manifest.provider_contract["provider"] == "deterministic-inventory"
    assert manifest.artifact_policy_versions == {"L0": "egr-164-v1"}
    assert [event.type for event in events] == ["run_created"]
    assert not any(event.type.startswith("dispatch_") for event in events)
    output = capsys.readouterr().out
    assert "SHADOW PLAN" in output
    assert "generate" in output
    assert "RE V2 — ACTIVE" in output


@pytest.mark.unit
def test_re_v2_dirty_polyrepo_fails_before_run_or_pointer_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_run

    first = tmp_path / "first"
    second = tmp_path / "second"
    _init_clean_v2_source(first)
    _init_clean_v2_source(second)
    (second / "dirty.py").write_text("dirty\n", encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    pointer = runs / ".current-re"
    pointer.write_text("re-existing\n", encoding="utf-8")
    external_home = tmp_path.parent / f"{tmp_path.name}-echelon-home"
    monkeypatch.setenv("ECHELON_HOME", str(external_home))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _cmd_re_run(["--engine", "v2", "--shadow"])

    assert exc.value.code == 2
    assert pointer.read_text(encoding="utf-8") == "re-existing\n"
    assert sorted(path.name for path in runs.iterdir()) == [".current-re"]
    error = capsys.readouterr().err
    assert "second" in error and "untracked" in error
    assert all(word in error.lower() for word in ("stash", "commit", "revert"))


@pytest.mark.unit
def test_re_v2_partition_binding_rejects_forged_workspace_source_set(
    tmp_path: Path,
) -> None:
    from echelon.cli import _re_v2_partition_manifest_id
    from harness.re_v2.workspace_snapshot import capture_workspace_snapshot

    source = tmp_path / "source"
    _init_clean_v2_source(source)
    declared = SimpleNamespace(id="source", path="source", git_role="source")
    snapshot = capture_workspace_snapshot(
        tmp_path,
        (declared,),
        tmp_path.parent / f"{tmp_path.name}-snapshots",
    )
    forged = SimpleNamespace(
        sources=(SimpleNamespace(id="other", path="other", git_role="source"),)
    )

    with pytest.raises(ValueError, match="source set"):
        _re_v2_partition_manifest_id(forged, snapshot)

    assert not (tmp_path / "runs").exists()


@pytest.mark.unit
def test_re_v2_live_creation_certifies_registered_l0_without_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_run
    from harness.re_v2.events import EventStore
    from harness.re_v2.ledger import Ledger, ObjectStore
    from harness.re_v2.planner import build_initial_inventory_graph
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    _init_clean_v2_source(tmp_path)
    external_home = tmp_path.parent / f"{tmp_path.name}-echelon-home"
    monkeypatch.setenv("ECHELON_HOME", str(external_home))
    monkeypatch.chdir(tmp_path)

    _cmd_re_run(["--engine", "v2"])

    run_id = (tmp_path / "runs" / ".current-re").read_text(encoding="utf-8").strip()
    run_dir = tmp_path / "runs" / run_id
    manifest = load_run_manifest(run_dir)
    paths = ReV2Paths.for_run(run_dir)
    events = EventStore(paths).replay()
    graph = build_initial_inventory_graph(
        manifest.source_snapshot_id, manifest.partition_manifest_id
    )
    ledger = Ledger(
        paths,
        ObjectStore(paths.objects),
        {
            template.verifier_id: template.verifier_version
            for template in graph.templates
        },
    ).replay()
    assert events[-1].type == "run_completed"
    assert len(ledger.accepted_artifacts) == 2
    assert len(ledger.certifications) == 2
    assert not any(event.type.startswith("synthesis_") for event in events)
    output = capsys.readouterr().out
    assert "RE V2 — COMPLETE" in output
    assert "synthesis: not registered" in output


@pytest.mark.unit
def test_re_v2_continue_authorizes_only_resource_ceiling_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_continue, _cmd_re_run
    from harness.re_v2.events import EventStore
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    _init_clean_v2_source(tmp_path)
    external_home = tmp_path.parent / f"{tmp_path.name}-echelon-home"
    monkeypatch.setenv("ECHELON_HOME", str(external_home))
    monkeypatch.chdir(tmp_path)
    _cmd_re_run(
        ["--engine", "v2", "--shadow", "--re-token-limit", "1"]
    )
    capsys.readouterr()
    run_id = (tmp_path / "runs" / ".current-re").read_text(encoding="utf-8").strip()
    run_dir = tmp_path / "runs" / run_id
    paths = ReV2Paths.for_run(run_dir)
    events = EventStore(paths)
    before = load_run_manifest(run_dir)
    events.append(
        "run_paused",
        {"reason": "token_limit", "reason_code": "tokens_exhausted"},
        occurred_at="2026-08-14T12:00:00Z",
    )

    _cmd_re_continue(["--re-token-limit", "2"])

    after = load_run_manifest(run_dir)
    history = events.replay()
    authorization = next(
        event for event in history if event.type == "budget_authorized"
    )
    assert authorization.payload == {
        "authorized_by": "echelon-cli",
        "dimension": "tokens",
        "new_value": 2,
        "old_value": 1,
        "reason": "CLI resource ceiling increase",
    }
    assert any(event.type == "run_resumed" for event in history)
    assert before == after
    assert after.initial_budget_policy.provider_attempt_limit == 1
    assert after.initial_budget_policy.artifact_generation_attempt_limit == 1
    assert "RE V2 — COMPLETE" in capsys.readouterr().out


@pytest.mark.unit
def test_re_v2_unsupported_protocol_reports_recorded_values_before_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_continue
    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.run_store import ReV2Paths

    run_dir = _create_pinned_v2_run(tmp_path)
    manifest_path = ReV2Paths.for_run(run_dir).manifest
    raw = json.loads(manifest_path.read_bytes())
    raw["engine_protocol_version"] = "9.9"
    manifest_path.write_bytes(canonical_json_bytes(raw))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli._re_lifecycle_controller",
        lambda *_args: pytest.fail("v1 controller was constructed"),
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_re_continue([])

    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "re-v2" in error
    assert "9.9" in error


def _create_v2_run_with_provider_contract(
    project_root: Path,
    snapshot_root: Path,
    provider_contract: dict[str, object],
) -> Path:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.model import BudgetPolicy, RunManifest
    from harness.re_v2.run_store import create_run_store
    from harness.re_v2.snapshot import capture_source_snapshot

    snapshot = capture_source_snapshot(
        project_root,
        snapshot_root,
        exclusions=(".echelon/cache", "re/.cache", "runs"),
    )
    run_dir = project_root / "runs" / "re-20260814-130000-000001"
    manifest = RunManifest(
        schema_version=1,
        engine="re-v2",
        engine_protocol_version="2.0",
        run_id=run_dir.name,
        created_at="2026-08-14T13:00:00Z",
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_kind=snapshot.kind,
        partition_manifest_id=content_digest(b"provider-pin-partitions"),
        requested_goals=("inventory",),
        initial_budget_policy=BudgetPolicy(
            token_limit=5_000_000,
            active_ms_limit=10_800_000,
            provider_attempt_limit=1,
            artifact_generation_attempt_limit=1,
            semantic_repair_round_limit=0,
            result_contract_retry_limit=0,
        ),
        provider_contract=provider_contract,
        artifact_policy_versions={"L0": "egr-164-v1"},
        parent_run_id=None,
    )
    create_run_store(run_dir, manifest)
    (project_root / "runs" / ".current-re").write_text(
        run_dir.name + "\n", encoding="utf-8"
    )
    return run_dir


@pytest.mark.unit
def test_re_v2_continue_preserves_legacy_content_snapshot_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_continue
    from harness.re_v2.events import EventStore
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    (tmp_path / "pyproject.toml").write_text("original\n", encoding="utf-8")
    external_home = tmp_path.parent / f"{tmp_path.name}-legacy-home"
    monkeypatch.setenv("ECHELON_HOME", str(external_home))
    run_dir = _create_v2_run_with_provider_contract(
        tmp_path,
        external_home / "re-v2" / "snapshots",
        {
            "provider": "deterministic-inventory",
            "provider_protocol_version": "re-v2-l0-v1",
            "result_contract_id": "deterministic-inventory-v1",
        },
    )
    before = load_run_manifest(run_dir)
    (tmp_path / "pyproject.toml").write_text("changed after capture\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _cmd_re_continue([])

    assert load_run_manifest(run_dir) == before
    assert EventStore(ReV2Paths.for_run(run_dir)).replay()[-1].type == "run_completed"
    assert "RE V2 — COMPLETE" in capsys.readouterr().out


@pytest.mark.unit
@pytest.mark.parametrize(
    "provider_contract",
    (
        {
            "provider": "deterministic-inventory",
            "provider_protocol_version": "future-l0",
            "result_contract_id": "deterministic-inventory-v1",
        },
        {
            "provider": "deterministic-inventory",
            "result_contract_id": "deterministic-inventory-v1",
        },
        {
            "provider": "deterministic-inventory",
            "provider_protocol_version": "re-v2-l0-v1",
            "result_contract_id": "future-result",
        },
        {
            "provider": "deterministic-inventory",
            "provider_protocol_version": "re-v2-l0-v1",
        },
    ),
)
def test_re_v2_rejects_nonexact_provider_contract_before_any_run_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider_contract: dict[str, object],
) -> None:
    from echelon.cli import _cmd_re_continue
    from harness.re_v2.run_store import ReV2Paths

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'fixture'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    external_home = tmp_path.parent / f"{tmp_path.name}-provider-pin-home"
    monkeypatch.setenv("ECHELON_HOME", str(external_home))
    run_dir = _create_v2_run_with_provider_contract(
        tmp_path,
        external_home / "re-v2" / "snapshots",
        provider_contract,
    )
    paths = ReV2Paths.for_run(run_dir)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _cmd_re_continue([])

    assert exc.value.code == 2
    assert "unsupported pinned RE v2 provider contract" in capsys.readouterr().err
    assert not paths.events.exists()
    assert not paths.ledger.exists()
    assert not paths.candidates.exists()
    assert not (paths.root / ".execution").exists()
