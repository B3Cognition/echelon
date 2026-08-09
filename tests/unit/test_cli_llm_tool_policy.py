"""Tests for CLI host-side LLM tool policy wiring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from echelon import cli
from harness.config import HarnessConfig, LlmConfig
from harness.provider_capability import (
    BUILD_PROVIDER_CAPABILITIES,
    CLI_PROVIDER_CAPABILITIES,
    ProviderCapability,
)
from harness.prosaic_prompt_loader import ProsaicCommandArtifact


@pytest.mark.unit
def test_dispatch_skill_command_routes_legacy_claude_review_through_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "echelon-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        "---\nname: echelon.review\n---\nreview $ARGUMENTS\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="claude", config_dir="~/.claude-work"),
    )
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config
            self.capabilities = CLI_PROVIDER_CAPABILITIES

        def run_prompt_result(self, worktree_path, prompt, *, request_metadata=None):
            calls.append((worktree_path, prompt, request_metadata))
            return SimpleNamespace(exit_code=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("review", ["005"])

    assert exc.value.code == 0
    assert calls
    assert calls[0][0] == str(tmp_path)
    assert "review 005" in calls[0][1]
    assert calls[0][2] is None


@pytest.mark.unit
def test_dispatch_skill_command_routes_legacy_build_with_canonical_execution_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "echelon-build"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        "---\nname: echelon.build\n---\nbuild $ARGUMENTS\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="claude"),
    )
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config
            self.capabilities = CLI_PROVIDER_CAPABILITIES

        def run_prompt_result(self, worktree_path, prompt, *, request_metadata=None):
            calls.append((worktree_path, prompt, request_metadata))
            return SimpleNamespace(exit_code=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "claude")
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("build", ["001-demo"])

    assert exc.value.code == 0
    assert not (tmp_path / ".echelon" / "prosaic" / "commands").exists()
    assert calls
    assert calls[0][0] == str(tmp_path)
    assert "build 001-demo" in calls[0][1]
    assert calls[0][2] == {"canonical_task_execution": True}


@pytest.mark.unit
def test_dispatch_skill_command_uses_project_prosaic_command_before_native_skill(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".echelon" / "prosaic").mkdir(parents=True)
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="claude"),
    )
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config
            self.capabilities = CLI_PROVIDER_CAPABILITIES

        def run_prompt_result(self, worktree_path, prompt, *, request_metadata=None):
            calls.append((worktree_path, prompt, request_metadata))
            return SimpleNamespace(exit_code=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "claude")
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)
    monkeypatch.setattr(
        "echelon.cli.ProsaicPromptLoader.load_command",
        lambda self, command_id: ProsaicCommandArtifact(
            frontmatter={
                "model_tier": "balanced",
                "effort": "high",
                "tools": "full",
                "color": "blue",
                "invocation": "automatic",
            },
            body="Review {{args}}.",
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("review", ["005"])

    assert exc.value.code == 0
    assert calls
    assert calls[0][0] == str(tmp_path)
    assert "Review 005." in calls[0][1]
    assert calls[0][2] == {
        "prompt_metadata": {
            "model_tier": "balanced",
            "effort": "high",
            "tools": "full",
            "color": "blue",
            "invocation": "automatic",
        }
    }


@pytest.mark.unit
def test_dispatch_skill_command_routes_copilot_through_ai_cli_provider(monkeypatch, tmp_path: Path) -> None:
    skill_dir = tmp_path / ".github" / "agents"
    skill_dir.mkdir(parents=True)
    (skill_dir / "echelon.review.agent.md").write_text(
        "---\nname: echelon.review\n---\nreview $ARGUMENTS\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="copilot"),
    )
    calls = []

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config
            self.capabilities = CLI_PROVIDER_CAPABILITIES

        def run_prompt_result(self, worktree_path, prompt, *, request_metadata=None):
            calls.append((worktree_path, prompt, request_metadata))
            return SimpleNamespace(exit_code=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "copilot")
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("review", ["005", "pr_url=https://github.com/org/repo/pull/1"])

    assert exc.value.code == 0
    assert calls
    assert calls[0][0] == str(tmp_path)
    assert "review 005 pr_url=https://github.com/org/repo/pull/1" in calls[0][1]
    assert calls[0][2] is None


@pytest.mark.unit
def test_dispatch_build_skill_rejects_artifact_only_provider(
    monkeypatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            cli="openai-compatible",
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
        ),
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "openai-compatible")
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("build", ["001-demo"])

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert 'Provider "openai-compatible" supports artifact work only.' in captured.err
    assert 'Command "echelon build" requires build capability.' in captured.err
    assert "Choose a build-capable provider." in captured.err


@pytest.mark.unit
def test_dispatch_spec_skill_allows_artifact_only_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "echelon-change"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        "---\nname: echelon.change\n---\nchange $ARGUMENTS\n",
        encoding="utf-8",
    )
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(
            cli="openai-compatible",
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
        ),
    )
    calls = []

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config
            self.capabilities = frozenset({ProviderCapability.ARTIFACT})

        def run_prompt_result(self, worktree_path, prompt, *, request_metadata=None):
            calls.append((worktree_path, prompt, request_metadata))
            return SimpleNamespace(exit_code=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "openai-compatible")
    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc:
        cli._dispatch_skill_command("change", ["001-demo", "clarify PM artifact"])

    assert exc.value.code == 0
    assert calls
    assert "change 001-demo clarify PM artifact" in calls[0][1]


@pytest.mark.unit
def test_provider_capability_gate_rejects_build_only_for_artifact_command(
    monkeypatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli="future-build-provider"),
    )

    class FakeProvider:
        def __init__(self, loaded_config):
            assert loaded_config is config
            self.capabilities = BUILD_PROVIDER_CAPABILITIES

    monkeypatch.setattr("echelon.cli.load_config", lambda project_dir, squad_only=True: config)
    monkeypatch.setattr("echelon.cli.AICodingCliProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc:
        cli._require_provider_capability(
            "echelon spec run",
            ProviderCapability.ARTIFACT,
            project_dir=tmp_path,
        )

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert 'Provider "future-build-provider" supports build work only.' in captured.err
    assert 'Command "echelon spec run" requires artifact capability.' in captured.err
    assert "Choose an artifact-capable provider." in captured.err
