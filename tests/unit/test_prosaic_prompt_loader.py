"""Tests for loading neutral Prosaic command artifacts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact, ProsaicPromptLoader


@pytest.mark.unit
def test_load_command_inspects_the_project_prosaic_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    (source / "commands").mkdir(parents=True)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "commands/echelon.bugfix.md",
                    "type": "command",
                    "frontmatter": {"name": "echelon.bugfix"},
                    "body": "Fix {{args}}.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path, executable="prosaic").load_command(
        "echelon.bugfix"
    )

    assert artifact is not None
    assert artifact.frontmatter == {"name": "echelon.bugfix"}
    assert artifact.body == "Fix {{args}}."
    assert captured == {
        "command": [
            "prosaic",
            "inspect",
            "commands/echelon.bugfix.md",
            "--source",
            str(source),
        ],
        "cwd": str(tmp_path),
    }


@pytest.mark.unit
def test_load_command_returns_none_without_a_project_prosaic_bundle(tmp_path: Path) -> None:
    assert ProsaicPromptLoader(tmp_path).load_command("echelon.bugfix") is None


@pytest.mark.unit
def test_load_command_returns_none_for_an_agent_only_prosaic_bundle(tmp_path: Path) -> None:
    (tmp_path / ".echelon" / "prosaic" / "subagents").mkdir(parents=True)

    assert ProsaicPromptLoader(tmp_path).load_command("echelon.bugfix") is None


@pytest.mark.unit
def test_load_subagent_inspects_the_project_prosaic_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    (source / "subagents").mkdir(parents=True)

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "subagents/echelon.summarizer.md",
                    "type": "subagent",
                    "frontmatter": {
                        "name": "echelon.summarizer",
                        "model_tier": "fast",
                        "effort": "low",
                        "tools": "write",
                    },
                    "body": "Summarize the run for a human.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path).load_subagent("echelon.summarizer")

    assert artifact is not None
    assert artifact.body == "Summarize the run for a human."
    assert artifact.frontmatter["model_tier"] == "fast"


@pytest.mark.unit
def test_deployed_summarizer_uses_the_id_only_selection_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "prosaic/subagents/echelon.summarizer.md").read_text(
        encoding="utf-8"
    )
    assert "selected_fact_ids" in text
    assert '"bullets"' not in text
    assert "model_tier: fast" in text
    assert "effort: low" in text
    assert "tools: write" in text


@pytest.mark.unit
def test_load_command_inlines_referenced_companion_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    companion = source / "commands" / "appendices" / "shared.md"
    companion.parent.mkdir(parents=True)
    companion.write_text("# Shared protocol\n\nCOMPANION_SENTINEL\n", encoding="utf-8")

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "commands/echelon.demo.md",
                    "type": "command",
                    "frontmatter": {"name": "echelon.demo"},
                    "body": "Load `commands/appendices/shared.md` before acting.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path).load_command("echelon.demo")

    assert artifact is not None
    assert "COMPANION_SENTINEL" in artifact.body
    assert artifact.body.count("COMPANION_SENTINEL") == 1


@pytest.mark.unit
def test_render_command_substitutes_neutral_arguments() -> None:
    prompt = ProsaicPromptLoader.render_command(
        ProsaicCommandArtifact(frontmatter={}, body="Fix {{args}}."),
        "the regression",
    ).prompt

    assert "Fix the regression." in prompt
    assert prompt.startswith("You were dispatched as a subagent")


@pytest.mark.unit
def test_render_command_preserves_artifact_metadata() -> None:
    artifact = ProsaicCommandArtifact(
        frontmatter={"model_tier": "balanced", "effort": "high", "color": "blue"},
        body="Fix {{args}}.",
    )

    rendered = ProsaicPromptLoader.render_command(artifact, "the regression")

    assert "Fix the regression." in rendered.prompt
    assert rendered.frontmatter == artifact.frontmatter
