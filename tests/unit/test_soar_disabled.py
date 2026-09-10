"""Retired SOAR routes must stop before subprocesses or workspace writes."""
from pathlib import Path
import subprocess
import sys
import os

import pytest


def test_existing_launcher_cannot_enable_codegen(monkeypatch, tmp_path, capsys):
    from echelon import cli
    binary = tmp_path / "python"
    launcher = tmp_path / "codegen"
    launcher.touch()
    launcher.chmod(0o755)
    monkeypatch.setattr(cli.sys, "executable", str(binary))
    with pytest.raises(SystemExit) as exc:
        cli._require_codegen_installation()
    assert exc.value.code == 2
    assert "disabled" in capsys.readouterr().err.lower()


def test_bridge_rejects_both_models_before_start(tmp_path):
    from codegen.bridge.soar_bridge import SOARBridge, SOARBridgeModel
    for model in SOARBridgeModel:
        with pytest.raises(RuntimeError, match="disabled"):
            SOARBridge(model=model, wm_state_file=tmp_path / "state.json")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("strategy", ["codegen", "codegenlight"])
def test_retired_strategy_rejected_before_loading(strategy, tmp_path):
    from harness.strategy_loader import load_strategies
    with pytest.raises(RuntimeError, match="disabled"):
        load_strategies("001", [strategy], str(tmp_path))


def test_renamed_strategy_cannot_dispatch_codegen(tmp_path):
    from harness.strategy_loader import load_strategies
    root = tmp_path / "001"
    root.mkdir()
    (root / "custom.md").write_text("---\ncommand: echelon codegen\n---\n")
    with pytest.raises(RuntimeError, match="disabled"):
        load_strategies("001", ["custom"], str(tmp_path))


def test_default_strategy_still_available(tmp_path):
    from harness.strategy_loader import load_strategies
    assert load_strategies("001", ["default"], str(tmp_path))["default"].build_command == "echelon build"


def test_installer_refuses_codegen_without_side_effects(tmp_path):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["/bin/bash", str(root / "scripts/install.sh"), "--with-codegen"],
                            env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "disabled" in (result.stdout + result.stderr).lower()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("args", [["run", "--intent", "test"], ["run", "--resume"], ["anchor", "."]])
def test_direct_cli_rejects_execution_before_workspace_changes(args, monkeypatch, tmp_path, capsys):
    from codegen.cli.codegen_cli import main
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert "disabled" in capsys.readouterr().err.lower()
    assert not list(tmp_path.iterdir())


def test_resume_loop_rejects_soar_before_reading_state():
    from harness.ralph import RalphController
    controller = object.__new__(RalphController)
    with pytest.raises(RuntimeError, match="disabled"):
        controller._run_loop_inner(1, 1, None, "echelon codegen", "")


def test_retired_overlay_preserves_other_context_without_writing(tmp_path, monkeypatch):
    from scripts.ca import soar
    monkeypatch.setenv("ECHELON_RUN_DIR", str(tmp_path))
    context = {"active_goal": "test", "other_memory": {"value": 1}}
    assert soar.enrich_context(context, "test-run") == context
    soar.update_soar_memory({"status": "DONE"}, "test-run")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("command", ['bash -c "soar --version"', 'soar; echo done', "zsh -lc 'echelon codegen 001'", "env X=1 /tmp/soar --version"])
def test_shell_wrappers_do_not_bypass_retirement(command):
    from codegen.retirement import reject_soar_command
    with pytest.raises(RuntimeError, match="disabled"):
        reject_soar_command(command)


@pytest.mark.parametrize("args, status, message", [(["run", "--resume"], 2, "disabled"), (["requirements", "--help"], 0, "mine")])
def test_documented_module_command_executes_real_dispatch(tmp_path, args, status, message):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-m", "codegen.cli.codegen_cli", *args],
                            cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(root / "src")},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == status
    assert message in result.stdout + result.stderr
    assert not list(tmp_path.iterdir())
