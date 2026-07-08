from __future__ import annotations

from harness.ai_cli_backend import CliRunResult
from harness.config import HarnessConfig, LlmConfig
from harness.squad_provider import SquadCliProvider


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
    responses = [
        CliRunResult(
            exit_code=0,
            stdout="I wrote the artifacts but forgot the final control block.",
            stderr="",
        ),
        CliRunResult(
            exit_code=0,
            stdout=(
                "echelon_result:\n"
                "  verdict: COMPLETE\n"
                "  state_updates: {}\n"
                "  journal_entries: []\n"
            ),
            stderr="",
        ),
    ]

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original phase prompt")

    assert result.verdict == "COMPLETE"
    assert result.result_repair_used is True
    assert result.result_repair_reason == "missing_echelon_result"
    assert len(prompts) == 2
    assert "Do not modify files" in prompts[1]
    assert "original phase prompt" not in prompts[1]


def test_squad_provider_repairs_schema_invalid_echelon_result_after_clean_exit(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    prompts: list[str] = []
    responses = [
        CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: MAYBE\n  state_updates: {}\n",
            stderr="",
        ),
        CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: PASS\n  state_updates: {}\n  journal_entries: []\n",
            stderr="",
        ),
    ]

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original phase prompt")

    assert result.verdict == "PASS"
    assert result.result_repair_used is True
    assert result.result_repair_reason == "schema_invalid_echelon_result"
    assert len(prompts) == 2
    assert "unsupported verdict" in prompts[1]


def test_squad_provider_repairs_malformed_echelon_result_after_clean_exit(monkeypatch, tmp_path) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="codex"),
    )
    provider = SquadCliProvider(config)
    responses = [
        CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: [unclosed",
            stderr="",
        ),
        CliRunResult(
            exit_code=0,
            stdout="echelon_result:\n  verdict: DONE\n  state_updates: {}\n  journal_entries: []\n",
            stderr="",
        ),
    ]

    def fake_run_agent_result(project_root, prompt, timeout_ms=None):
        return responses.pop(0)

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original phase prompt")

    assert result.verdict == "DONE"
    assert result.result_repair_used is True
    assert result.result_repair_reason == "malformed_echelon_result"


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
            stdout="echelon_result:\n  verdict: [unclosed",
            stderr="failed",
            timed_out=True,
        )

    monkeypatch.setattr(provider, "run_agent_result", fake_run_agent_result)

    result = provider.exec_agent(str(tmp_path), "original phase prompt")

    assert result.echelon_result is None
    assert result.result_repair_used is False
    assert calls == 1
