from __future__ import annotations

from pathlib import Path

import yaml

from echelon.workspace_sources import ensure_source_config_entry


def test_ensure_source_appends_contract_without_reserializing_config(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    original = (
        "# Operator formatting is authoritative.\n"
        "version: \"4\"\n"
        "analysis:\n"
        "  note: >-\n"
        "    Keep this folded scalar.\n"
    )
    config.write_text(original, encoding="utf-8")

    assert ensure_source_config_entry(tmp_path, "sources/demo") is True

    assert config.read_text(encoding="utf-8") == (
        original
        + "\nworkspace:\n"
        "  git_role: orchestration\n"
        "\nsources:\n"
        "- id: demo\n"
        "  path: sources/demo\n"
    )


def test_ensure_source_changes_only_existing_sources_value(tmp_path: Path) -> None:
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    original = (
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources:\n"
        "  - id: api\n"
        "    path: sources/api\n"
        "harness:\n"
        "  verify_command: \"npm test\"\n"
    )
    config.write_text(original, encoding="utf-8")

    assert ensure_source_config_entry(tmp_path, "sources/demo") is True

    rendered = config.read_text(encoding="utf-8")
    assert rendered.startswith("workspace:\n  git_role: orchestration\nsources:\n")
    assert rendered.endswith('harness:\n  verify_command: "npm test"\n')
    assert yaml.safe_load(rendered)["sources"] == [
        {"id": "api", "path": "sources/api"},
        {"id": "demo", "path": "sources/demo"},
    ]
