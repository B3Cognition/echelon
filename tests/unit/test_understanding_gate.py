"""Controller-owned Understanding evidence and score projection."""

import json
import inspect
from pathlib import Path

import pytest
import yaml
from unittest.mock import MagicMock

from understanding.service import UnderstandingBundle

from harness.understanding_gate import (
    has_current_understanding_evidence,
    run_understanding_gate,
)
from harness.phase_graph import PhaseGraph
from harness.squad import SquadController
from harness.squad_executors import DeterministicUnderstandingExecutor
from harness.squad_state import SquadStateStore


def _bundle(*, passed: bool = True) -> UnderstandingBundle:
    scores = {
        "overall": 0.90,
        "structure": 0.89,
        "testability": 0.88,
        "semantic": 0.87,
        "cognitive": 0.86,
        "readability": 0.85,
        "depth": 0.84,
        "behavioral": 0.83,
    }
    thresholds = {key: 0.50 for key in scores}
    gates = {
        key: {"score": value, "threshold": thresholds[key], "pass": passed}
        for key, value in scores.items()
    }
    return UnderstandingBundle(
        analysis={
            "spec_path": "/ignored/spec.md",
            "metrics": {},
            "entity_analysis": {"entities": []},
            "behavioral_analysis": {"transitions": []},
        },
        thresholds=thresholds,
        scores=scores,
        gates=gates,
        passed=passed,
        requirement_count=2,
        per_requirement=(),
        findings=(),
        diagrams={"enabled": False, "status": "skipped", "outputs": []},
    )


def _workspace(tmp_path: Path) -> tuple[Path, Path, str]:
    project = tmp_path / "project"
    spec_dir = project / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text(
        "# Spec\n\n- **FR-001**: The system SHALL store the report.\n",
        encoding="utf-8",
    )
    squad_dir = project / ".specify" / "squad" / "run-1"
    return project, squad_dir, "specs/001-demo"


@pytest.mark.unit
def test_deterministic_executor_constructor_is_provider_free() -> None:
    parameters = inspect.signature(DeterministicUnderstandingExecutor).parameters

    assert "provider" not in parameters


@pytest.mark.unit
def test_runner_persists_all_gates_and_controller_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, squad_dir, spec_dir = _workspace(tmp_path)
    monkeypatch.setattr(
        "harness.understanding_gate.analyze_spec_bundle",
        lambda *args, **kwargs: _bundle(),
    )

    result = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=3,
        spec_dir=spec_dir,
        config={"quality_gates": {"overall": 0.81}},
    )

    assert result.operational_error is None
    assert result.report_path is not None
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["phase"] == "phase1-why2"
    assert report["iteration"] == 3
    assert set(report["scores"]) == {
        "overall",
        "structure",
        "testability",
        "semantic",
        "cognitive",
        "readability",
        "depth",
        "behavioral",
    }
    assert report["spec"]["path"] == "specs/001-demo/spec.md"
    assert len(report["spec"]["sha256"]) == 64

    updates = result.state_updates([])
    score = updates["quality_scores"][0]
    assert score["pass_id"] == "WHY2-iter-3"
    assert score["source"] == "harness:understanding"
    assert score["evidence"] == str(result.report_path)
    assert updates["understanding_evidence"]["digest"] == result.report_digest


@pytest.mark.unit
def test_runner_reuses_immutable_evidence_and_deduplicates_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, squad_dir, spec_dir = _workspace(tmp_path)
    calls = 0

    def analyze(*args: object, **kwargs: object) -> UnderstandingBundle:
        nonlocal calls
        calls += 1
        return _bundle()

    monkeypatch.setattr("harness.understanding_gate.analyze_spec_bundle", analyze)
    first = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase3-consensus",
        iteration=2,
        spec_dir=spec_dir,
        config={},
    )
    first_updates = first.state_updates([])
    second = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase3-consensus",
        iteration=2,
        spec_dir=spec_dir,
        config={},
    )
    second_updates = second.state_updates(first_updates["quality_scores"])

    assert calls == 1
    assert second.report_path == first.report_path
    assert second.report_digest == first.report_digest
    assert len(second_updates["quality_scores"]) == 1
    assert second_updates["quality_scores"][0]["pass_id"] == "WHY3-iter-2"


@pytest.mark.unit
def test_runner_reuses_digest_qualified_evidence_after_spec_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, squad_dir, spec_dir = _workspace(tmp_path)
    calls = 0

    def analyze(*args: object, **kwargs: object) -> UnderstandingBundle:
        nonlocal calls
        calls += 1
        return _bundle()

    monkeypatch.setattr("harness.understanding_gate.analyze_spec_bundle", analyze)
    first = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=1,
        spec_dir=spec_dir,
        config={},
    )
    (project / spec_dir / "spec.md").write_text(
        "# Spec\n\n- **FR-002**: The system SHALL delete the report.\n",
        encoding="utf-8",
    )
    changed = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=1,
        spec_dir=spec_dir,
        config={},
    )
    retried = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=1,
        spec_dir=spec_dir,
        config={},
    )

    assert first.report_path != changed.report_path
    assert retried.operational_error is None
    assert retried.report_path == changed.report_path
    assert calls == 2


@pytest.mark.unit
def test_runner_uses_unique_evidence_for_resolved_config_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, squad_dir, spec_dir = _workspace(tmp_path)
    calls = 0
    diagram_dirs: list[Path] = []

    def analyze(*args: object, **kwargs: object) -> UnderstandingBundle:
        nonlocal calls
        calls += 1
        diagram_dirs.append(Path(str(kwargs["diagram_output_dir"])))
        return _bundle()

    monkeypatch.setattr("harness.understanding_gate.analyze_spec_bundle", analyze)
    results = [
        run_understanding_gate(
            project_root=project,
            squad_dir=squad_dir,
            phase="phase1-why2",
            iteration=1,
            spec_dir=spec_dir,
            config={
                "quality_gates": {"overall": threshold},
                "understanding": {"diagram": {"enabled": True}},
            },
        )
        for threshold in (0.81, 0.82, 0.83)
    ]
    retried = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=1,
        spec_dir=spec_dir,
        config={
            "quality_gates": {"overall": 0.83},
            "understanding": {"diagram": {"enabled": True}},
        },
    )

    assert all(result.operational_error is None for result in results)
    assert len({result.report_path for result in results}) == 3
    assert len(set(diagram_dirs)) == 3
    assert retried.report_path == results[-1].report_path
    assert calls == 3


@pytest.mark.unit
def test_completed_gate_failure_is_not_an_operational_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, squad_dir, spec_dir = _workspace(tmp_path)
    monkeypatch.setattr(
        "harness.understanding_gate.analyze_spec_bundle",
        lambda *args, **kwargs: _bundle(passed=False),
    )

    result = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=1,
        spec_dir=spec_dir,
        config={},
    )

    assert result.operational_error is None
    assert result.completed is True
    assert result.passed is False
    assert result.state_updates([])["quality_scores"][0]["pass"] is False


@pytest.mark.parametrize("change", ["diagram_config", "spec_path"])
def test_restart_requires_the_same_analysis_inputs(tmp_path, monkeypatch, change):
    """A matching body hash alone cannot reuse another analysis request."""
    from dataclasses import replace
    project, squad_dir, spec_dir = _workspace(tmp_path)
    def analyze(*args, **kwargs):
        return replace(_bundle(), diagrams={"enabled": kwargs["diagrams_enabled"],
                                           "status": "skipped", "outputs": []})
    monkeypatch.setattr("harness.understanding_gate.analyze_spec_bundle", analyze)
    options = dict(project_root=project, squad_dir=squad_dir, phase="phase1-why2",
                   iteration=1, spec_dir=spec_dir, config={})
    first = run_understanding_gate(**options)
    if change == "diagram_config":
        options["config"] = {"understanding": {"diagram": {"enabled": True}}}
    else:
        other = project / "specs/002-other"
        other.mkdir()
        (other / "spec.md").write_bytes((project / spec_dir / "spec.md").read_bytes())
        options["spec_dir"] = "specs/002-other"
    changed = run_understanding_gate(**options)
    retried = run_understanding_gate(**options)
    assert changed.completed
    assert changed.report_path != first.report_path
    assert changed.report["spec"]["path"] == options["spec_dir"] + "/spec.md"
    assert changed.report["diagrams"]["enabled"] == (change == "diagram_config")
    assert retried.report_path == changed.report_path
    assert retried.report_digest == changed.report_digest


def test_analysis_cannot_certify_a_spec_changed_during_execution(tmp_path, monkeypatch):
    project, squad_dir, spec_dir = _workspace(tmp_path)
    def analyze(path, **kwargs):
        path.write_text("# Changed\n- FR-000001: A different requirement.\n")
        return _bundle()
    monkeypatch.setattr("harness.understanding_gate.analyze_spec_bundle", analyze)
    result = run_understanding_gate(project_root=project, squad_dir=squad_dir,
        phase="phase1-why2", iteration=1, spec_dir=spec_dir, config={})
    assert not result.completed
    assert result.operational_error
    assert "quality_scores" not in result.state_updates([])
    assert result.report["status"] == "error"


def test_real_analysis_evidence_restarts_without_duplicate_scores(tmp_path):
    """Use the actual local analyzer, report writer and current-evidence check."""
    project, squad_dir, spec_dir = _workspace(tmp_path)
    options = dict(project_root=project, squad_dir=squad_dir, phase="phase1-why2",
                   iteration=1, spec_dir=spec_dir, config={})
    first = run_understanding_gate(**options)
    assert first.completed, first.operational_error
    assert first.report["requirement_count"] == 1
    updates = first.state_updates([])
    second = run_understanding_gate(**options)
    assert second.report_digest == first.report_digest
    assert second.report_path == first.report_path
    assert second.state_updates(updates["quality_scores"]) == updates
    assert has_current_understanding_evidence({"spec_dir": spec_dir, **updates},
        project_root=project, phase="phase1-why2")


def test_multiple_operational_errors_do_not_occupy_success_evidence_identity(tmp_path, monkeypatch):
    project, squad_dir, spec_dir = _workspace(tmp_path)
    options = dict(project_root=project, squad_dir=squad_dir, phase="phase1-why2",
        iteration=1, spec_dir=spec_dir, config={})
    retained = []
    for message in ("temporary analyzer failure", "different temporary failure"):
        def fail(*args, **kwargs):
            raise OSError(message)
        with monkeypatch.context() as patch:
            patch.setattr("harness.understanding_gate.analyze_spec_bundle", fail)
            result = run_understanding_gate(**options)
        assert result.operational_error and result.report_path is not None
        retained.append((result.report_path, result.report_path.read_bytes()))
    result = run_understanding_gate(**options)
    assert result.completed, result.operational_error
    assert all(path.read_bytes() == content for path, content in retained)
    repeated = run_understanding_gate(**options)
    assert repeated.report_digest == result.report_digest


def test_legacy_digest_report_reuses_only_matching_inputs(tmp_path, monkeypatch):
    from harness.understanding_gate import _evidence_identity
    project, squad_dir, spec_dir = _workspace(tmp_path)
    monkeypatch.setattr("harness.understanding_gate.analyze_spec_bundle", lambda *a, **k: _bundle())
    options = dict(project_root=project, squad_dir=squad_dir, phase="phase1-why2",
                   iteration=1, spec_dir=spec_dir, config={})
    first = run_understanding_gate(**options)
    report = dict(first.report)
    report.pop("analysis_inputs")
    legacy = first.report_path.with_name("phase1-why2-iter-1-" + _evidence_identity(
        spec_digest=report["spec"]["sha256"], thresholds=report["thresholds"], diagram_enabled=False)[:12] + ".json")
    legacy.write_text(json.dumps(report))
    first.report_path.write_text('{"status":"error"}')
    before = legacy.read_bytes()
    retried = run_understanding_gate(**options)
    assert retried.completed
    assert retried.report_path == legacy
    assert legacy.read_bytes() == before


@pytest.mark.unit
def test_missing_spec_is_persisted_as_operational_error(tmp_path: Path) -> None:
    project = tmp_path / "project"
    squad_dir = project / ".specify" / "squad" / "run-1"

    result = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=1,
        spec_dir="specs/001-missing",
        config={},
    )

    assert result.completed is False
    assert result.operational_error == "spec.md not found: specs/001-missing/spec.md"
    assert result.report_path is not None
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "error"
    assert report["error"] == result.operational_error

    retried = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=1,
        spec_dir="specs/001-missing",
        config={},
    )
    assert retried.operational_error == result.operational_error
    assert retried.report_path == result.report_path


@pytest.mark.unit
def test_current_evidence_requires_matching_controller_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, squad_dir, spec_dir = _workspace(tmp_path)
    monkeypatch.setattr(
        "harness.understanding_gate.analyze_spec_bundle",
        lambda *args, **kwargs: _bundle(),
    )
    result = run_understanding_gate(
        project_root=project,
        squad_dir=squad_dir,
        phase="phase1-why2",
        iteration=1,
        spec_dir=spec_dir,
        config={},
    )
    updates = result.state_updates([])
    state = {
        "spec_dir": spec_dir,
        "understanding_evidence": updates["understanding_evidence"],
        "quality_scores": [],
    }

    assert not has_current_understanding_evidence(
        state, project_root=project, phase="phase1-why2"
    )
    state["quality_scores"] = updates["quality_scores"]
    assert has_current_understanding_evidence(
        state, project_root=project, phase="phase1-why2"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "config_path",
    ["runtime/config-template.yml"],
)
def test_distributed_config_disables_automatic_diagrams_by_default(
    config_path: str,
) -> None:
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))

    assert payload["understanding"]["diagram"]["enabled"] is False


@pytest.mark.unit
def test_deterministic_executor_continues_completed_failure_without_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    project, squad_dir, spec_dir = _workspace(tmp_path)
    graph = PhaseGraph(
        root / "runtime/workflow/definition.yaml",
        prosaic_subagents_dir=root / "prosaic/subagents",
    )
    store = SquadStateStore(squad_dir)
    store.initialize("run-1", "greenfield", "demo", 0, "phase1-understanding")
    state = store.load()
    state["spec_dir"] = spec_dir
    state["iteration"] = 4
    store.save(state)
    executor = DeterministicUnderstandingExecutor(
        graph,
        root / "runtime",
        project,
        squad_dir,
    )

    monkeypatch.setattr(
        "harness.squad_executors.run_understanding_gate",
        lambda **kwargs: run_understanding_gate(
            **kwargs,
        ),
    )
    monkeypatch.setattr(
        "harness.understanding_gate.analyze_spec_bundle",
        lambda *args, **kwargs: _bundle(passed=False),
    )

    result = executor.execute(graph.get("phase1-understanding"), store)

    assert result.exit_code == 0
    assert result.verdict == "DONE"
    assert result.state_updates["quality_scores"][-1]["pass"] is False
    assert result.state_updates["understanding_evidence"]["phase"] == "phase1-why2"


@pytest.mark.unit
def test_deterministic_executor_blocks_operational_error_without_provider(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    project = tmp_path / "project"
    squad_dir = project / ".specify" / "squad" / "run-1"
    graph = PhaseGraph(
        root / "runtime/workflow/definition.yaml",
        prosaic_subagents_dir=root / "prosaic/subagents",
    )
    store = SquadStateStore(squad_dir)
    store.initialize("run-1", "greenfield", "demo", 0, "phase3-understanding")
    state = store.load()
    state["spec_dir"] = "specs/001-missing"
    store.save(state)
    executor = DeterministicUnderstandingExecutor(
        graph,
        root / "runtime",
        project,
        squad_dir,
    )

    result = executor.execute(graph.get("phase3-understanding"), store)

    assert result.exit_code == 0
    assert result.verdict == "BLOCKED"
    assert result.state_updates["blocked_reason"].startswith("spec.md not found:")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("target_phase", "gate_phase"),
    [
        ("phase1-why2", "phase1-understanding"),
        ("phase3-consensus", "phase3-understanding"),
    ],
)
def test_legacy_model_scored_resume_adds_certified_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_phase: str,
    gate_phase: str,
) -> None:
    root = Path(__file__).resolve().parents[2]
    project, squad_dir, spec_dir = _workspace(tmp_path)
    graph = PhaseGraph(
        root / "runtime/workflow/definition.yaml",
        prosaic_subagents_dir=root / "prosaic/subagents",
    )
    store = SquadStateStore(squad_dir)
    store.initialize("run-1", "greenfield", "demo", 0, target_phase)
    state = store.load()
    state.update(
        {
            "spec_dir": spec_dir,
            "iteration": 2,
            "quality_scores": [{"source": "sage", "pass": True}],
        }
    )
    store.save(state)
    controller = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=root / "runtime",
        project_root=project,
        squad_dir=squad_dir,
    )
    monkeypatch.setattr(
        "harness.understanding_gate.analyze_spec_bundle",
        lambda *args, **kwargs: _bundle(),
    )

    assert controller._guard_understanding_evidence(target_phase) == gate_phase
    node = graph.get(gate_phase)
    result = controller._executors["deterministic_understanding"].execute(node, store)
    snapshot = store.capture_routing_snapshot(expected_phase=gate_phase)
    prepared = controller._prepare_phase_result(node, result, snapshot)
    decision = store.prepare_routing_decision(
        prepared,
        snapshot=snapshot,
        from_phase=gate_phase,
        to_phase=target_phase,
    )
    store.advance(
        gate_phase,
        target_phase,
        decision,
    )

    migrated = store.load()
    assert migrated["quality_scores"][0] == {"source": "sage", "pass": True}
    assert migrated["quality_scores"][-1]["source"] == "harness:understanding"
    assert migrated["quality_scores"][-1]["pass_id"].endswith("iter-2")
    assert migrated["understanding_evidence"]["phase"] == target_phase
