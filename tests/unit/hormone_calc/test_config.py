"""Tests for src/hormone_calc/config.py — DynamicsConfig loading + defaults."""
from pathlib import Path
import textwrap
import pytest

from hormone_calc.config import (
    DynamicsConfig,
    DEFAULT_DYNAMICS,
    load,
    Band,
)


def test_default_dynamics_has_5_budget_bands():
    assert len(DEFAULT_DYNAMICS.budget_pressure.bands) == 5
    assert DEFAULT_DYNAMICS.budget_pressure.bands[0].upto == 0.40
    assert DEFAULT_DYNAMICS.budget_pressure.bands[0].delta == 0.00
    assert DEFAULT_DYNAMICS.budget_pressure.bands[4].upto == 1.00
    assert DEFAULT_DYNAMICS.budget_pressure.bands[4].delta == 0.15


def test_default_dynamics_has_8_archetypes():
    archetypes = set(DEFAULT_DYNAMICS.task_complexity.archetype_base.keys())
    assert archetypes == {
        "exploration", "validation", "feasibility", "solution",
        "build", "innovation", "learning", "control",
    }


def test_default_dynamics_build_archetype_base():
    assert DEFAULT_DYNAMICS.task_complexity.archetype_base["build"] == 0.80


def test_default_dynamics_implementer_bump():
    assert DEFAULT_DYNAMICS.task_complexity.agent_bump["IMPLEMENTER"] == 0.10


def test_load_absent_file_returns_default(tmp_path):
    nonexistent = tmp_path / "missing.yml"
    cfg = load(nonexistent)
    assert cfg is DEFAULT_DYNAMICS or cfg == DEFAULT_DYNAMICS


def test_load_yaml_without_endocrine_dynamics_returns_default(tmp_path):
    yml = tmp_path / "no-dynamics.yml"
    yml.write_text("endocrine:\n  enabled: true\n  baselines:\n    foo: [0.5]\n")
    cfg = load(yml)
    assert cfg == DEFAULT_DYNAMICS


def test_load_yaml_with_dynamics_parses_correctly(tmp_path):
    yml = tmp_path / "custom.yml"
    yml.write_text(textwrap.dedent("""
        endocrine:
          dynamics:
            budget_pressure:
              bands:
                - { upto: 0.5, delta: 0.10 }
                - { upto: 1.0, delta: 0.20 }
              critical_broadcast: 0.08
            iteration_pressure:
              bands:
                - { upto: 1.0, delta: 0.05 }
            task_complexity:
              multiplier: 0.20
              archetype_base:
                exploration: 0.50
              agent_bump:
                CUSTOM: 0.25
    """))
    cfg = load(yml)
    assert len(cfg.budget_pressure.bands) == 2
    assert cfg.budget_pressure.bands[0].delta == 0.10
    assert cfg.budget_pressure.critical_broadcast == 0.08
    assert cfg.task_complexity.multiplier == 0.20
    assert cfg.task_complexity.agent_bump["CUSTOM"] == 0.25


def test_load_malformed_yaml_returns_default(tmp_path):
    yml = tmp_path / "bad.yml"
    yml.write_text("endocrine:\n  dynamics: [this is not a mapping]")
    cfg = load(yml)
    assert cfg == DEFAULT_DYNAMICS
