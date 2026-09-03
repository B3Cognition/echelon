from __future__ import annotations

from pathlib import Path
import multiprocessing
import os

import pytest

from tests.unit.test_re_v2_protocol_27_controller import (
    _ScriptedProvider,
    _validated_controller_inputs,
)


class _Crash(RuntimeError):
    pass


class _CrashOnce:
    def __init__(self, boundary: str) -> None:
        self.boundary = boundary
        self.fired = False

    def __call__(self, observed: str) -> None:
        if not self.fired and observed == self.boundary:
            self.fired = True
            raise _Crash(observed)


class _CrashNth:
    def __init__(self, boundary: str, occurrence: int) -> None:
        self.boundary = boundary
        self.occurrence = occurrence
        self.seen = 0

    def __call__(self, observed: str) -> None:
        if observed != self.boundary:
            return
        self.seen += 1
        if self.seen == self.occurrence:
            raise _Crash(observed)


class _CrashPrefixOnce:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def __call__(self, observed: str) -> None:
        if observed.startswith(self.prefix):
            raise _Crash(observed)


class _MarkerProvider(_ScriptedProvider):
    def __init__(self, marker: Path) -> None:
        super().__init__()
        self.marker = marker

    def exec_agent(self, project_root: str, prompt: str, **kwargs):
        with self.marker.open("a", encoding="utf-8") as stream:
            stream.write("provider-call\n")
        return super().exec_agent(project_root, prompt, **kwargs)


def _die_at_boundary(
    run_dir: str,
    boundary: str,
    marker: str | None = None,
) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.inputs import load_protocol_27_inputs

    inputs = load_protocol_27_inputs(Path(run_dir))
    provider = _ScriptedProvider() if marker is None else _MarkerProvider(Path(marker))
    try:
        Protocol27Controller(
            inputs,
            provider_factory=lambda: provider,  # type: ignore[arg-type]
            fault_hook=_CrashOnce(boundary),
        ).run_to_closure()
    except _Crash:
        os._exit(17)
    os._exit(18)


@pytest.mark.integration
@pytest.mark.parametrize(
    "boundary",
    (
        "after_provider_capture",
        "after_capture_commit",
        "after_dispatch_observed",
        "after_candidate_staged",
        "after_assessment",
        "after_certification",
        "after_acceptance_ledger",
        "after_certification_event",
        "after_acceptance_event",
        "after_root_ledger",
        "after_root",
    ),
)
def test_recovery_is_idempotent_at_every_post_provider_boundary(
    tmp_path: Path,
    boundary: str,
) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider()
    crash = _CrashOnce(boundary)
    with pytest.raises(_Crash, match=boundary):
        Protocol27Controller(
            inputs,
            provider_factory=lambda: provider,  # type: ignore[arg-type]
            fault_hook=crash,
        ).run_to_closure()
    calls_before_resume = len(provider.calls)

    result = run_protocol_27_synthesis(
        inputs.paths.root.parent,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    )

    assert result.synthesis_closure_complete
    assert len(provider.calls) == 13
    assert len(provider.calls) >= calls_before_resume
    assert len(set(provider.calls)) == 13


@pytest.mark.integration
def test_recovery_needs_no_parent_origin_after_child_activation(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider()
    with pytest.raises(_Crash):
        Protocol27Controller(
            inputs,
            provider_factory=lambda: provider,  # type: ignore[arg-type]
            fault_hook=_CrashOnce("after_capture_commit"),
        ).run_to_closure()

    result = run_protocol_27_synthesis(
        inputs.paths.root.parent,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    )

    assert result.synthesis_closure_complete
    assert len(provider.calls) == 13


@pytest.mark.integration
@pytest.mark.parametrize(
    "boundary",
    ("started_lease_fsynced", "after_dispatch_reserved"),
)
def test_dead_provider_owner_is_abandoned_before_bounded_retry(
    tmp_path: Path,
    boundary: str,
) -> None:
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    inputs = _validated_controller_inputs(tmp_path)
    process = multiprocessing.get_context("fork").Process(
        target=_die_at_boundary,
        args=(str(inputs.paths.root.parent), boundary),
    )
    process.start()
    process.join(timeout=20)
    assert process.exitcode == 17
    provider = _ScriptedProvider()

    result = run_protocol_27_synthesis(
        inputs.paths.root.parent,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    )

    assert result.synthesis_closure_complete
    assert len(provider.calls) == 13
    assert result.provider_attempts == 14
    assert result.contract_retries == 1


@pytest.mark.integration
def test_recovery_finishes_existing_retry_without_a_third_call(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider(malformed_first=True)
    with pytest.raises(_Crash):
        Protocol27Controller(
            inputs,
            provider_factory=lambda: provider,  # type: ignore[arg-type]
            fault_hook=_CrashNth("after_provider_capture", 2),
        ).run_to_closure()
    assert len(provider.calls) == 2

    result = run_protocol_27_synthesis(
        inputs.paths.root.parent,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    )

    assert result.synthesis_closure_complete
    assert len(provider.calls) == 14
    assert result.provider_attempts == 14
    assert result.contract_retries == 1


@pytest.mark.integration
def test_terminal_recovery_is_byte_idempotent(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.recovery import (
        load_protocol_27_run_context,
        recover_protocol_27_run,
    )

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider()
    result = Protocol27Controller(
        inputs,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    ).run_to_closure()
    assert result.synthesis_closure_complete
    before = (inputs.paths.events.read_bytes(), inputs.paths.ledger.read_bytes())

    first = recover_protocol_27_run(
        load_protocol_27_run_context(inputs.paths.root.parent)
    )
    second = recover_protocol_27_run(
        load_protocol_27_run_context(inputs.paths.root.parent)
    )

    assert first.pending_action is None
    assert second.pending_action is None
    assert first.repaired_boundaries == second.repaired_boundaries == ()
    assert (inputs.paths.events.read_bytes(), inputs.paths.ledger.read_bytes()) == before


@pytest.mark.integration
def test_process_death_after_durable_capture_does_not_repeat_provider_call(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    inputs = _validated_controller_inputs(tmp_path)
    marker = tmp_path / "provider-calls.log"
    process = multiprocessing.get_context("fork").Process(
        target=_die_at_boundary,
        args=(
            str(inputs.paths.root.parent),
            "execution_capture_fsynced",
            str(marker),
        ),
    )
    process.start()
    process.join(timeout=20)
    assert process.exitcode == 17
    provider = _MarkerProvider(marker)

    result = run_protocol_27_synthesis(
        inputs.paths.root.parent,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    )

    assert result.synthesis_closure_complete
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "provider-call"
    ] * 13
    assert len(provider.calls) == 12


@pytest.mark.integration
def test_recovery_repairs_interrupted_materialization_without_provider(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider()
    with pytest.raises(_Crash, match="materialization_published"):
        Protocol27Controller(
            inputs,
            provider_factory=lambda: provider,  # type: ignore[arg-type]
            fault_hook=_CrashPrefixOnce("materialization_published:"),
        ).run_to_closure()
    calls = len(provider.calls)

    result = run_protocol_27_synthesis(
        inputs.paths.root.parent,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    )

    assert result.synthesis_closure_complete
    assert result.terminal_kind == "complete"
    assert len(provider.calls) == calls
