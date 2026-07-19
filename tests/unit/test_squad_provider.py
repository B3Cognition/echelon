from __future__ import annotations

import subprocess

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig, LlmConfig
from harness.squad_provider import PhaseAGitBoundaryError, SquadCliProvider
from harness.echelon_result_schema import EchelonResultContract


def test_squad_provider_parses_codex_backend_echelon_result(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        return CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: PASS\n  state_updates: {}\n",
            stderr="",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "prompt")

    assert result.exit_code == 0
    assert result.verdict == "PASS"
    assert result.raw_output.startswith("echelon_result:")


def test_squad_provider_repairs_missing_echelon_result_after_clean_exit(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    prompts: list[str] = []

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        prompts.append(prompt)
        if len(prompts) == 1:
            return CliRunResult(
                exit_code=0,
                stdout="I created the files and updated tasks.md, but forgot the block.\n",
                stderr="",
            )
        return CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: DONE\n  state_updates:\n    next_phase: DONE\n",
            stderr="",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original prompt")

    assert len(prompts) == 2
    assert "Do not edit files" in prompts[1]
    assert "original prompt" in prompts[1]
    assert "forgot the block" in prompts[1]
    assert result.verdict == "DONE"
    assert result.state_updates == {"next_phase": "DONE"}
    assert result.echelon_result_repair_attempted is True
    assert result.echelon_result_repair_succeeded is True


def test_squad_provider_does_not_repair_timeout_or_nonzero_exit(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    calls = 0

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        nonlocal calls
        calls += 1
        return CliRunResult(
            exit_code=1,
            stdout="provider failed before emitting control payload",
            stderr="boom",
            timed_out=True,
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original prompt")

    assert calls == 1
    assert result.echelon_result is None
    assert result.echelon_result_repair_attempted is False


def test_squad_provider_captures_provider_session_limit_without_repair(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    calls = 0

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        nonlocal calls
        calls += 1
        return CliRunResult(
            exit_code=2,
            stdout="You've hit your session limit · resets 4am (Europe/Prague)\n",
            stderr="",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original prompt")

    assert calls == 1
    assert result.echelon_result is None
    assert result.provider_limit_message == "You've hit your session limit · resets 4am (Europe/Prague)"
    assert result.echelon_result_repair_attempted is False


def test_squad_provider_repairs_schema_invalid_echelon_result_after_clean_exit(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    prompts: list[str] = []

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        prompts.append(prompt)
        if len(prompts) == 1:
            return CliRunResult(
                exit_code=0,
                stdout="echelon_result:\n  verdict: MAYBE\n  state_updates: {}\n",
                stderr="",
            )
        return CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: PASS\n  state_updates: {}\n",
            stderr="",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original prompt")

    assert len(prompts) == 2
    assert "unsupported verdict 'MAYBE'" in prompts[1]
    assert result.verdict == "PASS"
    assert result.echelon_result_repair_attempted is True
    assert result.echelon_result_repair_succeeded is True


def test_squad_provider_does_not_accept_failed_repair_invocation(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    prompts: list[str] = []

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        prompts.append(prompt)
        if len(prompts) == 1:
            return CliRunResult(
                exit_code=0,
                stdout="clean completion without control payload",
                stderr="",
            )
        return CliRunResult(
            exit_code=2,
            stdout="echelon_result:\n  verdict: DONE\n  state_updates: {}\n",
            stderr="repair crashed",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original prompt")

    assert len(prompts) == 2
    assert result.echelon_result is None
    assert result.echelon_result_repair_attempted is True
    assert result.echelon_result_repair_succeeded is False


def test_squad_provider_repairs_missing_required_dispatch_state(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    prompts: list[str] = []
    contract = EchelonResultContract(
        allowed_state_update_keys=frozenset({"tasks_lexicon_pass"}),
        required_state_update_keys=frozenset({"tasks_lexicon_pass"}),
        state_update_types={"tasks_lexicon_pass": "boolean"},
        allowed_verdicts=frozenset({"COMPLETE", "BLOCKED"}),
        unexpected_state_updates="quarantine",
    )

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        prompts.append(prompt)
        if len(prompts) == 1:
            return CliRunResult(
                exit_code=0,
                stdout=(
                    "echelon_result:\n"
                    "  verdict: COMPLETE\n"
                    "  state_updates:\n"
                    "    tasks_lexicon_pas: true\n"
                ),
                stderr="",
            )
        return CliRunResult(
            exit_code=0,
            stdout=(
                "echelon_result:\n"
                "  verdict: COMPLETE\n"
                "  state_updates:\n"
                "    tasks_lexicon_pass: true\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original prompt", result_contract=contract)

    assert len(prompts) == 2
    assert "required state_updates" in prompts[1]
    assert result.state_updates == {"tasks_lexicon_pass": True}
    assert result.echelon_result_repair_attempted is True
    assert result.echelon_result_repair_succeeded is True


def test_squad_provider_quarantines_extra_reporting_state_without_repair(
    monkeypatch, tmp_path
) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    calls = 0
    contract = EchelonResultContract(
        allowed_state_update_keys=frozenset(),
        allowed_verdicts=frozenset({"COMPLETE", "BLOCKED"}),
        unexpected_state_updates="quarantine",
    )

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        nonlocal calls
        calls += 1
        return CliRunResult(
            exit_code=0,
            stdout=(
                "echelon_result:\n"
                "  verdict: COMPLETE\n"
                "  state_updates:\n"
                "    total_tasks: 61\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original prompt", result_contract=contract)

    assert calls == 1
    assert result.verdict == "COMPLETE"
    assert result.state_updates == {}
    assert result.quarantined_state_updates == {"total_tasks": 61}
    assert result.echelon_result_repair_attempted is False


@pytest.mark.parametrize("mutation", ["branch", "commit"])
def test_squad_provider_rejects_git_mutation_during_agent_boundary(
    monkeypatch, tmp_path, mutation
) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Echelon Tests"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "echelon@example.test"], cwd=tmp_path, check=True
    )
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    config = HarnessConfig(
        target_repo=".", target_default_branch="main", provider="docker", llm=LlmConfig(cli="codex")
    )
    provider = SquadCliProvider(config)

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        if mutation == "branch":
            subprocess.run(["git", "switch", "-c", "unexpected"], cwd=tmp_path, check=True)
        else:
            (tmp_path / "agent.txt").write_text("unexpected\n", encoding="utf-8")
            subprocess.run(["git", "add", "agent.txt"], cwd=tmp_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "unexpected agent commit"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
            )
        return CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: PASS\n  state_updates: {}\n",
            stderr="",
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    with pytest.raises(PhaseAGitBoundaryError, match="mutated Git"):
        provider.exec_agent(str(tmp_path), "prompt")
