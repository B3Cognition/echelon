import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from harness.skill_loader import build_skill_prompt, find_skill


def test_find_skill_prefers_workspace_prosaic_command_for_every_provider(
    tmp_path: Path,
) -> None:
    command = tmp_path / ".echelon/prosaic/commands/echelon.review.md"
    command.parent.mkdir(parents=True)
    command.write_text("---\ndescription: Review\n---\n\nReview {{args}}.\n", encoding="utf-8")

    for cli in ("claude", "codex", "copilot", "opencode", "openai-compatible"):
        assert find_skill("echelon.review", tmp_path, cli) == command


def test_find_skill_does_not_treat_provider_output_as_echelon_source(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / ".claude/skills/echelon-review/SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy provider output\n", encoding="utf-8")

    assert find_skill("echelon.review", tmp_path, "claude") is None


def test_build_skill_prompt_uses_prosaic_inspect_for_neutral_command(
    tmp_path: Path,
) -> None:
    command = tmp_path / ".echelon/prosaic/commands/echelon.review.md"
    command.parent.mkdir(parents=True)
    command.write_text("source is inspected, not read directly\n", encoding="utf-8")
    inspected = {
        "type": "command",
        "frontmatter": {"description": "Review"},
        "body": "Review {{args}}.",
    }

    with patch("harness.prosaic_prompt_loader.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            ["prosaic", "inspect"],
            0,
            stdout=json.dumps(inspected),
            stderr="",
        )
        prompt = build_skill_prompt(command, "spec-123")

    assert "Review spec-123." in prompt
    run.assert_called_once()
    assert run.call_args.args[0][:3] == [
        "prosaic",
        "inspect",
        "commands/echelon.review.md",
    ]
