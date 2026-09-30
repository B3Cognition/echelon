"""Structural boundary for the controller-only delivery runtime."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_delivery_execution_is_absent() -> None:
    retired = (
        "src/harness/llm_build_runner.py",
        "src/harness/delivery_prompt.py",
        "prosaic/commands/echelon.build.md",
        "runtime/workflow/phases/build-1-init.md",
        "runtime/workflow/phases/build-8-finalize.md",
    )
    assert [path for path in retired if (ROOT / path).exists()] == []
    assert importlib.util.find_spec("harness.llm_build_runner") is None
    assert importlib.util.find_spec("harness.delivery_prompt") is None


def test_legacy_build_graph_and_skill_mapping_are_absent() -> None:
    definition = yaml.safe_load(
        (ROOT / "runtime/workflow/definition.yaml").read_text(encoding="utf-8")
    )
    phase_ids = {phase["id"] for phase in definition["phases"]}
    assert not {phase_id for phase_id in phase_ids if phase_id.startswith("build-")}
    assert "build" not in definition

    from harness import skill_loader

    assert not hasattr(skill_loader, "build_command_to_skill_base")
    assert not hasattr(skill_loader, "resolve_llm_prompt")
