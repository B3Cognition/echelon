"""Offline repair→Synthesis proof and recovery through the existing owners."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tests.unit.test_repair_refresh_inputs import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller,
    selection, install_why1, RepairExecutor, select_refresh, bind_input,
)


class RefreshExecutor(RepairExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        reply = json.loads(response.stdout)
        if reply["operation_id"].startswith("synthesizer-") and reply["step"] == "propose":
            reply["revisions"] = [dict(id="U-000001", expected_revision="3")]
        return replace(response, stdout=json.dumps(reply))


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_refresh_publishes_from_repair_and_replays_immutable_ancestry(checkpoint_case, provider, monkeypatch):
    publish_synthesis_refresh(checkpoint_case, provider, monkeypatch)


def publish_synthesis_refresh(checkpoint_case, provider, monkeypatch, *, prepare_tracker=False):
    from harness.discovery_operation import run_discovery_operation
    from harness.discovery_publication import prepare_discovery_publication
    from harness.discovery_completion import decode_binding, released_discovery_input_projectors
    from harness.discovery_producer import tracker_round, SOURCE_FIELDS
    from harness.element_identity_publication import encode_publication_request
    from tests.unit.test_discovery_completion import drain
    from tests.integration.test_squad_controller import _install_prepared_routed_completion
    root, store, identity, _ = checkpoint_case
    install_why1(checkpoint_case)
    executor = RefreshExecutor(provider)
    request = {**selection(checkpoint_case), "through_phase": "phase1-why1"}
    ctrl = controller(checkpoint_case, executor)
    if provider == "claude":
        guided = store.load()
        guided["autonomy_mode"] = "guided"
        store.save(guided)
        executor.clarification = True
        executor.why_verdict = "STOP_AND_ASK"
        assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-tracker"
        assert ctrl.resume_with_human_input("Use arrow keys")
        assert ctrl.run(managed_discovery=request).phase == "phase1-why1"
        assert ctrl.resume_with_human_input("Single player")
        executor.why_verdict = "FAIL"
        assert ctrl.run(managed_discovery=request).phase == "phase1-discover"
    else:
        assert ctrl.run(managed_discovery=request, create_managed_discovery=True).phase == "phase1-discover"
    assert ctrl.run(managed_discovery=request).summary == "managed_repair_dependency_refresh_not_supported"
    if prepare_tracker:
        select_refresh(root, store, "tracker")
        select_refresh(root, store, "why1")
    select_refresh(root, store, "synthesizer")
    bound = bind_input(root, store)
    original = {key: deepcopy(bound[key]) for key in (
        "managed_synthesizer_source", "managed_synthesizer_operation", "managed_synthesizer_turns")}
    receipts = {path: path.read_bytes() for path in store.squad_dir.glob("*.json")
        if "turns" in path.name or "reservations" in path.name}
    reports = {path: (root / "specs/game" / path).read_bytes() for path in ("issues.md", "assumption-review.md", "user-intent.md")}
    human_context = {path: path.read_bytes() for path in (
        *(store.staging_dir / name for name in ("user-clarifications.md", "feature-policy.json", "feature-policy.md")),
        store.squad_dir / "reasoning-journal.jsonl") if path.exists()}
    # Exercise the inactive operation/publication boundary. Automatic controller
    # ordering is intentionally still guarded; no fixture bypasses source/proof checks.
    active = deepcopy(bound)
    active["phase"] = "phase1-synthesizer"
    store.save(active)
    old_binding = original["managed_synthesizer_operation"]["binding"]
    paths = tuple(old_binding["artifact_paths"])
    def execute():
        return run_discovery_operation(root, store, executor, producer="synthesizer", create=True,
            input_tree="inputs", artifact_paths=paths, editable_revisions=(("U-000001", "3"),),
            unowned_writable_paths=paths, intent=old_binding["intent"])
    before = store.load()
    calls = len(executor.calls)
    history = identity.identity_history(spec_id="game")
    for target in (root / "specs/game/issues.md", root / ".echelon/runtime/templates/risks-template.md"):
        raw = target.read_bytes()
        try:
            target.write_bytes(raw + b"Changed after refresh input binding\n")
            assert execute().status == "blocked"
            assert store.load() == before and len(executor.calls) == calls
            assert identity.identity_history(spec_id="game") == history
        finally:
            target.write_bytes(raw)
    outcome = execute()
    assert outcome.status == "reviewed", outcome
    expected_calls = 24 if provider == "claude" else 18
    assert len(executor.calls) == expected_calls and outcome.token_usage == 21
    package = prepare_discovery_publication(root, store, executor, producer="synthesizer", completion_id="d" * 32)
    recovery = json.loads(package.request.recovery_payload)
    row = tracker_round(store.load(), producer="synthesizer")
    assert recovery["version"] == 9
    assert recovery["source_completion"] == row["execution_input"]["source"]
    assert recovery["source_completion"] == {key: bound["last_dispatch"][key] for key in SOURCE_FIELDS}
    assert recovery["refresh"] == row["refresh"]
    assert recovery["execution_input"] == row["execution_input"]
    assert recovery["predecessor"] == row["predecessor"]
    if provider == "claude":
        captured = json.dumps(executor.calls[-3]["context"]["evidence"])
        assert "Use arrow keys" in captured and "Single player" in captured
    sealed = ctrl._prepare_spec_step_effects(from_phase="phase1-synthesizer", to_phase="phase1-why1",
        snapshot=store.capture_routing_snapshot(expected_phase="phase1-synthesizer"), manual_phase_run=False,
        conditional_skip=False, record_completion=True, publication_marker=package.publication.marker.to_dict(),
        completion_id="d" * 32, managed_discovery_request=encode_publication_request(package.request))
    assert decode_binding(sealed.intent.publication, state=store.load()).producer == "synthesizer"
    from harness.squad_completion import CompletionError
    for damage in ("version", "source", "repair", "predecessor", "comparison", "extra"):
        altered = deepcopy(recovery)
        if damage == "version":
            altered["version"] = 3
            for key in ("refresh", "execution_input", "predecessor"):
                del altered[key]
        elif damage == "source": altered["source_completion"] = row["refresh"]["predecessor_source"]
        elif damage == "repair": altered["refresh"]["repair_unit"] = "0" * 64
        elif damage == "predecessor": altered["predecessor"] = "synthesis-" + "0" * 32
        elif damage == "comparison": altered["execution_input"]["dependencies"]["after_sha256"] = "0" * 64
        else: altered["refresh"]["untrusted"] = True
        forged = replace(package.request, recovery_payload=json.dumps(altered, sort_keys=True, separators=(",", ":")))
        publication = deepcopy(sealed.intent.publication)
        publication["managed_discovery"]["request"] = encode_publication_request(forged)
        with pytest.raises(CompletionError): decode_binding(publication, state=store.load())
    # Recompute the bound decision from authenticated accepted predecessor
    # postimages, independently of the protected-state equality above.
    from harness.discovery_completion import _refresh_predecessor, _require_refresh_dependencies
    previous = _refresh_predecessor(root, store.squad_dir, store.load(), row)
    decoded = decode_binding(sealed.intent.publication, state=store.load())
    selection_value = store.load()["managed_discovery_bootstrap"]["selection"]
    arguments = (previous, row["refresh"]["predecessor_source"], decoded.sources,
        decoded.source, selection_value, store.squad_dir, root)
    _require_refresh_dependencies(row, *arguments)
    altered = deepcopy(row)
    altered["execution_input"]["dependencies"]["after_sha256"] = "0" * 64
    with pytest.raises(ValueError): _require_refresh_dependencies(altered, *arguments)
    _install_prepared_routed_completion(store, sealed, token_usage_delta=21)
    from harness.element_identity_store import IdentityStore
    from tests.unit.test_discovery_turns import Interrupted
    original_apply = IdentityStore.apply_identity_publication
    def interrupt(*args, **kwargs):
        original_apply(*args, **kwargs)
        raise Interrupted()
    with monkeypatch.context() as patch:
        patch.setattr(IdentityStore, "apply_identity_publication", interrupt)
        with pytest.raises(Interrupted): drain(ctrl)
    assert drain(controller(checkpoint_case, executor)).recovered
    saved = store.load()
    assert saved["phase"] == "phase1-why1" and saved["token_usage"] == expected_calls * 7
    assert saved["phase_dispatch_counts"]["phase1-synthesizer"] == 2
    assert {key: saved[key] for key in original} == original
    assert all(path.read_bytes() == raw for path, raw in receipts.items())
    assert all(path.read_bytes() == raw for path, raw in human_context.items())
    assert {path: (root / "specs/game" / path).read_bytes() for path in reports} == reports
    heads = {row["element_id"]: row["revision"] for row in json.loads(identity.identity_history(spec_id="game").payload)["entities"]}
    assert heads["U-000001"] == "4" and heads["ISS-000001"] == "1"
    source = {key: saved["last_dispatch"][key] for key in SOURCE_FIELDS}
    released_discovery_input_projectors(root, store.squad_dir, saved, source=source)
    assert len(executor.calls) == expected_calls
    assert not drain(controller(checkpoint_case, executor)).recovered
    return executor, request
