from __future__ import annotations

from pathlib import Path
import sys

from harness.ai_cli_backend import CliRunResult
from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.run_summary import (
    RunSummaryContext,
    SummaryAgent,
    summarize_run,
    summarize_run_for_cli,
)


class _RecordingProvider:
    def __init__(self, result: CliRunResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def run_agent_result(
        self,
        cwd: str,
        prompt: str,
        **kwargs: object,
    ) -> CliRunResult:
        self.calls.append((cwd, prompt, kwargs))
        return self.result


def _context(project_root: Path) -> RunSummaryContext:
    return RunSummaryContext(
        project_root=project_root,
        command="echelon spec continue",
        task="Add a human-readable run handoff.",
        status="done",
        facts=(
            "Published specs/123-run-handoff/spec.md.",
            "Verification passed: 42 tests.",
        ),
        next_step="echelon delivery run 123-run-handoff",
        inspect_paths=(project_root / "runs" / "spec-123",),
    )


def test_summarize_run_uses_fast_low_agent_in_isolated_directory(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout=(
                "Published the run-handoff specification.\n"
                "Verified the result with 42 passing tests.\n"
                "The specification is ready for delivery."
            ),
            stderr="",
        )
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low", "tools": "write"},
    )

    summary = summarize_run(_context(project_root), provider=provider, agent=agent)

    assert summary == (
        "Published the run-handoff specification.\n"
        "Verified the result with 42 passing tests.\n"
        "The specification is ready for delivery."
    )
    assert len(provider.calls) == 1
    cwd, prompt, kwargs = provider.calls[0]
    assert Path(cwd) != project_root
    assert project_root not in Path(cwd).parents
    assert not Path(cwd).exists()
    assert '"command": "echelon spec continue"' in prompt
    assert '"status": "done"' in prompt
    assert "Published specs/123-run-handoff/spec.md." in prompt
    assert kwargs["timeout_ms"] == 30_000
    assert kwargs["request_metadata"] == {
        "allow_non_git_cwd": True,
        "prompt_metadata": {
            "model_tier": "fast",
            "effort": "low",
            "tools": "write",
            "quiet": True,
        }
    }


def test_summarize_run_falls_back_when_agent_fails(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(exit_code=1, stdout="", stderr="provider unavailable")
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low"},
    )

    summary = summarize_run(_context(project_root), provider=provider, agent=agent)

    assert summary == (
        "Echelon finished echelon spec continue with status done.\n"
        "Published specs/123-run-handoff/spec.md.\n"
        "Verification passed: 42 tests.\n"
        "Next: echelon delivery run 123-run-handoff"
    )


def test_summarize_run_keeps_provider_progress_out_of_the_terminal(
    tmp_path: Path,
    capsys,
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()

    class NoisyProvider(_RecordingProvider):
        def run_agent_result(self, cwd: str, prompt: str, **kwargs: object):
            print("provider progress")
            print("provider warning", file=sys.stderr)
            return super().run_agent_result(cwd, prompt, **kwargs)

    provider = NoisyProvider(
        CliRunResult(exit_code=0, stdout="Useful human summary.", stderr="")
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low"},
    )

    assert summarize_run(_context(project_root), provider=provider, agent=agent)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_summarize_run_rejects_empty_model_output(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(exit_code=0, stdout="```text\n\n```", stderr="")
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low"},
    )

    summary = summarize_run(_context(project_root), provider=provider, agent=agent)

    assert summary.startswith("Echelon finished echelon spec continue")


def test_summarize_run_never_prints_raw_model_json(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout='{"summary":"Published the specification."}',
            stderr="",
        )
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low"},
    )

    summary = summarize_run(_context(project_root), provider=provider, agent=agent)

    assert summary.startswith("Echelon finished echelon spec continue")
    assert "{" not in summary


def test_summarize_run_for_cli_loads_the_dedicated_workspace_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout="Finished the requested specification.\nIt is ready for delivery.",
            stderr="",
        )
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "harness.prosaic_prompt_loader.ProsaicPromptLoader.load_subagent",
        lambda _loader, agent_id: (
            captured.setdefault("agent_id", agent_id)
            and ProsaicCommandArtifact(
                frontmatter={"model_tier": "fast", "effort": "low"},
                body="Summarize this run.",
            )
        ),
    )
    monkeypatch.setattr(
        "harness.config.load_config",
        lambda root, squad_only=False: captured.update(
            {"config_root": root, "squad_only": squad_only}
        )
        or object(),
    )
    monkeypatch.setattr(
        "harness.llm_provider.AICodingCliProvider",
        lambda _config: provider,
    )

    summary = summarize_run_for_cli(_context(project_root))

    assert summary == (
        "Finished the requested specification.\nIt is ready for delivery."
    )
    assert captured == {
        "agent_id": "echelon.summarizer",
        "config_root": project_root,
        "squad_only": True,
    }
