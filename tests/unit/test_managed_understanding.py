"""Managed deterministic analysis uses the existing report/completion owners."""
import json
import pytest

from tests.unit.test_managed_what import (
    case, enrolled, turn_prepared, prepared, checkpoint_case, controller,
    selection, install_what, WhatExecutor,
)


@pytest.fixture
def captured_analysis(tmp_path):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.understanding_gate import run_understanding_gate
    from tests.unit.test_managed_spec_contract import SPEC
    root, run = tmp_path.resolve(), tmp_path.resolve() / "runs/first"
    spec = root / "specs/game"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(SPEC)
    config = {"understanding": {"diagram": {"enabled": False}}}
    gate = run_understanding_gate(project_root=root, squad_dir=run, phase="phase1-why2",
        iteration=0, spec_dir="specs/game", config=config)
    assert gate.completed
    report = gate.report_path.relative_to(root).as_posix()
    publication = SquadPublicationTransaction.begin(root, run, "a" * 32).seal()
    with publication.inspect_sources(tree_paths=("specs/game",), file_paths=(report,)) as sources:
        pass
    recovery = dict(report_path=report, iteration=0, prior_scores=[], config=config,
        thresholds=gate.report["thresholds"])
    return root, run, gate, recovery, sources


def test_captured_real_numeric_report_projects_exact_executor_updates(captured_analysis):
    from harness.discovery_understanding import _report_result
    root, run, gate, recovery, sources = captured_analysis
    assert _report_result(recovery, sources, root, run, "specs/game") == dict(
        verdict="DONE", state_updates=gate.state_updates([]))


@pytest.mark.parametrize("damage", ["duplicate", "nonfinite", "score", "spec", "threshold", "diagram"])
def test_captured_report_rejects_tampering(captured_analysis, damage):
    from dataclasses import replace
    from harness.discovery_understanding import _report_result
    from harness.proportional_quality import QualityCandidateIntegrityError
    root, run, _, recovery, sources = captured_analysis
    item, = sources.files
    report = json.loads(item.content)
    if damage == "duplicate":
        content = item.content[:-1] + b', "schema_version": 1}'
    elif damage == "nonfinite":
        content = item.content[:-1] + b', "extra": NaN}'
    else:
        if damage == "score": report["scores"]["overall"] = 0.999
        elif damage == "spec": report["spec"]["sha256"] = "0" * 64
        elif damage == "threshold": recovery["thresholds"] = {"overall": 0}
        else: report["analysis_inputs"]["diagram_enabled"] = not report["analysis_inputs"]["diagram_enabled"]
        content = json.dumps(report).encode()
    altered = replace(sources, files=(replace(item, content=content),))
    with pytest.raises((ValueError, QualityCandidateIntegrityError)):
        _report_result(recovery, altered, root, run, "specs/game")


def test_managed_understanding_completes_real_analysis_without_provider_dispatch(checkpoint_case):
    from harness.discovery_producer import SOURCE_FIELDS
    from harness.discovery_completion import _retained_input_projection
    from harness.understanding_gate import has_current_understanding_evidence
    root, store, identity, _ = checkpoint_case
    install_what(checkpoint_case)
    executor = WhatExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-understanding"}
    result = controller(checkpoint_case, executor).run(managed_discovery=selected, create_managed_discovery=True)
    assert result.phase == "phase1-why2", result
    state = store.load()
    assert state["token_usage"] == 126 and len(executor.calls) == 18
    assert state["last_dispatch"]["phase_id"] == "phase1-understanding"
    assert state["last_dispatch"]["post_dispatch_complete"]
    assert has_current_understanding_evidence(state, project_root=root, phase="phase1-why2")
    source = {key: state["last_dispatch"][key] for key in SOURCE_FIELDS}
    binding, _, _ = _retained_input_projection(root, store.squad_dir, state, identity,
        operation_id="discovery-completion-" + source["dispatch_id"], source=source,
        require_checkpoint=True, required_route=("phase1-understanding", "phase1-why2"))
    assert binding.producer == "understanding"
    assert binding.request.operations == ()
    assert binding.candidate["history"] == binding.source["history"]
    assert "provider" not in binding.recovery
    before = identity.identity_history(spec_id="game")
    report = root / state["understanding_evidence"]["path"]
    original = report.read_bytes()
    assert json.loads(original)["analysis_inputs"]["spec_sha256"] == json.loads(original)["spec"]["sha256"]
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == "phase1-why2"
    assert store.load() == state and identity.identity_history(spec_id="game") == before
    assert report.read_bytes() == original and len(executor.calls) == 18


@pytest.mark.parametrize("failure", ["analysis", "report_write"])
def test_managed_analysis_failure_retries_without_losing_parent(checkpoint_case, monkeypatch, failure):
    from harness import understanding_gate
    root, store, identity, _ = checkpoint_case
    install_what(checkpoint_case)
    executor = WhatExecutor()
    selected = {**selection(checkpoint_case), "through_phase": "phase1-understanding"}
    result = controller(checkpoint_case, executor).run(
        managed_discovery={**selected, "through_phase": "phase1-what"}, create_managed_discovery=True)
    assert result.phase == "phase1-understanding"
    before = identity.identity_history(spec_id="game")
    def fail(*args, **kwargs):
        raise OSError("Test analysis or evidence storage unavailable")
    with monkeypatch.context() as patch:
        patch.setattr(understanding_gate, "analyze_spec_bundle" if failure == "analysis" else "_write_immutable_report", fail)
        result = controller(checkpoint_case, executor).run(managed_discovery=selected)
    state = store.load()
    assert result.phase == "phase1-understanding" and state["status"] == "blocked", result
    assert state["understanding_evidence"]["status"] == "error"
    assert "Test analysis or evidence storage unavailable" in state["blocked_reason"]
    assert identity.identity_history(spec_id="game") == before and len(executor.calls) == 18
    assert controller(checkpoint_case, executor).run(managed_discovery=selected).phase == "phase1-why2"
    assert store.load()["status"] == "running"
    assert store.load()["last_dispatch"]["post_dispatch_complete"]
    assert identity.identity_history(spec_id="game") == before and len(executor.calls) == 18
