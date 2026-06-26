"""Pytest migration for extension registry sync contract checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.contract.registry_sync import (
    actual_agent_prompt_files,
    missing_registered_agent_files,
    missing_re_agent_phase_files,
    neutral_re_command_count,
    re_agent_entry_count,
    re_phase_count,
    registered_agent_files,
    unregistered_agent_prompt_files,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_all_agent_prompt_files_are_registered() -> None:
    assert unregistered_agent_prompt_files(ROOT) == []


@pytest.mark.unit
def test_all_registered_agents_have_prompt_files() -> None:
    assert missing_registered_agent_files(ROOT) == []


@pytest.mark.unit
def test_registered_agent_count_matches_prompt_file_count() -> None:
    assert len(registered_agent_files(ROOT)) == len(actual_agent_prompt_files(ROOT))


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
