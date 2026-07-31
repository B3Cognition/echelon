"""Tests for Echelon's normalized Prosaic source export."""

from __future__ import annotations

from pathlib import Path

import yaml

from harness.prosaic_export import export_normalized_agents, export_normalized_prose


def test_export_normalized_agents_uses_manifest_metadata_and_discards_native_frontmatter(
    tmp_path: Path,
) -> None:
    extension = tmp_path / "extension"
    agents = extension / "agents"
    agents.mkdir(parents=True)
    (agents / "chief.md").write_text(
        "---\n"
        "name: legacy-chief\n"
        "description: Legacy description\n"
        "model: claude-sonnet-4-6\n"
        "---\n\n"
        "# Chief\n",
        encoding="utf-8",
    )
    (agents / "validator.md").write_text("# Validator\n", encoding="utf-8")
    (extension / "extension.yml").write_text(
        "provides:\n"
        "  commands:\n"
        "    - name: speckit.echelon.chief\n"
        "      file: agents/chief.md\n"
        "      description: Canonical chief\n"
        "      behavior:\n"
        "        execution: agent\n"
        "        capability: balanced\n"
        "        tools: full\n"
        "    - name: speckit.echelon.re-validator\n"
        "      file: agents/validator.md\n"
        "      description: Canonical validator\n"
        "      behavior:\n"
        "        execution: agent\n"
        "        capability: strong\n",
        encoding="utf-8",
    )
    destination = tmp_path / ".echelon" / "prosaic"
    stale = destination / "subagents" / "echelon.removed-agent.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale\n", encoding="utf-8")

    result = export_normalized_agents(extension, destination)

    assert result.exported_count == 2
    chief = destination / "subagents" / "echelon.chief.md"
    validator = destination / "subagents" / "echelon.re-validator.md"
    assert chief.exists()
    assert validator.exists()
    assert not stale.exists()
    _, chief_frontmatter, chief_body = chief.read_text(encoding="utf-8").split("---\n", 2)
    assert yaml.safe_load(chief_frontmatter) == {
        "name": "speckit.echelon.chief",
        "description": "Canonical chief",
        "execution": "agent",
        "capability": "balanced",
        "tools": "full",
    }
    assert "model:" not in chief_frontmatter
    assert chief_body == "# Chief\n"
    assert validator.read_text(encoding="utf-8").endswith("# Validator\n")


def test_export_normalized_prose_writes_manifest_defined_commands(tmp_path: Path) -> None:
    extension = tmp_path / "extension"
    commands = extension / "commands"
    commands.mkdir(parents=True)
    (commands / "echelon.bugfix.md").write_text(
        "---\nname: native-name\nmodel: native-model\n---\n\nFix $ARGUMENTS.\n",
        encoding="utf-8",
    )
    (extension / "extension.yml").write_text(
        "provides:\n"
        "  commands:\n"
        "    - name: speckit.echelon.bugfix\n"
        "      file: commands/echelon.bugfix.md\n"
        "      description: Canonical bugfix\n"
        "      behavior:\n"
        "        execution: isolated\n"
        "        invocation: automatic\n",
        encoding="utf-8",
    )

    result = export_normalized_prose(extension, tmp_path / ".echelon" / "prosaic")

    assert result.exported_count == 1
    command = tmp_path / ".echelon" / "prosaic" / "commands" / "echelon.bugfix.md"
    _, frontmatter, body = command.read_text(encoding="utf-8").split("---\n", 2)
    assert yaml.safe_load(frontmatter) == {
        "name": "speckit.echelon.bugfix",
        "description": "Canonical bugfix",
        "execution": "command",
        "invocation": "automatic",
    }
    assert "model:" not in frontmatter
    assert body == "Fix {{args}}.\n"
