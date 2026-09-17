"""Captured gate evaluation must not read or publish live canonical files."""
import hashlib
import json
from dataclasses import replace
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from harness import spec_lexicon_gate
from tests.unit.test_managed_lexicon import (case, enrolled, turn_prepared, prepared,
    checkpoint_case, controller, selection, install_lexicon, LexiconExecutor)


SOURCE = """# Feature Specification

## Functional Requirements
- **FR-000001**: Preserve the scene.

## Acceptance Criteria
- **AC-000001**: Given the scene, when rendered, then it remains visible.
"""
DERIVED = f"""# SOURCE: spec.md
# SOURCE_SHA256: {hashlib.sha256(SOURCE.encode()).hexdigest()}
ARTIFACT: SPEC
TITLE: Scene preservation

REQ: FR-000001
GIVEN: the scene is available
WHEN: it renders
THEN: the system MUST preserve the visible scene
OUTPUT: a visible scene
EXAMPLE: AC-000001

AC: AC-000001
GIVEN: the scene is available
WHEN: it renders
THEN: the scene is visible
"""


def evaluate(root, **changes):
    evaluate_captured = getattr(spec_lexicon_gate, "evaluate_captured_spec_lexicon", None)
    assert callable(evaluate_captured), "The native gate needs a write-free captured-input boundary"
    arguments = dict(
        derived_text=DERIVED, source_text=SOURCE, glossary_text=None,
        derived_path=root / "requirements.lexicon.md", source_path=root / "spec.md",
        glossary_path=root / "glossary.md", report_path=root / "spec-lexicon-report.json",
        artifact_type="SPEC", previous_attempts=2,
    )
    return evaluate_captured(**{**arguments, **changes})


def test_captured_pass_resets_attempts_without_reading_or_writing_live_files(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        for method in ("open", "is_file", "stat"):
            original = getattr(Path, method)
            def no_project_io(path, *args, _original=original, **kwargs):
                if path.is_relative_to(tmp_path):
                    pytest.fail("Captured evaluation touched live project files")
                return _original(path, *args, **kwargs)
            patch.setattr(Path, method, no_project_io)
        result, report = evaluate(tmp_path)
    assert result.state_updates() == dict(lexicon_evaluation="passed", lexicon_attempts=0,
        lexicon_pass=True, lexicon_findings=0, lexicon_report=str(tmp_path / "spec-lexicon-report.json"))
    assert report["ok"] is True and report["findings"] == []
    assert report["artifact_path"] == str(tmp_path / "requirements.lexicon.md")
    assert report["source_path"] == str(tmp_path / "spec.md")
    assert report["glossary_path"] == str(tmp_path / "glossary.md")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("prior,expected", [(0, 1), (2, 3), (-1, 1), (None, 1), ("2", 3)])
def test_captured_grammar_failure_uses_native_attempt_count(prior, expected, tmp_path):
    result, report = evaluate(tmp_path, derived_text="Not a Lexicon document\n", previous_attempts=prior)
    assert result.evaluation == "failed" and result.passed is False
    assert result.attempts == expected
    assert result.findings > 0
    assert "parse-error" in {item["code"] for item in report["findings"]}
    assert not any(item["code"].startswith("source-id-") for item in report["findings"])
    assert not (tmp_path / "spec-lexicon-report.json").exists()


@pytest.mark.parametrize("missing", ["derived_text", "source_text"])
def test_missing_captured_input_is_pending_without_report_or_charge(tmp_path, missing):
    result, report = evaluate(tmp_path, **{missing: None})
    assert result.state_updates() == dict(lexicon_evaluation="pending", lexicon_attempts=0)
    assert report is None and result.report_path is None


def test_captured_source_drift_is_failure_not_an_opportunity_to_rehash_metadata(tmp_path):
    result, report = evaluate(tmp_path, source_text=SOURCE + "\nChanged source.\n")
    assert result.evaluation == "failed" and result.attempts == 3
    assert any("source" in item["code"] for item in report["findings"])
    assert report["source_sha256"] != hashlib.sha256(SOURCE.encode()).hexdigest()


def test_captured_report_binds_exact_unicode_and_crlf_bytes(tmp_path):
    result, report = evaluate(tmp_path, derived_text="Uncertified café\r\n",
        source_text="Source café\r\n", glossary_text="Glossary café\r\n")
    assert result.evaluation == "failed"
    assert report["source_sha256"] == "f7483dc87ec9cf6044f0a3522f448adef0015386beee6724aaea7d26cb3ca45f"
    assert report["artifact_sha256"] == hashlib.sha256(b"Uncertified caf\xc3\xa9\r\n").hexdigest()
    assert report["glossary_sha256"] == hashlib.sha256(b"Glossary caf\xc3\xa9\r\n").hexdigest()


def test_captured_validator_error_is_pending_and_cannot_publish_evidence(tmp_path, monkeypatch):
    def unavailable(**kwargs):
        raise ValueError("Test validator unavailable")
    monkeypatch.setattr(spec_lexicon_gate, "validate_spec_lexicon_texts", unavailable)
    result, report = evaluate(tmp_path)
    assert result.state_updates() == dict(lexicon_evaluation="pending", lexicon_attempts=0)
    assert report is None and result.report_path is None
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def captured_gate_sources(tmp_path):
    from harness.squad_publication import SquadPublicationTransaction
    spec = tmp_path / "specs/game"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(SOURCE)
    (spec / "requirements.lexicon.md").write_text(DERIVED)
    (tmp_path / "runs/first").mkdir(parents=True)
    publication = SquadPublicationTransaction.begin(tmp_path, tmp_path / "runs/first", "a" * 32).seal()
    with publication.inspect_sources(tree_paths=("specs/game",), file_paths=()) as sources:
        pass
    return tmp_path, sources


@pytest.mark.parametrize("setting,value", [
    ("path", "other.lexicon.md"), ("source_ref", "other.md"),
    ("glossary_file", "other-glossary.md"), ("report", "spec.md"), ("type", "tasks"),
])
def test_managed_gate_refuses_unadmitted_paths_instead_of_using_defaults(captured_gate_sources, setting, value):
    from harness.discovery_lexicon import _gate_evaluation
    root, sources = captured_gate_sources
    config = {"lexicon_gate": {"enabled": True, "artifacts": {"spec": {setting: value}}}}
    with pytest.raises(ValueError):
        _gate_evaluation(sources, root, "specs/game", config, 0)
    assert not (root / "specs/game/spec-lexicon-report.json").exists()


def test_managed_gate_evaluates_the_snapshot_not_later_live_source_bytes(captured_gate_sources):
    from harness.discovery_lexicon import _gate_evaluation
    root, sources = captured_gate_sources
    (root / "specs/game/spec.md").write_text("Changed after capture\n")
    result, report = _gate_evaluation(sources, root, "specs/game", {"lexicon_gate": {"enabled": True}}, 0)
    assert result.passed is True and report["source_sha256"] == "1d61a1cce98a4c4dfc5e7effed8447e6e52699cae2a960b8215d3a92f1f9e231"
    assert not (root / "specs/game/spec-lexicon-report.json").exists()


def test_managed_repair_gate_retains_prior_attempts(captured_gate_sources):
    from harness.discovery_lexicon import _gate_evaluation
    root, sources = captured_gate_sources
    result, _ = _gate_evaluation(sources, root, "specs/game", {"lexicon_gate": {"enabled": True}}, 2)
    assert result.passed is True and result.attempts == 0
    spec = sources.trees[0]
    bad = replace(spec, files=tuple(replace(item, content=b"Still invalid\n")
        if item.path.endswith("/requirements.lexicon.md") else item for item in spec.files))
    result, _ = _gate_evaluation(replace(sources, trees=(bad,)), root, spec.path,
        {"lexicon_gate": {"enabled": True}}, 2)
    assert result.passed is False and result.attempts == 3


@pytest.mark.parametrize("changed", [False, True])
def test_repair_progress_uses_sealed_postimage_not_live_file(tmp_path, changed):
    from harness.discovery_lexicon import projected_lexicon_progress
    from harness.squad_publication import SquadPublicationTransaction
    spec = tmp_path / "specs/game"
    spec.mkdir(parents=True)
    original = b"Invalid translation\n"
    (spec / "requirements.lexicon.md").write_bytes(original)
    (spec / "spec-lexicon-report.json").write_text(json.dumps(dict(ok=False,
        artifact_path=str(spec / "requirements.lexicon.md"), artifact_sha256=hashlib.sha256(original).hexdigest())))
    run = tmp_path / "runs/first"
    run.mkdir(parents=True)
    from harness.discovery_publication import _seal
    publication = _seal(tmp_path, run, {"specs/game/requirements.lexicon.md": original + (b"Changed\n" if changed else b"")}, {})
    with publication.inspect_sources(tree_paths=("specs/game",), file_paths=()) as sources:
        assert projected_lexicon_progress(sources, root=tmp_path, spec_dir=spec) is changed
    assert (spec / "requirements.lexicon.md").read_bytes() == original


def test_native_preparation_admits_staged_lexicon_repair(checkpoint_case):
    from harness.discovery_publication import _seal
    from harness.squad_provider import SquadAgentResult
    root, store, _, _ = checkpoint_case
    original = b"Invalid translation\n"
    spec = root / "specs/game"
    (spec / "requirements.lexicon.md").write_bytes(original)
    (spec / "spec-lexicon-report.json").write_text(json.dumps(dict(ok=False,
        artifact_path=str(spec / "requirements.lexicon.md"), artifact_sha256=hashlib.sha256(original).hexdigest())))
    state = store.load()
    state.update(phase="phase1-lexicon-derive", lexicon_evaluation="failed", lexicon_pass=False,
        lexicon_attempts=1, lexicon_report=str(spec / "spec-lexicon-report.json"), spec_dir="specs/game")
    store.save(state)
    publication = _seal(root, store.squad_dir, {"specs/game/requirements.lexicon.md": b"Changed translation\n"}, {})
    ctrl = controller(checkpoint_case, LexiconExecutor())
    with publication.inspect_sources(tree_paths=("specs/game",), file_paths=()) as sources:
        prepared = ctrl._prepare_phase_result(ctrl._graph.get("phase1-lexicon-derive"),
            SquadAgentResult(0, dict(verdict="DONE", state_updates={}), "", 0, False),
            store.capture_routing_snapshot(expected_phase="phase1-lexicon-derive"), publication_sources=sources)
    assert prepared.routing_override is None


def assert_gate_source_drift_refused(project_spec, root):
    from harness.squad_source_snapshot import inspect_project_tree
    with inspect_project_tree(root, "specs/game") as tree:
        project_spec(tree)
        for name in ("spec.md", "glossary.md", "requirements.lexicon.md", "spec-lexicon-report.json"):
            item, = (item for item in tree.files if item.path == "specs/game/" + name)
            changed = item.content + b"\nChanged evidence\n"
            damaged = replace(item, content=changed, image=replace(item.image,
                sha256=hashlib.sha256(changed).hexdigest()))
            with pytest.raises((ValueError, RuntimeError)):
                project_spec(replace(tree, files=tuple(damaged if row.path == item.path else row for row in tree.files)))


@pytest.mark.parametrize("derived", [DERIVED, "Not a Lexicon document\n"])
def test_captured_and_native_gate_have_same_report_and_policy(tmp_path, derived):
    (tmp_path / "spec.md").write_text(SOURCE)
    (tmp_path / "requirements.lexicon.md").write_text(derived)
    captured, report = evaluate(tmp_path, derived_text=derived)
    assert not (tmp_path / "spec-lexicon-report.json").exists()
    native = spec_lexicon_gate.run_spec_lexicon_gate(project_root=tmp_path,
        spec_dir_ref=str(tmp_path), config={"lexicon_gate": {"enabled": True}}, previous_attempts=2)
    assert native == captured
    assert json.loads((tmp_path / "spec-lexicon-report.json").read_text()) == report


@pytest.mark.parametrize("passed,iteration,cap,want", [
    (False, 0, 3, "phase1-lexicon-derive"),
    (False, 3, 3, "terminal-blocked"),
    (False, 0, 1, "terminal-blocked"),
    (True, 0, 3, "checkpoint-assess"),
    (True, 3, 1, "checkpoint-assess"),
])
def test_gate_proof_has_one_exact_native_route_even_with_warn_policy(passed, iteration, cap, want):
    from harness import discovery_lexicon
    route = getattr(discovery_lexicon, "lexicon_gate_route", None)
    assert callable(route), "Saved gate proofs must bind one exact native routing outcome"
    config = {"lexicon_gate": {"enabled": True, "artifacts": {"spec": {"enabled": True}},
        "max_repair_attempts": cap, "on_exhausted": "warn"}}
    updates = dict(lexicon_pass=passed, lexicon_evaluation="passed" if passed else "failed",
        lexicon_attempts=0 if passed else 1)
    assert route(config, dict(iteration=iteration, max_iterations=3), updates) == want


def test_gate_entry_requires_real_derivation_authority_before_any_work(checkpoint_case):
    from tests.unit.test_why1_tracker_parent import source
    root, store, identity, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    executor = LexiconExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-lexicon"}
    ctrl = controller(checkpoint_case, executor)
    ctrl._admit_managed_discovery(selected, True)
    state = store.load()
    state.update(phase="phase1-lexicon", last_dispatch={**source("a"),
        "phase_id": "phase1-lexicon-derive", "post_dispatch_complete": True})
    store.save(state)
    before, history = store.load(), identity.identity_history(spec_id="game")
    result = ctrl.run(managed_discovery=selected)
    assert result.summary == "managed_lexicon_gate_requires_reconciliation"
    assert store.load() == before and executor.calls == []
    assert identity.identity_history(spec_id="game") == history
    assert not (root / "specs/game/spec-lexicon-report.json").exists()


def assert_retained_gate(root, store, identity):
    """Check real released authority and detached, rehashed envelope attacks."""
    from harness.discovery_completion import decode_binding
    from harness.element_identity_publication import encode_publication_request
    from harness.squad_completion import CompletionError, _validate_intent
    state = store.load()
    row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + state["last_dispatch"]["dispatch_id"])
    proof = json.loads(row["completion_payload"])["proof"]
    publication = proof["intent"]["publication"]
    binding = decode_binding(publication, state=state)
    assert binding.producer == "lexicon_gate" and binding.request.operations == ()
    assert binding.candidate["history"] == binding.source["history"]
    for operation in binding.sources.publication.operations:
        assert (root / operation.target).read_bytes() == operation.postimage_bytes
    # Rehashing the saved policy does not authorize changing the run's limit.
    recovery = deepcopy(binding.recovery)
    recovery["routing_state"]["max_iterations"] = state["max_iterations"] + 1
    changed = deepcopy(publication)
    changed["managed_discovery"]["request"] = encode_publication_request(replace(binding.request,
        recovery_payload=json.dumps(recovery, sort_keys=True, separators=(",", ":"))))
    with pytest.raises(CompletionError):
        decode_binding(changed, state=state)
    for destination in {"checkpoint-assess", "terminal-blocked", "phase1-lexicon-derive", "phase2-decide"} - {proof["intent"]["route"]["to_phase"]}:
        intent = deepcopy(proof["intent"])
        intent["route"]["to_phase"] = destination
        # This is the same closed validator used before hashing new intents
        # and when validating detached retained completion proofs.
        with pytest.raises(CompletionError):
            _validate_intent(intent)
    for damage in ("result", "parent", "counter", "version"):
        recovery = deepcopy(binding.recovery)
        if damage == "result": recovery["result"]["state_updates"]["lexicon_findings"] += 1
        elif damage == "parent": recovery["source_completion"]["dispatch_id"] = "0" * 32
        elif damage == "counter": recovery["previous_attempts"] = 1
        else: recovery["version"] = True
        changed = deepcopy(publication)
        changed["managed_discovery"]["request"] = encode_publication_request(replace(binding.request,
            recovery_payload=json.dumps(recovery, sort_keys=True, separators=(",", ":"))))
        with pytest.raises(CompletionError):
            decode_binding(changed)
    assert store.load() == state


def test_managed_gate_publishes_native_failure_once_without_provider_work(checkpoint_case):
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    from harness.discovery_completion import decode_binding, released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS
    root, store, identity, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = LexiconExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-lexicon"}
    ctrl = controller(checkpoint_case, executor)
    ctrl._admit_managed_discovery(selected, True)
    result = ctrl.run(managed_discovery={**selected, "through_phase": "phase1-lexicon-derive"})
    assert result.phase == "phase1-lexicon", result
    before = store.load()
    history = identity.identity_history(spec_id="game")
    files = {path.name: path.read_bytes() for path in (root / "specs/game").iterdir()
        if path.is_file() and path.name != "spec-artifact-graph.json"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    assert result.phase == "phase1-lexicon-derive", result
    state = store.load()
    assert state["lexicon_evaluation"] == "failed" and state["lexicon_pass"] is False
    assert state["lexicon_attempts"] == 1
    assert state["token_usage"] == before["token_usage"] == 168 and len(executor.calls) == 24
    assert state["last_dispatch"]["phase_id"] == "phase1-lexicon"
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    report = root / "specs/game/spec-lexicon-report.json"
    assert json.loads(report.read_bytes())["ok"] is False
    assert {name: (root / "specs/game" / name).read_bytes() for name in files} == files
    assert identity.identity_history(spec_id="game") == history
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    row = identity.identity_publication(spec_id="game", operation_id="discovery-completion-" + source["dispatch_id"])
    binding = decode_binding(json.loads(row["completion_payload"])["proof"]["intent"]["publication"], state=state)
    assert binding.producer == "lexicon_gate" and binding.request.operations == ()
    assert binding.candidate["history"] == binding.source["history"]
    assert "provider" not in binding.recovery
    project_spec, _ = released_discovery_input_projectors(root, store.squad_dir, state, source=source)
    assert_gate_source_drift_refused(project_spec, root)
    # This increment ends at the native repair handoff, not a second derivation.
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == state and len(executor.calls) == 24
    assert identity.pending_identity_publication(spec_id="game") is None
    assert_retained_gate(root, store, identity)


class PassingLexiconExecutor(LexiconExecutor):
    def run_inspection_turn(self, *args, **kwargs):
        response = super().run_inspection_turn(*args, **kwargs)
        payload = json.loads(args[1].split("\nHOST_INPUT_JSON\n", 1)[1])
        assignment = payload["assignment"]
        if assignment.get("producer") == "lexicon" and assignment["step"] == "author":
            text = DERIVED.replace(hashlib.sha256(SOURCE.encode()).hexdigest(),
                payload["context"]["lexicon_source"]["source_sha256"])
            text = text.replace("AC: AC-000001\n", """REQ: NFR-000001
GIVEN: the scene is available
WHEN: it renders
THEN: the system MUST run in a browser
OUTPUT: a visible scene in a browser
EXAMPLE: AC-000001

AC: AC-000001
""")
            result = json.loads(response.stdout)
            result["artifacts"] = {"requirements.lexicon.md": text}
            response = replace(response, stdout=json.dumps(result))
        return response


def continue_repair(case, provider="codex", *, progress=True):
    """Reusable against a fresh corridor or an untouched retained failed gate."""
    from harness.discovery_completion import released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS
    root, store, identity, _ = case
    before = store.load()
    history = identity.identity_history(spec_id="game")
    assert before["phase"] == "phase1-lexicon-derive" and before["lexicon_attempts"] == 1
    previous = deepcopy(before["managed_lexicon_rounds"])
    executor = PassingLexiconExecutor(provider) if progress else LexiconExecutor(provider)
    selected = {**selection(case), "through_phase": "phase1-lexicon-derive"}
    result = controller(case, executor).run(managed_discovery=selected)
    assert result.phase == ("phase1-lexicon" if progress else "terminal-blocked"), (result, store.load().get("controller_contract_error"))
    state = store.load()
    assert state["lexicon_attempts"] == 1 and state["token_usage"] == before["token_usage"] + 21
    assert len(executor.calls) == 3
    rounds = state["managed_lexicon_rounds"]
    assert rounds["rounds"][previous["active"]] == previous["rounds"][previous["active"]]
    assert rounds["rounds"][rounds["active"]]["predecessor"] == previous["active"]
    assert identity.identity_history(spec_id="game") == history
    released_discovery_input_projectors(root, store.squad_dir, state,
        source={key: state["last_dispatch"][key] for key in SOURCE_FIELDS})
    if progress:
        result = controller(case, executor).run(managed_discovery={**selected, "through_phase": "phase1-lexicon"})
        assert result.phase == "checkpoint-assess", result
        assert store.load()["lexicon_attempts"] == 0 and store.load()["lexicon_pass"] is True
    settled = store.load()
    controller(case, executor).run(managed_discovery={**selected, "through_phase": "phase1-lexicon"})
    assert store.load() == settled and len(executor.calls) == 3
    assert identity.identity_history(spec_id="game") == history


@pytest.mark.parametrize("provider,progress", [("codex", True), ("claude", False)])
def test_managed_failed_gate_repair_retains_authority_and_stops_no_progress(checkpoint_case, provider, progress):
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    root, store, _, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    selected = {**selection(checkpoint_case), "through_phase": "phase1-lexicon"}
    result = controller(checkpoint_case, LexiconExecutor(provider)).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "phase1-lexicon-derive", result
    continue_repair(checkpoint_case, provider, progress=progress)
    if progress:
        from tests.unit.test_managed_checkpoint_assess import install_commander, continue_checkpoint
        install_commander(root)
        continue_checkpoint(checkpoint_case, provider, fault="before_state")


def test_managed_gate_pass_reaches_checkpoint_without_executing_it(checkpoint_case):
    from harness.quality_scores import QUALITY_GATE_SCORE_KEYS
    from harness.discovery_completion import released_discovery_input_projectors
    from harness.discovery_producer import SOURCE_FIELDS
    root, store, identity, _ = checkpoint_case
    install_lexicon(checkpoint_case)
    config = root / ".echelon/config.yml"
    value = yaml.safe_load(config.read_text())
    value["quality_gates"] = {key: 0.0 for key in QUALITY_GATE_SCORE_KEYS}
    config.write_text(yaml.safe_dump(value))
    executor = PassingLexiconExecutor("claude")
    selected = {**selection(checkpoint_case), "through_phase": "phase1-lexicon"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "checkpoint-assess", (result, store.load().get("controller_contract_error"))
    state = store.load()
    assert state["lexicon_pass"] is True and state["lexicon_evaluation"] == "passed"
    assert state["lexicon_attempts"] == 0 and state["lexicon_findings"] == 0
    assert spec_lexicon_gate.has_current_spec_lexicon_evidence(state, project_root=root, config=value)
    assert state["token_usage"] == 168 and len(executor.calls) == 24
    assert state["last_dispatch"]["phase_id"] == "phase1-lexicon"
    assert state["last_dispatch"]["post_dispatch_complete"] is True
    assert not (state.get("phase_dispatch_counts") or {}).get("checkpoint-assess")
    assert not (state.get("phase_dispatch_counts") or {}).get("phase2-decide")
    history = identity.identity_history(spec_id="game")
    project_spec, _ = released_discovery_input_projectors(root, store.squad_dir, state,
        source={key: state["last_dispatch"][key] for key in SOURCE_FIELDS})
    assert_gate_source_drift_refused(project_spec, root)
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == result.phase
    assert store.load() == state and len(executor.calls) == 24
    assert identity.identity_history(spec_id="game") == history
    assert_retained_gate(root, store, identity)
