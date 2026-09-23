"""Consuming tests for the inactive, explicitly bound preparation sequence."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.fulfillment_preparation import (
    FulfillmentPreparationContext, FulfillmentPreparationError, prepare_fulfillment_inputs,
)
from harness.verify_spec_run import init_verify_spec_run


@pytest.fixture(autouse=True)
def scripted_graph_tools(tmp_path, monkeypatch):
    from tests.unit.test_harness_main_codegraph_evidence import _write_fake_bridge
    from tests.unit.test_harness_main_perlgraph_evidence import _write_fake_perlgraph_cli
    bridge = _write_fake_bridge(tmp_path / "tools")
    perl = _write_fake_perlgraph_cli(tmp_path / "tools")
    monkeypatch.setattr("harness.codegraph_evidence.resolve_codegraph_bridge", lambda _: bridge)
    monkeypatch.setattr("harness.perlgraph_evidence.resolve_perlgraph_cli", lambda _: perl)
    return bridge, perl


@pytest.fixture
def preparation_context(tmp_path):
    workspace = tmp_path / "workspace"
    source = workspace / "sources/api"
    spec = workspace / "specs/001-greeting"
    source.mkdir(parents=True)
    spec.mkdir(parents=True)
    (workspace / ".echelon").mkdir()
    (workspace / ".echelon/config.yml").write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n")
    (source / "app.py").write_text("def hello(): return 'hello'\n")
    (spec / "spec.md").write_text(
        "# Spec\nFR-000001: Return a greeting.\nFR-002: Keep legacy identity.\n"
        "FR-1000000: Support large identity.\n")
    (spec / "tasks.md").write_text(
        "- [ ] T-000001 complexity=standard phase=build req=FR-000001 depends=none\n")
    run = init_verify_spec_run(project_root=source, spec_id="001", spec_dir=spec,
                               timestamp="preparation").verify_run_dir
    return FulfillmentPreparationContext(source, workspace, "api", source, "001", spec, run)


def _state(context, **updates):
    path = context.verify_run_dir / "state.json"
    state = json.loads(path.read_text())
    state.update(updates)
    path.write_text(json.dumps(state))


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _reject_without_writes(context, match):
    before = _snapshot(context.workspace_root)
    with pytest.raises(FulfillmentPreparationError, match=match):
        prepare_fulfillment_inputs(context)
    assert _snapshot(context.workspace_root) == before


@pytest.mark.parametrize("field,value", [
    ("spec_id", "different"), ("project_root", "/wrong"),
    ("orchestration_root", "/wrong"), ("spec_dir", "/wrong"),
    ("verify_run_dir", "/wrong"), ("verify_scope", "scoped"),
    ("scoped_ids", ["FR-000001"]), ("base_full_verify_commit", "a" * 40),
])
def test_wrong_binding_is_rejected_before_writes(preparation_context, field, value):
    _state(preparation_context, **{field: value})
    _reject_without_writes(preparation_context, field)


@pytest.mark.parametrize("state", ["{", "[]", '{"status":"complete"}', '{"status":"blocked"}'])
def test_malformed_or_terminal_state_is_rejected(preparation_context, state):
    (preparation_context.verify_run_dir / "state.json").write_text(state)
    _reject_without_writes(preparation_context, "state|in_progress")


@pytest.mark.parametrize("filename", ["state.json", "spec.md", "tasks.md"])
def test_missing_prerequisite_is_rejected(preparation_context, filename):
    root = preparation_context.verify_run_dir if filename == "state.json" else preparation_context.spec_dir
    (root / filename).unlink()
    _reject_without_writes(preparation_context, filename)


@pytest.mark.parametrize("filename", [
    "implementation-map.md", "judgment-prepass.json", "fulfillment-report.fallback.md",
])
def test_prior_semantic_artifacts_are_preserved(preparation_context, filename):
    (preparation_context.verify_run_dir / filename).write_text("prior evidence\n")
    _reject_without_writes(preparation_context, "semantic")


@pytest.mark.parametrize("updates", [
    {"source_id": "other"}, {"source_root": Path("/wrong")},
    {"scope": "invalid"}, {"scope": "scoped"},
    {"scoped_ids": ("FR-000001",)}, {"base_full_verify_commit": "a" * 40},
    {"scope": "scoped", "scoped_ids": ("FR-000001", "FR-000001")},
])
def test_invalid_context_is_rejected(preparation_context, updates):
    _reject_without_writes(replace(preparation_context, **updates), "source|scope|commit|duplicate")


@pytest.mark.parametrize("filename", [
    "state.json", "codegraph-analysis.json", "perlgraph-summary.json",
    "canonical-requirements.md", "requirement-audit.md", "coverage-evidence.json",
    "codegraph-evidence-map.md", "topology-receipt.json", "product-inventory.json",
])
def test_symlinked_destinations_are_rejected(preparation_context, tmp_path, filename):
    target = tmp_path / "outside"
    target.write_text("do not overwrite")
    path = preparation_context.verify_run_dir / filename
    path.unlink(missing_ok=True)
    path.symlink_to(target)
    _reject_without_writes(preparation_context, "symlink")
    assert target.read_text() == "do not overwrite"


@pytest.mark.parametrize("kind", ["missing", "malformed_context", "directory_context"])
def test_invalid_observation_is_rejected_before_graphs(preparation_context, kind):
    context = preparation_context
    if kind == "missing":
        context = replace(context, observer_required=True)
    elif kind == "malformed_context":
        (context.verify_run_dir / "coverage-observation-context.json").write_text("{")
    else:
        (context.verify_run_dir / "coverage-observation-context.json").mkdir()
    _reject_without_writes(context, "observation")


def test_real_preparation_order_and_artifacts(preparation_context, monkeypatch):
    import harness.fulfillment_preparation as preparation
    calls = []
    names = ["prepare_codegraph", "prepare_perlgraph", "write_topology_evidence_receipt",
             "prepare_canonical_requirements", "prepare_product_inventory",
             "prepare_requirement_audit", "prepare_coverage", "prepare_evidence_map"]
    for name in names:
        original = getattr(preparation, name)
        def spy(*args, _original=original, _name=name, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(preparation, name, spy)
    context = preparation_context
    spec_before = _snapshot(context.spec_dir)
    source_before = _snapshot(context.source_root)
    result = prepare_fulfillment_inputs(context)
    assert calls == names
    assert result.canonical_ids == ("FR-000001", "FR-002", "FR-1000000")
    assert result.scoped_ids == ()
    assert result.verify_run_dir == context.verify_run_dir
    assert result.topology_status == "ready"
    assert _snapshot(context.spec_dir) == spec_before
    assert _snapshot(context.source_root) == source_before  # fake tool's empty .codegraph is scratch
    expected = {"state.json", "codegraph-analysis.json", "codegraph-summary.json",
                "perlgraph-analysis.json", "perlgraph-summary.json", "topology-receipt.json",
                "canonical-requirements.json", "canonical-requirements.md",
                "product-inventory.json", "product-inventory.md", "requirement-audit.md",
                "coverage-evidence.json", "coverage-evidence.md",
                "codegraph-evidence-map.json", "codegraph-evidence-map.md"}
    assert set(_snapshot(context.verify_run_dir)) == expected
    state = json.loads((context.verify_run_dir / "state.json").read_text())
    for key in ("structural_evidence", "perlgraph_evidence", "topology_evidence",
                "canonical_requirements", "product_inventory", "requirement_audit",
                "coverage_evidence", "codegraph_evidence_map"):
        assert state[key] == "ready"
    assert state["status"] == "in_progress"
    assert state["canonical_requirements_count"] == state["requirement_audit_count"] == 3
    assert "fulfillment_artifacts" not in state
    assert not (context.spec_dir / "fulfillment-report.md").exists()
    assert not list(context.workspace_root.rglob("*ledger*"))


def test_scoped_preparation_keeps_full_inventory_and_exact_ids(preparation_context):
    context = replace(preparation_context, scope="scoped",
                      scoped_ids=("FR-002", "FR-1000000"), base_full_verify_commit="a" * 40)
    _state(context, verify_scope=context.scope, scoped_ids=list(context.scoped_ids),
           base_full_verify_commit=context.base_full_verify_commit)
    result = prepare_fulfillment_inputs(context)
    assert result.canonical_ids == ("FR-000001", "FR-002", "FR-1000000")
    assert result.scoped_ids == ("FR-002", "FR-1000000")
    assert json.loads((context.verify_run_dir / "state.json").read_text())["status"] == "in_progress"


def test_unknown_scoped_id_is_not_synthesized(preparation_context):
    context = replace(preparation_context, scope="scoped", scoped_ids=("FR-999999",))
    _state(context, verify_scope="scoped", scoped_ids=list(context.scoped_ids))
    with pytest.raises(FulfillmentPreparationError, match="unknown scoped"):
        prepare_fulfillment_inputs(context)
    inventory = json.loads((context.verify_run_dir / "canonical-requirements.json").read_text())
    assert [row["id"] for row in inventory["requirements"]] == ["FR-000001", "FR-002", "FR-1000000"]


@pytest.mark.parametrize("failed", [("codegraph",), ("perlgraph",), ("codegraph", "perlgraph")])
def test_typed_graph_failures_preserve_degradation(preparation_context, scripted_graph_tools, failed):
    for provider, path in zip(("codegraph", "perlgraph"), scripted_graph_tools):
        if provider in failed:
            path.write_text('process.stderr.write("scripted graph failure"); process.exit(1);')
    result = prepare_fulfillment_inputs(preparation_context)
    assert result.topology_status == ("unavailable" if len(failed) == 2 else "degraded")
    state = json.loads((result.verify_run_dir / "state.json").read_text())
    assert state["status"] == "in_progress"
    for provider in failed:
        assert (result.verify_run_dir / f"{provider}-error.txt").is_file()
        key = "structural_evidence" if provider == "codegraph" else "perlgraph_evidence"
        assert state[key] == "degraded"
    assert state["codegraph_evidence_map"] == (
        "skipped_degraded_codegraph" if "codegraph" in failed else "ready")


def test_unexpected_graph_failure_is_not_degradation(preparation_context, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("unexpected writer defect")
    monkeypatch.setattr("harness.fulfillment_preparation.prepare_codegraph", broken)
    with pytest.raises(FulfillmentPreparationError, match="codegraph.*unexpected writer defect"):
        prepare_fulfillment_inputs(preparation_context)
    state = json.loads((preparation_context.verify_run_dir / "state.json").read_text())
    assert state["structural_evidence"] == "pending"
    assert not (preparation_context.verify_run_dir / "perlgraph-analysis.json").exists()


@pytest.mark.parametrize("kind", ["run_outside", "run_symlink", "runs_symlink", "spec_outside"])
def test_path_escape_is_rejected(preparation_context, tmp_path, kind):
    context = preparation_context
    outside = tmp_path / "outside"
    if kind == "spec_outside":
        context.spec_dir.rename(outside)
        context = replace(context, spec_dir=outside)
    elif kind == "runs_symlink":
        (context.workspace_root / "runs").rename(outside)
        (context.workspace_root / "runs").symlink_to(outside, target_is_directory=True)
    else:
        context.verify_run_dir.rename(outside)
        if kind == "run_symlink":
            context.verify_run_dir.symlink_to(outside, target_is_directory=True)
        else:
            context = replace(context, verify_run_dir=outside)
    before = _snapshot(outside)
    _reject_without_writes(context, "escapes|symlink")
    assert _snapshot(outside) == before


def test_source_root_must_match_registered_source(preparation_context):
    _reject_without_writes(replace(preparation_context, source_root=preparation_context.spec_dir), "source")


def test_managed_delivery_worktree_is_accepted(preparation_context):
    import subprocess
    context = preparation_context
    def git(*args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    git("init", "-b", "main", cwd=context.source_root)
    git("add", ".", cwd=context.source_root)
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture",
        cwd=context.source_root)
    mirror = context.workspace_root / "runs/mirror.git"
    git("clone", "--mirror", str(context.source_root), str(mirror), cwd=context.workspace_root)
    worktree = context.workspace_root / "runs/build/worktrees/iter-0"
    worktree.parent.mkdir(parents=True)
    git("worktree", "add", "-b", "harness/test", str(worktree), "main", cwd=mirror)
    context = replace(context, project_root=worktree)
    _state(context, project_root=str(worktree))
    result = prepare_fulfillment_inputs(context)
    receipt = json.loads((result.verify_run_dir / "topology-receipt.json").read_text())
    assert result.topology_status == "ready"
    assert receipt["source_id"] == "api"
    assert receipt["source_path"] == "sources/api"


def test_arbitrary_alternate_project_is_rejected(preparation_context, tmp_path):
    project = tmp_path / "arbitrary"
    project.mkdir()
    context = replace(preparation_context, project_root=project)
    _state(context, project_root=str(project))
    _reject_without_writes(context, "worktree")


def test_unsupported_graph_is_explicit_evidence(preparation_context, scripted_graph_tools):
    from tests.unit.test_topology_evidence import _perl_unsupported, _summary
    perl = scripted_graph_tools[1]
    analysis = _perl_unsupported()
    analysis["repo_path"] = str(preparation_context.project_root)
    # Script only the external process. Real graph and topology validators consume the output.
    perl.write_text(
        'const fs = require("fs"); const args = process.argv;\n'
        f'fs.writeFileSync(args[args.indexOf("--output-path")+1], {json.dumps(json.dumps(analysis))});\n'
        f'fs.writeFileSync(args[args.indexOf("--summary-path")+1], '
        f'{json.dumps(json.dumps(_summary("perlgraph", analysis)))});\n')
    result = prepare_fulfillment_inputs(preparation_context)
    receipt = json.loads((result.verify_run_dir / "topology-receipt.json").read_text())
    assert result.topology_status == "ready"
    assert receipt["providers"]["perlgraph"]["status"] == "unsupported"


@pytest.mark.parametrize("via_context", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_real_observation_is_validated_before_preparation(
    preparation_context, tmp_path, monkeypatch, via_context, stale,
):
    import hashlib
    from tests.unit import test_coverage_observation as observations
    context = preparation_context
    coverage_map = context.spec_dir / "coverage-map.md"
    coverage_map.write_text("# Coverage\n")
    monkeypatch.setattr(observations, "_MAP_HASH", hashlib.sha256(coverage_map.read_bytes()).hexdigest())
    observation = observations._write_observation(tmp_path / "receipts")
    if via_context:
        (context.verify_run_dir / "coverage-observation-context.json").write_text(json.dumps({
            "schema_version": 1, "observer_required": True,
            "coverage_observation": observation.ref.as_mapping(),
        }))
    else:
        context = replace(context, observer_required=True, observation_path=observation.ref.path)
    if stale:
        coverage_map.write_text("# Changed coverage\n")
        _reject_without_writes(context, "observation.*fingerprint")
    else:
        result = prepare_fulfillment_inputs(context)
        assert result.canonical_ids == ("FR-000001", "FR-002", "FR-1000000")
        evidence = json.loads((result.verify_run_dir / "coverage-evidence.json").read_text())
        assert evidence["observer_required"] is True


@pytest.mark.parametrize("rows", [[None], [{"id": "invalid"}], [{"id": "FR-001"}, {"id": "FR-001"}]])
def test_invalid_generated_inventory_is_rejected(preparation_context, monkeypatch, rows):
    import harness.fulfillment_preparation as preparation
    original = preparation.prepare_canonical_requirements
    def corrupt(**kwargs):
        result = original(**kwargs)
        result.json_path.write_text(json.dumps({"requirements": rows}))
        return result
    monkeypatch.setattr(preparation, "prepare_canonical_requirements", corrupt)
    with pytest.raises(FulfillmentPreparationError, match="canonical.*invalid|canonical.*duplicate"):
        prepare_fulfillment_inputs(preparation_context)
    assert not (preparation_context.verify_run_dir / "product-inventory.json").exists()


def test_prior_report_and_current_run_pointer_are_untouched(preparation_context):
    context = preparation_context
    (context.spec_dir / "fulfillment-report.md").write_text("prior canonical report")
    (context.workspace_root / "runs/.current").write_text("some-other-run")
    before = _snapshot(context.spec_dir)
    result = prepare_fulfillment_inputs(context)
    assert result.verify_run_dir == context.verify_run_dir
    assert _snapshot(context.spec_dir) == before
    assert (context.workspace_root / "runs/.current").read_text() == "some-other-run"
