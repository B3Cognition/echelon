from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from echelon.cli import _cmd_run, _consume_mode_arg, _print_squad_summary


def test_consume_mode_arg_accepts_split_form() -> None:
    mode, next_index = _consume_mode_arg(
        ["--mode", "banzai", "build notes"],
        0,
        command_name="echelon run",
    )

    assert mode == "banzai"
    assert next_index == 2


def test_consume_mode_arg_accepts_equals_form() -> None:
    mode, next_index = _consume_mode_arg(
        ["--mode=banzai", "build notes"],
        0,
        command_name="echelon run",
    )

    assert mode == "banzai"
    assert next_index == 1


def test_consume_mode_arg_ignores_non_mode_token() -> None:
    mode, next_index = _consume_mode_arg(
        ["build notes"],
        0,
        command_name="echelon run",
    )

    assert mode is None
    assert next_index == 0


def test_consume_mode_arg_rejects_missing_mode(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _consume_mode_arg(["--mode"], 0, command_name="echelon run")

    assert exc.value.code == 1
    assert "--mode requires" in capsys.readouterr().err


def test_consume_mode_arg_rejects_invalid_mode(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _consume_mode_arg(["--mode=turbo"], 0, command_name="echelon run")

    assert exc.value.code == 1
    assert "invalid mode 'turbo'" in capsys.readouterr().err


def test_cmd_run_exits_nonzero_when_squad_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    squad_dir = tmp_path / "runs" / "spec-20260706-120000-000001"

    class FakeController:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(self, **_kwargs: object) -> SimpleNamespace:
            squad_dir.mkdir(parents=True, exist_ok=True)
            (squad_dir / "state.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "phase": "terminal-blocked",
                        "spec_id": "905-import-prose",
                        "spec_dir": "specs/905-import-prose",
                        "blocked_reason": "Understanding validation unavailable",
                        "completed_phases": ["phase1-constitution", "phase1-what"],
                        "last_dispatch": {"phase_id": "phase1-why2"},
                        "created_at": "2026-07-11T08:00:00+00:00",
                        "updated_at": "2026-07-11T08:02:31+00:00",
                        "cost_usd": 0.1234,
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(
                status="blocked",
                phase="terminal-blocked",
                run_id="spec-20260706-120000-000001",
            )

    monkeypatch.setattr("echelon.cli._print_extension_drift_warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight_for_squad_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._find_current_run_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._select_squad_dir", lambda *_args, **_kwargs: (squad_dir, True))
    monkeypatch.setattr("echelon.cli._print_cost_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_prior_knowledge", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_staging_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_open_issues", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_next_steps", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("harness.config.load_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.config.get_full_resolved_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.phase_graph.PhaseGraph", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.squad.SquadController", FakeController)

    with pytest.raises(SystemExit) as exc:
        _cmd_run(["build notes", "--mode=banzai"], project_root=tmp_path, ext_dir=tmp_path / "ext")

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "SQUAD SUMMARY" in out
    assert "✗ BLOCKED" in out
    assert "spec" in out
    assert "905-import-prose" in out
    assert "current" in out
    assert "phase1-why2 (terminal-blocked)" in out
    assert "2 phases completed: phase1-constitution -> phase1-what" in out
    assert "stopped" in out
    assert "Understanding validation unavailable" in out
    assert "continue" in out
    assert "echelon spec continue" in out
    assert "will retry the blocked phase; it was not marked complete" in out
    assert "blocked  ·  2m 31s  ·  $0.1234" in out


def test_blocked_summary_recaps_current_issues_and_prints_absolute_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    squad_dir = tmp_path / "runs" / "spec-20260723-180158-273719"
    spec_dir = tmp_path / "specs" / "001-sdk"
    squad_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (spec_dir / "issues.md").write_text(
        "\n".join(
            [
                "# Issues — WHY2",
                "",
                "## Summary",
                "- **CRITICAL:** 1",
                "- **HIGH:** 2",
                "- **MEDIUM:** 0",
                "- **LOW:** 0",
                "",
                "## Issues",
                "",
                "### ISS-001: SDK authentication scheme is undefined",
                "- **Severity:** CRITICAL",
                "",
                "### ISS-002: Retry policy needs a product decision",
                "- **Severity:** HIGH",
            ]
        ),
        encoding="utf-8",
    )
    (squad_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "spec_id": "001-sdk",
                "spec_dir": "specs/001-sdk",
                "blocked_reason": "phase_dispatch_limit",
                "escalation_question": "Phase 'phase1-what' has been dispatched too often.",
                "phase_dispatch_limit_phase": "phase1-what",
            }
        ),
        encoding="utf-8",
    )

    _print_squad_summary(
        tmp_path,
        squad_dir,
        SimpleNamespace(status="blocked", phase="terminal-blocked"),
        mode="semi",
        message="Create an SDK",
    )

    output = capsys.readouterr().out
    assert "issues" in output
    assert "CRITICAL 1 · HIGH 2" in output
    assert "[CRITICAL] SDK authentication scheme is undefined" in output
    assert "[HIGH] Retry policy needs a product decision" in output
    assert str((spec_dir / "issues.md").resolve()) in output


def test_cmd_run_passes_repeatable_implementation_targets_and_ignore_re(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for source in ("api", "web"):
        source_root = tmp_path / "sources" / source
        source_root.mkdir(parents=True)
        (source_root / "package.json").write_text("{}\n", encoding="utf-8")
    product = tmp_path / "sources" / "PBS-E-45"
    product.mkdir(parents=True)
    (product / "requirements.md").write_text("# Product request\n", encoding="utf-8")
    squad_dir = tmp_path / "runs" / "spec-20260706-120000-000001"
    captured: dict[str, object] = {}

    class FakeController:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                status="done",
                phase="DONE",
                run_id="spec-20260706-120000-000001",
            )

    monkeypatch.setattr("echelon.cli._print_extension_drift_warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight_for_squad_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._find_current_run_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._select_squad_dir", lambda *_args, **_kwargs: (squad_dir, True))
    monkeypatch.setattr("echelon.cli._print_cost_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_prior_knowledge", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_staging_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_open_issues", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_next_steps", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("harness.config.load_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.config.get_full_resolved_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.phase_graph.PhaseGraph", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.squad.SquadController", FakeController)

    _cmd_run(
        [
            "build notes",
            "--target",
            "sources/api",
            "--target",
            "sources/web",
            "--ignore-re",
            "--input=requirement:sources/PBS-E-45",
        ],
        project_root=tmp_path,
        ext_dir=tmp_path / "ext",
    )

    assert captured["implementation_targets"] == ["sources/api", "sources/web"]
    assert "target_source" not in captured
    assert captured["ignore_re"] is True
    assert captured["product_inputs"].manifest_hash


@pytest.mark.parametrize("policy", ["changed", "target-changed", "target-only"])
def test_cmd_run_rejects_moved_reverse_engineering_policies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    policy: str,
) -> None:
    monkeypatch.setattr("echelon.cli._print_extension_drift_warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight", lambda *_args, **_kwargs: None)

    with pytest.raises(SystemExit) as exc:
        _cmd_run(
            ["build notes", f"--re-policy={policy}"],
            project_root=tmp_path,
            ext_dir=tmp_path / "ext",
        )

    assert exc.value.code == 2
    assert "moved to 'echelon re run'" in capsys.readouterr().err


def test_cmd_run_target_init_prepares_target_and_syncs_workspace_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".echelon").mkdir()
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.write_text(
        "workspace:\n  git_role: orchestration\nsources: []\n",
        encoding="utf-8",
    )
    squad_dir = tmp_path / "runs" / "spec-20260711-120000-000001"
    captured: dict[str, object] = {}

    class FakeController:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, **kwargs: object) -> SimpleNamespace:
            captured["user_message"] = kwargs["user_message"]
            return SimpleNamespace(
                status="done",
                phase="DONE",
                run_id="spec-20260711-120000-000001",
            )

    monkeypatch.setattr("echelon.cli._print_extension_drift_warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight_for_squad_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._find_current_run_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._select_squad_dir", lambda *_args, **_kwargs: (squad_dir, True))
    monkeypatch.setattr("echelon.cli._print_cost_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_prior_knowledge", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_staging_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_open_issues", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._print_next_steps", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("harness.config.load_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.config.get_full_resolved_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("harness.squad_provider.SquadCliProvider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.phase_graph.PhaseGraph", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("harness.squad.SquadController", FakeController)

    _cmd_run(
        ["build notes", "--target", "sources/optasearch-pro", "--init"],
        project_root=tmp_path,
        ext_dir=tmp_path / "ext",
    )

    target = tmp_path / "sources" / "optasearch-pro"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert captured["implementation_targets"] == ["sources/optasearch-pro"]
    assert captured["user_message"] == "build notes"
    assert (target / ".git").exists()
    assert config["sources"] == [
        {"id": "optasearch-pro", "path": "sources/optasearch-pro"}
    ]


def test_cmd_run_target_init_requires_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    squad_dir = tmp_path / "runs" / "spec-20260711-120000-000001"

    monkeypatch.setattr("echelon.cli._print_extension_drift_warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight_for_squad_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._find_current_run_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._select_squad_dir", lambda *_args, **_kwargs: (squad_dir, True))

    with pytest.raises(SystemExit) as exc:
        _cmd_run(["build notes", "--init"], project_root=tmp_path, ext_dir=tmp_path / "ext")

    assert exc.value.code == 1
    assert "--init requires --target" in capsys.readouterr().err


def test_cmd_run_requires_targets_before_multi_source_phase_a(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for source in ("api", "web"):
        source_root = tmp_path / "sources" / source
        source_root.mkdir(parents=True)
        (source_root / "package.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr("echelon.cli._print_extension_drift_warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._enforce_project_config_compatibility", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.cli._workspace_git_preflight", lambda *_args, **_kwargs: None)

    with pytest.raises(SystemExit) as exc:
        _cmd_run(["build notes"], project_root=tmp_path, ext_dir=tmp_path / "ext")

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "multiple source repositories" in err
    assert "--target" in err
