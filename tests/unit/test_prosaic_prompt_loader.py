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
def test_load_agent_inspects_the_project_prosaic_subagent_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ".echelon" / "prosaic"
    (source / "subagents").mkdir(parents=True)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "id": "subagents/echelon.summarizer.md",
                    "type": "agent",
                    "frontmatter": {
                        "name": "echelon.summarizer",
                        "model_tier": "fast",
                        "effort": "low",
                    },
                    "body": "Return summary JSON only.",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("harness.prosaic_prompt_loader.subprocess.run", fake_run)

    artifact = ProsaicPromptLoader(tmp_path).load_agent("echelon.summarizer")

    assert artifact is not None
    assert artifact.frontmatter["model_tier"] == "fast"
    assert artifact.frontmatter["effort"] == "low"
    assert captured == {
        "command": [
            "prosaic",
            "inspect",
            "subagents/echelon.summarizer.md",
            "--source",
            str(source),
        ],
        "cwd": str(tmp_path),
    }


@pytest.mark.unit
def test_render_agent_appends_encoded_evidence_without_commander_preamble() -> None:
    artifact = ProsaicCommandArtifact(
        frontmatter={"model_tier": "fast", "effort": "low"},
        body="Return summary JSON only.",
    )

    rendered = ProsaicPromptLoader.render_agent(
        artifact,
        '{"status":"done","goal":"Add sessions"}',
    )

    assert rendered.prompt == (
        "Return summary JSON only.\n\n"
        "## Evidence Packet\n"
        "```json\n"
        '{"status":"done","goal":"Add sessions"}\n'
        "```\n"
    )
    assert "You were dispatched as a subagent" not in rendered.prompt
    assert rendered.frontmatter == {"model_tier": "fast", "effort": "low"}


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
