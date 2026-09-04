from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from harness.re_v2.protocol_28.lifecycle import (
    L4DispatchResultV1,
    Protocol28CheckpointAdoptionV1,
    Protocol28LifecycleError,
    continue_protocol_28_run,
    create_or_reuse_protocol_28_child,
    find_exact_protocol_28_child,
    run_protocol_28_exhaustive,
)
from harness.re_v2.protocol_28.inputs import (
    publish_protocol_28_run,
    stage_exhaustive_inputs,
)
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from tests.unit.test_re_v2_protocol_28_inputs import _fixture
from tests.unit.test_re_v2_protocol_28_artifacts import _candidate_fixture
from harness.re_v2.protocol_28.artifacts import (
    ExhaustiveDiagnosticV1,
    ExhaustiveVerificationV1,
)
from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_28.checkpoints import (
    CheckpointSelectionBundleV2,
    CheckpointSelectionEntryV2,
)
from harness.re_v2.protocol_28.checkpoint_cache import load_checkpoint_cache_v2
from tests.unit.test_re_v2_protocol_28_checkpoints import _checkpoint


class _PassingBackend:
    def __init__(self) -> None:
        self.roles: list[str] = []

    def execute(self, role, _agent, _context, _schema, _reservation):  # type: ignore[no-untyped-def]
        self.roles.append(role)
        entry, spec, _evidence, candidate = _candidate_fixture()
        if role == "producer":
            value = candidate.to_json_dict()
        else:
            value = ExhaustiveVerificationV1(
                1,
                spec.identity,
                candidate.identity,
                entry.verifier_contract_hash,
                "PASS",
                (),
                candidate.covered_primary_evidence_ids,
                candidate.addressed_finding_ids,
            ).to_json_dict()
        return L4DispatchResultV1(
            canonical_json_bytes(value),
            "test-provider",
            "test-model",
            "2026-08-31T12:00:00Z",
            "2026-08-31T12:00:01Z",
            1000,
            token_status="trusted_exact",
            billable_tokens=5,
            active_status="trusted_exact",
            active_ms=1000,
        )


class _MalformedFirstVerifierBackend(_PassingBackend):
    def __init__(self) -> None:
        super().__init__()
        self._verifier_calls = 0

    def execute(self, role, agent, context, schema, reservation):  # type: ignore[no-untyped-def]
        if role == "verifier":
            self._verifier_calls += 1
            if self._verifier_calls == 1:
                self.roles.append(role)
                return L4DispatchResultV1(
                    b"{}\n",
                    "test-provider",
                    "test-model",
                    "2026-08-31T12:00:00Z",
                    "2026-08-31T12:00:01Z",
                    1000,
                    token_status="trusted_exact",
                    billable_tokens=5,
                    active_status="trusted_exact",
                    active_ms=1000,
                )
        return super().execute(role, agent, context, schema, reservation)


class _UnaccountedMalformedFirstVerifierBackend(_MalformedFirstVerifierBackend):
    def execute(self, role, agent, context, schema, reservation):  # type: ignore[no-untyped-def]
        result = super().execute(role, agent, context, schema, reservation)
        if role == "verifier" and self._verifier_calls == 1:
            return replace(
                result,
                token_status="unavailable",
                billable_tokens=None,
                active_status="unavailable",
                active_ms=None,
            )
        return result


class _InvalidResultBackend(_PassingBackend):
    def execute(self, role, _agent, _context, _schema, _reservation):  # type: ignore[no-untyped-def]
        self.roles.append(role)
        return object()


class _MalformedFirstProducerBackend(_PassingBackend):
    def __init__(self) -> None:
        super().__init__()
        self._producer_calls = 0

    def execute(self, role, agent, context, schema, reservation):  # type: ignore[no-untyped-def]
        if role == "producer":
            self._producer_calls += 1
            if self._producer_calls == 1:
                self.roles.append(role)
                return L4DispatchResultV1(
                    b"{}\n",
                    "test-provider",
                    "test-model",
                    "2026-08-31T12:00:00Z",
                    "2026-08-31T12:00:01Z",
                    1000,
                    token_status="trusted_exact",
                    billable_tokens=5,
                    active_status="trusted_exact",
                    active_ms=1000,
                )
        return super().execute(role, agent, context, schema, reservation)


class _AlwaysMalformedProducerBackend(_PassingBackend):
    def execute(self, role, _agent, _context, _schema, _reservation):  # type: ignore[no-untyped-def]
        self.roles.append(role)
        return L4DispatchResultV1(
            b"{}\n",
            "test-provider",
            "test-model",
            "2026-08-31T12:00:00Z",
            "2026-08-31T12:00:01Z",
            1000,
            token_status="trusted_exact",
            billable_tokens=5,
            active_status="trusted_exact",
            active_ms=1000,
        )


class _RepairThenPassBackend(_PassingBackend):
    def __init__(self) -> None:
        super().__init__()
        self._producer_calls = 0
        self._verifier_calls = 0

    def execute(self, role, _agent, _context, _schema, _reservation):  # type: ignore[no-untyped-def]
        self.roles.append(role)
        entry, spec, _evidence, original = _candidate_fixture()
        repaired = replace(
            original, rendered_markdown="Authenticated exhaustive evidence after repair."
        )
        if role == "producer":
            self._producer_calls += 1
            value = original if self._producer_calls == 1 else repaired
        else:
            self._verifier_calls += 1
            candidate = original if self._verifier_calls == 1 else repaired
            diagnostics = ()
            verdict = "PASS"
            if self._verifier_calls == 1:
                verdict = "REPAIR"
                diagnostics = (
                    ExhaustiveDiagnosticV1(
                        1,
                        candidate.identity,
                        entry.verifier_contract_hash,
                        "invalid-or-insufficient-evidence",
                        candidate.covered_primary_subject_ids,
                        candidate.covered_primary_evidence_ids,
                        (),
                        "The first attempt needs stronger evidence explanation.",
                    ),
                )
            value = ExhaustiveVerificationV1(
                1,
                spec.identity,
                candidate.identity,
                entry.verifier_contract_hash,
                verdict,
                diagnostics,
                candidate.covered_primary_evidence_ids,
                candidate.addressed_finding_ids,
            )
        return L4DispatchResultV1(
            canonical_json_bytes(value.to_json_dict()),
            "test-provider",
            "test-model",
            "2026-08-31T12:00:00Z",
            "2026-08-31T12:00:01Z",
            1000,
            token_status="trusted_exact",
            billable_tokens=5,
            active_status="trusted_exact",
            active_ms=1000,
        )


@pytest.mark.unit
def test_exact_child_is_published_once_then_reused(tmp_path: Path) -> None:
    manifest, inputs = _fixture("re-l4-exact")

    first = create_or_reuse_protocol_28_child(tmp_path, inputs)
    before = (first / "v2" / "run.json").read_bytes()
    second = create_or_reuse_protocol_28_child(tmp_path, inputs)

    assert first == second
    assert (second / "v2" / "run.json").read_bytes() == before
    assert find_exact_protocol_28_child(
        tmp_path, manifest.exhaustive_request.request_id
    ) == first
    assert (tmp_path / "runs" / ".current-re").read_text(encoding="utf-8") == (
        "re-l4-exact\n"
    )


@pytest.mark.unit
def test_child_is_not_visible_before_manifest_publication(tmp_path: Path) -> None:
    _manifest, inputs = _fixture("re-l4-crash")

    def crash(point: str) -> None:
        if point == "before_manifest_publish":
            raise RuntimeError("stop-before-manifest")

    with pytest.raises(RuntimeError, match="stop-before-manifest"):
        create_or_reuse_protocol_28_child(tmp_path, inputs, fault_hook=crash)

    assert not (tmp_path / "runs" / "re-l4-crash").exists()
    assert find_exact_protocol_28_child(
        tmp_path, inputs.manifest.exhaustive_request.request_id
    ) is None
    assert not (tmp_path / "runs" / ".current-re").exists()


@pytest.mark.unit
def test_exact_child_lookup_rejects_duplicate_authority(tmp_path: Path) -> None:
    _manifest, inputs = _fixture("re-l4-first")
    create_or_reuse_protocol_28_child(tmp_path, inputs)
    duplicate_manifest = replace(inputs.manifest, run_id="re-l4-duplicate")
    duplicate_inputs = replace(inputs, manifest=duplicate_manifest)
    stage = tmp_path / "runs" / ".re-l4-duplicate.stage"
    duplicate = tmp_path / "runs" / "re-l4-duplicate"
    stage_exhaustive_inputs(stage, duplicate_inputs)
    publish_protocol_28_run(stage, duplicate, duplicate_manifest)

    with pytest.raises(Protocol28LifecycleError, match="multiple protocol-2.8"):
        find_exact_protocol_28_child(
            tmp_path, inputs.manifest.exhaustive_request.request_id
        )


@pytest.mark.unit
def test_higher_budget_reuses_semantic_child_instead_of_retargeting(tmp_path: Path) -> None:
    manifest, inputs = _fixture("re-l4-budget")
    first = create_or_reuse_protocol_28_child(tmp_path, inputs)
    raised = replace(
        inputs,
        manifest=replace(
            manifest,
            budget_policy=replace(manifest.budget_policy, token_limit=800_000),
        ),
    )

    reused = create_or_reuse_protocol_28_child(tmp_path, raised)

    assert reused == first
    assert (
        find_exact_protocol_28_child(
            tmp_path, manifest.exhaustive_request.request_id
        )
        == first
    )


@pytest.mark.unit
def test_exhaustive_runner_accepts_pair_builds_root_and_replays_zero_call(
    tmp_path: Path,
) -> None:
    _manifest, inputs = _fixture("re-l4-live")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _PassingBackend()

    completed = run_protocol_28_exhaustive(run_dir, lambda: backend)
    calls_after_completion = tuple(backend.roles)
    replayed = run_protocol_28_exhaustive(run_dir, lambda: backend)

    assert completed.state == "evidence_complete"
    assert completed.accepted_slices == completed.planned_slices == 1
    assert completed.run_root_id is not None
    assert calls_after_completion == ("producer", "verifier")
    assert tuple(backend.roles) == calls_after_completion
    assert replayed.run_root_id == completed.run_root_id


@pytest.mark.unit
def test_completed_slice_is_exported_as_an_authentic_v2_checkpoint(
    tmp_path: Path,
) -> None:
    _manifest, inputs = _fixture("re-l4-exported")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)

    completed = run_protocol_28_exhaustive(run_dir, lambda: _PassingBackend())
    index, manifests, quarantine = load_checkpoint_cache_v2(tmp_path)

    assert completed.accepted_slices == 1
    assert len(index.entries) == len(manifests) == 1
    assert quarantine == ()
    checkpoint = next(iter(manifests.values()))
    assert checkpoint.origin_run_id == run_dir.name
    assert checkpoint.plan_entry in inputs.exhaustive_plan.target_plans[0].entries
    assert checkpoint.origin_manifest_hash in checkpoint.immutable_object_hashes
    assert checkpoint.origin_event_prefix_hash in checkpoint.immutable_object_hashes
    assert checkpoint.origin_ledger_prefix_hash in checkpoint.immutable_object_hashes


@pytest.mark.unit
def test_exported_checkpoint_adoption_survives_origin_and_cache_removal(
    tmp_path: Path,
) -> None:
    from harness.re_v2.ledger import ObjectStore

    origin_workspace = tmp_path / "origin-workspace"
    sibling_workspace = tmp_path / "sibling-workspace"
    origin_workspace.mkdir()
    sibling_workspace.mkdir()
    _manifest, origin_inputs = _fixture("re-l4-origin")
    origin_run = create_or_reuse_protocol_28_child(origin_workspace, origin_inputs)
    run_protocol_28_exhaustive(origin_run, lambda: _PassingBackend())
    _index, manifests, _quarantine = load_checkpoint_cache_v2(origin_workspace)
    checkpoint = next(iter(manifests.values()))
    origin_store = ObjectStore(origin_run / "v2" / "objects")
    checkpoint_objects = {
        object_id: origin_store.read_blob(object_id)
        for object_id in checkpoint.immutable_object_hashes
    }
    selection = CheckpointSelectionBundleV2(
        2,
        (
            CheckpointSelectionEntryV2(
                checkpoint.slice_spec.output_artifact_key_id,
                checkpoint.identity,
                checkpoint.accepted_slice.identity,
            ),
        ),
        (),
        (),
        (),
    )
    _sibling_manifest, sibling_inputs = _fixture("re-l4-sibling")
    sibling_run = create_or_reuse_protocol_28_child(
        sibling_workspace,
        sibling_inputs,
        checkpoint_adoption=Protocol28CheckpointAdoptionV1(
            selection,
            {checkpoint.identity: checkpoint},
            {checkpoint.identity: checkpoint_objects},
        ),
    )
    backend = _PassingBackend()

    completed = run_protocol_28_exhaustive(sibling_run, lambda: backend)
    shutil.rmtree(origin_workspace)
    replayed = run_protocol_28_exhaustive(sibling_run, lambda: backend)

    assert completed.state == replayed.state == "evidence_complete"
    assert completed.run_root_id == replayed.run_root_id
    assert backend.roles == []
    _index, sibling_manifests, _quarantine = load_checkpoint_cache_v2(
        sibling_workspace
    )
    assert any(
        item.origin_run_id == sibling_run.name
        for item in sibling_manifests.values()
    )


@pytest.mark.unit
def test_selected_v2_checkpoint_is_adopted_before_any_provider_dispatch(
    tmp_path: Path,
) -> None:
    _manifest, inputs = _fixture("re-l4-adopted")
    checkpoint, _expectation, objects, _store = _checkpoint(tmp_path / "origin")
    old_policy = checkpoint.artifact_policy_catalog_id
    new_policy = inputs.parent_authority_bundle.inherited_artifact_policy_catalog_id
    checkpoint_objects = dict(objects)
    checkpoint_objects.pop(old_policy)
    checkpoint_objects[new_policy] = inputs.authority_objects[new_policy]
    inventory = tuple(sorted(checkpoint_objects))
    checkpoint = replace(
        checkpoint,
        artifact_policy_catalog_id=new_policy,
        immutable_object_hashes=inventory,
        immutable_object_byte_counts={
            key: len(value) for key, value in checkpoint_objects.items()
        },
    )
    selection = CheckpointSelectionBundleV2(
        2,
        (
            CheckpointSelectionEntryV2(
                checkpoint.slice_spec.output_artifact_key_id,
                checkpoint.identity,
                checkpoint.accepted_slice.identity,
            ),
        ),
        (),
        (),
        (),
    )
    adoption = Protocol28CheckpointAdoptionV1(
        selection,
        {checkpoint.identity: checkpoint},
        {checkpoint.identity: checkpoint_objects},
    )

    run_dir = create_or_reuse_protocol_28_child(
        tmp_path, inputs, checkpoint_adoption=adoption
    )
    backend = _PassingBackend()
    completed = run_protocol_28_exhaustive(run_dir, lambda: backend)

    assert completed.state == "evidence_complete"
    assert backend.roles == []


@pytest.mark.unit
def test_resource_blocked_child_resumes_after_monotonic_authorization(
    tmp_path: Path,
) -> None:
    manifest, inputs = _fixture("re-l4-resume")
    constrained = replace(
        inputs,
        manifest=replace(
            manifest,
            budget_policy=replace(manifest.budget_policy, token_limit=10),
        ),
    )
    run_dir = create_or_reuse_protocol_28_child(tmp_path, constrained)
    backend = _PassingBackend()

    paused = run_protocol_28_exhaustive(run_dir, lambda: backend)
    resumed = continue_protocol_28_run(
        run_dir,
        token_limit=400_000,
        active_ms_limit=None,
        provider_factory=lambda: backend,
    )

    assert paused.state == "resource_blocked"
    assert paused.reason_code == "l4_tokens_budget_exhausted"
    assert resumed.state == "evidence_complete"
    assert backend.roles == ["producer", "verifier"]


@pytest.mark.unit
def test_restart_parses_durable_producer_capture_before_replacement_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.protocol_28.lifecycle as lifecycle

    _manifest, inputs = _fixture("re-l4-capture-recovery")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _PassingBackend()
    original = lifecycle.record_candidate_result
    crashed = False

    def crash_before_parse(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("crash-after-capture")
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "record_candidate_result", crash_before_parse)
    with pytest.raises(RuntimeError, match="crash-after-capture"):
        run_protocol_28_exhaustive(run_dir, lambda: backend)
    monkeypatch.setattr(lifecycle, "record_candidate_result", original)

    recovered = run_protocol_28_exhaustive(run_dir, lambda: backend)

    assert recovered.state == "evidence_complete"
    assert backend.roles == ["producer", "verifier"]


@pytest.mark.unit
def test_restart_projects_durable_acceptance_before_root_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.protocol_28.lifecycle as lifecycle

    _manifest, inputs = _fixture("re-l4-acceptance-recovery")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _PassingBackend()
    original = lifecycle._record_acceptance_events
    crashed = False

    def crash_after_acceptance(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("crash-after-acceptance")
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "_record_acceptance_events", crash_after_acceptance)
    with pytest.raises(RuntimeError, match="crash-after-acceptance"):
        run_protocol_28_exhaustive(run_dir, lambda: backend)
    monkeypatch.setattr(lifecycle, "_record_acceptance_events", original)

    recovered = run_protocol_28_exhaustive(run_dir, lambda: backend)

    assert recovered.state == "evidence_complete"
    assert backend.roles == ["producer", "verifier"]


@pytest.mark.unit
def test_restart_parses_durable_verifier_capture_without_duplicate_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.protocol_28.lifecycle as lifecycle

    _manifest, inputs = _fixture("re-l4-verifier-recovery")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _PassingBackend()
    original = lifecycle.record_verification_result
    crashed = False

    def crash_before_parse(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("crash-after-verifier-capture")
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "record_verification_result", crash_before_parse)
    with pytest.raises(RuntimeError, match="crash-after-verifier-capture"):
        run_protocol_28_exhaustive(run_dir, lambda: backend)
    monkeypatch.setattr(lifecycle, "record_verification_result", original)

    recovered = run_protocol_28_exhaustive(run_dir, lambda: backend)

    assert recovered.state == "evidence_complete"
    assert backend.roles == ["producer", "verifier"]


@pytest.mark.unit
def test_malformed_verifier_uses_one_fresh_retry_without_regenerating_candidate(
    tmp_path: Path,
) -> None:
    _manifest, inputs = _fixture("re-l4-verifier-retry")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _MalformedFirstVerifierBackend()

    completed = run_protocol_28_exhaustive(run_dir, lambda: backend)

    assert completed.state == "evidence_complete"
    assert backend.roles == ["producer", "verifier", "verifier"]


@pytest.mark.unit
def test_verifier_retry_resource_pause_resumes_without_regenerating_candidate(
    tmp_path: Path,
) -> None:
    _manifest, inputs = _fixture("re-l4-verifier-retry-pause")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _UnaccountedMalformedFirstVerifierBackend()

    paused = run_protocol_28_exhaustive(run_dir, lambda: backend)
    resumed = continue_protocol_28_run(
        run_dir,
        token_limit=None,
        active_ms_limit=900_000,
        provider_factory=lambda: backend,
    )

    assert paused.state == "resource_blocked"
    assert paused.reason_code == "l4_active_ms_budget_exhausted"
    assert resumed.state == "evidence_complete"
    assert backend.roles == ["producer", "verifier", "verifier"]


@pytest.mark.unit
def test_invalid_backend_result_abandons_dispatch_and_blocks_truthfully(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context

    _manifest, inputs = _fixture("re-l4-invalid-backend-result")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _InvalidResultBackend()

    with pytest.raises(Protocol28LifecycleError, match="invalid result"):
        run_protocol_28_exhaustive(run_dir, lambda: backend)

    context = load_protocol_28_run_context(run_dir)
    projection = context.controller.rebuild_projection()
    assert projection.lifecycle_state == "execution_blocked"
    assert context.resources.decision.open_token_reservations == 0


@pytest.mark.unit
def test_malformed_producer_consumes_attempt_and_releases_paired_verifier(
    tmp_path: Path,
) -> None:
    manifest, inputs = _fixture("re-l4-producer-retry")
    inputs = replace(
        inputs,
        manifest=replace(
            manifest,
            budget_policy=replace(
                manifest.budget_policy, active_ms_limit=1_200_000
            ),
        ),
    )
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _MalformedFirstProducerBackend()

    completed = run_protocol_28_exhaustive(run_dir, lambda: backend)

    assert completed.state == "evidence_complete"
    assert backend.roles == ["producer", "producer", "verifier"]


@pytest.mark.unit
def test_terminal_slice_failure_keeps_one_original_reason_on_replay(
    tmp_path: Path,
) -> None:
    manifest, inputs = _fixture("re-l4-terminal-failure")
    inputs = replace(
        inputs,
        manifest=replace(
            manifest,
            budget_policy=replace(
                manifest.budget_policy, active_ms_limit=1_200_000
            ),
        ),
    )
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _AlwaysMalformedProducerBackend()

    first = run_protocol_28_exhaustive(run_dir, lambda: backend)
    second = run_protocol_28_exhaustive(run_dir, lambda: backend)
    events = load_protocol_28_run_context(run_dir).events.replay()
    failures = [event for event in events if event.type == "slice_failed"]

    assert first.reason_code == second.reason_code == (
        "semantic_repair_attempts_exhausted"
    )
    assert len(failures) == 1
    assert failures[0].payload["reason_code"] == first.reason_code


@pytest.mark.unit
def test_semantic_repair_generates_only_same_slice_then_passes(tmp_path: Path) -> None:
    manifest, inputs = _fixture("re-l4-semantic-repair")
    inputs = replace(
        inputs,
        manifest=replace(
            manifest,
            budget_policy=replace(
                manifest.budget_policy, active_ms_limit=1_200_000
            ),
        ),
    )
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _RepairThenPassBackend()

    completed = run_protocol_28_exhaustive(run_dir, lambda: backend)

    assert completed.state == "evidence_complete"
    assert backend.roles == ["producer", "verifier", "producer", "verifier"]
