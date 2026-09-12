from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from echelon.spec_graph import GraphEdge, GraphInput, GraphNode, SpecArtifactGraph, SpecGraphError
from harness.squad_publication_snapshot import PublicationImageDescriptor
from harness.squad_source_snapshot import (
    ProjectDirectorySnapshot, ProjectFileSnapshot, ProjectTreeSnapshot,
)


pytestmark = pytest.mark.unit


def _tree(files=None, *, root="specs/demo", directories=(), exists=True):
    """Construct valid detached fixture images; no physical capture or skip."""
    files = files or {}
    names = {root} if exists else set()
    for name in (*files, *directories):
        path = PurePosixPath(root, name)
        names.update(parent.as_posix() for parent in path.parents if parent.as_posix().startswith(root))
    names.update(f"{root}/{name}" for name in directories)
    return ProjectTreeSnapshot(
        root, exists,
        tuple(ProjectDirectorySnapshot(name, 0o755) for name in sorted(names)),
        tuple(ProjectFileSnapshot(
            f"{root}/{name}",
            PublicationImageDescriptor("file", hashlib.sha256(data).hexdigest(), 0o644), data,
        ) for name, data in sorted(files.items())),
    )


def _build(tree, *, spec_id="demo", lifecycle="phase_a"):
    from echelon.spec_graph_structure import build_spec_graph_structure
    return build_spec_graph_structure(spec_id=spec_id, tree=tree, lifecycle=lifecycle)


def _render(structure):
    """A test-only structural container, deliberately not the complete graph wire."""
    return (json.dumps({
        "spec_id": structure.spec_id,
        "inputs": [item.to_dict() for item in sorted(structure.inputs, key=lambda item: (item.role, item.path))],
        "nodes": [item.to_dict() for item in sorted(structure.nodes, key=lambda item: item.id)],
        "edges": [item.to_dict() for item in sorted(structure.edges, key=lambda item: (item.source, item.type, item.target))],
    }, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _json(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _rich_files():
    return {
        "spec.md": (
            "# Café\r\n\r\n- FR-016b: Keep legacy.\r\n"
            "- AC-000001: Café naïve.\r\n- FR-1000000: Keep identity.\r\n"
            "- NFR-10000000: Stay quick.\r\nReference FR-777777 and FR-888888.\r\n"
        ).encode(),
        "plan.md": b"- FR-777777: Plan definition supersedes the reference.\n- FR-1000000: Does not supersede spec.\n",
        "coverage-map.md": b"- FR-888888: Coverage definition supersedes reference.\n- FR-999999: Coverage only.\n",
        "tasks.md": (
            "- [x] T-10000000 complexity=standard phase=verify req=FR-1000000,AC-000001,FR-777777,FR-999999,UNMAPPED depends=none target=ui/app\r\n"
            "  **Status:** DONE_WITH_CONCERNS\r\n"
            "- [ ] T-000001 complexity=trivial phase=build req=INFRA depends=none\r\n"
            "- [ ] T-999999 complexity=complex phase=build req=FR-016b,NFR-10000000,FR-1234567 depends=T-000001\r\n"
            "  **Status:** DEFERRED\r\n"
        ).encode(),
        "inputs/manifest.json": b'{"schema_version":1}',
        "inputs/catalog.json": b'{"units":[{"id":"unit-a"},{"id":"unit-b"}]}',
        "inputs/traceability.json": _json({"requirements": [
            {"input_unit_id": "unit-b", "spec_ids": ["FR-1000000", "AC-000001"]},
            {"input_unit_id": " unit-a ", "spec_ids": ["FR-1000000", "FR-777777"]},
            {"input_unit_id": "unit-b", "spec_ids": ["FR-1000000"]},
        ]}),
        "deferred-scope.json": _json({"schema_version": 1, "entries": [
            {"entry_id": "d-1", "status": "deferred", "selected_ids": ["FR-016b", "FR-absent"],
             "derived_task_ids": ["T-999999"], "prior_task_statuses": {"T-999999": "PENDING"},
             "reason": "Décision", "deferred_at": "2026-09-13", "planned_at": None},
            {"entry_id": "d-2", "status": "planned", "selected_ids": ["FR-1000000"],
             "derived_task_ids": ["T-000001"], "prior_task_statuses": {},
             "reason": "Restored", "deferred_at": "2026-09-12", "planned_at": "2026-09-13"},
        ]}),
        "verified-fulfillment-ledger.json": _json({"schema_version": 2, "rows": [
            {"requirement_id": "FR-1000000", "status": "implemented", "evidence_refs": ["src/a.py", "tests/a.py"],
             "verified_commit": "abc123", "verified_at": "2026-09-13", "spec_input_hash": "old-spec",
             "implementation_input_hash": "old-impl", "artifact_hashes": {"src/a.py": "old-hash"},
             "verifier_version": "v2", "verify_scope": "full", "source_report_path": "runs/old/report.md",
             "selected_evidence": ["tests/a.py"], "receipt_refs": [{"path": "runs/old/receipt.json", "receipt_sha256": "receipt-a", "evidence_sha256": "evidence-a"}],
             "candidate_content_fingerprint": "candidate-a", "requirement_set_fingerprint": "requirements-a", "contract_hash": "contract-a"},
            {"requirement_id": "AC-000001", "status": "partial"},
            {"requirement_id": "FR-777777", "status": "implemented"},
        ]}),
        "amendments/002/change-request.md": b"# Change\n",
        "amendments/002/impact.md": b"# Impact\n",
        "amendments/002/inputs/manifest.json": b"{}",
        "amendments/002/inputs/catalog.json": b"{}",
        "amendments/002/inputs/traceability.json": b"{}",
        "amendments/not-numeric/change-request.md": b"ignored",
        "amendments/002/unselected.md": b"ignored",
        ".hidden.bin": b"\x00\xff",
        "re-context.json": b'{"status":"attached","artifacts":[]}',
    }


def _rich_expected(files):
    """Hand-derived complete records, independent of production transformations."""
    from echelon.spec_graph_structure import SpecGraphStructure
    nodes = [GraphNode("spec:demo", "Spec", {"spec_id": "demo", "path": "specs/demo", "lifecycle": "build"})]
    edges = []
    for item_id, category, line, text in (
        ("AC-000001", "acceptance", 4, "- AC-000001: Café naïve."),
        ("FR-1000000", "functional", 5, "- FR-1000000: Keep identity."),
        ("FR-016b", "functional", 3, "- FR-016b: Keep legacy."),
        ("NFR-10000000", "non_functional", 6, "- NFR-10000000: Stay quick."),
    ):
        nodes.append(GraphNode(f"req:demo:{item_id}", "Requirement", {
            "requirement_id": item_id, "category": category, "source_line": line,
            "source_path": "specs/demo/spec.md", "source_text": text,
        }))
        edges.append(GraphEdge("spec:demo", "HAS_REQUIREMENT", f"req:demo:{item_id}", {}))
    # Explicit policy selection/roles: neither the registry nor builder chooses expectations.
    artifacts = (
        ("coverage-map.md", "supporting-context", False, "mined"),
        ("inputs/catalog.json", "product-input", False, "not-mined-by-policy"),
        ("inputs/manifest.json", "product-input", False, "not-mined-by-policy"),
        ("inputs/traceability.json", "product-input", False, "not-mined-by-policy"),
        ("plan.md", "supporting-context", False, "mined"),
        ("re-context.json", "reverse-engineering", False, "not-mined-by-policy"),
        ("spec.md", "requirements-source", True, "mined"),
        ("tasks.md", "task-source", True, "mined"),
        ("verified-fulfillment-ledger.json", "verification-evidence", False, "mined"),
        ("amendments/002/change-request.md", "amendment-control", False, "not-mined-by-policy"),
        ("amendments/002/impact.md", "amendment-control", False, "not-mined-by-policy"),
        ("amendments/002/inputs/manifest.json", "amendment-control", False, "not-mined-by-policy"),
        ("amendments/002/inputs/catalog.json", "amendment-control", False, "not-mined-by-policy"),
        ("amendments/002/inputs/traceability.json", "amendment-control", False, "not-mined-by-policy"),
    )
    inputs = []
    for name, role, required, mining_status in artifacts:
        path = f"specs/demo/{name}"
        digest = "sha256:" + hashlib.sha256(files[name]).hexdigest()
        nodes.append(GraphNode(f"artifact:demo:{path}", "Artifact", {
            "path": path, "role": role, "hash": digest, "mining_status": mining_status,
        }))
        inputs.append(GraphInput(path, digest, role.replace("-", "_"), required, None, None))
    for task, status, phase, target, unresolved, implemented in (
        ("T-10000000", "DONE_WITH_CONCERNS", "verify", "ui/app", ["FR-777777", "FR-999999"], ["AC-000001", "FR-1000000"]),
        ("T-000001", "PENDING", "build", None, [], []),
        ("T-999999", "DEFERRED", "build", None, ["FR-1234567"], ["FR-016b", "NFR-10000000"]),
    ):
        nodes.append(GraphNode(f"task:demo:{task}", "Task", {
            "task_id": task, "status": status, "phase": phase, "target": target,
            "unresolved_requirement_ids": unresolved,
        }))
        edges.extend(GraphEdge(f"task:demo:{task}", "IMPLEMENTS", f"req:demo:{item}", {}) for item in implemented)
    edges.extend([
        GraphEdge("req:demo:AC-000001", "DERIVED_FROM", "artifact:demo:specs/demo/inputs/catalog.json", {"input_unit_ids": ["unit-b"]}),
        GraphEdge("req:demo:FR-1000000", "DERIVED_FROM", "artifact:demo:specs/demo/inputs/catalog.json", {"input_unit_ids": ["unit-a", "unit-b"]}),
    ])
    for entry, status, selected, derived, reason in (
        ("d-1", "deferred", ["FR-016b", "FR-absent"], ["T-999999"], "Décision"),
        ("d-2", "planned", ["FR-1000000"], ["T-000001"], "Restored"),
    ):
        nodes.append(GraphNode(f"deferral:demo:{entry}", "Deferral", {
            "entry_id": entry, "status": status, "selected_ids": selected,
            "derived_task_ids": derived, "reason": reason,
        }))
    edges.extend([
        GraphEdge("req:demo:FR-016b", "DEFERRED_BY", "deferral:demo:d-1", {}),
        GraphEdge("task:demo:T-999999", "DEFERRED_BY", "deferral:demo:d-1", {}),
    ])
    for revision in ("002", "10"):
        nodes.append(GraphNode(f"amendment:demo:{revision}", "Amendment", {
            "revision": revision, "path": f"specs/demo/amendments/{revision}", "status": "promoted",
        }))
        edges.append(GraphEdge("spec:demo", "AMENDED_BY", f"amendment:demo:{revision}", {}))
    edges.extend([
        GraphEdge("req:demo:FR-1000000", "VERIFIED_BY", "artifact:demo:specs/demo/verified-fulfillment-ledger.json", {
            "verification_status": "IMPLEMENTED", "evidence_refs": ["src/a.py", "tests/a.py"],
            "verified_commit": "abc123", "verify_scope": "full", "selected_evidence": ["tests/a.py"],
            "receipt_refs": [{"path": "runs/old/receipt.json", "receipt_sha256": "receipt-a", "evidence_sha256": "evidence-a"}],
            "candidate_content_fingerprint": "candidate-a", "requirement_set_fingerprint": "requirements-a",
            "contract_hash": "contract-a", "complete": True,
        }),
        GraphEdge("req:demo:AC-000001", "VERIFIED_BY", "artifact:demo:specs/demo/verified-fulfillment-ledger.json", {
            "verification_status": "PARTIAL", "evidence_refs": [], "verified_commit": "", "verify_scope": "",
            "selected_evidence": [], "receipt_refs": [], "candidate_content_fingerprint": "",
            "requirement_set_fingerprint": "", "contract_hash": "", "complete": False,
        }),
    ])
    return SpecGraphStructure("demo", tuple(inputs), tuple(nodes), tuple(edges))


def test_rich_structure_has_complete_independent_records_and_rendered_bytes():
    files = _rich_files()
    result = _build(_tree(files, directories=("amendments/10",)), lifecycle="build")
    expected = _rich_expected(files)
    assert sorted(result.inputs, key=lambda item: item.path) == sorted(expected.inputs, key=lambda item: item.path)
    assert sorted(result.nodes, key=lambda item: item.id) == sorted(expected.nodes, key=lambda item: item.id)
    assert result.edges == expected.edges
    assert [node.id for node in result.nodes if node.type == "Task"] == [
        "task:demo:T-10000000", "task:demo:T-000001", "task:demo:T-999999",
    ]
    assert _render(result) == _render(expected)


def test_physical_roots_do_not_change_any_records_or_bytes():
    files = _rich_files()
    canonical = _build(_tree(files, directories=("amendments/10",)), lifecycle="build")
    run_local = _build(_tree(files, root="runs/spec-123/staging/not-demo", directories=("amendments/10",)), lifecycle="build")
    assert run_local == canonical
    assert _render(run_local) == _render(canonical)
    assert b"runs/spec-123" not in _render(run_local)


@pytest.mark.parametrize("exists", [False, True])
def test_missing_and_empty_roots_return_only_observed_spec(exists):
    result = _build(_tree(exists=exists), spec_id="007-café [draft]:✓", lifecycle="landed")
    assert result.inputs == result.edges == ()
    assert result.nodes == (GraphNode("spec:007-café [draft]:✓", "Spec", {
        "spec_id": "007-café [draft]:✓", "path": "specs/007-café [draft]:✓", "lifecycle": "landed",
    }),)


@pytest.mark.parametrize("lifecycle,required", [("phase_a", False), ("build", True), ("verified", True), ("landed", True)])
def test_lifecycle_is_explicit_and_sets_only_task_required_policy(lifecycle, required):
    result = _build(_tree({
        "spec.md": b"---\nstatus: landed\n---\n- FR-001: Good.\n",
        "tasks.md": b"- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n",
    }), lifecycle=lifecycle)
    assert result.nodes[0].properties["lifecycle"] == lifecycle
    assert {item.path: item.required for item in result.inputs} == {
        "specs/demo/spec.md": True, "specs/demo/tasks.md": required,
    }


@pytest.mark.parametrize("status,complete", [
    ("implemented", True), ("missing", False), ("partial", False),
    ("deviated", False), ("unverified", False), ("waived", True), ("", True),
])
def test_verified_status_retains_legacy_complete_interpretation(status, complete):
    result = _build(_tree({
        "spec.md": b"- FR-001: Good.\n",
        "verified-fulfillment-ledger.json": _json({"rows": [{"requirement_id": "FR-001", "status": status}]}),
    }))
    assert result.edges[-1] == GraphEdge("req:demo:FR-001", "VERIFIED_BY", "artifact:demo:specs/demo/verified-fulfillment-ledger.json", {
        "verification_status": status.upper(), "evidence_refs": [], "verified_commit": "", "verify_scope": "",
        "selected_evidence": [], "receipt_refs": [], "candidate_content_fingerprint": "",
        "requirement_set_fingerprint": "", "contract_hash": "", "complete": complete,
    })


@pytest.mark.parametrize("status", ["PENDING", "BLOCKED", "DONE", "DONE_WITH_CONCERNS", "DEGRADED", "DEFERRED", "HISTORICAL"])
def test_task_status_retains_existing_progress_observation(status):
    result = _build(_tree({"tasks.md": (
        f"- [ ] T-1000000 complexity=standard phase=build req=INFRA,UNMAPPED depends=none\n  **Status:** {status}\n"
    ).encode()}))
    assert result.nodes[-1] == GraphNode("task:demo:T-1000000", "Task", {
        "task_id": "T-1000000", "status": status, "phase": "build", "target": None,
        "unresolved_requirement_ids": [],
    })


@pytest.mark.parametrize("files,rejected", [
    ({}, False), ({"spec.md": b""}, False), ({"tasks.md": b""}, True),
    ({"tasks.md": b"malformed secret"}, True),
    ({"tasks.md": b"- [ ] T-001 complexity=standard phase=build req=INFRA depends=none\n" * 2}, True),
    ({"tasks.md": b"\xff"}, True),
    ({"deferred-scope.json": b""}, True), ({"deferred-scope.json": b"{secret"}, True),
    ({"deferred-scope.json": b"\xff"}, True),
    ({"deferred-scope.json": b'{"schema_version":1,"entries":[]}'}, False),
    ({"verified-fulfillment-ledger.json": b""}, True),
    ({"verified-fulfillment-ledger.json": b"{secret"}, True),
    ({"verified-fulfillment-ledger.json": b"\xff"}, True),
    ({"verified-fulfillment-ledger.json": b"{}"}, False),
    ({"verified-fulfillment-ledger.json": b'{"rows":[7]}'}, False),
    ({"inputs/traceability.json": b"{secret"}, False),
    ({"inputs/traceability.json": b"{secret", "inputs/catalog.json": b"{}"}, True),
    ({"inputs/traceability.json": b"\xff", "inputs/catalog.json": b"{}"}, True),
    ({"inputs/traceability.json": b"[]", "inputs/catalog.json": b"{}"}, True),
    ({"inputs/traceability.json": b'{"requirements":{}}', "inputs/catalog.json": b"{}"}, True),
    ({"inputs/traceability.json": b'{"requirements":[7]}', "inputs/catalog.json": b"{}"}, True),
    ({"inputs/traceability.json": b'{"requirements":[{"spec_ids":{}}]}', "inputs/catalog.json": b"{}"}, True),
    ({"inputs/traceability.json": b"{}", "inputs/catalog.json": b"\xff", "inputs/manifest.json": b"{secret"}, False),
    ({"re-context.json": b"{secret"}, False),
])
def test_file_presence_decoding_and_parser_contracts(files, rejected):
    if rejected:
        with pytest.raises(SpecGraphError) as caught:
            _build(_tree(files))
        assert str(caught.value) == "invalid captured spec graph structure"
        assert caught.value.__cause__ is caught.value.__context__ is None
    else:
        _build(_tree(files))


def test_requirement_sources_keep_utf8_replacement():
    result = _build(_tree({"spec.md": b"- FR-1000000: Caf\xff.\r\n", "plan.md": b"\xff", "coverage-map.md": b"\xff"}))
    assert result.nodes[1] == GraphNode("req:demo:FR-1000000", "Requirement", {
        "requirement_id": "FR-1000000", "category": "functional", "source_line": 1,
        "source_path": "specs/demo/spec.md", "source_text": "- FR-1000000: Caf�.",
    })


@pytest.mark.parametrize("name,rejected", [("spec.md", False), ("tasks.md", False), ("deferred-scope.json", True), ("verified-fulfillment-ledger.json", False)])
def test_directories_preserve_reader_presence_rules(name, rejected):
    tree = _tree(directories=(name,))
    if rejected:
        with pytest.raises(SpecGraphError):
            _build(tree)
    else:
        assert _build(tree).inputs == ()


class _String(str):
    pass


class _Tree(ProjectTreeSnapshot):
    pass


@pytest.mark.parametrize("spec_id", [None, 7, b"demo", _String("demo"), "", " demo", "demo ", ".", "..", "a/b", "a\\b", "a\0b", "a\nb", "a\x7fb", "a\x85b", "\ud800"])
def test_unsafe_or_inexact_spec_ids_reject_without_exception_document(spec_id):
    with pytest.raises(SpecGraphError) as caught:
        _build(_tree(), spec_id=spec_id)
    assert caught.value.__cause__ is caught.value.__context__ is None


@pytest.mark.parametrize("lifecycle", [None, 1, b"build", _String("build"), "", "Build", "build ", "active"])
def test_unknown_or_inexact_lifecycle_rejects(lifecycle):
    with pytest.raises(SpecGraphError):
        _build(_tree(), lifecycle=lifecycle)


def _damaged_trees():
    valid = _tree({"spec.md": b"- FR-001: Good.\n"})
    file = valid.files[0]
    return [
        None, {}, _Tree(valid.path, valid.exists, valid.directories, valid.files),
        replace(valid, exists=1), replace(valid, path="../demo"),
        replace(valid, directories=list(valid.directories)), replace(valid, files=list(valid.files)),
        replace(valid, files=(replace(file, content=b"changed"),)),
        replace(valid, files=(replace(file, content=bytearray(file.content)),)),
        replace(valid, files=(replace(file, image=replace(file.image, mode=True)),)),
        replace(valid, files=(replace(file, image=replace(file.image, sha256="0" * 64)),)),
        replace(valid, files=(replace(file, path="specs/demolition/spec.md"),)),
        replace(valid, files=(replace(file, path="specs/demo/missing/spec.md"),)),
        replace(valid, files=(file, file)), replace(valid, directories=()),
        replace(valid, exists=False),
        replace(valid, directories=(replace(valid.directories[0], mode=-1),)),
    ]


@pytest.mark.parametrize("tree", _damaged_trees())
def test_damaged_or_unsupported_snapshots_are_rejected(tree):
    with pytest.raises(SpecGraphError) as caught:
        _build(tree)
    assert str(caught.value) == "invalid captured spec graph structure"
    assert caught.value.__cause__ is caught.value.__context__ is None


def test_outputs_own_records_and_all_nested_mutable_properties():
    from echelon.spec_graph_structure import SpecGraphStructure
    tree = _tree(_rich_files(), directories=("amendments/10",))
    before = deepcopy(tree)
    retained = _build(tree, lifecycle="build")
    expected = _rich_expected(_rich_files())
    other = _build(tree, lifecycle="build")
    assert tree == before
    for item in other.nodes:
        item.properties.clear()
    for item in other.edges:
        for value in item.properties.values():
            if isinstance(value, list):
                for nested in value:
                    if isinstance(nested, dict):
                        nested.clear()
                value.clear()
        item.properties.clear()
    source = next(item for item in tree.files if item.path == "specs/demo/spec.md")
    object.__setattr__(source, "content", b"changed")
    object.__setattr__(source.image, "sha256", "f" * 64)
    object.__setattr__(source, "path", "runs/changed/spec.md")
    object.__setattr__(tree, "files", ())
    assert _render(retained) == _render(expected)
    assert not isinstance(retained, (SpecArtifactGraph, ProjectTreeSnapshot))
    assert not hasattr(retained, "generator_version")
    assert not hasattr(retained, "memory_receipts")
    assert not hasattr(retained, "source_set_digest")
    with pytest.raises(FrozenInstanceError):
        retained.spec_id = "different"
    # The carrier is deliberately not a validator for manually assembled values.
    assert SpecGraphStructure("", (), (), ()).spec_id == ""


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_process_control_exceptions_escape_the_public_boundary(monkeypatch, error):
    import echelon.spec_graph_structure as structure
    def stop(**kwargs):
        raise error("stop")
    monkeypatch.setattr(structure, "extract_canonical_requirements_from_texts", stop)
    with pytest.raises(error):
        _build(_tree())


def test_legacy_graph_local_boundary_matches_complete_fragment(tmp_path, secure_posix, monkeypatch):
    import echelon.spec_graph as graph_module
    import echelon.mempalace_audit as memory_audit
    import echelon.mempalace_requirements as memory
    import echelon.mempalace_spec_evidence as evidence
    from echelon.spec_graph_structure import SpecGraphStructure
    from harness.squad_source_snapshot import inspect_project_tree

    spec_dir = tmp_path / "specs/demo"
    files = _rich_files()
    # Explicit frontmatter supplies a real build/verified lifecycle observation.
    files["spec.md"] = b"---\nstatus: ready_to_land\n---\n" + files["spec.md"]
    for name, data in files.items():
        path = spec_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (spec_dir / "amendments/10").mkdir()
    with inspect_project_tree(tmp_path, "specs/demo") as tree:
        pass

    class Adapter:
        wing = "fixture-wing"
        palace_path = tmp_path / "unused-memory"

        def plan_canonical_rows(self, content, *, source, artifact_metadata):
            return []

        def plan_canonical_support_rows(self, content, *, source, artifact_metadata):
            return []

        def plan_spec_evidence_artifact_rows(self, content, *, source, artifact_metadata):
            return []

    monkeypatch.setattr(memory, "create_requirement_memory_adapter", lambda project_root, run_id: Adapter())
    monkeypatch.setattr(evidence, "create_spec_evidence_memory_adapter", lambda project_root, run_id: Adapter())
    monkeypatch.setattr(memory_audit, "audit_spec_memory", lambda project_root, selector: SimpleNamespace(
        schema_version=1, wing="fixture-wing", status="pass", expected_count=0,
        present_current_count=0, missing=[], stale=[], wrong_wing=[], wrong_room=[],
        duplicate=[], non_canonical=[], lifecycle_excluded=[], errors=[],
    ))
    monkeypatch.setattr(evidence, "audit_spec_evidence_memory", memory_audit.audit_spec_memory)
    original = graph_module._add_canonical_memory
    observed = []

    def retain_then_enrich(root, spec_dir, nodes, edges, inputs, receipts):
        observed.append(deepcopy(SpecGraphStructure("demo", tuple(inputs.values()), tuple(nodes.values()), tuple(edges))))
        return original(root, spec_dir, nodes, edges, inputs, receipts)

    monkeypatch.setattr(graph_module, "_add_canonical_memory", retain_then_enrich)
    full = graph_module.build_spec_graph(tmp_path, spec_dir)
    captured = _build(tree, lifecycle="verified")
    assert observed == [captured]
    assert _render(observed[0]) == _render(captured)
    assert {item.path: item for item in captured.inputs}["specs/demo/tasks.md"].role == "task_source"
    final_inputs = {item.path: item for item in full.inputs}
    task_input = next(item for item in captured.inputs if item.path == "specs/demo/tasks.md")
    assert final_inputs["specs/demo/tasks.md"] == replace(task_input, role="supporting_context")
    task_artifact = next(node for node in captured.nodes if node.id == "artifact:demo:specs/demo/tasks.md")
    final_nodes = {node.id: node for node in full.nodes}
    assert final_nodes[task_artifact.id] == replace(task_artifact, properties={**task_artifact.properties, "role": "supporting-context"})
    assert {receipt.domain for receipt in full.memory_receipts} == {"canonical-spec", "spec-evidence"}


def test_structure_composes_with_real_sealed_source_publication(tmp_path, secure_posix):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_projection import project_publication_source_images
    from harness.squad_source_snapshot import inspect_project_tree

    project = tmp_path.resolve()
    spec_dir = project / "specs/demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_bytes(b"- FR-001: Original.\n")
    (spec_dir / "tasks.md").write_bytes(b"- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n")
    (spec_dir / ".hidden.bin").write_bytes(b"\x00\xffunchanged")
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(project, squad, "3" * 32)
    replacements = {
        "spec.md": "- FR-1000000: Changed café.\r\n".encode(),
        "tasks.md": b"- [x] T-10000000 complexity=standard phase=build req=FR-1000000 depends=none\n",
        "amendments/001/change-request.md": b"# Identity update\n",
    }
    for index, (name, data) in enumerate(replacements.items()):
        stage = transaction.build_path(f"after-{index}")
        stage.write_bytes(data)
        target = Path("specs/demo") / name
        transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs/demo",)) as initial:
        pass
    projected = project_publication_source_images(initial)
    expected = _build(projected.trees[0], lifecycle="build")
    assert _render(_build(initial.trees[0], lifecycle="build")) != _render(expected)
    final = prepared.publish_sources(initial)
    with inspect_project_tree(project, "specs/demo") as actual:
        pass
    assert actual == final.trees[0] == projected.trees[0]
    assert _render(_build(actual, lifecycle="build")) == _render(expected)
    assert {node.id for node in expected.nodes if node.type == "Requirement"} == {"req:demo:FR-1000000"}
    assert GraphEdge("task:demo:T-10000000", "IMPLEMENTS", "req:demo:FR-1000000", {}) in expected.edges
    assert any(node.id == "amendment:demo:001" for node in expected.nodes)
    assert (spec_dir / ".hidden.bin").read_bytes() == b"\x00\xffunchanged"
    assert not (spec_dir / "spec-artifact-graph.json").exists()


def test_captured_builder_has_no_ambient_observations_or_effects(monkeypatch):
    import builtins
    import io
    import os
    import random
    import secrets
    import socket
    import sqlite3
    import subprocess
    import time
    import echelon.spec_graph as graph
    import echelon.spec_graph_structure as structure
    import echelon.mempalace_requirements as memory
    import echelon.topology_registry as topology

    tree = _tree(_rich_files(), root="runs/spec-123/stage", directories=("amendments/10",))
    expected = _rich_expected(_rich_files())
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("ambient operation")
        raise AssertionError("captured construction used an ambient operation")

    with monkeypatch.context() as patch:
        for owner, names in (
            (builtins, ("open",)), (io, ("open",)),
            (Path, ("open", "read_bytes", "read_text", "write_bytes", "write_text", "stat", "lstat", "resolve", "absolute", "cwd", "home", "iterdir", "glob", "rglob", "exists", "is_file", "is_dir", "mkdir", "unlink", "rename", "replace")),
            (os, ("open", "read", "write", "stat", "lstat", "fstat", "listdir", "scandir", "getcwd", "getenv", "system", "popen", "urandom")),
            (type(os.environ), ("__getitem__", "__iter__", "get", "__setitem__")),
            (subprocess, ("Popen", "run", "check_output", "check_call", "call")),
            (time, ("time", "monotonic", "perf_counter", "sleep")),
            (random, ("random", "randint", "getrandbits", "choice")),
            (secrets, ("token_bytes", "token_hex", "token_urlsafe")),
            (socket, ("socket", "create_connection", "getaddrinfo")),
            (sqlite3, ("connect",)),
            (memory, ("create_requirement_memory_adapter", "load_canonical_spec_snapshot", "load_supporting_artifact_snapshots")),
            (topology, ("load_topology_index",)),
            (graph, ("build_spec_graph", "_add_canonical_memory", "_add_evidence_memory", "_add_re_memory", "_add_re_topology", "_linked_re_artifacts", "_generator_version")),
        ):
            for name in names:
                patch.setattr(owner, name, forbidden)
        result = structure.build_spec_graph_structure(spec_id="demo", tree=tree, lifecycle="build")
    assert calls == []
    assert _render(result) == _render(expected)


@pytest.mark.parametrize("first,second", [("echelon.spec_graph", "echelon.spec_graph_structure"), ("echelon.spec_graph_structure", "echelon.spec_graph")])
def test_import_initialization_preserves_original_graph_model_identity(first, second):
    import os
    import subprocess
    import sys
    code = (
        "import importlib; "
        f"importlib.import_module({first!r}); importlib.import_module({second!r}); "
        "from echelon import spec_graph as g, spec_graph_structure as s; "
        "assert s.GraphNode is g.GraphNode; assert s.GraphInput is g.GraphInput; "
        "assert s.GraphEdge is g.GraphEdge; print('model identity preserved')"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "src"})
    assert (completed.returncode, completed.stdout, completed.stderr) == (0, "model identity preserved\n", "")


@pytest.mark.parametrize("name,content,legacy_error", [
    ("tasks.md", b"\xff", UnicodeDecodeError),
    ("tasks.md", b"", SpecGraphError),
    ("verified-fulfillment-ledger.json", b"\xff", UnicodeDecodeError),
    ("verified-fulfillment-ledger.json", b"{secret", json.JSONDecodeError),
    ("inputs/traceability.json", b"\xff", SpecGraphError),
])
def test_legacy_path_helpers_keep_their_exception_contract(tmp_path, name, content, legacy_error):
    import echelon.spec_graph as graph
    spec_dir = tmp_path / "specs/demo"
    path = spec_dir / name
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    nodes, edges, inputs = {}, [], {}
    if name == "tasks.md":
        operation = lambda: graph._add_tasks(tmp_path.resolve(), spec_dir, set(), nodes, edges)
    elif name == "verified-fulfillment-ledger.json":
        operation = lambda: graph._add_verified_ledger(tmp_path.resolve(), spec_dir, set(), nodes, edges, inputs)
    else:
        (path.parent / "catalog.json").write_bytes(b"{}")
        operation = lambda: graph._add_traceability(spec_dir, set(), nodes, edges)
    with pytest.raises(legacy_error):
        operation()


def test_legacy_artifact_adapter_still_reads_external_additions_and_role_overrides(tmp_path):
    import echelon.spec_graph as graph
    root = tmp_path.resolve()
    spec_dir = root / "specs/demo"
    spec_dir.mkdir(parents=True)
    artifact = root / "re/evidence.md"
    artifact.parent.mkdir()
    artifact.write_bytes(b"evidence\n")
    nodes, inputs = {}, {}
    node_id = graph._add_artifact(root, spec_dir, artifact, nodes, inputs, role="explicit-role")
    digest = "sha256:" + hashlib.sha256(b"evidence\n").hexdigest()
    assert nodes == {"artifact:demo:re/evidence.md": GraphNode(node_id, "Artifact", {
        "path": "re/evidence.md", "role": "explicit-role", "hash": digest,
        "mining_status": "not-mined-by-policy",
    })}
    assert inputs == {"re/evidence.md": GraphInput("re/evidence.md", digest, "explicit_role", False)}


@pytest.fixture
def secure_posix():
    from harness.squad_publication import _secure_posix_capabilities_available
    if not _secure_posix_capabilities_available():
        pytest.skip("secure POSIX capture is unavailable")


def test_captured_structure_retains_real_spec_after_file_change(tmp_path, secure_posix):
    import importlib
    from harness.canonical_requirements import extract_canonical_requirements
    from harness.squad_source_snapshot import inspect_project_tree
    spec_dir = tmp_path / "specs/demo"
    spec_dir.mkdir(parents=True)
    spec_file = spec_dir / "spec.md"
    original = b"# Game\n\n- FR-1000000: Keep question identity.\n"
    spec_file.write_bytes(original)
    rows = extract_canonical_requirements(spec_dir)
    assert [(row.id, row.source_kind, row.source_file, row.source_line, row.source_text) for row in rows] == [
        ("FR-1000000", "spec", "spec.md", 3, "- FR-1000000: Keep question identity.")
    ]
    with inspect_project_tree(tmp_path, "specs/demo") as tree:
        assert tree.files[0].content == original
    spec_file.write_bytes(b"# Changed\n\n- FR-000002: Different subject.\n")
    module = importlib.import_module("echelon.spec_graph_structure")
    result = module.build_spec_graph_structure(spec_id="demo", tree=tree, lifecycle="phase_a")
    assert {node.id for node in result.nodes if node.type == "Requirement"} == {"req:demo:FR-1000000"}
