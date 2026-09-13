from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.protocol_22.controller import Protocol22Controller
from tests.unit.test_re_v2_protocol_22_controller import _baseline_context


@pytest.mark.integration
def test_protocol_22_controller_is_a_separate_schema_2_surface() -> None:
    assert Protocol22Controller.__module__.endswith("protocol_22.controller")


@pytest.mark.integration
def test_completed_controller_replay_is_idempotent_and_issues_no_new_calls(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(tmp_path, malformed_result=True)

    first = Protocol22Controller(context).run_until_stopped()
    calls = provider.calls
    event_hashes = tuple(event.event_hash for event in first.events)
    second = Protocol22Controller(context).run_until_stopped()

    assert first.status == second.status == "completed"
    assert provider.calls == calls
    assert tuple(event.event_hash for event in second.events) == event_hashes


@pytest.mark.integration
def test_controller_does_not_duplicate_configured_materialization_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _provider = _baseline_context(tmp_path, malformed_result=True)
    validator_calls = 0

    def validate_materialization() -> None:
        nonlocal validator_calls
        validator_calls += 1

    context = replace(
        context,
        materialization_validator=validate_materialization,
    )

    def duplicate_materialization(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("controller duplicated recovery materialization validation")

    monkeypatch.setattr(
        Protocol22Controller,
        "_materialize_accepted_l1",
        duplicate_materialization,
    )

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "completed"
    assert validator_calls == 2
