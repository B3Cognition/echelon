"""Real completion owner with reviewed discovery; no public runtime admission."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from echelon.spec_lifecycle import PhaseAExecutionLock, SpecRunExecutionLock
from harness.element_identity_publication import encode_publication_request
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.prepared_phase_result import prepare_phase_result
from harness.squad import SquadController
from harness.squad_completion import CompletionError, load_prepared_spec_step_effects
from harness.squad_provider import SquadAgentResult
from harness.spec_step import load_prepared_spec_step, prepare_spec_step
from harness.squad_publication import PreparedSquadPublication
from harness.state_transaction_namespace import PENDING_SPEC_STEP_KEY
from harness.element_identity_store import IdentityStore
from tests.unit.test_discovery_publication import (
    case, enrolled, turn_prepared, prepared, execute, DiscoveryExecutor, prepare,
)
from tests.unit.test_discovery_turns import Interrupted


def _install_prepared_routed_completion(
    store,
    prepared_completion,
    *,
    token_usage_delta=0,
):
    """Install current spec-step authority around a sealed effect companion."""
    route = prepared_completion.intent.route
    from_phase = str(route["from_phase"])
    to_phase = str(route["to_phase"])
    prepared_result = prepare_phase_result(
        PhaseNode(id=from_phase, type="agent", allowed_state_updates=[]),
        SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        ),
        controller_updates={},
    )
    snapshot = store.capture_routing_snapshot(expected_phase=from_phase)
    transaction_updates = {
        "_spec_step_effect_plan": prepared_completion.marker.to_dict(),
    }
    publication = prepared_completion.intent.publication
    if publication["kind"] == "external":
        transaction_updates["_spec_step_publication_plan"] = publication["marker"]
    decision = store.prepare_routing_decision(
        prepared_result,
        snapshot=snapshot,
        from_phase=from_phase,
        to_phase=to_phase,
        judgment_payloads=[
            judgment["echelon_result"]
            for judgment in prepared_completion.intent.judgments
        ],
        manual_phase_run=bool(route["manual_phase_run"]),
        dispatch_id=prepared_completion.marker.completion_id,
        transaction_state_updates=transaction_updates,
        token_usage_delta=token_usage_delta,
    )
    final_state, _ = store.prepare_advance_postimage(
        from_phase,
        to_phase,
        decision,
    )
    final_state.pop("_spec_step_effect_plan", None)
    final_state.pop("_spec_step_publication_plan", None)
    dispatch = final_state["last_dispatch"]
    dispatch.pop("completion_intent_sha256", None)
    dispatch.pop("completion_origin", None)
    dispatch.pop("completion_publication_binding_sha256", None)
    dispatch["post_dispatch_complete"] = True
    dispatch["spec_step_id"] = prepared_completion.marker.completion_id
    dispatch["state_revision"] = decision.expected_state_revision + 2
    effects = list(prepared_completion.intent.effect_plan)
    publication_marker = None
    if publication["kind"] == "external":
        effects.insert(0, "publication")
        publication_marker = publication["marker"]
    step = prepare_spec_step(
        store.squad_dir,
        step_id=prepared_completion.marker.completion_id,
        origin="routed",
        expected_state_revision=decision.expected_state_revision,
        expected_previous_dispatch_sha256=decision.expected_previous_dispatch_sha256,
        route=prepared_completion.intent.route,
        effects=tuple(effects),
        publication=publication_marker,
        final_state=final_state,
        provenance={
            "completion_marker": prepared_completion.marker.to_dict(),
            "effect_intent": prepared_completion.intent.to_dict(),
            "prepared_result_sha256": decision.prepared_result.preparation_sha256,
            "routing_decision_sha256": decision.routing_sha256,
            "judgment_payload_sha256": list(decision.judgment_payload_sha256),
            "token_usage_delta": decision.token_usage_delta,
        },
    )
    store.begin_spec_step(step, snapshot=snapshot)


def controller(prepared, executor):
    root, state, _, _ = prepared
    repo = Path(__file__).resolve().parents[2]
    return SquadController(executor, state, PhaseGraph(repo / "runtime/workflow/definition.yaml"),
        repo, root, squad_dir=state.squad_dir)


def completion(prepared, executor, *, managed=True, request=None):
    package = prepare(prepared, executor)
    ctrl = controller(prepared, executor)
    extra = dict(managed_discovery_request=encode_publication_request(package.request) if request is None else request) if managed else {}
    sealed = ctrl._prepare_spec_step_effects(from_phase="phase1-discover", to_phase="phase1-what",
        snapshot=prepared[1].capture_routing_snapshot(expected_phase="phase1-discover"),
        manual_phase_run=False, conditional_skip=False, record_completion=True,
        publication_marker=package.publication.marker.to_dict(), completion_id="a" * 32, **extra)
    return ctrl, package, sealed


def drain(ctrl):
    with PhaseAExecutionLock.acquire(ctrl._project_root, "test-completion"):
        with SpecRunExecutionLock.acquire(ctrl._squad_dir, "test-completion"):
            return ctrl._drain_pending_spec_step()


def pending_spec_companion(ctrl):
    """Return the sealed compatibility view under spec-step authority."""
    state = ctrl._state_store.load()
    step = load_prepared_spec_step(
        ctrl._squad_dir,
        state[PENDING_SPEC_STEP_KEY],
    )
    marker = step.intent.provenance["completion_marker"]
    completion = load_prepared_spec_step_effects(
        ctrl._project_root,
        ctrl._squad_dir,
        marker,
    )
    return (
        ctrl._legacy_completion_effect_state(step, marker, completion),
        completion,
        step,
    )


def test_completion_retains_exact_reviewed_publication_and_read_set(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    before = prepared[1].load()
    ctrl, package, sealed = completion(prepared, executor)
    loaded = load_prepared_spec_step_effects(ctrl._project_root, ctrl._squad_dir, sealed.marker)
    assert loaded.intent.publication["managed_discovery"] == dict(version=1, request=encode_publication_request(package.request))
    assert loaded.marker.step == "awaiting_publication"
    assert len(executor.calls) == 3 and prepared[1].load() == before
    assert prepared[2].pending_identity_publication(spec_id="game") is None


@pytest.mark.parametrize("claim", ["parent", "child"])
def test_discovery_dispatch_cannot_acquire_restoration_continuation_authority(prepared, claim):
    from harness.discovery_completion import decode_binding
    from harness.element_identity_publication import PublicationContinuationClaim
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    package = prepare(prepared, executor)
    fields = (dict(continuation_id="discovery-restore-" + "a" * 32) if claim == "parent" else
        dict(continuation=PublicationContinuationClaim("other", "b" * 64, "c" * 64, "a" * 32, "d" * 64)))
    request = replace(package.request, **fields)
    with pytest.raises(CompletionError):
        decode_binding(dict(kind="external", marker=package.publication.marker.to_dict(),
            managed_discovery=dict(version=1, request=encode_publication_request(request))),
            completion_id="a" * 32, state=prepared[1].load())
    assert prepared[2].pending_identity_publication(spec_id="game") is None


def why2_envelope(prepared):
    """Closed shape fixture only; no accepted WHY2 operation or ancestry authority."""
    from dataclasses import asdict
    from harness.discovery_completion import _document, _json, _hash
    from harness.discovery_publication import _seal, _graph
    from harness.discovery_quality import capture_quality_policy
    from harness.element_identity_publication import PublicationSourceClaim
    from harness.element_identity_snapshot import IdentityHistorySnapshot
    from harness.squad_source_snapshot import PublicationSourcesSnapshot
    from harness.squad_source_baseline_codec import encode_initial_publication_sources
    from harness.squad_source_manifest import snapshot_source_manifest
    from tests.unit.test_managed_spec_contract import PASS_ISSUES, routing
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    package = prepare(prepared, executor)
    recovery = _document(package.request.recovery_payload)
    source = _document(recovery["source_inputs"])
    source["quality_policy"] = capture_quality_policy({"spec_authoring_mode": "proportional"})
    history = IdentityHistorySnapshot(**source["history"])
    artifacts = {"issues.md": PASS_ISSUES, "quality-gates.md": "## Verdict: PASS\n"}
    root, state_store = prepared[:2]
    writes = {"specs/game/" + name: text.encode() for name, text in artifacts.items()}
    provisional = _seal(root, state_store.squad_dir, writes, {})
    def capture(publication):
        with publication.inspect_sources(tree_paths=tuple(tree.path for tree in package.sources.trees),
                file_paths=tuple(item.path for item in package.sources.files)) as sources:
            return sources
    graph = _graph(capture(provisional), history, dict(spec_id="game", spec_path="specs/game"))
    writes["specs/game/spec-artifact-graph.json"] = graph
    publication = _seal(root, state_store.squad_dir, writes, {})
    sources = capture(publication)
    source["manifest"] = asdict(snapshot_source_manifest(trees=sources.trees, files=sources.files))
    parent = dict(dispatch_id="b" * 32, completion_intent_sha256="c" * 64,
        completion_receipts_sha256="d" * 64, completed_publication_binding_sha256="e" * 64)
    candidate = dict(artifacts=artifacts, proposal={"new_subjects": [], "revisions": []}, reservations=[], operations=[],
        history=asdict(history), routing=routing("why2"))
    operation = dict(binding={"operation_id": "why2-" + parent["dispatch_id"], "spec_id": "game", "run_id": "first",
        "intent": {"kind": "validate"}, "artifact_paths": list(artifacts), "fingerprint": _hash(source)},
        attempts=[{"result": {"status": "accepted", "candidate_sha256": _hash(candidate)}}])
    recovery.update(version=15, producer="why2", source_completion=parent, resolution=None, predecessor=None,
        operation=operation, candidate_inputs=_json(candidate), candidate_sha256=_hash(candidate),
        source_inputs=_json(source), source_fingerprint=_hash(source), review={"routing": routing("why2")},
        sources=encode_initial_publication_sources(sources), graph_sha256=hashlib.sha256(graph).hexdigest())
    spec, = (tree for tree in sources.trees if tree.path == "specs/game")
    request = replace(package.request, recovery_payload=_json(recovery), operations=(), proposed_history_sha256=history.sha256,
        manifest_sha256=publication.marker.manifest_sha256, sources=PublicationSourceClaim(package.request.sources.context_id,
            package.request.sources.expected_operation_id,
            encode_initial_publication_sources(PublicationSourcesSnapshot(sources.publication, (spec,), ()))))
    return publication, request


def test_only_exact_why2_root_can_declare_a_completion_restoration(prepared):
    from harness.discovery_completion import decode_binding
    publication, request = why2_envelope(prepared)
    def envelope(value):
        return dict(kind="external", marker=publication.marker.to_dict(),
            managed_discovery=dict(version=1, request=encode_publication_request(value)))
    # The fixture must be a valid ordinary closed envelope before adding a link.
    assert decode_binding(envelope(request), completion_id="a" * 32).producer == "why2"
    declared = replace(request, continuation_id="discovery-restore-" + "a" * 32)
    assert decode_binding(envelope(declared), completion_id="a" * 32).request == declared
    with pytest.raises(CompletionError):
        decode_binding(envelope(replace(request, continuation_id="discovery-restore-" + "f" * 32)), completion_id="a" * 32)
    # Closed shape grants neither an accepted provider operation nor ancestry.
    with pytest.raises(CompletionError):
        decode_binding(envelope(declared), completion_id="a" * 32, state=prepared[1].load())


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_existing_completion_owner_publishes_applies_and_releases(prepared, provider):
    executor = DiscoveryExecutor(provider)
    assert execute(prepared, executor, create=True).status == "reviewed"
    ctrl, package, sealed = completion(prepared, executor)
    _install_prepared_routed_completion(prepared[1], sealed, token_usage_delta=21)
    result = drain(ctrl)
    assert result.recovered, prepared[1].load()
    assert not result.blocked, prepared[1].load()
    state = prepared[1].load()
    assert state["phase"] == "phase1-what" and state["last_dispatch"]["post_dispatch_complete"] is True
    assert state["token_usage"] == 21
    assert "_spec_step_effect_plan" not in state and "_spec_step_publication_plan" not in state
    assert prepared[2].identity_history(spec_id="game") == package.candidate.history
    row = prepared[2].identity_publication(spec_id="game", operation_id="discovery-completion-" + sealed.marker.completion_id)
    assert row["state"] == "released" and row["completion_payload"]
    assert (prepared[0] / "specs/game/spec-artifact-graph.json").read_bytes() == package.graph
    assert not package.publication._transaction_root.exists() and not sealed._transaction_root.exists()
    assert len(executor.calls) == 3


def test_managed_run_cannot_use_ordinary_publication_drain(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    ctrl, _, sealed = completion(prepared, executor, managed=False)
    _install_prepared_routed_completion(prepared[1], sealed)
    outcome = drain(ctrl)
    assert outcome.recovered and outcome.blocked
    assert list((prepared[0] / "specs/game").iterdir()) == []
    assert prepared[2].identity_history(spec_id="game").payload != ""
    assert prepared[2].pending_identity_publication(spec_id="game") is None


def test_input_drift_blocks_before_publication_intent(prepared):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    ctrl, _, sealed = completion(prepared, executor)
    _install_prepared_routed_completion(prepared[1], sealed)
    (prepared[0] / ".echelon/constitution.md").write_text("Changed constraint")
    outcome = drain(ctrl)
    assert outcome.recovered and outcome.blocked
    assert list((prepared[0] / "specs/game").iterdir()) == []
    assert prepared[2].pending_identity_publication(spec_id="game") is None
    assert PENDING_SPEC_STEP_KEY in prepared[1].load() and len(executor.calls) == 3










@pytest.mark.parametrize("key", ["managed_identity", "managed_discovery_bootstrap", "managed_discovery_turns", "managed_discovery_operation"])
def test_any_managed_selection_requires_completion_association(key):
    from harness.discovery_completion import decode_binding
    with pytest.raises(CompletionError):
        decode_binding({"kind": "none"}, state={key: None})


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


@pytest.mark.parametrize("damage", ["completion_id", "candidate_hash", "source_hash", "candidate_preimage",
    "source_preimage", "graph", "operations", "provider", "bootstrap", "review", "duplicate_key", "version"])
def test_forged_request_never_becomes_publication_authority(prepared, damage):
    from harness.discovery_completion import authenticate
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    package = prepare(prepared, executor)
    ctrl = controller(prepared, executor)
    recovery = json.loads(package.request.recovery_payload)
    if damage == "completion_id": recovery["completion_id"] = "b" * 32
    elif damage == "candidate_hash": recovery["candidate_sha256"] = "b" * 64
    elif damage == "source_hash": recovery["source_fingerprint"] = "b" * 64
    elif damage in {"candidate_preimage", "source_preimage"}:
        field, digest = ("candidate_inputs", "candidate_sha256") if damage == "candidate_preimage" else ("source_inputs", "source_fingerprint")
        value = json.loads(recovery[field])
        if damage == "candidate_preimage": value["artifacts"]["unknowns.md"] += "Forged content"
        else: value["runtime"]["user_request"] = "Forged request"
        recovery[field] = canonical(value)
        recovery[digest] = hashlib.sha256(recovery[field].encode("ascii")).hexdigest()
        if damage == "candidate_preimage": recovery["operation"]["attempts"][-1]["result"]["candidate_sha256"] = recovery[digest]
        else: recovery["operation"]["binding"]["fingerprint"] = recovery[digest]
    elif damage == "graph": recovery["graph_sha256"] = "b" * 64
    elif damage == "provider": recovery["provider"]["binding_sha256"] = "b" * 64
    elif damage == "bootstrap": recovery["operation"]["binding"]["operation_id"] = "other"
    elif damage == "review": recovery["review"]["verdict"] = "reject"
    elif damage == "version": recovery["version"] = True
    raw = canonical(recovery)
    if damage == "duplicate_key": raw = raw[:-1] + ',"version":2}'
    request = replace(package.request, recovery_payload=raw,
        operations=() if damage == "operations" else package.request.operations)
    with pytest.raises(CompletionError) as caught:
        forged = ctrl._prepare_spec_step_effects(from_phase="phase1-discover", to_phase="phase1-what",
            snapshot=prepared[1].capture_routing_snapshot(expected_phase="phase1-discover"),
            manual_phase_run=False, conditional_skip=False, record_completion=True,
            publication_marker=package.publication.marker.to_dict(), completion_id="a" * 32,
            managed_discovery_request=encode_publication_request(request))
        authenticate(prepared[0], prepared[1].squad_dir, prepared[1].load(), forged)
    assert "Forged" not in str(caught.value) and caught.value.__context__ is None
    assert prepared[2].pending_identity_publication(spec_id="game") is None
    assert list((prepared[0] / "specs/game").iterdir()) == [] and len(executor.calls) == 3


def test_partial_promotion_is_recovered_with_original_full_read_set(prepared, monkeypatch):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    ctrl, package, sealed = completion(prepared, executor)
    _install_prepared_routed_completion(prepared[1], sealed)
    promote = PreparedSquadPublication._promote
    def partial(self, pinned, **kwargs):
        def interrupt(position):
            if position == 1: raise Interrupted()
        return promote(self, pinned, **{**kwargs, "fault_hook": interrupt})
    with monkeypatch.context() as patch:
        patch.setattr(PreparedSquadPublication, "_promote", partial)
        with pytest.raises(Interrupted): drain(ctrl)
    assert len(list((prepared[0] / "specs/game").iterdir())) == 1
    assert prepared[2].pending_identity_publication(spec_id="game")["state"] == "prepared"
    source = prepared[0] / "inputs/task.md"
    original = source.read_bytes()
    source.write_text("Changed input")
    blocked = drain(controller(prepared, executor))
    assert blocked.recovered and blocked.blocked
    assert len(list((prepared[0] / "specs/game").iterdir())) == 1
    source.write_bytes(original)
    assert drain(controller(prepared, executor)).recovered
    assert (prepared[0] / "specs/game/spec-artifact-graph.json").read_bytes() == package.graph
    assert len(executor.calls) == 3


@pytest.mark.parametrize("ambient", ["staging", "canonical", "wip"])
def test_completion_cannot_import_uncaptured_staging_into_context(prepared, ambient):
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    ctrl, _, sealed = completion(prepared, executor)
    _install_prepared_routed_completion(prepared[1], sealed)
    path = {"staging": prepared[1].squad_dir / "staging/foreign.md",
        "canonical": prepared[0] / "specs/999-foreign/spec.md",
        "wip": prepared[1].squad_dir / "specs/999-foreign/spec.md"}[ambient]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Unreviewed foreign identity U-999999 and FR-999999")
    result = drain(ctrl)
    context = (prepared[1].squad_dir / "context/current-feature-context.md").read_text()
    assert result.recovered
    assert "U-999999" not in context and "FR-999999" not in context
    assert "U-000001: Camera choice" in context and "# Assumptions" in context and "See U-000001." in context
    registry = json.loads((prepared[1].squad_dir / "context/feature-registry.snapshot.json").read_text())
    assert registry["features"] == [] and registry["wip_features"] == []
    assert len(executor.calls) == 3


def test_partial_context_install_reuses_frozen_captured_projection(prepared, monkeypatch):
    import harness.squad as squad
    executor = DiscoveryExecutor()
    assert execute(prepared, executor, create=True).status == "reviewed"
    ctrl, package, sealed = completion(prepared, executor)
    _install_prepared_routed_completion(prepared[1], sealed)
    install = squad.install_or_verify_completion_context
    def partial_context(*args, **kwargs):
        def interrupt(point):
            if point == "after_install:current-feature-context.md": raise Interrupted()
        return install(*args, **kwargs, fault_hook=interrupt)
    with monkeypatch.context() as patch:
        patch.setattr(squad, "install_or_verify_completion_context", partial_context)
        with pytest.raises(Interrupted): drain(ctrl)
    step = load_prepared_spec_step(
        prepared[1].squad_dir,
        prepared[1].load()[PENDING_SPEC_STEP_KEY],
    )
    marker = ctrl._completion_marker_from_spec_step(step)
    assert marker["step"] == "context"
    loaded = load_prepared_spec_step_effects(prepared[0], prepared[1].squad_dir, marker)
    frozen_receipt = loaded.receipts["effects"]["context"]
    context = prepared[1].squad_dir / "context/current-feature-context.md"
    assert "U-000001: Camera choice" in context.read_text()
    assert prepared[2].pending_identity_publication(spec_id="game")["state"] == "applied"
    assert package.publication._transaction_root.exists()
    def no_generation(*args, **kwargs):
        raise AssertionError("receipted context must not regenerate")
    with monkeypatch.context() as patch:
        patch.setattr("echelon.context_builder.build_run_context", no_generation)
        recovered = drain(controller(prepared, executor))
        assert recovered.recovered and not recovered.blocked
    assert "U-000001: Camera choice" in context.read_text()
    assert len(frozen_receipt["files"]) == 5
    assert prepared[2].pending_identity_publication(spec_id="game") is None
    assert len(executor.calls) == 3
