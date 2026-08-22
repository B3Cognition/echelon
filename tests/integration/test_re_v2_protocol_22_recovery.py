from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.protocol_22.execution import Committed
from harness.re_v2.protocol_22.recovery import recover_protocol_22_run
from tests.unit.test_re_v2_protocol_22_recovery import interrupted_dispatch


@pytest.mark.integration
def test_staging_recovery_commits_and_replays_without_execution(tmp_path: Path) -> None:
    fixture = interrupted_dispatch(
        tmp_path,
        started=True,
        staging=True,
        committed=False,
    )

    first = recover_protocol_22_run(fixture.context)
    second = recover_protocol_22_run(fixture.context)

    assert first.dispatch_actions[fixture.dispatch_id] == "finish_commit"
    assert second.dispatch_actions[fixture.dispatch_id] == "adopt_committed"
    assert isinstance(
        fixture.context.execution_store.capture_state(fixture.dispatch_id),
        Committed,
    )
    assert [event.type for event in second.events].count("dispatch_observed") == 1
    assert fixture.provider.calls == 0
