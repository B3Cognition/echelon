from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import shutil

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.execution import Committed
from harness.re_v2.protocol_22.inputs import (
    create_protocol_22_run_store,
    load_protocol_22_inputs,
)
from harness.re_v2.protocol_22.materialization import (
    materialize_accepted_l1,
    validate_or_repair_materialization,
)
from harness.re_v2.protocol_22.recovery import recover_protocol_22_run
from harness.re_v2.recovery import ProcessState
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    detect_re_engine,
    load_run_manifest,
)
from tests.unit.test_re_v2_protocol_22_controller import _baseline_context
from tests.unit.test_re_v2_protocol_22_inputs import _input_fixture
from tests.unit.test_re_v2_protocol_22_materialization import (
    _completed_context,
    _projection_by_fragment,
)
from tests.unit.test_re_v2_protocol_22_recovery import _Inspector, interrupted_dispatch


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


def _tree_bytes(root: Path) -> tuple[tuple[str, bytes], ...]:
    if not root.exists():
        return ()
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("boundary", "manifest_is_durable"),
    (
        ("object_published:", False),
        ("catalog_published:workspace_partition", False),
        ("manifest_temporary_fsynced", False),
        ("manifest_linked", True),
    ),
)
def test_creation_fault_boundaries_remain_unambiguous_across_two_restarts(
    tmp_path: Path,
    boundary: str,
    manifest_is_durable: bool,
) -> None:
    inputs, manifest = _input_fixture()
    run_dir = tmp_path / "runs" / manifest.run_id
    hit = False

    def crash_once(point: str) -> None:
        nonlocal hit
        if not hit and (
            point == boundary
            or (boundary.endswith(":") and point.startswith(boundary))
        ):
            hit = True
            raise RuntimeError(f"crash at {point}")

    with pytest.raises(RuntimeError, match="crash at"):
        create_protocol_22_run_store(
            run_dir,
            manifest,
            inputs,
            fault_hook=crash_once,
        )

    assert hit
    before = _tree_bytes(run_dir)
    if manifest_is_durable:
        for _ in range(2):
            assert load_run_manifest(run_dir) == manifest
            loaded = load_protocol_22_inputs(
                ReV2Paths.for_run(run_dir),
                manifest,
            )
            assert loaded.workspace_partition == inputs.workspace_partition
            assert loaded.artifact_policy == inputs.artifact_policy
            assert loaded.executor_contract == inputs.executor_contract
            assert dict(loaded.immutable_objects) == dict(inputs.immutable_objects)
    else:
        for _ in range(2):
            with pytest.raises(ReV2RunStoreError, match="incomplete"):
                detect_re_engine(run_dir)
    assert _tree_bytes(run_dir) == before


@dataclass
class _BoundaryCrash:
    target: str
    provider_seen: bool = False
    hit: bool = False

    def __call__(self, point: str) -> None:
        if point == "provider_envelope_fsynced":
            self.provider_seen = True
        if self.hit or not self._matches(point):
            return
        self.hit = True
        raise RuntimeError(f"crash at {point}")

    def _matches(self, point: str) -> bool:
        if self.target == "provider_envelope":
            return point == "provider_envelope_fsynced"
        if self.target == "execution_input":
            return self.provider_seen and point == "execution_input_fsynced"
        if self.target == "dispatch_start":
            return self.provider_seen and point.startswith("dispatch_started:")
        if self.target == "observed_event":
            return self.provider_seen and point.startswith("dispatch_observed:")
        if self.target == "reconstruction_event":
            return point.startswith("result_contract_reconstructed:")
        if self.target == "deterministic_certification":
            return not self.provider_seen and point.startswith("certification_receipt:")
        if self.target == "candidate_assessment":
            return point.startswith("candidate_assessment:")
        if self.target == "certification_event":
            return point.startswith("candidate_certified:")
        if self.target == "acceptance_receipt":
            return self.provider_seen and point.startswith(
                "artifact_acceptance_receipt:"
            )
        if self.target == "artifact_event":
            return self.provider_seen and point.startswith("artifact_accepted:")
        exact = {
            "candidate_blob": "candidate_blob_fsynced",
            "candidate_inventory": "candidate_inventory_fsynced",
            "stdout_blob": "stdout_blob_fsynced",
            "usage_blob": "usage_blob_fsynced",
            "execution_capture": "execution_capture_fsynced",
            "staging_ready": "capture_staging_ready_fsynced",
            "capture_commit": "capture_committed_fsynced",
        }
        return self.provider_seen and point == exact.get(self.target)


_SUCCESS_BOUNDARIES = (
    "provider_envelope",
    "execution_input",
    "dispatch_start",
    "candidate_blob",
    "candidate_inventory",
    "stdout_blob",
    "usage_blob",
    "execution_capture",
    "staging_ready",
    "capture_commit",
    "observed_event",
    "reconstruction_event",
    "deterministic_certification",
    "candidate_assessment",
    "certification_event",
    "acceptance_receipt",
    "artifact_event",
)


@pytest.mark.integration
@pytest.mark.parametrize("boundary", _SUCCESS_BOUNDARIES)
def test_success_boundary_crashes_converge_without_reissuing_a_dispatch(
    tmp_path: Path,
    boundary: str,
) -> None:
    from harness.re_v2.protocol_22.controller import Protocol22Controller

    context, provider = _baseline_context(
        tmp_path,
        malformed_result=boundary == "reconstruction_event",
        scripts=(
            {"domain-baseline": ["usage_overflow"]}
            if boundary == "usage_blob"
            else None
        ),
    )
    crash = _BoundaryCrash(boundary)

    with pytest.raises(RuntimeError, match="crash at"):
        Protocol22Controller(context, crash).run_until_stopped()
    assert crash.hit

    dead_context = replace(
        context,
        process_inspector=_Inspector(ProcessState.DEAD),
    )
    first = Protocol22Controller(dead_context).run_until_stopped()
    first_events = context.paths.events.read_bytes()
    first_ledger = context.paths.ledger.read_bytes()
    second = Protocol22Controller(dead_context).run_until_stopped()

    assert first.status == second.status == "completed"
    assert context.paths.events.read_bytes() == first_events
    assert context.paths.ledger.read_bytes() == first_ledger
    assert len(first_ledger.splitlines()) == len(set(first_ledger.splitlines()))
    starts = [
        event.payload["dispatch_id"]
        for event in second.events
        if event.type == "dispatch_started"
    ]
    assert len(starts) == len(set(starts))
    assert max(provider.calls_by_kind.values(), default=0) <= 2


@pytest.mark.integration
@pytest.mark.parametrize(
    ("boundary", "scripts", "point_prefix"),
    (
        (
            "item_failure_receipt",
            {"domain-baseline": ["invalid_candidate", "invalid_candidate"]},
            "work_item_failure_receipt:",
        ),
        (
            "executor_failure_receipt",
            {"domain-baseline": ["usage_overflow"]},
            "executor_failure_receipt:",
        ),
        (
            "failure_event",
            {"domain-baseline": ["invalid_candidate", "invalid_candidate"]},
            "work_item_failed:",
        ),
    ),
)
def test_failure_boundary_crashes_converge_to_one_terminal_receipt(
    tmp_path: Path,
    boundary: str,
    scripts: dict[str, list[str]],
    point_prefix: str,
) -> None:
    from harness.re_v2.protocol_22.controller import Protocol22Controller

    del boundary
    context, provider = _baseline_context(tmp_path, scripts=scripts)
    hit = False

    def crash_once(point: str) -> None:
        nonlocal hit
        if not hit and point.startswith(point_prefix):
            hit = True
            raise RuntimeError(f"crash at {point}")

    with pytest.raises(RuntimeError, match="crash at"):
        Protocol22Controller(context, crash_once).run_until_stopped()
    assert hit

    dead_context = replace(
        context,
        process_inspector=_Inspector(ProcessState.DEAD),
    )
    first = Protocol22Controller(dead_context).run_until_stopped()
    first_events = context.paths.events.read_bytes()
    first_ledger = context.paths.ledger.read_bytes()
    second = Protocol22Controller(dead_context).run_until_stopped()

    assert first.status == second.status == "failed"
    assert context.paths.events.read_bytes() == first_events
    assert context.paths.ledger.read_bytes() == first_ledger
    assert len(first_ledger.splitlines()) == len(set(first_ledger.splitlines()))
    assert [event.type for event in second.events].count("run_failed") == 1
    assert max(provider.calls_by_kind.values(), default=0) <= 2


@pytest.mark.integration
@pytest.mark.parametrize(
    "boundary",
    ("quarantine_move", "materialized_json", "materialized_markdown"),
)
def test_materialization_boundary_crashes_rebuild_exact_bytes_once(
    tmp_path: Path,
    boundary: str,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    domain, artifact_hash = _projection_by_fragment(initial, "/domains/")
    if boundary == "quarantine_move":
        markdown = domain / "baseline.md"
        markdown.chmod(0o600)
        markdown.write_text("corrupt\n", encoding="utf-8")
        prefix = "materialization_quarantined:"
    else:
        shutil.rmtree(domain)
        prefix = (
            "materialization_json_fsynced:"
            if boundary == "materialized_json"
            else "materialization_markdown_fsynced:"
        )
    hit = False

    def crash_once(point: str) -> None:
        nonlocal hit
        if not hit and point == prefix + artifact_hash:
            hit = True
            raise RuntimeError(f"crash at {point}")

    with pytest.raises(RuntimeError, match="crash at"):
        validate_or_repair_materialization(context, crash_once)
    assert hit

    validate_or_repair_materialization(context)
    first = _tree_bytes(context.paths.root / "materialized")
    validate_or_repair_materialization(context)
    second = _tree_bytes(context.paths.root / "materialized")

    assert second == first
    assert content_digest(domain.joinpath("baseline.json").read_bytes()) == artifact_hash
