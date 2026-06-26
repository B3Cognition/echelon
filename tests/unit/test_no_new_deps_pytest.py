"""Pytest migration for the no-new-dependencies shell contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.contract.no_new_deps import (
    find_banned_dependency_declarations,
    find_banned_script_invocations,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_python_config_does_not_add_tool_dependencies() -> None:
    findings = find_banned_dependency_declarations(ROOT)

    assert findings == []


@pytest.mark.unit
def test_journal_scripts_do_not_invoke_banned_tools() -> None:
    scripts = [
        ROOT / "extension/scripts/bash/validate-journal-entry.sh",
        ROOT / "extension/scripts/bash/journal-append.sh",
    ]

    findings = find_banned_script_invocations(scripts)

    assert findings == []
