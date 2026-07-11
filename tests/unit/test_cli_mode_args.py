from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from echelon.cli import _cmd_run, _consume_mode_arg


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
) -> None:
    squad_dir = tmp_path / "runs" / "spec-20260706-120000-000001"

    class FakeController:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(self, **_kwargs: object) -> SimpleNamespace:
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


def test_cmd_run_passes_re_target_and_policy_to_squad_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        ["build notes", "--target", "prosaic", "--re-policy=target-only"],
        project_root=tmp_path,
        ext_dir=tmp_path / "ext",
    )

    assert captured["target_source"] == "prosaic"
    assert captured["re_policy"] == "target-only"


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
    assert captured["target_source"] == "sources/optasearch-pro"
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
