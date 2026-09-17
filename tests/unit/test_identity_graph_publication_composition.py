"""Fixture composition of immutable graph/source publication and the real journal.

No production staging protocol, semantic approval, memory audit acquisition, or
controller completion authority is provided by these tests.
"""

from contextlib import closing
from dataclasses import dataclass, replace
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import stat

import pytest

from echelon.spec_graph import GraphEdge, render_spec_graph
from echelon.spec_graph_captured import CapturedGraphMemory, build_captured_identity_graph
from echelon.spec_graph_memory import GraphMemoryAudit, GraphMemorySource
from echelon.spec_memory_miner import plan_canonical_requirement_drawers
from harness.element_artifacts import parse_identity_artifact
from harness.element_identity_bindings import ReferenceClaim
from harness.element_identity_candidate import IdentityEditScope
from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources
from harness.element_identity_lifecycle import ElementCreate, ElementRevision
from harness.element_identity_publication import (
    PublicationIntentRequest, PublicationOperation, PublicationSourceClaim,
    decode_publication_request, encode_publication_request,
)
from harness.element_identity_request_codec import encode_request
from harness.element_identity_snapshot import IdentityHistorySnapshot
from harness.element_identity_store import IdentityStore, IdentityStoreError
from harness.squad_publication import (
    PreparedSquadPublication, PublicationError, SquadPublicationTransaction, load_prepared_publication,
)
from harness.squad_source_baseline_codec import (
    decode_initial_publication_sources, encode_initial_publication_sources,
)
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_projection import ProjectedPublicationSources, project_publication_source_images
from harness.squad_source_snapshot import PublicationSourcesSnapshot
from tests.unit.test_squad_source_projection_images import secure_posix


pytestmark = pytest.mark.unit

SPEC = "specs/demo/spec.md"
GRAPH = "specs/demo/spec-artifact-graph.json"
EVIDENCE = "specs/demo/evidence/verify.md"
BINARY = "specs/demo/.retained.bin"
BEFORE = b"- **FR-000001**: Move using WASD.\n"
AFTER = b"- **FR-000001**: Move using arrow keys.\n"
EVIDENCE_BYTES = b"See FR-000001.\n"
BINARY_BYTES = b"\x00\xffretained"
DATABASE = ".echelon/identity/registry.sqlite3"
COMPLETION = "fixture-only guarded exit; not authenticated squad completion"


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _sql_state(project):
    with closing(sqlite3.connect(project / DATABASE)) as connection:
        return tuple(connection.iterdump())


def _counts(project):
    with closing(sqlite3.connect(project / DATABASE)) as connection:
        return {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("reservations", "entities", "revisions", "reference_claims",
                              "source_publications", "publication_intents")}


def _graph(sources, history):
    content = next(item.content for tree in sources.trees for item in tree.files if item.path == SPEC)
    assert content == AFTER
    rows = tuple(plan_canonical_requirement_drawers(
        content, source=SPEC, wing="composition-test-wing",
        artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + _sha(content)},
    ))
    # Deterministic supplied observation only: no collection was queried or written.
    audit = GraphMemoryAudit("returned", 1, "composition-test-wing", "pass", 1, 1, 1,
                             (), (), (), (), (), (), (), ())
    result = build_captured_identity_graph(
        spec_id="demo", lifecycle="phase_a", generator_version="composition-test",
        sources=sources, policy_paths=(EVIDENCE,),
        memory=(CapturedGraphMemory("canonical-spec", (GraphMemorySource(SPEC, content, "requirement", ""),), rows, audit),),
        re_artifacts=(), re_sources=(), history=history,
    )
    requirement = next(node for node in result.nodes if node.id == "req:demo:FR-000001")
    assert requirement.properties["identity"]["revision"] == "2"
    old = next(node for node in result.nodes if node.type == "ElementRevision" and node.properties["revision"] == "1")
    claim, = (node for node in result.nodes if node.type == "ReferenceClaim")
    assert claim.properties["target_revision_matches_current"] is False
    assert GraphEdge(claim.id, "ASSESSES_REVISION", old.id, {}) in result.edges
    return render_spec_graph(result)


def _preview(project, store, initial, operations, *, graph=False):
    before = _sql_state(project)
    assembled = assemble_candidate_sources(
        initial, (CandidateSourceBinding(SPEC, SPEC, "requirements"),
                  CandidateSourceBinding(EVIDENCE, EVIDENCE, "evidence")),
        writable_paths=(SPEC, GRAPH) if graph else (SPEC,),
        opaque_write_paths=(GRAPH,) if graph else (),
    )
    assert assembled.diagnostics == ()
    preview = store.preview_identity_candidate(
        spec_id="demo", artifacts=assembled.artifacts,
        scope=IdentityEditScope((SPEC,), ("FR-000001",)), operations=operations,
    )
    assert preview.check.diagnostics == () and preview.history is not None
    reference, = preview.check.references
    assert (reference.target_id, reference.assessed_revisions, reference.assessment_state) == (
        "FR-000001", ("1",), "historical")
    assert _sql_state(project) == before
    return preview


def _seal(project, transaction_id, writes):
    transaction = SquadPublicationTransaction.begin(project, project / "runs/spec-test", transaction_id)
    stages = {}
    for target, content in writes:
        stage = transaction.build_path(Path(target).name)
        stage.write_bytes(content)
        stage.chmod(0o640)
        transaction.add_write(Path(target), stage, owned_paths={Path(target)})
        stages[target] = stage
    return transaction.seal(), stages


@dataclass
class Composition:
    project: Path
    store: IdentityStore
    prepared: PreparedSquadPublication
    initial: PublicationSourcesSnapshot
    projected: ProjectedPublicationSources
    history: IdentityHistorySnapshot
    old_history: IdentityHistorySnapshot
    registration: dict
    request: PublicationIntentRequest
    graph: bytes
    stages: dict
    provisional: PreparedSquadPublication


def _composition(tmp_path):
    project = tmp_path.resolve()
    store = IdentityStore.initialize(project)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    assert label == "FR-000001" and type(label) is str
    old, = parse_identity_artifact(path=SPEC, role="requirements", text=BEFORE.decode()).declarations
    new, = parse_identity_artifact(path=SPEC, role="requirements", text=AFTER.decode()).declarations
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(ElementCreate(label, "Movement", old.content, "reserve"),))
    reference, = parse_identity_artifact(path=EVIDENCE, role="evidence", text=EVIDENCE_BYTES.decode()).references
    assert (reference.target_id, reference.span.start, reference.span.end, reference.relation) == (label, 4, 13, "evidence")
    store.record_reference_claims(spec_id="demo", operation_id="old-evidence", claims=(
        ReferenceClaim(EVIDENCE, _sha(EVIDENCE_BYTES), "span:4:13", label, "1", reference.relation),))
    old_history = store.identity_history(spec_id="demo")
    (project / "runs/spec-test").mkdir(parents=True)
    (project / "specs/demo/evidence").mkdir(parents=True)
    (project / "specs/demo/empty").mkdir()
    for target, content in ((SPEC, BEFORE), (EVIDENCE, EVIDENCE_BYTES), (BINARY, BINARY_BYTES)):
        (project / target).write_bytes(content)
        (project / target).chmod(0o640)
    assert not (project / GRAPH).exists()
    operations = (PublicationOperation("lifecycle", "revise", encode_request("lifecycle", (
        ElementRevision(label, "1", "Movement", new.content),))),)

    # Never promoted, never assigned an identity intent, never unsealed or reused.
    provisional, _ = _seal(project, "11111111111111111111111111111111", ((SPEC, AFTER),))
    with provisional.inspect_sources(tree_paths=("specs/demo",)) as source_only:
        pass
    source_preview = _preview(project, store, source_only, operations)
    graph = _graph(project_publication_source_images(source_only), source_preview.history)

    prepared, stages = _seal(project, "22222222222222222222222222222222", ((SPEC, AFTER), (GRAPH, graph)))
    with prepared.inspect_sources(tree_paths=("specs/demo",)) as initial:
        pass
    assert initial.publication.promoted_prefix == 0
    assert snapshot_source_manifest(trees=initial.trees, files=initial.files) == snapshot_source_manifest(
        trees=source_only.trees, files=source_only.files)
    registration = store.register_source_context(
        spec_id="demo", context_id="test-source", operation_id="source-registration",
        manifest=snapshot_source_manifest(trees=initial.trees, files=initial.files),
    )
    preview = _preview(project, store, initial, operations, graph=True)
    assert preview.history == source_preview.history
    projected = project_publication_source_images(initial)
    assert _graph(projected, preview.history) == graph
    assert next(item.content for tree in projected.trees for item in tree.files if item.path == GRAPH) == graph
    assert next(op.postimage_bytes for op in initial.publication.operations if op.target == GRAPH) == graph
    request = PublicationIntentRequest(
        prepared.marker.manifest_sha256,
        "fixture-only recovery claim; not controller completion authority",
        operations,
        PublicationSourceClaim("test-source", "source-registration", encode_initial_publication_sources(initial)),
        proposed_history_sha256=preview.history.sha256,
    )
    assert json.loads(encode_publication_request(request))["version"] == "3"
    assert store.identity_history(spec_id="demo") == old_history
    return Composition(project, store, prepared, initial, projected, preview.history,
                       old_history, registration, request, graph, stages, provisional)


def _prepare(case):
    result = case.store.prepare_identity_publication(spec_id="demo", operation_id="publish-revision", request=case.request)
    assert case.store.prepare_identity_publication(spec_id="demo", operation_id="publish-revision", request=case.request) == result
    return result


def _assert_pending(case, state):
    pending = case.store.pending_identity_publication(spec_id="demo")
    assert pending == case.store.identity_publication(spec_id="demo", operation_id="publish-revision")
    assert pending["state"] == state and pending["completion_payload"] is None
    assert pending["request"] == encode_publication_request(case.request)
    assert decode_publication_request(pending["request"]) == case.request
    assert decode_initial_publication_sources(case.request.sources.baseline_payload) == case.initial
    if state == "prepared":
        assert pending["application_receipt"] is None
        assert case.store.identity_history(spec_id="demo") == case.old_history
        assert case.store.source_context(spec_id="demo", context_id="test-source") == case.registration
        assert _counts(case.project) == dict(reservations=1, entities=1, revisions=1, reference_claims=1,
                                             source_publications=1, publication_intents=1)
        with closing(sqlite3.connect(case.project / DATABASE)) as connection:
            assert connection.execute("SELECT sequence,application_sha256 FROM source_publications").fetchall() == [("1", None)]
    before = _sql_state(case.project)
    with pytest.raises(IdentityStoreError):
        case.store.reserve(spec_id="demo", kind="FR", operation_id="conflicting-reserve", count=1)
    with pytest.raises(IdentityStoreError):
        case.store.apply_lifecycle(spec_id="demo", operation_id="conflicting-revision", changes=(
            ElementRevision("FR-000001", "1" if state == "prepared" else "2", "Movement", "Conflict"),))
    assert _sql_state(case.project) == before
    return pending


def _assert_final(case, final, application, preparation):
    assert (case.project / SPEC).read_bytes() == AFTER
    assert (case.project / GRAPH).read_bytes() == case.graph
    assert (case.project / EVIDENCE).read_bytes() == EVIDENCE_BYTES
    assert (case.project / BINARY).read_bytes() == BINARY_BYTES
    assert list((case.project / "specs/demo/empty").iterdir()) == []
    assert final.publication.promoted_prefix == 2
    assert snapshot_source_manifest(trees=final.trees, files=final.files) == case.projected.manifest
    assert (final.trees, final.files) == (case.projected.trees, case.projected.files)
    for target in (SPEC, GRAPH, EVIDENCE, BINARY):
        assert stat.S_IMODE((case.project / target).stat().st_mode) == 0o640
    assert case.store.identity_history(spec_id="demo") == case.history
    assert IdentityStore.open(case.project).identity_history(spec_id="demo") == case.history
    history = json.loads(case.history.payload)
    assert [(r["element_id"], r["revision"], r["subject"], r["operation_id"]) for r in history["revisions"]] == [
        ("FR-000001", "1", "Movement", "create"), ("FR-000001", "2", "Movement", "revise")]
    assert history["reference_claims"] == json.loads(case.old_history.payload)["reference_claims"]
    assert history["reference_claims"][0]["target_revision"] == "1"
    expected_source = dict(case.registration, operation_id="publish-revision", sequence="1",
                           manifest={"payload": case.projected.manifest.payload, "sha256": case.projected.manifest.sha256})
    assert case.store.source_context(spec_id="demo", context_id="test-source") == expected_source
    assert application == {
        "version": "3", "identity_history_sha256": case.history.sha256, "publication": preparation,
        "operations": [{"method": "lifecycle", "operation_id": "revise", "receipt": [
            {"element_id": "FR-000001", "revision": "2", "status": "active", "lineage": []}]}],
        "sources": expected_source,
    }
    assert _counts(case.project) == dict(reservations=1, entities=1, revisions=2, reference_claims=1,
                                         source_publications=1, publication_intents=1)
    pending = _assert_pending(case, "applied")
    assert pending["application_receipt"] == json.dumps(application, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert _graph(case.projected, case.store.identity_history(spec_id="demo")) == case.graph


def _release_and_retry(case, application):
    before = _sql_state(case.project)
    assert case.store.apply_identity_publication(spec_id="demo", operation_id="publish-revision") == application
    assert _sql_state(case.project) == before
    release = case.store.release_identity_publication(
        spec_id="demo", operation_id="publish-revision", completion_payload=COMPLETION)
    after = _sql_state(case.project)
    reopened = IdentityStore.open(case.project)
    assert reopened.apply_identity_publication(spec_id="demo", operation_id="publish-revision") == application
    assert reopened.release_identity_publication(spec_id="demo", operation_id="publish-revision", completion_payload=COMPLETION) == release
    assert reopened.pending_identity_publication(spec_id="demo") is None
    assert reopened.identity_history(spec_id="demo") == case.history
    retained = reopened.identity_publication(spec_id="demo", operation_id="publish-revision")
    assert (retained["state"], retained["completion_payload"], retained["request"]) == (
        "released", COMPLETION, encode_publication_request(case.request))
    assert _sql_state(case.project) == after


def test_sealed_graph_and_sources_match_applied_identity_history(tmp_path, secure_posix):
    # Catch omitted physical graph promotion, wrong history association and evidence rebinding.
    case = _composition(tmp_path)
    preparation = _prepare(case)
    _assert_pending(case, "prepared")
    assert case.store.source_context(spec_id="demo", context_id="test-source") == case.registration
    applications = []

    def apply_after_sources(final):
        # Fixture owns the hook; real journal and publisher own all mutations.
        applications.append(case.store.apply_identity_publication(spec_id="demo", operation_id="publish-revision"))

    final = case.prepared.publish_sources(case.initial, after_publish=apply_after_sources)
    application, = applications
    _assert_final(case, final, application, preparation)
    _release_and_retry(case, application)


def _reopen_from_retained(project):
    """Recovery inputs come from the actual retained journal, not a current capture."""
    store = IdentityStore.open(project)
    pending = store.pending_identity_publication(spec_id="demo")
    request = decode_publication_request(pending["request"])
    initial = decode_initial_publication_sources(request.sources.baseline_payload)
    prepared = load_prepared_publication(project, project / "runs/spec-test", initial.publication.marker)
    return store, prepared, initial, request


def _assert_prefix(case, prefix):
    with case.prepared.inspect_sources(tree_paths=("specs/demo",)) as observed:
        assert observed.publication.promoted_prefix == prefix
    # Use the native order; graph may precede spec. Never turn this capture into a baseline.
    for index, operation in enumerate(case.initial.publication.operations):
        target = case.project / operation.target
        want = operation.postimage_bytes if index < prefix else operation.current_bytes
        assert (target.read_bytes() if target.exists() else None) == want
        assert case.stages[operation.target].read_bytes() == operation.postimage_bytes
        assert stat.S_IMODE(case.stages[operation.target].stat().st_mode) == operation.postimage.mode
    assert encode_initial_publication_sources(case.initial) == case.request.sources.baseline_payload
    # The provisional transaction is still a distinct intact seal, without an identity intent.
    assert case.provisional.marker != case.prepared.marker


def _resume_and_finish(case, preparation):
    store, prepared, initial, request = _reopen_from_retained(case.project)
    assert (initial, request, prepared.marker) == (case.initial, case.request, case.prepared.marker)
    case = replace(case, store=store, prepared=prepared, initial=initial, request=request)
    assert _prepare(case) == preparation
    applications = []
    final = prepared.publish_sources(initial, after_publish=lambda _: applications.append(
        store.apply_identity_publication(spec_id="demo", operation_id="publish-revision")))
    application, = applications
    _assert_final(case, final, application, preparation)
    _release_and_retry(case, application)
    return application


@pytest.mark.parametrize("position", [0, 1, 2], ids=["before-first", "after-first", "after-all-before-apply"])
def test_promotion_interruption_retains_exact_journal_and_resumes(tmp_path, secure_posix, position):
    # Catch partial promotion being mistaken for completion, or recovery reallocating history.
    case = _composition(tmp_path)
    preparation = _prepare(case)
    _assert_pending(case, "prepared")
    calls, applications = [], []

    def fault(boundary):
        calls.append(boundary)
        if boundary == position:
            raise RuntimeError("fixture promotion interruption")

    with pytest.raises(PublicationError, match="^publish_io$"):
        case.prepared.publish_sources(case.initial, fault_hook=fault, after_publish=lambda _: applications.append(
            case.store.apply_identity_publication(spec_id="demo", operation_id="publish-revision")))
    assert calls == list(range(position + 1)) and applications == []
    _assert_prefix(case, position)
    _assert_pending(case, "prepared")
    _resume_and_finish(case, preparation)


def test_failure_after_identity_apply_retains_pending_and_retries_exactly(tmp_path, secure_posix):
    # Catch treating a committed database effect as successful guarded publication.
    case = _composition(tmp_path)
    preparation = _prepare(case)
    applications = []

    def apply_then_fail(_):
        applications.append(case.store.apply_identity_publication(spec_id="demo", operation_id="publish-revision"))
        raise RuntimeError("fixture after application interruption")

    with pytest.raises(RuntimeError, match="^fixture after application interruption$"):
        case.prepared.publish_sources(case.initial, after_publish=apply_then_fail)
    application, = applications
    _assert_prefix(case, 2)
    with case.prepared.inspect_sources(tree_paths=("specs/demo",)) as observed:
        _assert_final(case, observed, application, preparation)
    assert _resume_and_finish(case, preparation) == application


def _exit_after_first_promotion(project_path, reached):
    project = Path(project_path)
    store, prepared, initial, _ = _reopen_from_retained(project)
    assert store.pending_identity_publication(spec_id="demo")["state"] == "prepared"

    def exit_at_boundary(position):
        if position == 1:
            reached.set()
            os._exit(73)  # Deliberately bypass Python unwinding and publisher cleanup.

    prepared.publish_sources(initial, fault_hook=exit_at_boundary)
    raise AssertionError("child unexpectedly completed publication")


def test_real_child_exit_after_first_promotion_recovers_from_persisted_material(tmp_path, secure_posix):
    # Catch reliance on exception unwinding, inherited Python objects or released locks.
    case = _composition(tmp_path)
    preparation = _prepare(case)
    context = multiprocessing.get_context("spawn")
    reached = context.Event()
    process = context.Process(target=_exit_after_first_promotion, args=(str(case.project), reached))
    process.start()
    try:
        assert reached.wait(10), "child did not reach first completed promotion"
        process.join(10)
        assert not process.is_alive() and process.exitcode == 73
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        process.close()
    store, prepared, initial, request = _reopen_from_retained(case.project)
    case = replace(case, store=store, prepared=prepared, initial=initial, request=request)
    _assert_prefix(case, 1)
    _assert_pending(case, "prepared")
    _resume_and_finish(case, preparation)


def _inventory(root):
    return {path.relative_to(root).as_posix(): (
        path.read_bytes() if path.is_file() else None, stat.S_IMODE(path.stat().st_mode))
        for path in root.rglob("*")}


@pytest.mark.parametrize("damage", ["evidence", "binary", "mode", "empty-directory-added",
                                     "empty-directory-removed", "preimage", "graph-stage-bytes", "graph-stage-mode"])
def test_native_source_or_seal_damage_blocks_before_apply_and_retains_material(tmp_path, secure_posix, damage):
    # Catch guards overlooking opaque dependencies, tree membership or the sealed graph itself.
    case = _composition(tmp_path)
    _prepare(case)
    _assert_pending(case, "prepared")
    if damage == "evidence":
        (case.project / EVIDENCE).write_bytes(b"changed evidence\n")
    elif damage == "binary":
        (case.project / BINARY).write_bytes(b"\x00\xfedrift")
    elif damage == "mode":
        (case.project / EVIDENCE).chmod(0o600)
    elif damage == "empty-directory-added":
        (case.project / "specs/demo/new-empty").mkdir()
    elif damage == "empty-directory-removed":
        (case.project / "specs/demo/empty").rmdir()
    elif damage == "preimage":
        (case.project / SPEC).write_bytes(b"changed canonical preimage\n")
    elif damage == "graph-stage-bytes":
        case.stages[GRAPH].write_bytes(b"damaged sealed graph\n")
    else:
        case.stages[GRAPH].chmod(0o600)
    inventory = _inventory(case.project)
    calls = []
    expected = "stage_corrupt" if damage.startswith("graph-stage-") else "target_drift"
    with pytest.raises(PublicationError, match=f"^{expected}$"):
        case.prepared.publish_sources(case.initial, before_publish=calls.append, after_publish=lambda _: calls.append(
            case.store.apply_identity_publication(spec_id="demo", operation_id="publish-revision")))
    assert calls == []
    assert not (case.project / GRAPH).exists()
    assert (case.project / SPEC).read_bytes() == (b"changed canonical preimage\n" if damage == "preimage" else BEFORE)
    _assert_pending(case, "prepared")
    assert all(stage.exists() for stage in case.stages.values())
    assert _inventory(case.project) == inventory


def test_post_apply_source_drift_fails_guarded_exit_and_recovery_without_release(tmp_path, secure_posix):
    # Catch post-hook source checks disappearing or recovery accepting a new dependency baseline.
    case = _composition(tmp_path)
    _prepare(case)
    applications = []

    def apply_then_drift(_):
        applications.append(case.store.apply_identity_publication(spec_id="demo", operation_id="publish-revision"))
        (case.project / EVIDENCE).write_bytes(b"post-apply evidence drift\n")

    with pytest.raises(PublicationError, match="^target_drift$"):
        case.prepared.publish_sources(case.initial, after_publish=apply_then_drift)
    application, = applications
    assert (case.project / SPEC).read_bytes() == AFTER and (case.project / GRAPH).read_bytes() == case.graph
    assert case.store.identity_history(spec_id="demo") == case.history
    assert case.store.source_context(spec_id="demo", context_id="test-source") == application["sources"]
    assert application["sources"]["sequence"] == "1"
    assert json.loads(_assert_pending(case, "applied")["application_receipt"]) == application
    store, prepared, initial, request = _reopen_from_retained(case.project)
    case = replace(case, store=store, prepared=prepared, initial=initial, request=request)
    before = _sql_state(case.project)
    inventory = _inventory(case.project)
    calls = []
    with pytest.raises(PublicationError, match="^target_drift$"):
        prepared.publish_sources(initial, after_publish=lambda _: calls.append(
            store.apply_identity_publication(spec_id="demo", operation_id="publish-revision")))
    assert calls == [] and _sql_state(case.project) == before
    assert _inventory(case.project) == inventory
    assert _assert_pending(case, "applied")["completion_payload"] is None
    assert _counts(case.project) == dict(reservations=1, entities=1, revisions=2, reference_claims=1,
                                         source_publications=1, publication_intents=1)


def test_stale_history_is_rejected_by_native_preparation_before_any_intent(tmp_path, secure_posix):
    # Catch preparation accepting an old complete-history claim after a real independent write.
    case = _composition(tmp_path)
    case.store.import_identities(spec_id="demo", operation_id="later-import", definitions=(("U-001", "Unknown"),))
    before = _sql_state(case.project)
    with pytest.raises(IdentityStoreError, match="proposed complete identity history differs"):
        _prepare(case)
    assert case.store.identity_publication(spec_id="demo", operation_id="publish-revision") is None
    assert case.store.pending_identity_publication(spec_id="demo") is None
    assert case.store.source_context(spec_id="demo", context_id="test-source") == case.registration
    assert _sql_state(case.project) == before
    _assert_prefix(case, 0)


def test_stale_source_head_is_rejected_by_native_preparation_before_intent(tmp_path, secure_posix):
    # Catch preparation overlooking a real accepted source predecessor advancement.
    case = _composition(tmp_path)
    noop, _ = _seal(case.project, "33333333333333333333333333333333", ())
    with noop.inspect_sources(tree_paths=("specs/demo",)) as initial:
        pass
    request = PublicationIntentRequest(noop.marker.manifest_sha256, "fixture source-head advance", (),
        PublicationSourceClaim("test-source", "source-registration", encode_initial_publication_sources(initial)))
    case.store.prepare_identity_publication(spec_id="demo", operation_id="source-only-advance", request=request)
    noop.publish_sources(initial, after_publish=lambda _: case.store.apply_identity_publication(
        spec_id="demo", operation_id="source-only-advance"))
    case.store.release_identity_publication(spec_id="demo", operation_id="source-only-advance", completion_payload=COMPLETION)
    head = case.store.source_context(spec_id="demo", context_id="test-source")
    assert (head["operation_id"], head["sequence"], head["manifest"]) == (
        "source-only-advance", "1", case.registration["manifest"])
    assert case.store.identity_history(spec_id="demo") == case.old_history
    before = _sql_state(case.project)
    with pytest.raises(IdentityStoreError, match="source predecessor or baseline differs"):
        _prepare(case)
    assert case.store.identity_publication(spec_id="demo", operation_id="publish-revision") is None
    assert case.store.pending_identity_publication(spec_id="demo") is None
    assert case.store.source_context(spec_id="demo", context_id="test-source") == head
    assert _sql_state(case.project) == before
    _assert_prefix(case, 0)
