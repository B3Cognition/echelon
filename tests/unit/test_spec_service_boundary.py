"""Typed application-service boundaries for active spec commands."""

from __future__ import annotations

import sys
import ast
import inspect
import textwrap
import json
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner


def _install_module(monkeypatch, name: str, **members: object) -> ModuleType:
    import echelon

    module = ModuleType(name)
    for member_name, value in members.items():
        setattr(module, member_name, value)
    monkeypatch.setitem(sys.modules, name, module)
    package_name, attribute = name.rsplit(".", 1)
    package = sys.modules[package_name]
    monkeypatch.setattr(package, attribute, module, raising=False)
    return module


def _invoke(*args: str):
    from echelon.cli_app import app

    return CliRunner().invoke(app, list(args))


def test_spec_add_input_routes_typed_values(monkeypatch):
    calls: list[tuple[Path, tuple[str, ...]]] = []
    _install_module(
        monkeypatch,
        "echelon.spec_service",
        add_input=lambda project_root, *, input_values: calls.append(
            (project_root, tuple(input_values))
        ),
    )
    result = _invoke(
        "spec", "add-input", "--input", "reference:notes.md",
        "--input", "requirement:req.md",
    )

    assert result.exit_code == 0
    assert calls == [
        (Path.cwd(), ("reference:notes.md", "requirement:req.md"))
    ]


def test_spec_resolve_routes_typed_values(monkeypatch):
    calls: list[tuple[Path, str, str | None, tuple[str, ...]]] = []
    _install_module(
        monkeypatch,
        "echelon.spec_service",
        resolve_issue=lambda project_root, *, issue_id, decision, extra_args=(): calls.append(
            (project_root, issue_id, decision, tuple(extra_args))
        ),
    )
    result = _invoke("spec", "resolve", "ISS-002", "Use SQLite", "--force")

    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "ISS-002", "Use SQLite", ("--force",))]


def test_spec_drop_target_routes_typed_values(monkeypatch):
    calls: list[tuple[Path, str, str, bool]] = []
    _install_module(
        monkeypatch,
        "echelon.spec_service",
        drop_target=lambda project_root, *, spec_id, target, confirm: calls.append(
            (project_root, spec_id, target, confirm)
        ),
    )
    result = _invoke(
        "spec", "drop-target", "001-demo", "sources/api", "--confirm"
    )

    assert result.exit_code == 0
    assert calls == [(Path.cwd(), "001-demo", "sources/api", True)]


def test_spec_targets_and_artifacts_route_typed_values(monkeypatch):
    target_calls: list[tuple[Path, str]] = []
    artifact_calls: list[tuple[Path, str, tuple[str, ...]]] = []
    _install_module(
        monkeypatch,
        "echelon.spec_service",
        show_targets=lambda project_root, *, spec_id: target_calls.append(
            (project_root, spec_id)
        ),
        write_artifacts=lambda project_root, *, spec_id, extra_args=(): artifact_calls.append(
            (project_root, spec_id, tuple(extra_args))
        ),
    )
    targets = _invoke("spec", "targets", "001-demo")
    artifacts = _invoke("spec", "artifacts", "001-demo", "legacy-extra")

    assert targets.exit_code == 0
    assert artifacts.exit_code == 0
    assert target_calls == [(Path.cwd(), "001-demo")]
    assert artifact_calls == [(Path.cwd(), "001-demo", ("legacy-extra",))]


def test_spec_amend_routes_typed_values(monkeypatch):
    calls: list[tuple[object, ...]] = []
    _install_module(
        monkeypatch,
        "echelon.spec_service",
        prepare_amendment=lambda project_root, **values: calls.append(
            (project_root, values)
        ),
    )
    result = _invoke(
        "spec", "amend", "001-demo", "Add export",
        "--input", "reference:notes.md", "--dry-run",
    )

    assert result.exit_code == 0
    assert calls == [
        (
            Path.cwd(),
            {
                "spec_id": "001-demo",
                "description": "Add export",
                "input_values": ("reference:notes.md",),
                "dry_run": True,
                "extra_args": (),
            },
        )
    ]


def test_hidden_spec_target_uses_service_rejection(monkeypatch):
    calls: list[bool] = []
    _install_module(
        monkeypatch,
        "echelon.spec_service",
        reject_target_mutation=lambda: calls.append(True),
    )
    result = _invoke("spec", "target", "001-demo", "sources/api")

    assert result.exit_code == 0
    assert calls == [True]


def test_spec_skill_commands_use_shared_typed_dispatch(monkeypatch):
    calls: list[tuple[str, tuple[str, ...], Path]] = []
    _install_module(
        monkeypatch,
        "echelon.skill_command_service",
        dispatch_skill=lambda command, arguments, *, project_root: calls.append(
            (command, tuple(arguments), project_root)
        ),
    )
    results = [
        _invoke("spec", "reopen", "001-demo", "from=report.json"),
        _invoke("spec", "bugfix", "001-demo", "Fix export"),
        _invoke("spec", "change", "001-demo", "Add export"),
    ]

    assert [result.exit_code for result in results] == [0, 0, 0]
    assert calls == [
        ("reopen", ("001-demo", "from=report.json"), Path.cwd()),
        ("bugfix", ("001-demo", "Fix export"), Path.cwd()),
        ("change", ("001-demo", "Add export"), Path.cwd()),
    ]


def test_review_compatibility_uses_shared_typed_dispatch(monkeypatch):
    calls: list[tuple[str, tuple[str, ...], Path]] = []
    _install_module(
        monkeypatch,
        "echelon.skill_command_service",
        dispatch_skill=lambda command, arguments, *, project_root: calls.append(
            (command, tuple(arguments), project_root)
        ),
    )
    result = _invoke("review", "001-demo", "--pr-url", "https://example.test/pr/1")

    assert result.exit_code == 0
    assert calls == [
        (
            "review",
            ("001-demo", "--pr-url", "https://example.test/pr/1"),
            Path.cwd(),
        )
    ]


def test_spec_run_routes_typed_request(monkeypatch):
    from echelon.spec_service import SpecRunRequest

    calls: list[tuple[Path, SpecRunRequest]] = []
    monkeypatch.setattr(
        "echelon.spec_service.run_spec",
        lambda project_root, request: calls.append((project_root, request)),
        raising=False,
    )
    result = _invoke(
        "spec", "run", "build notes", "--mode", "banzai",
        "--target", "sources/api", "--input", "requirement:req.md",
        "--perfectionist",
    )

    assert result.exit_code == 0
    assert calls == [(Path.cwd(), SpecRunRequest(
        description="build notes",
        mode="banzai",
        perfectionist=True,
        targets=("sources/api",),
        input_values=("requirement:req.md",),
    ))]


def test_spec_recovery_routes_use_typed_service_values(monkeypatch):
    from echelon.spec_service import SpecRewindRequest

    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "echelon.spec_service.show_status",
        lambda project_root: calls.append(("status", project_root)),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.spec_service.continue_spec",
        lambda project_root, **values: calls.append(("continue", project_root, values)),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.spec_service.resume_spec",
        lambda project_root, **values: calls.append(("resume", project_root, values)),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.spec_service.rewind_spec",
        lambda project_root, request: calls.append(("rewind", project_root, request)),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.spec_service.repair_traceability",
        lambda project_root, **values: calls.append(("repair", project_root, values)),
        raising=False,
    )
    results = [
        _invoke("spec", "status"),
        _invoke("spec", "continue", "--mode", "guided"),
        _invoke("spec", "resume", "approved"),
        _invoke("spec", "rewind", "phase1-what", "--commit", "abc", "--confirm"),
        _invoke("spec", "repair-traceability", "--confirm"),
    ]

    assert [result.exit_code for result in results] == [0, 0, 0, 0, 0]
    assert calls == [
        ("status", Path.cwd()),
        ("continue", Path.cwd(), {"mode": "guided", "extra_args": ()}),
        ("resume", Path.cwd(), {"answer": "approved", "extra_args": ()}),
        ("rewind", Path.cwd(), SpecRewindRequest(
            phase_id="phase1-what", checkpoint_commit="abc", confirm=True,
        )),
        ("repair", Path.cwd(), {"confirm": True}),
    ]


def test_spec_retarget_routes_typed_request(monkeypatch):
    from echelon.spec_service import SpecRetargetRequest

    calls: list[tuple[Path, SpecRetargetRequest]] = []
    monkeypatch.setattr(
        "echelon.spec_service.retarget_spec",
        lambda project_root, request: calls.append((project_root, request)),
        raising=False,
    )
    result = _invoke(
        "spec", "retarget", "001-demo", "--target", "sources/api", "--confirm"
    )

    assert result.exit_code == 0
    assert calls == [(Path.cwd(), SpecRetargetRequest(
        spec_id="001-demo", targets=("sources/api",), confirm_count=1,
    ))]


def test_active_spec_and_phase_surfaces_do_not_import_legacy_cli():
    import echelon.cli as legacy_cli
    import echelon.cli_app as cli_app
    import echelon.phase_service as phase_service

    active = {
        "spec_run", "spec_retarget", "spec_status", "spec_continue", "spec_resume",
        "spec_add_input", "spec_resolve", "spec_rewind",
        "spec_repair_traceability", "spec_drop_target", "spec_targets",
        "spec_artifacts", "spec_reopen", "spec_bugfix", "spec_change", "spec_amend",
    }
    for name in active:
        source = textwrap.dedent(inspect.getsource(getattr(cli_app, name)))
        assert "echelon import cli" not in source
        assert "echelon.cli import" not in source
    phase_source = inspect.getsource(phase_service)
    assert "echelon import cli" not in phase_source
    assert "echelon.cli import" not in phase_source

    forbidden = {
        "_cmd_spec_run", "_cmd_spec_retarget", "_cmd_spec_continue",
        "_cmd_spec_resume", "_cmd_status", "_cmd_rewind",
        "_cmd_repair_traceability",
    }
    definitions = {
        node.name
        for node in ast.parse(inspect.getsource(legacy_cli)).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not definitions & forbidden


@pytest.mark.parametrize(
    "persisted_version",
    [pytest.param(None, id="unversioned"), pytest.param(2, id="future_version")],
)
def test_spec_run_rejects_non_current_state_before_provider_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    persisted_version: object,
) -> None:
    from echelon import spec_service
    from echelon.spec_service import SpecRunRequest

    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{}\n", encoding="utf-8")
    squad_dir = tmp_path / "runs" / "spec-current"
    squad_dir.mkdir(parents=True)
    state = {
        "run_id": squad_dir.name,
        "status": "running",
        "phase": "phase1-what",
        "user_message": "build notes",
    }
    if persisted_version is not None:
        state["phase_a_state_version"] = persisted_version
    state_path = squad_dir / "state.json"
    state_path.write_bytes(json.dumps(state, sort_keys=True).encode("utf-8"))
    before = state_path.read_bytes()
    provider_constructions: list[object] = []

    monkeypatch.setattr(
        spec_service,
        "_installed_phase_runtime_or_exit",
        lambda _root: tmp_path / "runtime",
    )
    monkeypatch.setattr(spec_service, "_project_echelon_config", lambda _root: config_path)
    monkeypatch.setattr(spec_service, "_require_provider_capability", lambda *_a, **_k: None)
    monkeypatch.setattr(spec_service, "_spec_summary_session", lambda *_a, **_k: nullcontext())
    monkeypatch.setattr(spec_service, "_enforce_project_config_compatibility", lambda *_a: None)
    monkeypatch.setattr(spec_service, "_workspace_git_preflight", lambda *_a, **_k: None)
    monkeypatch.setattr(
        spec_service,
        "_workspace_git_preflight_for_squad_run",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        spec_service,
        "_resolve_spec_run_implementation_targets",
        lambda *_a, **_k: ["."],
    )
    monkeypatch.setattr(spec_service, "_find_current_run_dir", lambda *_a: squad_dir)
    monkeypatch.setattr(
        spec_service,
        "_select_squad_dir",
        lambda *_a, **_k: (squad_dir, False),
    )
    monkeypatch.setattr("harness.config.load_config", lambda *_a, **_k: object())
    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        lambda config: provider_constructions.append(config),
    )

    with pytest.raises(SystemExit) as error:
        spec_service.run_spec(
            tmp_path,
            SpecRunRequest(description="build notes"),
        )

    assert error.value.code == 2
    assert state_path.read_bytes() == before
    assert provider_constructions == []
    assert "echelon spec run --reset" in capsys.readouterr().err
