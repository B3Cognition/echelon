"""Canonical Prosaic/runtime registry sync contract checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.contract.registry_sync import (
    invalid_subagent_frontmatter_names,
    missing_re_agent_phase_files,
    missing_workflow_agent_prompt_files,
    neutral_re_command_count,
    re_agent_entry_count,
    re_phase_count,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_all_workflow_agents_have_prosaic_subagent_prompts() -> None:
    assert missing_workflow_agent_prompt_files(ROOT) == []


@pytest.mark.unit
def test_prosaic_subagent_names_match_their_filenames() -> None:
    assert invalid_subagent_frontmatter_names(ROOT) == []


@pytest.mark.unit
def test_re_workflow_phase_count_is_stable() -> None:
    assert re_phase_count(ROOT) == 13


@pytest.mark.unit
def test_re_agent_phases_have_prompt_files() -> None:
    assert missing_re_agent_phase_files(ROOT) == []


@pytest.mark.unit
def test_re_agent_entry_count_is_stable() -> None:
    assert re_agent_entry_count(ROOT) == 9


@pytest.mark.unit
def test_re_commands_are_neutral_wrappers() -> None:
    assert neutral_re_command_count(ROOT) == 12
