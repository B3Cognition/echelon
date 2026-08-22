from __future__ import annotations

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
