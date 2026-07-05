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
