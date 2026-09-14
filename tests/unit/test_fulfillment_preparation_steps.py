"""Preparation must retain the real writers' artifacts and CLI state semantics."""
import json

import pytest


@pytest.fixture
def inputs(tmp_path):
    spec, run, source = (tmp_path / name for name in ("spec", "run", "source"))
    for path in (spec, run, source):
        path.mkdir()
    (spec / "spec.md").write_text("# Spec\nFR-000001: Return a greeting.\n")
    (spec / "tasks.md").write_text("- [ ] T-000001 complexity=standard phase=build req=FR-000001 depends=none\n")
    (source / "app.py").write_text("def hello(): return 'hello'\n")
    (run / "state.json").write_text(json.dumps({"keep": "sentinel"}))
    return spec, run, source


def test_inventory_audit_and_coverage_preserve_rows_and_state(inputs):
    from harness import fulfillment_preparation_steps as steps
    spec, run, source = inputs
    inventory = steps.prepare_canonical_requirements(spec_dir=spec, verify_run_dir=run)
    product = steps.prepare_product_inventory(project_root=source, verify_run_dir=run)
    audit = steps.prepare_requirement_audit(verify_run_dir=run)
    coverage = steps.prepare_coverage(spec_dir=spec, verify_run_dir=run)
    state = json.loads((run / "state.json").read_text())
    assert inventory.count == audit.count == 1
    assert state == {"keep": "sentinel", "canonical_requirements": "ready",
                     "canonical_requirements_count": 1, "product_inventory": "ready",
                     "product_inventory_count": 1, "product_inventory_source": product.inventory_source,
                     "requirement_audit": "ready", "requirement_audit_count": 1,
                     "coverage_evidence": "ready"}
    assert "FR-000001" in audit.audit_path.read_text()
    assert json.loads(coverage.json_path.read_text())["observer_required"] is False
    assert json.loads(product.json_path.read_text())["entries"][0]["path"] == "app.py"


@pytest.mark.parametrize("step", ["canonical", "product", "audit", "coverage", "codegraph", "perlgraph", "map"])
def test_missing_state_cannot_create_replacement_or_artifacts(inputs, step):
    from harness import fulfillment_preparation_steps as steps
    spec, run, source = inputs
    (run / "state.json").unlink()
    calls = {
        "canonical": lambda: steps.prepare_canonical_requirements(spec_dir=spec, verify_run_dir=run),
        "product": lambda: steps.prepare_product_inventory(project_root=source, verify_run_dir=run),
        "audit": lambda: steps.prepare_requirement_audit(verify_run_dir=run),
        "coverage": lambda: steps.prepare_coverage(spec_dir=spec, verify_run_dir=run),
        "codegraph": lambda: steps.prepare_codegraph(project_root=source, spec_dir=spec, verify_run_dir=run),
        "perlgraph": lambda: steps.prepare_perlgraph(project_root=source, spec_dir=spec, verify_run_dir=run),
        "map": lambda: _map(steps, spec, run),
    }
    with pytest.raises(OSError):
        calls[step]()
    assert list(run.iterdir()) == []


def _map(steps, spec, run):
    return steps.prepare_evidence_map(
        requirement_audit_path=run / "requirement-audit.md",
        codegraph_analysis_path=run / "codegraph-analysis.json", tasks_path=spec / "tasks.md",
        out_json_path=run / "codegraph-evidence-map.json", out_md_path=run / "codegraph-evidence-map.md")


@pytest.mark.parametrize("provider,field", [("codegraph", "structural_evidence"), ("perlgraph", "perlgraph_evidence")])
def test_graph_runtime_unavailable_retains_degraded_artifacts(inputs, monkeypatch, provider, field):
    from harness import fulfillment_preparation_steps as steps
    from harness.codegraph_evidence import CodeGraphEvidenceError
    from harness.perlgraph_evidence import PerlGraphEvidenceError
    spec, run, source = inputs
    # Only the external Node runtime lookup is unavailable; the writer is real.
    monkeypatch.setattr(f"harness.{provider}_evidence.shutil.which", lambda name: None)
    with pytest.raises((CodeGraphEvidenceError, PerlGraphEvidenceError)):
        getattr(steps, f"prepare_{provider}")(project_root=source, spec_dir=spec, verify_run_dir=run)
    state = json.loads((run / "state.json").read_text())
    assert state[field] == "degraded" and state["keep"] == "sentinel"
    assert (run / f"{provider}-summary.json").is_file()
    assert (run / f"{provider}-error.txt").is_file()


@pytest.mark.parametrize("degraded", [True, False])
def test_absent_analysis_is_skipped_only_for_recorded_degradation(inputs, degraded):
    from harness import fulfillment_preparation_steps as steps
    spec, run, _ = inputs
    (run / "requirement-audit.md").write_text("# Audit\n")
    (run / "state.json").write_text(json.dumps({"structural_evidence": "degraded" if degraded else "ready"}))
    if degraded:
        assert _map(steps, spec, run) is None
        payload = json.loads((run / "codegraph-evidence-map.json").read_text())
        assert payload["status"] == "skipped_degraded_codegraph"
        assert payload["requirements"] == []
    else:
        with pytest.raises(FileNotFoundError, match="codegraph-analysis.json"):
            _map(steps, spec, run)
        assert not (run / "codegraph-evidence-map.json").exists()


@pytest.mark.parametrize("context", ["{", "[]", '{"schema_version": 1}', None])
def test_required_or_malformed_observation_is_not_silently_optional(inputs, context):
    from harness import fulfillment_preparation_steps as steps
    from harness.coverage_observation import CoverageObservationError
    spec, run, _ = inputs
    steps.prepare_canonical_requirements(spec_dir=spec, verify_run_dir=run)
    if context is not None:
        (run / "coverage-observation-context.json").write_text(context)
    with pytest.raises(CoverageObservationError):
        steps.prepare_coverage(spec_dir=spec, verify_run_dir=run, observer_required=context is None)
    state = json.loads((run / "state.json").read_text())
    assert state["coverage_evidence"] == "invalid"
    assert not (run / "coverage-evidence.json").exists()


@pytest.mark.parametrize("state_text", ["{", "[]"])
def test_legacy_inventory_step_retains_malformed_state_compatibility(inputs, state_text):
    from harness import fulfillment_preparation_steps as steps
    spec, run, _ = inputs
    (run / "state.json").write_text(state_text)
    steps.prepare_canonical_requirements(spec_dir=spec, verify_run_dir=run)
    assert json.loads((run / "state.json").read_text()) == {
        "canonical_requirements": "ready", "canonical_requirements_count": 1}


def test_cli_missing_map_input_retains_exit_two(inputs):
    from tests.unit.test_harness_main_fulfillment_artifacts import _run_harness
    spec, run, _ = inputs
    result = _run_harness(["write-codegraph-evidence-map", str(run / "requirement-audit.md"),
                           str(run / "codegraph-analysis.json"), str(spec / "tasks.md"),
                           str(run / "map.json"), str(run / "map.md")])
    assert result.returncode == 2
    assert "missing required input:" in result.stderr


@pytest.mark.parametrize("missing", ["requirement-audit.md", "codegraph-analysis.json", "tasks.md"])
def test_map_missing_inputs_have_direct_and_cli_parity(inputs, missing):
    from harness import fulfillment_preparation_steps as steps
    from tests.unit.test_harness_main_fulfillment_artifacts import _run_harness
    spec, run, _ = inputs
    (run / "requirement-audit.md").write_text("# Audit\n")
    (run / "codegraph-analysis.json").write_text("{}")
    missing_path = (spec if missing == "tasks.md" else run) / missing
    missing_path.unlink()
    before = (run / "state.json").read_bytes()
    with pytest.raises(FileNotFoundError, match=missing):
        _map(steps, spec, run)
    result = _run_harness(["write-codegraph-evidence-map", str(run / "requirement-audit.md"),
                           str(run / "codegraph-analysis.json"), str(spec / "tasks.md"),
                           str(run / "map.json"), str(run / "map.md")])
    assert result.returncode == 2
    assert result.stderr.strip() == f"missing required input: {missing_path}"
    assert not (run / "map.json").exists()
    assert not (run / "codegraph-evidence-map.json").exists()
    assert (run / "state.json").read_bytes() == before


@pytest.mark.parametrize("stale", [False, True])
@pytest.mark.parametrize("via_context", [False, True])
def test_observation_loading_checks_real_receipt_and_current_map(inputs, tmp_path, monkeypatch, stale, via_context):
    import hashlib
    from harness.fulfillment_preparation_steps import load_preparation_observation
    from harness.coverage_observation import CoverageObservationError
    from tests.unit import test_coverage_observation as observations
    spec, run, _ = inputs
    coverage_map = spec / "coverage-map.md"
    coverage_map.write_text("current coverage map")
    monkeypatch.setattr(observations, "_MAP_HASH", hashlib.sha256(coverage_map.read_bytes()).hexdigest())
    observation = observations._write_observation(tmp_path / "receipts")
    if via_context:
        (run / "coverage-observation-context.json").write_text(json.dumps({
            "schema_version": 1, "observer_required": True,
            "coverage_observation": observation.ref.as_mapping(),
        }))
    if stale:
        coverage_map.write_text("changed coverage map")
    before = (run / "state.json").read_bytes()
    kwargs = dict(spec_dir=spec, verify_run_dir=run, observer_required=not via_context,
                  observation_path=None if via_context else observation.ref.path)
    if stale:
        with pytest.raises(CoverageObservationError, match="fingerprint"):
            load_preparation_observation(**kwargs)
    else:
        required, loaded = load_preparation_observation(**kwargs)
        assert required and loaded.ref.observation_sha256 == observation.ref.observation_sha256
    assert (run / "state.json").read_bytes() == before
