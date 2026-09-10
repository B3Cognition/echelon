from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_discovery import DiscoveryBoundary, DiscoveryError
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.run_store import ReV2Paths
from tests.unit.test_re_v2_knowledge_discovery import _setup


def _request(boundary, binding, objects, paths=("worker.py",)):
    context = json.loads(boundary.provider_bytes(binding))
    inventory = {row["path"]: row for row in context["inventory"]}
    return boundary.admit(binding, canonical_json_bytes({
        "schema_version": 1, "kind": "evidence_requests", "source_id": "api",
        "requests": [{"obligation_id": context["origin_obligation_id"],
                      "reason_class": "missing-behavior",
                      "selector": {"source_id": "api", "path": path, "byte_start": 0,
                                   "byte_end": inventory.get(path, {}).get("byte_count", 1)}}
                     for path in paths],
    }))


def _phase_setup(tmp_path, files=None, fault=None, *, schema_version=2):
    _, _, _, _, args = _setup(tmp_path, files)
    paths = ReV2Paths.for_run(tmp_path / "re-test")
    paths.root.mkdir(parents=True)
    objects = ObjectStore(paths.objects)
    boundary = DiscoveryBoundary(*args[:5], objects, args[6])
    from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
    record = next(r for r in args[1].sources[0].files if r.source_relative_path == "app.py")
    binding = boundary.prepare(
        (EvidenceSelectorV1("api", "app.py", 0, record.byte_count),),
        schema_version=schema_version,
    )
    cls = importlib.import_module("harness.re_v2.knowledge_acquisition").DiscoveryAcquisition
    phase = cls(paths, boundary, binding, fault_hook=fault)
    return phase, paths, boundary, binding, objects, cls


def _use_historical_schema_1_expansion_defaults(monkeypatch, boundary):
    prepare = boundary.prepare
    verify_selection = boundary.verify_selection

    def historical_prepare(selectors, *, schema_version=1):
        return prepare(selectors, schema_version=1)

    def historical_verify(selectors, *, schema_version=1):
        return verify_selection(selectors, schema_version=1)

    monkeypatch.setattr(boundary, "prepare", historical_prepare)
    monkeypatch.setattr(boundary, "verify_selection", historical_verify)
    return prepare, verify_selection


@pytest.mark.unit
def test_reopen_preserves_a_committed_historical_schema_1_expansion(
    tmp_path, monkeypatch
):
    """Replaying a committed v1 revision must not reconstruct the v2 default."""
    phase, paths, boundary, binding, objects, cls = _phase_setup(
        tmp_path, schema_version=1
    )
    prepare, verify_selection = _use_historical_schema_1_expansion_defaults(
        monkeypatch, boundary
    )
    batch = _request(boundary, binding, objects)
    committed = phase.resolve(binding, batch)
    binding_bytes = objects.read_blob(committed.binding_id)
    binding_value = json.loads(binding_bytes)
    context_bytes = objects.read_blob(binding_value["context_id"])
    revision_bytes = objects.read_blob(committed.revision_id)
    ledger_bytes = phase.ledger.path.read_bytes()
    before = {
        path: path.read_bytes()
        for path in objects.root.rglob("*")
        if path.is_file()
    }
    assert binding_value["schema_version"] == 1
    monkeypatch.setattr(boundary, "prepare", prepare)
    monkeypatch.setattr(boundary, "verify_selection", verify_selection)

    reopened = cls(paths, boundary, binding)

    assert reopened.status() == committed
    assert reopened.provider_bytes() == phase.provider_bytes()
    assert objects.read_blob(committed.binding_id) == binding_bytes
    assert objects.read_blob(binding_value["context_id"]) == context_bytes
    assert objects.read_blob(committed.revision_id) == revision_bytes
    assert reopened.ledger.path.read_bytes() == ledger_bytes
    assert {
        path: path.read_bytes()
        for path in objects.root.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.unit
def test_recover_preserves_a_staged_historical_schema_1_expansion(
    tmp_path, monkeypatch
):
    """An unfinished v1 revision must commit its staged v1 binding, not upgrade."""
    def crash(name):
        if name == "context_staged":
            raise SimulatedCrash(name)

    phase, paths, boundary, binding, objects, cls = _phase_setup(
        tmp_path, fault=crash, schema_version=1
    )
    prepare, verify_selection = _use_historical_schema_1_expansion_defaults(
        monkeypatch, boundary
    )
    batch = _request(boundary, binding, objects)
    with pytest.raises(SimulatedCrash, match="context_staged"):
        phase.resolve(binding, batch)
    staged = []
    for path in objects.root.rglob("*"):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (isinstance(value, dict)
                and value.get("kind") == "private_discovery_binding"
                and value.get("schema_version") == 1
                and len(value.get("selectors", [])) == 2):
            staged.append((payload, value))
    assert len(staged) == 1
    expected_binding, expected_binding_value = staged[0]
    expected_binding_id = content_digest(expected_binding)
    expected_context_id = expected_binding_value["context_id"]
    expected_context = objects.read_blob(expected_context_id)
    assert objects.read_blob(expected_binding_id) == expected_binding
    assert objects.read_blob(expected_context_id) == expected_context
    before = {
        path: path.read_bytes()
        for path in objects.root.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(boundary, "prepare", prepare)
    monkeypatch.setattr(boundary, "verify_selection", verify_selection)

    recovered = cls(paths, boundary, binding).recover()

    assert recovered.binding_id == expected_binding_id
    assert json.loads(objects.read_blob(recovered.binding_id))["schema_version"] == 1
    assert objects.read_blob(expected_binding_id) == expected_binding
    assert objects.read_blob(expected_context_id) == expected_context
    assert {
        path: path.read_bytes()
        for path in objects.root.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.unit
def test_resolution_authenticates_requests_and_returns_safe_or_unknown_evidence(tmp_path):
    boundary, binding, _, objects, _ = _setup(tmp_path, {
        "app.py": "def run(): return 3\n", "worker.py": "def retry(): return False\n",
        ".env": "API_TOKEN=synthetic-acquisition-canary\n",
    })
    batch = _request(boundary, binding, objects, ("worker.py", "missing.py", ".env"))
    requests = boundary.read_requests(binding, batch)
    outcomes = [json.loads(objects.read_blob(boundary.resolve_request(binding, batch, row["request_id"])))
                for row in requests]
    by_path = {row["selector"]["path"]: row for row in outcomes}
    assert by_path["worker.py"]["disposition"] == "resolved"
    assert by_path["missing.py"]["reason_code"] == "unavailable-evidence"
    assert by_path[".env"]["reason_code"] == "excluded-path"
    assert by_path[".env"]["disposition"] == "unknown"
    projection = objects.read_blob(by_path["worker.py"]["projection_id"])
    assert b"def retry" in projection
    assert all(b"synthetic-acquisition-canary" not in objects.read_blob(row["projection_id"])
               for row in outcomes if row["projection_id"])


@pytest.mark.unit
def test_forged_staged_availability_is_rejected(tmp_path):
    boundary, binding, _, objects, _ = _setup(tmp_path)
    batch = _request(boundary, binding, objects, ("missing.py",))
    forged = json.loads(objects.read_blob(batch))
    forged["requests"][0].update(state="pending", reason_code=None)
    fake_id = objects.put_blob(canonical_json_bytes(forged))
    with pytest.raises(DiscoveryError, match="request-receipt-mismatch"):
        boundary.read_requests(binding, fake_id)


@pytest.mark.unit
def test_acquisition_is_cumulative_and_replays_completed_batches(tmp_path):
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path)
    batch = _request(boundary, binding, objects, ("worker.py", "missing.py"))
    first = phase.resolve(binding, batch)
    assert first.rounds == 1 and first.pending_id is None
    assert first.binding_id != binding
    context = json.loads(phase.provider_bytes())
    assert len(context["evidence"]) == 2
    assert any(row["reason_code"] == "unavailable-evidence" for row in context["evidence_request_outcomes"])
    reopened = cls(paths, boundary, binding)
    assert reopened.resolve(binding, batch) == first
    assert reopened.provider_bytes() == phase.provider_bytes()


@pytest.mark.unit
def test_third_expansion_is_denied_after_restart_without_budget_or_source_mutation(tmp_path):
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path)
    paths.events.write_bytes(b"existing shared reservations stay owned by the controller\n")
    source = tmp_path / "workspace" / "sources" / "api" / "app.py"
    # The pinned snapshot, not the source checkout, is read by acquisition.
    source_before = source.read_bytes()
    first = phase.resolve(binding, _request(boundary, binding, objects, ("worker.py",)))
    second = phase.resolve(first.binding_id, _request(boundary, first.binding_id, objects, ("missing.py",)))
    assert second.rounds == 2
    reopened = cls(paths, boundary, binding)
    with pytest.raises(DiscoveryError, match="evidence-expansion-limit"):
        reopened.resolve(second.binding_id, _request(boundary, second.binding_id, objects, ("other.py",)))
    assert reopened.status() == second
    assert paths.events.read_bytes() == b"existing shared reservations stay owned by the controller\n"
    assert source.read_bytes() == source_before


class SimulatedCrash(RuntimeError):
    pass


@pytest.mark.unit
@pytest.mark.parametrize("boundary_name", ["request_recorded", "outcome_staged", "outcome_recorded", "context_staged", "context_committed"])
def test_crash_recovery_keeps_one_round_and_never_reresolves_recorded_outcomes(tmp_path, boundary_name, monkeypatch):
    def crash(name):
        if name == boundary_name:
            raise SimulatedCrash(name)
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path, fault=crash)
    batch = _request(boundary, binding, objects, ("worker.py", "missing.py"))
    calls = []
    original = boundary.resolve_request
    def resolve(*args):
        calls.append(args[-1])
        return original(*args)
    monkeypatch.setattr(boundary, "resolve_request", resolve)
    with pytest.raises(SimulatedCrash):
        phase.resolve(binding, batch)
    reopened = cls(paths, boundary, binding)
    if boundary_name != "context_committed":
        assert reopened.status().binding_id == binding
        with pytest.raises(DiscoveryError, match="evidence-expansion-pending"):
            reopened.provider_bytes()
    recovered = reopened.recover()
    assert recovered.rounds == 1 and recovered.pending_id is None
    assert len(set(calls)) == 2
    # An orphan blob has no ledger authority and may be recomputed. Recorded
    # outcomes, unlike this staged-only blob, are never resolved twice.
    assert len(calls) == (3 if boundary_name == "outcome_staged" else 2)
    assert reopened.resolve(binding, batch) == recovered
    assert b"def retry" in reopened.provider_bytes()


@pytest.mark.unit
def test_live_checkout_changes_do_not_change_expansion_evidence(tmp_path):
    phase, _, boundary, binding, objects, _ = _phase_setup(tmp_path)
    checkout = tmp_path / "workspace" / "sources" / "api" / "worker.py"
    checkout.write_text("DO NOT SEND THIS LIVE CHECKOUT\n")
    phase.resolve(binding, _request(boundary, binding, objects))
    assert b"def retry" in phase.provider_bytes()
    assert b"DO NOT SEND" not in phase.provider_bytes()
    assert checkout.read_text() == "DO NOT SEND THIS LIVE CHECKOUT\n"


@pytest.mark.unit
def test_unknown_and_withheld_evidence_remain_visible_without_leaking_mapping_ids(tmp_path):
    phase, _, boundary, binding, objects, _ = _phase_setup(tmp_path, {
        "app.py": "def run(): return 3\n", ".env": "API_TOKEN=synthetic-acquisition-canary\n",
    })
    phase.resolve(binding, _request(boundary, binding, objects, (".env", "missing.py")))
    output = phase.provider_bytes()
    context = json.loads(output)
    assert {row["reason_code"] for row in context["evidence_request_outcomes"]} == {"excluded-path", "unavailable-evidence"}
    assert all(row["disposition"] == "unknown" for row in context["evidence_request_outcomes"])
    assert b"synthetic-acquisition-canary" not in output
    assert b"mapping_id" not in output and b"original_content_id" not in output


@pytest.mark.unit
def test_different_pending_batch_is_rejected_then_recovered(tmp_path):
    def crash(name):
        if name == "request_recorded":
            raise SimulatedCrash(name)
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path, fault=crash)
    with pytest.raises(SimulatedCrash):
        phase.resolve(binding, _request(boundary, binding, objects))
    reopened = cls(paths, boundary, binding)
    with pytest.raises(DiscoveryError, match="evidence-expansion-pending"):
        reopened.resolve(binding, _request(boundary, binding, objects, ("missing.py",)))
    assert reopened.recover().rounds == 1


@pytest.mark.unit
def test_stale_context_and_new_initial_binding_cannot_reset_rounds(tmp_path):
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path)
    first = phase.resolve(binding, _request(boundary, binding, objects))
    with pytest.raises(DiscoveryError, match="stale-discovery-binding"):
        phase.resolve(binding, _request(boundary, binding, objects, ("missing.py",)))
    with pytest.raises(DiscoveryError, match="discovery-opening-mismatch"):
        cls(paths, boundary, first.binding_id)
    assert cls(paths, boundary, binding).status() == first


@pytest.mark.unit
def test_completed_replay_does_not_invoke_the_resolver(tmp_path, monkeypatch):
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path)
    batch = _request(boundary, binding, objects)
    completed = phase.resolve(binding, batch)
    def forbidden(*args):
        pytest.fail("recorded evidence was resolved again")
    monkeypatch.setattr(boundary, "resolve_request", forbidden)
    reopened = cls(paths, boundary, binding)
    assert reopened.recover() == completed
    assert reopened.resolve(binding, batch) == completed


@pytest.mark.unit
def test_context_capacity_failure_retains_outcomes_without_activating_partial_context(tmp_path, monkeypatch):
    files = {"app.py": "def run(): return 3\n"}
    files.update({f"part{i}.txt": "x" * 65000 for i in range(5)})
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path, files)
    batch = _request(boundary, binding, objects, tuple(f"part{i}.txt" for i in range(5)))
    with pytest.raises(DiscoveryError, match="discovery-context-bound"):
        phase.resolve(binding, batch)
    assert phase.status().binding_id == binding
    assert phase.status().rounds == 1 and phase.status().pending_id is not None
    def forbidden(*args):
        pytest.fail("capacity recovery repeated a resolved request")
    monkeypatch.setattr(boundary, "resolve_request", forbidden)
    reopened = cls(paths, boundary, binding)
    with pytest.raises(DiscoveryError, match="discovery-context-bound"):
        reopened.recover()
    with pytest.raises(DiscoveryError, match="evidence-expansion-pending"):
        reopened.provider_bytes()


@pytest.mark.unit
@pytest.mark.parametrize("damage", ["context", "journal", "missing-outcome"])
def test_corrupt_durable_closure_fails_closed_without_reset(tmp_path, damage):
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path)
    phase.resolve(binding, _request(boundary, binding, objects))
    history, state = phase.ledger.replay_with_history()
    if damage == "journal":
        with phase.ledger.path.open("ab") as stream:
            stream.write(b'{"incomplete"')
    else:
        oid = state.context_id if damage == "context" else state.outcome_ids[0]
        target = objects._path(oid)
        if damage == "missing-outcome":
            target.unlink()
        else:
            target.chmod(0o600)
            target.write_bytes(b"tampered")
    before = phase.ledger.path.read_bytes()
    with pytest.raises(DiscoveryError):
        cls(paths, boundary, binding)
    assert phase.ledger.path.read_bytes() == before


@pytest.mark.unit
def test_acquisition_uses_the_existing_run_ownership_lock(tmp_path):
    import concurrent.futures
    import threading
    from harness.re_v2.protocol_22.recovery import protocol_22_run_lock
    phase, paths, boundary, binding, objects, _ = _phase_setup(tmp_path)
    batch = _request(boundary, binding, objects)
    entered, finished = threading.Event(), threading.Event()
    def run():
        entered.set()
        try:
            return phase.resolve(binding, batch)
        finally:
            finished.set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with protocol_22_run_lock(paths):
            future = pool.submit(run)
            assert entered.wait(2)
            assert not finished.wait(0.1)
            assert phase.status().rounds == 0
        assert future.result(timeout=10).rounds == 1


@pytest.mark.unit
@pytest.mark.parametrize("source_ids", [("api", "worker"), ("api", "API")])
def test_two_selected_sources_can_acquire_under_one_run_without_resetting_each_other(tmp_path, source_ids):
    from dataclasses import replace
    from echelon.workspace_model import WorkspaceInfo, WorkspaceManifest
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
    from harness.re_v2.protocol_22.partition import (
        ImplementationAuthorityV1, PartitionAuthoritiesV1, build_workspace_partition_catalog,
    )
    from harness.re_v2.workspace_snapshot import capture_workspace_snapshot
    from tests.unit.test_re_v2_workspace_snapshot import _clean_repo, _sources
    workspace = tmp_path / "workspace"
    repos = [_clean_repo(workspace / "sources" / name, {"app.py": "run()\n", "extra.py": "extra()\n"})
             for name in ("first", "second")]
    sources = tuple(replace(source, id=source_id) for source, source_id in zip(_sources(workspace, *repos), source_ids))
    snapshot = capture_workspace_snapshot(workspace, sources, tmp_path / "snapshots")
    manifest = WorkspaceManifest(schema_version=1, workspace=WorkspaceInfo(
        root=workspace.resolve(), git_role="orchestration", git_present=False), sources=sources)
    authority = ImplementationAuthorityV1(id="fixture", version="1", implementation_digest=content_digest(b"fixture"))
    partition = build_workspace_partition_catalog(snapshot, manifest, PartitionAuthoritiesV1(
        partitioner=authority, ownership_policy=authority))
    paths = ReV2Paths.for_run(tmp_path / "re-test")
    paths.root.mkdir(parents=True)
    objects, quarantine = ObjectStore(paths.objects), ObjectStore(tmp_path / "quarantine")
    cls = importlib.import_module("harness.re_v2.knowledge_acquisition").DiscoveryAcquisition
    phases = []
    for source in sources:
        origin = content_digest({"source": source.id, "obligation": "discovery"})
        boundary = DiscoveryBoundary(snapshot, partition, source.id, "standard", origin, objects, quarantine)
        binding = boundary.prepare((EvidenceSelectorV1(source.id, "app.py", 0, 6),))
        phase = cls(paths, boundary, binding)
        batch = boundary.admit(binding, canonical_json_bytes({
            "schema_version": 1, "kind": "evidence_requests", "source_id": source.id,
            "requests": [{"obligation_id": origin, "reason_class": "ownership",
                          "selector": EvidenceSelectorV1(source.id, "extra.py", 0, 8).to_json_dict()}],
        }))
        phase.resolve(binding, batch)
        phases.append(phase)
        changed_origin = DiscoveryBoundary(snapshot, partition, source.id, "standard",
                                           content_digest({"renamed": origin}), objects, quarantine)
        renamed_binding = changed_origin.prepare((EvidenceSelectorV1(source.id, "app.py", 0, 6),))
        with pytest.raises(DiscoveryError, match="discovery-opening-mismatch"):
            cls(paths, changed_origin, renamed_binding)
        assert phase.status().rounds == 1
    assert all(phase.status().rounds == 1 for phase in phases)
    assert phases[0].ledger.path != phases[1].ledger.path
    assert {phase.opening["budget_run_id"] for phase in phases} == {"re-test"}


@pytest.mark.unit
def test_each_replay_authenticates_a_request_batch_once_not_per_outcome(tmp_path, monkeypatch):
    phase, _, boundary, binding, objects, _ = _phase_setup(tmp_path)
    phase.resolve(binding, _request(boundary, binding, objects, ("worker.py", "missing.py")))
    calls = []
    original = boundary.read_requests
    def counted(binding_id, batch_id):
        calls.append(batch_id)
        return original(binding_id, batch_id)
    monkeypatch.setattr(boundary, "read_requests", counted)
    phase.status()
    # Authenticate the full base context once per batch in this replay. Each
    # outcome still independently verifies its selected pinned evidence bytes.
    assert len(calls) == 1
    phase.status()
    assert len(calls) == 2  # No cache survives into a later replay.


@pytest.mark.unit
def test_later_provider_input_rechecks_pinned_bytes_after_a_successful_replay(tmp_path):
    phase, _, boundary, binding, objects, _ = _phase_setup(tmp_path)
    phase.resolve(binding, _request(boundary, binding, objects))
    assert b"def retry" in phase.provider_bytes()
    captured = list((tmp_path / "snapshots").rglob("worker.py"))
    assert len(captured) == 1
    captured[0].chmod(0o600)
    captured[0].write_text("changed pinned evidence\n")
    before = phase.ledger.path.read_bytes()
    with pytest.raises(DiscoveryError):
        phase.provider_bytes()
    assert phase.ledger.path.read_bytes() == before


@pytest.mark.unit
def test_status_and_provider_input_validate_without_writing_evidence_objects(tmp_path, monkeypatch):
    phase, _, boundary, binding, objects, _ = _phase_setup(tmp_path)
    completed = phase.resolve(binding, _request(boundary, binding, objects))
    def forbidden(*args):
        pytest.fail("read-only replay tried to persist evidence")
    monkeypatch.setattr(objects, "put_blob", forbidden)
    assert phase.status() == completed
    assert b"def retry" in phase.provider_bytes()


@pytest.mark.unit
def test_repeat_against_expanded_context_reuses_evidence_without_spending_round(tmp_path, monkeypatch):
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path)
    completed = phase.resolve(binding, _request(boundary, binding, objects))
    repeated = _request(boundary, completed.binding_id, objects)
    def forbidden(*args):
        pytest.fail("identical evidence request was resolved again")
    monkeypatch.setattr(boundary, "resolve_request", forbidden)
    reopened = cls(paths, boundary, binding)
    assert reopened.resolve(completed.binding_id, repeated) == completed
    assert reopened.status().rounds == 1


@pytest.mark.unit
def test_mixed_batch_rebinds_reused_outcomes_and_resolves_only_new_requests(tmp_path, monkeypatch):
    phase, paths, boundary, binding, objects, cls = _phase_setup(tmp_path)
    completed = phase.resolve(binding, _request(boundary, binding, objects))
    batch = _request(boundary, completed.binding_id, objects, ("worker.py", "missing.py"))
    calls = []
    original = boundary.resolve_request
    def counted(binding_id, batch_id, request_id):
        calls.append(request_id)
        return original(binding_id, batch_id, request_id)
    monkeypatch.setattr(boundary, "resolve_request", counted)
    second = phase.resolve(completed.binding_id, batch)
    assert second.rounds == 2
    assert len(calls) == 1
    history, _ = phase.ledger.replay_with_history()
    assert len([r for r in history if r.type == "evidence_reused"]) == 1
    assert cls(paths, boundary, binding).recover() == second
    repeated = _request(boundary, second.binding_id, objects, ("worker.py", "missing.py"))
    assert phase.resolve(second.binding_id, repeated) == second  # Still reusable at the ceiling.


@pytest.mark.unit
def test_acquisition_namespace_syncs_both_parent_directory_entries(tmp_path, monkeypatch):
    from harness.re_v2 import knowledge_acquisition
    from harness.re_v2.ledger import _fsync_directory
    synced = []
    def sync(path):
        synced.append(path)
        _fsync_directory(path)
    monkeypatch.setattr(knowledge_acquisition, "_sync_directory", sync, raising=False)
    _, paths, _, _, _, _ = _phase_setup(tmp_path)
    assert paths.root in synced
    assert paths.root / "discovery" in synced


@pytest.mark.unit
def test_retrying_an_old_completed_batch_never_returns_a_stale_active_revision(tmp_path):
    phase, _, boundary, binding, objects, _ = _phase_setup(tmp_path)
    original_batch = _request(boundary, binding, objects)
    first = phase.resolve(binding, original_batch)
    second = phase.resolve(first.binding_id, _request(boundary, first.binding_id, objects, ("missing.py",)))
    assert phase.resolve(binding, original_batch) == second
    assert phase.status() == second
