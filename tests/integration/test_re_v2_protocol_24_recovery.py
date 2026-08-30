from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.protocol_24.controller import Protocol24Controller
from harness.re_v2.protocol_22.model import ExecutionInputV1
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.recovery import ProcessState
from tests.integration.test_re_v2_protocol_24_controller import _child_context
from tests.unit.test_re_v2_protocol_22_recovery import _Inspector


class _CrashOnce:
    def __init__(self, boundary_prefix: str, context: object) -> None:
        self.boundary_prefix = boundary_prefix
        self.context = context
        self.crashed = False

    def __call__(self, boundary: str) -> None:
        if self.crashed or not boundary.startswith(self.boundary_prefix):
            return
        events = self.context.event_store.replay()
        started = next(
            (item for item in reversed(events) if item.type == "dispatch_started"),
            None,
        )
        if started is None:
            return
        execution_input = load_canonical_object(
            self.context.object_store.read_blob(
                str(started.payload["execution_input_hash"])
            ),
            ExecutionInputV1.from_json_dict,
        )
        if execution_input.deterministic_invocation is not None:
            return
        self.crashed = True
        raise RuntimeError(f"simulated crash at {boundary}")


@pytest.mark.integration
@pytest.mark.parametrize(
    "boundary",
    (
        "dispatch_started:",
        "execution_capture_fsynced",
        "capture_staging_ready_fsynced",
        "capture_committed_fsynced",
        "candidate_blob_fsynced",
        "candidate_record_fsynced",
        "candidate_persisted:",
        "certification_receipt:",
        "candidate_assessment:",
        "candidate_certified:",
        "artifact_acceptance_receipt:",
        "artifact_accepted:",
    ),
)
def test_l2_crash_boundaries_converge_without_duplicate_provider_execution(
    tmp_path: Path,
    boundary: str,
) -> None:
    context, provider = _child_context(tmp_path, paused=False, provider_mode="cli")
    assert provider is not None
    provider_dispatch_ids: list[str] = []
    execute = provider.execute

    def tracked_execute(execution_input: object, *args: object, **kwargs: object):
        provider_dispatch_ids.append(execution_input.dispatch_id)
        return execute(execution_input, *args, **kwargs)

    provider.execute = tracked_execute
    crash = _CrashOnce(boundary, context)

    with pytest.raises(RuntimeError, match="simulated crash"):
        Protocol24Controller(context, crash).run_until_stopped()
    assert crash.crashed

    recovered = replace(
        context,
        process_inspector=_Inspector(ProcessState.DEAD),
    )
    first = Protocol24Controller(recovered).run_until_stopped()
    calls = provider.calls
    hashes = tuple(item.event_hash for item in first.events)
    second = Protocol24Controller(recovered).run_until_stopped()

    assert first.status == second.status == "completed"
    assert provider.calls == calls
    assert provider.calls in {2, 3}
    assert len(provider_dispatch_ids) == len(set(provider_dispatch_ids))
    assert len(provider_dispatch_ids) == provider.calls
    assert tuple(item.event_hash for item in second.events) == hashes
    assert second.ledger.accepted_artifacts == first.ledger.accepted_artifacts
    assert len(first.ledger.accepted_artifacts) == len(context.graph.templates)


@pytest.mark.integration
def test_l2_terminal_replay_materializes_without_new_dispatch(tmp_path: Path) -> None:
    context, provider = _child_context(tmp_path, paused=False, provider_mode="cli")
    assert provider is not None
    first = Protocol24Controller(context).run_until_stopped()
    calls = provider.calls
    event_hashes = tuple(item.event_hash for item in first.events)

    second = Protocol24Controller(context).run_until_stopped()

    assert first.status == second.status == "completed"
    assert provider.calls == calls == 2
    assert tuple(item.event_hash for item in second.events) == event_hashes
