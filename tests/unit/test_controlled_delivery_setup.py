"""Controller-only delivery setup boundaries."""

from pathlib import Path

import pytest

from harness.delivery_results import ImplementationResult
from harness.run_intent import RunIntent
from harness.state import StateStore
from tests.unit.test_coordinator import _make_coordinator


def test_delivery_without_llm_provider_blocks_before_ralph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _make_coordinator(tmp_path)
    constructed: list[bool] = []

    class UnexpectedRalph:
        def __init__(self, **kwargs):
            constructed.append(True)

        def run_loop(self, **kwargs):
            return ImplementationResult(
                "blocked", "fixture_stop", 0, 0, None, 0, None
            )

    monkeypatch.setattr("harness.coordinator.RalphController", UnexpectedRalph)

    result = coordinator.start(
        RunIntent(spec_id="spec-001", max_outer=1, max_inner=1)
    )[0]

    assert result.status == "blocked"
    assert result.termination_reason == "delivery_configuration_invalid"
    assert constructed == []
    state = StateStore(tmp_path / "runs/state", "spec-001", "default").read()
    assert "LLM provider" in state["build_reason"]


def test_noncanonical_strategy_blocks_before_ralph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _make_coordinator(tmp_path)
    coordinator._config.llm.enabled = True
    strategy = tmp_path / "runs/strategies/spec-001/default.md"
    strategy.write_text(
        "---\ncommand: custom build\n---\nDo the work.\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "harness.coordinator.AICodingCliProvider", lambda config: object()
    )

    result = coordinator.start(
        RunIntent(spec_id="spec-001", max_outer=1, max_inner=1)
    )[0]

    assert result.status == "blocked"
    assert result.termination_reason == "delivery_configuration_invalid"
    state = StateStore(tmp_path / "runs/state", "spec-001", "default").read()
    assert "echelon build" in state["build_reason"]


def test_coordinator_passes_controller_context_without_resolving_build_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _make_coordinator(tmp_path)
    coordinator._config.llm.enabled = True
    monkeypatch.setattr(
        "harness.coordinator.AICodingCliProvider", lambda config: object()
    )
    captured: list[str] = []

    class BuildBoundary:
        def __init__(self, **kwargs):
            pass

        def run_loop(self, **kwargs):
            captured.append(kwargs["build_prompt"])
            return ImplementationResult(
                "blocked", "fixture_stop", 0, 0, None, 0, None
            )

    monkeypatch.setattr("harness.coordinator.RalphController", BuildBoundary)

    result = coordinator.start(RunIntent(
        spec_id="spec-001",
        max_outer=1,
        max_inner=1,
        task_description="Repair task T-001",
    ))[0]

    assert result.termination_reason == "fixture_stop"
    assert captured == [
        "spec spec-001 strategy=default semi mode\n\nRepair task T-001"
    ]
