"""Captured artifact audits exercise native planning and classification offline."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib
from pathlib import Path
import traceback

import pytest

from echelon import mempalace_spec_evidence as evidence, mempalace_re as re_memory
from echelon.spec_memory_miner import (
    _spec_evidence_artifact_from_bytes, _re_artifact_from_bytes, scrub_secrets,
)
from harness.squad_publication import SquadPublicationTransaction
from harness.squad_source_projection import project_publication_source_images
from tests.unit.test_mempalace_captured_audit import _project, _capture, _storage
from tests.unit.test_squad_source_projection_images import secure_posix
from tests.unit.test_mempalace_re import write_typed_re_workspace_with_misleading_names
from harness.re_artifacts import ReArtifactDescriptor
from harness.re_registry import canonical_re_artifact_descriptors, load_published_index
from echelon.mempalace_requirements import SpecMemoryError

pytestmark = pytest.mark.unit
SPEC_ID = "001-demo"
TREE_PATH = "specs/001-demo"


class Collection:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.calls = []
        self.writes = []

    def get(self, *, include, ids=None, where=None, limit=None, offset=0):
        assert include == ["documents", "metadatas"]
        self.calls.append((ids, where, limit, offset))
        if ids is not None:
            selected = [key for key in ids if key in self.rows]
        else:
            wing = where["wing"]
            wing = wing["$eq"] if isinstance(wing, dict) else wing
            selected = [key for key, row in self.rows.items() if row[1].get("wing") == wing]
            selected = selected[offset:offset + limit] if limit is not None else selected[offset:]
        return {"ids": selected, "documents": [self.rows[k][0] for k in selected],
                "metadatas": [self.rows[k][1] for k in selected]}

    def forbidden(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("audit attempted storage mutation")

    add = upsert = update = delete = create_collection = get_or_create_collection = forbidden


def _rows(root, snapshots, domain="evidence"):
    adapter = (evidence.SpecEvidenceMemoryAdapter if domain == "evidence" else re_memory.ReMemoryAdapter)(root, "audit")
    planner = adapter.plan_spec_evidence_artifact_rows if domain == "evidence" else adapter.plan_re_artifact_rows
    parser = _spec_evidence_artifact_from_bytes if domain == "evidence" else _re_artifact_from_bytes
    rows = {}
    for snapshot in snapshots:
        metadata = snapshot.artifact_metadata
        plans = planner(snapshot.content, source=snapshot.source, artifact_metadata=metadata)
        _, requirements = parser(snapshot.content, source=snapshot.source, artifact_metadata=metadata)
        for plan, requirement in zip(plans, requirements, strict=True):
            rows[plan.drawer_id] = (scrub_secrets(requirement.content), {
                **metadata, "wing": adapter.wing, "room": plan.room,
                "deterministic_identity_schema_version": 1,
                "requirement_id": plan.requirement_id,
                "canonical_spec_sha256": plan.canonical_spec_sha256,
                "requirement_content_sha256": plan.requirement_content_sha256,
            })
    return rows


def test_captured_evidence_audit_uses_candidate_bytes_and_native_storage_rows(tmp_path, monkeypatch, secure_posix):
    root, spec_dir = _project(tmp_path, monkeypatch, spec=b"---\nstatus: landed\n---\nFR-001: Demo.\n")
    evidence_path = spec_dir / "evidence-grades.md"
    old_bytes = b"# Grades\n\nOld evidence.\n"
    new_bytes = b"# Grades\n\nCandidate evidence.\n"
    evidence_path.write_bytes(old_bytes)
    old_snapshots = evidence.load_spec_evidence_artifact_snapshots(root, SPEC_ID)
    old_rows = _rows(root, old_snapshots)
    squad = root / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(root, squad, "a" * 32)
    stage = transaction.build_path("evidence-grades.md")
    stage.write_bytes(new_bytes)
    target = Path(TREE_PATH) / "evidence-grades.md"
    transaction.add_write(target, stage, owned_paths={target})
    with transaction.seal().inspect_sources(tree_paths=(TREE_PATH,)) as initial:
        pass
    projected_tree, = project_publication_source_images(initial).trees
    content = next(item.content for item in projected_tree.files if item.path == target.as_posix())
    candidate = replace(old_snapshots[0], content=content, artifact_metadata={
        **old_snapshots[0].artifact_metadata,
        "artifact_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
    })
    candidate_rows = _rows(root, [candidate])
    collection = Collection(old_rows)
    _storage(monkeypatch, root, collection)
    native_old_report = evidence.audit_spec_evidence_memory(root, SPEC_ID)
    assert native_old_report.status == "pass"
    assert native_old_report.present_current_count == len(old_rows)
    collection.rows = deepcopy(candidate_rows)
    native_candidate_rows_against_old_disk = evidence.audit_spec_evidence_memory(root, SPEC_ID)
    assert native_candidate_rows_against_old_disk.status == "fail"
    captured = importlib.import_module("echelon.mempalace_captured_artifact_audit")
    report = captured.audit_captured_spec_evidence_memory(
        root, spec_id=SPEC_ID, tree=projected_tree, maximum_scan_rows=2000)
    assert report.status == "pass"
    assert report.present_current_count == len(candidate_rows)
    assert evidence_path.read_bytes() == old_bytes
    assert collection.writes == []


def _case(tmp_path, monkeypatch, domain="evidence"):
    if domain == "catalog":
        root = tmp_path.resolve()
        write_typed_re_workspace_with_misleading_names(root)
        monkeypatch.setattr("codegen.memory.context._get_palace_path", lambda: str(root / "palace"))
        descriptors = canonical_re_artifact_descriptors(root, load_published_index(root))
        snapshots = re_memory.load_re_artifact_snapshots(root)
        tree = _capture(root, "re")
    else:
        root, spec_dir = _project(tmp_path, monkeypatch, spec=b"---\nstatus: landed\n---\nFR-001: Demo.\n")
        descriptors = None
        if domain == "evidence":
            (spec_dir / "evidence-grades.md").write_bytes(b"# Grades\n\nEvidence.\n")
            snapshots = evidence.load_spec_evidence_artifact_snapshots(root, SPEC_ID)
            tree = _capture(root)
        else:
            path = root / "re/sources/api/architecture.md"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"# Architecture\n\nA service.\n")
            snapshots = re_memory.load_re_artifact_snapshots(root)
            tree = _capture(root, "re")
    rows = _rows(root, snapshots, domain)
    collection = Collection(rows)
    _storage(monkeypatch, root, collection)
    return root, tree, descriptors, snapshots, collection


def _audit(root, tree, descriptors=None, **kwargs):
    from echelon import mempalace_captured_artifact_audit as captured
    budget = kwargs.pop("maximum_scan_rows", 2000)
    if tree.path == "re":
        return captured.audit_captured_re_memory(root, tree=tree, descriptors=descriptors, maximum_scan_rows=budget, **kwargs)
    return captured.audit_captured_spec_evidence_memory(root, spec_id=SPEC_ID, tree=tree, maximum_scan_rows=budget, **kwargs)


def _native(root, domain):
    return evidence.audit_spec_evidence_memory(root, SPEC_ID) if domain == "evidence" else re_memory.audit_re_memory(root)


@pytest.mark.parametrize("domain", ["evidence", "legacy", "catalog"])
@pytest.mark.parametrize("change", [
    "present", "missing", "document", "artifact_hash", "canonical_spec_sha256",
    "requirement_content_sha256", "wing", "room", "scope", "artifact_path",
    "source_file", "artifact_kind", "canonical", "spec_id", "requirement_id",
    "deterministic_identity_schema_version", "lifecycle_status", "status",
    "duplicate", "historical", "noncanonical_extra", "unrelated", "stale_extra",
    "malformed_document", "malformed_metadata", "duplicate_response",
])
def test_full_native_report_parity(tmp_path, monkeypatch, domain, change):
    root, tree, descriptors, snapshots, collection = _case(tmp_path, monkeypatch, domain)
    key = next(iter(collection.rows))
    document, metadata = collection.rows[key]
    if change == "missing":
        del collection.rows[key]
    elif change == "document":
        collection.rows[key] = ("changed content", metadata)
    elif change in {"duplicate", "historical", "noncanonical_extra", "unrelated", "stale_extra"}:
        extra = deepcopy(metadata)
        if change == "historical":
            extra["lifecycle_status"] = "superseded"
        elif change == "noncanonical_extra":
            extra["canonical"] = False
        elif change == "unrelated":
            extra["artifact_kind"] = "other"
        elif change == "stale_extra":
            extra["requirement_id"] = "not-planned"
        collection.rows["extra"] = (document, extra)
    elif change.startswith("malformed_") or change == "duplicate_response":
        # The complete wing agrees: malformed expected fetch has no valid row.
        del collection.rows[key]
        original = collection.get
        def get(**kwargs):
            raw = original(**kwargs)
            if kwargs.get("ids") is not None:
                raw["ids"].append(key)
                raw["documents"].append(None if change == "malformed_document" else document)
                raw["metadatas"].append(None if change == "malformed_metadata" else metadata)
                if change == "duplicate_response":
                    raw["ids"].append(key)
                    raw["documents"].append(document)
                    raw["metadatas"].append(metadata)
            return raw
        monkeypatch.setattr(collection, "get", get)
    elif change != "present":
        if change == "status":
            metadata.pop("lifecycle_status")
        metadata[change] = False if change == "canonical" else "removed" if change in {"status", "lifecycle_status"} else "wrong"
    native = _native(root, domain)
    report = _audit(root, tree, descriptors)
    assert report.to_dict() == native.to_dict()
    assert report.artifact_count == len(snapshots)
    if change in {"duplicate", "historical", "noncanonical_extra"}:
        assert report.status == "warn"
        assert report.duplicate == (["extra"] if change == "duplicate" else [])
        if domain == "evidence":
            assert report.historical == ([] if change == "duplicate" else ["extra"])
        else:
            assert "historical" not in report.to_dict()
    elif change in {"present", "unrelated"} or change == "spec_id" and domain != "evidence":
        assert report.status == "pass"
    else:
        assert report.status == "fail"
    assert collection.writes == []


@pytest.mark.parametrize("physical", [TREE_PATH, "runs/spec-demo/specs/001-demo", ".echelon/staging/001-demo"])
def test_evidence_selection_and_native_component_order(tmp_path, monkeypatch, physical):
    root, tree, _, _, collection = _case(tmp_path, monkeypatch)
    selected = set(evidence.CANONICAL_SPEC_EVIDENCE_ARTIFACTS) | {
        "evidence/" + name for name in (*evidence.PUBLISHED_VERIFY_EVIDENCE_ARTIFACTS, "manifest.json")}
    for name in selected | {"unknown.md", "evidence/unknown.md", "evidence/nested/requirement-audit.md"}:
        path = root / TREE_PATH / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# Evidence\n\nObserved.\n")
    snapshots = evidence.load_spec_evidence_artifact_snapshots(root, SPEC_ID)
    assert [s.source for s in snapshots] == [TREE_PATH + "/" + str(p) for p in sorted(map(Path, selected))]
    # Component ordering puts the evidence directory before evidence-grades.md.
    sources = [s.source for s in snapshots]
    assert sources.index(TREE_PATH + "/evidence/manifest.json") < sources.index(TREE_PATH + "/evidence-grades.md")
    rooms = {s.artifact_metadata["room"] for s in snapshots}
    assert rooms == {"spec-fulfillment-evidence", "spec-implementation-evidence", "spec-documentation-evidence", "spec-verification-evidence", "spec-evidence-context"}
    collection.rows = _rows(root, snapshots)
    if physical != TREE_PATH:
        import shutil
        shutil.copytree(root / TREE_PATH, root / physical)
    tree = _capture(root, physical)
    assert _audit(root, tree).to_dict() == _native(root, "evidence").to_dict()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_landed_frontmatter_universal_newlines_preserve_evidence_hash(tmp_path, monkeypatch, newline):
    root, tree, _, _, collection = _case(tmp_path, monkeypatch)
    (root / TREE_PATH / "spec.md").write_bytes(newline.join([b"---", b"status: ' LANDED '", b"---", b"text"]))
    content = newline.join([b"# Grades", b"", b"Evidence."])
    (root / TREE_PATH / "evidence-grades.md").write_bytes(content)
    snapshots = evidence.load_spec_evidence_artifact_snapshots(root, SPEC_ID)
    assert snapshots[0].artifact_metadata["artifact_hash"] == "sha256:" + hashlib.sha256(content).hexdigest()
    collection.rows = _rows(root, snapshots)
    assert _audit(root, _capture(root)).to_dict() == _native(root, "evidence").to_dict()


@pytest.mark.parametrize("content", [b"", b"# No frontmatter", b"---\nstatus: draft\n---\n", b"---\n[landed]\n---\n", b"---\nstatus: [\n---\n"])
def test_landed_gate_and_explicit_override(tmp_path, monkeypatch, content):
    root, _, _, _, collection = _case(tmp_path, monkeypatch)
    (root / TREE_PATH / "spec.md").write_bytes(content)
    tree = _capture(root)
    with pytest.raises(SpecMemoryError, match="^invalid captured artifact memory input$") as error:
        _audit(root, tree)
    assert error.value.__cause__ is error.value.__context__ is None
    assert collection.calls == []
    assert _audit(root, tree, allow_unlanded=True).status == "pass"


def test_empty_evidence_still_observes_extras(tmp_path, monkeypatch):
    root, _, _, _, collection = _case(tmp_path, monkeypatch)
    (root / TREE_PATH / "evidence-grades.md").unlink()
    report = _audit(root, _capture(root))
    assert report.artifact_count == report.expected_count == 0
    assert report.status == "fail" and report.stale == sorted(collection.rows)
    assert all(ids is None for ids, _, _, _ in collection.calls)


@pytest.mark.parametrize("domain", ["evidence", "legacy", "catalog"])
def test_native_utf8_planning_failure(tmp_path, monkeypatch, domain):
    root, tree, descriptors, snapshots, collection = _case(tmp_path, monkeypatch, domain)
    (root / snapshots[0].source).write_bytes(b"\xff")
    if descriptors is not None:
        # Native registry rightly rejects stale descriptors, so planner parity is
        # exercised separately by legacy/evidence; supplied catalog stays pure.
        descriptors = tuple(replace(d, sha256="sha256:" + hashlib.sha256(b"\xff").hexdigest()) if d.path == snapshots[0].source else d for d in descriptors)
    tree = _capture(root, tree.path)
    report = _audit(root, tree, descriptors)
    assert report.status == "fail" and report.expected_count == 0 and report.errors == ["ValueError"]
    assert report.artifact_count == len(snapshots)
    assert collection.calls == []
    if domain != "catalog":
        assert report.to_dict() == _native(root, domain).to_dict()


@pytest.mark.parametrize("domain", ["evidence", "legacy", "catalog"])
@pytest.mark.parametrize("field,value", [
    ("project_root", "private-value"), ("project_root", Path("relative")),
    ("maximum_scan_rows", None), ("maximum_scan_rows", 0), ("maximum_scan_rows", -1),
    ("maximum_scan_rows", True), ("maximum_scan_rows", 2.0), ("maximum_scan_rows", "2"),
    ("tree", None), ("tree", {}),
])
def test_invalid_scalar_input_before_acquisition(tmp_path, monkeypatch, domain, field, value):
    from echelon import mempalace_captured_artifact_audit as captured
    root, tree, descriptors, _, collection = _case(tmp_path, monkeypatch, domain)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid source reached acquisition")
    monkeypatch.setattr(evidence, "create_spec_evidence_memory_adapter", forbidden)
    monkeypatch.setattr(re_memory, "create_re_memory_adapter", forbidden)
    kwargs = dict(project_root=root, tree=tree, maximum_scan_rows=2000)
    if domain == "evidence":
        kwargs["spec_id"] = SPEC_ID
        audit = captured.audit_captured_spec_evidence_memory
    else:
        kwargs["descriptors"] = descriptors
        audit = captured.audit_captured_re_memory
    kwargs[field] = value
    with pytest.raises(SpecMemoryError) as caught:
        audit(**kwargs)
    assert str(caught.value) == "invalid captured artifact memory input"
    assert caught.value.__cause__ is caught.value.__context__ is None
    assert "manifest_invalid" not in "".join(traceback.format_exception(caught.value))
    assert collection.calls == []


@pytest.mark.parametrize("field,value", [
    ("spec_id", 1), ("spec_id", ""), ("spec_id", "../001-demo"),
    ("spec_id", "001-demo/child"), ("spec_id", "001-demo\\child"), ("spec_id", "\ud800"),
    ("allow_unlanded", 0), ("allow_unlanded", 1), ("allow_unlanded", None),
    ("allow_unlanded", "true"),
])
def test_exact_evidence_options(tmp_path, monkeypatch, field, value):
    from echelon.mempalace_captured_artifact_audit import audit_captured_spec_evidence_memory
    root, tree, _, _, collection = _case(tmp_path, monkeypatch)
    monkeypatch.setattr(evidence, "create_spec_evidence_memory_adapter", lambda *a, **k: pytest.fail("acquired"))
    kwargs = dict(project_root=root, spec_id=SPEC_ID, tree=tree, maximum_scan_rows=2000)
    kwargs[field] = value
    with pytest.raises(SpecMemoryError):
        audit_captured_spec_evidence_memory(**kwargs)
    assert collection.calls == []


@pytest.mark.parametrize("domain", ["evidence", "legacy", "catalog"])
@pytest.mark.parametrize("damage", ["hash", "bytes", "file_mode", "directory_mode", "membership", "order"])
def test_all_original_records_validate_even_when_ignored(tmp_path, monkeypatch, domain, damage):
    root, tree, descriptors, _, collection = _case(tmp_path, monkeypatch, domain)
    opaque = root / tree.path / ".opaque.bin"
    opaque.write_bytes(b"\xff\x00")
    tree = _capture(root, tree.path)
    item = next(f for f in tree.files if f.path.endswith(".opaque.bin"))
    if damage == "hash":
        object.__setattr__(item.image, "sha256", "0" * 64)
    elif damage == "bytes":
        object.__setattr__(item, "content", b"changed")
    elif damage == "file_mode":
        object.__setattr__(item.image, "mode", -1)
    elif damage == "directory_mode":
        object.__setattr__(tree.directories[0], "mode", -1)
    elif damage == "membership":
        object.__setattr__(item, "path", tree.path + "/missing-parent/opaque.bin")
    else:
        object.__setattr__(tree, "files", tuple(reversed(tree.files)))
    monkeypatch.setattr(evidence, "create_spec_evidence_memory_adapter", lambda *a, **k: pytest.fail("acquired"))
    monkeypatch.setattr(re_memory, "create_re_memory_adapter", lambda *a, **k: pytest.fail("acquired"))
    with pytest.raises(SpecMemoryError) as caught:
        _audit(root, tree, descriptors)
    assert caught.value.__cause__ is caught.value.__context__ is None
    assert collection.calls == []


@pytest.mark.parametrize("damage", [
    "none", "list", "empty", "duplicate", "order", "record", "path", "hash", "owner", "source_id",
    "unmined_hash", "all_unmined", "missing_index", "index_directory",
])
def test_explicit_catalog_contract_never_falls_back(tmp_path, monkeypatch, damage):
    root, tree, descriptors, _, collection = _case(tmp_path, monkeypatch, "catalog")
    if damage == "none":
        descriptors = None
    elif damage == "list":
        descriptors = list(descriptors)
    elif damage == "empty":
        descriptors = ()
    elif damage == "duplicate":
        descriptors = (*descriptors, descriptors[-1])
    elif damage == "order":
        descriptors = tuple(reversed(descriptors))
    elif damage == "record":
        descriptors = ({},)
    elif damage == "all_unmined":
        descriptors = tuple(d for d in descriptors if d.kind not in re_memory.MINED_RE_ARTIFACT_KINDS)
        assert descriptors
    elif damage in {"missing_index", "index_directory"}:
        (root / "re/index.json").unlink()
        if damage == "index_directory":
            (root / "re/index.json").mkdir()
        tree = _capture(root, "re")
    else:
        index = next(i for i, d in enumerate(descriptors) if d.kind not in re_memory.MINED_RE_ARTIFACT_KINDS) if damage == "unmined_hash" else 0
        changed = descriptors[index]
        if damage in {"hash", "unmined_hash"}:
            changed = replace(changed, sha256="sha256:" + "0" * 64)
        elif damage == "path":
            changed = replace(changed, path="re/missing.md")
        elif damage == "owner":
            changed = replace(changed, scope="workspace", source_id=None)
        elif damage == "source_id":
            changed = replace(changed, source_id="../api")
        descriptors = (*descriptors[:index], changed, *descriptors[index + 1:])
    monkeypatch.setattr(re_memory, "create_re_memory_adapter", lambda *a, **k: pytest.fail("acquired"))
    with pytest.raises(SpecMemoryError) as caught:
        _audit(root, tree, descriptors)
    assert caught.value.__cause__ is caught.value.__context__ is None
    assert collection.calls == []


def test_catalog_is_not_registry_association_proof_and_preserves_metadata(tmp_path, monkeypatch):
    from echelon.mempalace_captured_artifact_audit import _capture_re
    root, tree, descriptors, native, collection = _case(tmp_path, monkeypatch, "catalog")
    selected = _capture_re(root, tree, descriptors, 2000)
    assert selected == native
    alpha = next(s for s in selected if s.source.endswith("notes/alpha.md"))
    assert alpha.artifact_metadata == {
        "scope": "reverse-engineering", "canonical": True, "artifact_kind": "re-architecture",
        "artifact_path": "re/sources/api/notes/alpha.md", "source_file": "re/sources/api/notes/alpha.md",
        "artifact_hash": "sha256:" + hashlib.sha256(b"# Typed architecture\n").hexdigest(),
        "lifecycle_status": "active", "provenance_type": "reverse_engineering_mine", "added_by": "echelon",
        "phase": "RE", "room": "re-source-architecture", "re_artifact_scope": "source", "re_source_id": "api",
    }
    workspace = next(s for s in selected if s.source.endswith("notes/kilo.md"))
    assert workspace.artifact_metadata["room"] == "re-workspace-decisions"
    assert workspace.artifact_metadata["re_artifact_scope"] == "workspace"
    assert "re_source_id" not in workspace.artifact_metadata
    assert not any(s.artifact_metadata["artifact_kind"] == "re-codegraph-analysis" for s in selected)
    # A captured index is only a presence witness; neither parsing nor catalog
    # completeness/association is claimed. Caller-selected subset remains explicit.
    (root / "re/index.json").write_bytes(b"not a registry document")
    tree = _capture(root, "re")
    assert _audit(root, tree, descriptors).status == "pass"
    assert _audit(root, tree, (next(d for d in descriptors if d.path == workspace.source),)).artifact_count == 1
    assert collection.writes == []


@pytest.mark.parametrize("damage", ["absent", "empty", "no_curated", "index_file", "index_dir", "wrong_root"])
def test_legacy_requires_curated_re_without_index(tmp_path, monkeypatch, damage):
    from echelon.mempalace_captured_artifact_audit import audit_captured_re_memory
    root, _, _, _, collection = _case(tmp_path, monkeypatch)
    directory = root / ("other" if damage == "wrong_root" else "re")
    if damage != "absent":
        directory.mkdir()
    if damage == "no_curated":
        (directory / "unknown.md").write_bytes(b"ignored")
    elif damage in {"index_file", "wrong_root"}:
        (directory / "index.json").write_bytes(b"{}")
    elif damage == "index_dir":
        (directory / "index.json").mkdir()
    tree = _capture(root, directory.name)
    monkeypatch.setattr(re_memory, "create_re_memory_adapter", lambda *a, **k: pytest.fail("acquired"))
    with pytest.raises(SpecMemoryError):
        audit_captured_re_memory(root, tree=tree, descriptors=None, maximum_scan_rows=2000)
    assert collection.calls == []


def test_legacy_full_selection_rooms_and_component_order(tmp_path, monkeypatch):
    from echelon.mempalace_captured_artifact_audit import _capture_re
    root, _, _, _, collection = _case(tmp_path, monkeypatch, "legacy")
    cases = {
        "re-analysis-manifest.json": "re-workspace-context",
        "sources/api/architecture.md": "re-source-architecture",
        "sources/api/contracts.md": "re-source-contracts",
        "sources/api/components.md": "re-source-components",
        "sources/api/codegraph-summary.json": "re-source-codegraph",
        "sources/api/adrs/choice.md": "re-source-decisions",
        "sources/api/specs/demo/spec.md": "re-generated-specs",
        "sources/api/specs/demo/checklist.md": "re-generated-specs",
        "sources/api/overview.md": "re-source-context",
        "workspace/codegraph-summary.json": "re-workspace-codegraph",
        "workspace/strategy/adrs/decision.md": "re-workspace-decisions",
        "workspace/strategy/plan.md": "re-strategy",
        "workspace/domains/domain.md": "re-domain-context",
        "workspace/overview.md": "re-workspace-context",
        "workspace/a/item.md": "re-workspace-context",
        "workspace/a-note.md": "re-workspace-context",
        "quality/semantic-quality-review.json": "re-quality-review",
        "quality/sources/api.json": "re-quality-review",
    }
    ignored = {".cache/overview.md", "sources/api/__pycache__/overview.md", "sources/api/unknown.md", "workspace/trace.log", "unknown.md"}
    for name in set(cases) | ignored:
        path = root / "re" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# Context\n\nObserved.\n")
    native = re_memory.load_re_artifact_snapshots(root)
    tree = _capture(root, "re")
    selected = _capture_re(root, tree, None, 2000)
    assert selected == native
    assert [s.source for s in selected] == ["re/" + str(p) for p in sorted(map(Path, cases))]
    for snapshot in selected:
        assert snapshot.artifact_metadata["room"] == cases[snapshot.source.removeprefix("re/")]
        assert "re_artifact_scope" not in snapshot.artifact_metadata
        assert "re_source_id" not in snapshot.artifact_metadata
    collection.rows = _rows(root, selected, "legacy")
    assert _audit(root, tree).to_dict() == _native(root, "legacy").to_dict()


@pytest.mark.parametrize("domain", ["evidence", "legacy"])
@pytest.mark.parametrize("fault", ["overflow", "cohort", "nested", "unexpected_id", "unexpected_malformed_id"])
def test_complete_observation_failures_are_unavailable(tmp_path, monkeypatch, domain, fault):
    root, tree, _, snapshots, collection = _case(tmp_path, monkeypatch, domain)
    key = next(iter(collection.rows))
    if fault == "overflow":
        collection.rows["extra"] = ("other", {"wing": "captured-audit-test"})
    elif fault == "nested":
        collection.rows[key][1]["nested"] = {"items": ["before"]}
    original = collection.get
    transitioned = False
    def get(**kwargs):
        nonlocal transitioned
        if kwargs.get("where") is not None and not transitioned:
            transitioned = True
            if fault == "cohort":
                collection.rows[key] = ("changed", collection.rows[key][1])
            elif fault == "nested":
                collection.rows[key][1]["nested"]["items"].append("after")
        raw = original(**kwargs)
        if kwargs.get("ids") is not None and fault.startswith("unexpected"):
            raw["ids"].append("unrequested")
            raw["documents"].append(None if "malformed" in fault else "other")
            raw["metadatas"].append({"wing": "captured-audit-test"})
        return raw
    monkeypatch.setattr(collection, "get", get)
    report = _audit(root, tree, maximum_scan_rows=1 if fault == "overflow" else 2000)
    assert report.status == "unavailable" and report.errors == ["SpecMemoryError"]
    assert report.artifact_count == len(snapshots) and report.expected_count == 1
    assert report.present_current_count == 0
    if fault.startswith("unexpected"):
        assert len(collection.calls) == 1


@pytest.mark.parametrize("domain", ["evidence", "legacy"])
@pytest.mark.parametrize("extra", ["duplicate", "historical", "stale"])
def test_complete_extras_beyond_native_window_without_another_query(tmp_path, monkeypatch, domain, extra):
    from echelon import mempalace_memory_audit
    root, tree, _, _, collection = _case(tmp_path, monkeypatch, domain)
    # Bound this regression to five rows while moving the native window to two.
    monkeypatch.setattr(mempalace_memory_audit, "MAX_MEMORY_AUDIT_SCAN_ROWS", 2)
    document, metadata = deepcopy(next(iter(collection.rows.values())))
    for index in range(3):
        collection.rows[f"unrelated-{index}"] = ("other", {"wing": "captured-audit-test"})
    if extra == "historical":
        metadata["lifecycle_status"] = "delivered"
    elif extra == "stale":
        metadata["requirement_id"] = "old"
    collection.rows["after-window"] = (document, metadata)
    assert _native(root, domain).status == "pass"
    collection.calls.clear()
    report = _audit(root, tree, maximum_scan_rows=5)
    assert report.status == ("fail" if extra == "stale" else "warn")
    assert report.duplicate == (["after-window"] if extra == "duplicate" else [])
    assert report.stale == (["after-window"] if extra == "stale" else [])
    if domain == "evidence":
        assert report.historical == (["after-window"] if extra == "historical" else [])
    # Each exact-budget pass needs its one-row overflow probe at offset five.
    assert len(collection.calls) == 5
    assert [(limit, offset) for _, _, limit, offset in collection.calls[1:]] == [(5, 0), (1, 5), (5, 0), (1, 5)]
    assert all(where is None or where == {"wing": "captured-audit-test"} for _, where, _, _ in collection.calls)


@pytest.mark.parametrize("domain", ["evidence", "legacy"])
@pytest.mark.parametrize("seam", ["factory", "planner", "open", "get", "copy", "scanner"])
@pytest.mark.parametrize("error_type", [RuntimeError, SystemExit, KeyboardInterrupt, GeneratorExit])
def test_operational_error_counts_and_process_control(tmp_path, monkeypatch, domain, seam, error_type):
    from echelon import mempalace_captured_audit
    root, tree, _, snapshots, collection = _case(tmp_path, monkeypatch, domain)
    module = evidence if domain == "evidence" else re_memory
    adapter_class = evidence.SpecEvidenceMemoryAdapter if domain == "evidence" else re_memory.ReMemoryAdapter
    def fail(*args, **kwargs):
        raise error_type("private-source-and-backend-details")
    if seam == "factory":
        monkeypatch.setattr(module, "create_spec_evidence_memory_adapter" if domain == "evidence" else "create_re_memory_adapter", fail)
    elif seam == "planner":
        monkeypatch.setattr(adapter_class, "plan_spec_evidence_artifact_rows" if domain == "evidence" else "plan_re_artifact_rows", fail)
    elif seam == "open":
        monkeypatch.setattr(adapter_class, "open_collection_read_only", fail)
    elif seam == "get":
        monkeypatch.setattr(collection, "get", fail)
    elif seam == "scanner":
        monkeypatch.setattr(mempalace_captured_audit, "scan_wing_rows_complete", fail)
    else:
        class Uncopyable:
            __deepcopy__ = fail
        next(iter(collection.rows.values()))[1]["nested"] = Uncopyable()
    if error_type in {KeyboardInterrupt, GeneratorExit}:
        with pytest.raises(error_type):
            _audit(root, tree)
        return
    report = _audit(root, tree)
    assert report.status == ("fail" if seam == "planner" else "unavailable")
    assert report.artifact_count == len(snapshots)
    assert report.expected_count == (0 if seam in {"factory", "planner"} else 1)
    assert report.present_current_count == 0 and report.errors == [error_type.__name__]
    assert "private-source-and-backend-details" not in repr(report.to_dict())
    if seam == "planner":
        assert report.to_dict() == _native(root, domain).to_dict()


@pytest.mark.parametrize("domain", ["evidence", "legacy", "catalog"])
def test_capture_detachment_and_no_live_source_or_registry_access(tmp_path, monkeypatch, domain):
    import harness.re_registry as registry
    import harness.re_artifacts as artifacts
    root, tree, descriptors, snapshots, collection = _case(tmp_path, monkeypatch, domain)
    before_rows = deepcopy(collection.rows)
    baseline = _audit(root, tree, descriptors)
    # Drift/delete sources after their physical observation closes.
    for item in tree.files:
        (root / item.path).unlink()
    module = evidence if domain == "evidence" else re_memory
    factory_name = "create_spec_evidence_memory_adapter" if domain == "evidence" else "create_re_memory_adapter"
    factory = getattr(module, factory_name)
    def mutate_originals(*args, **kwargs):
        object.__setattr__(tree.files[0], "content", b"mutated by backend callback")
        if descriptors:
            for descriptor in descriptors:
                object.__setattr__(descriptor, "kind", "re-analysis")
                object.__setattr__(descriptor, "source_id", "other")
        return factory(*args, **kwargs)
    monkeypatch.setattr(module, factory_name, mutate_originals)
    def forbidden(*args, **kwargs):
        pytest.fail("captured audit reread/resolved live source or registry")
    monkeypatch.setattr(evidence, "load_spec_evidence_artifact_snapshots", forbidden)
    monkeypatch.setattr(evidence, "resolve_spec_dir", forbidden)
    monkeypatch.setattr(re_memory, "load_re_artifact_snapshots", forbidden)
    monkeypatch.setattr(re_memory, "resolve_re_root", forbidden)
    monkeypatch.setattr(re_memory, "load_published_index", forbidden)
    monkeypatch.setattr(re_memory, "canonical_re_artifact_descriptors", forbidden)
    monkeypatch.setattr(registry, "load_published_index", forbidden)
    monkeypatch.setattr(registry, "canonical_re_artifact_descriptors", forbidden)
    monkeypatch.setattr(artifacts, "validate_re_artifact_descriptor", forbidden)
    original_read = Path.read_text
    def read_config_only(path, *args, **kwargs):
        assert path == root / ".echelon/config.yml"
        return original_read(path, *args, **kwargs)
    with monkeypatch.context() as paths:
        paths.setattr(Path, "resolve", forbidden)
        paths.setattr(Path, "read_bytes", forbidden)
        paths.setattr(Path, "read_text", read_config_only)
        report = _audit(root, tree, descriptors)
    assert report.to_dict() == baseline.to_dict()
    assert report.status == "pass"
    assert collection.rows == before_rows and collection.writes == []


@pytest.mark.parametrize("domain", ["evidence", "legacy"])
@pytest.mark.parametrize("error_type", [ValueError, SystemExit, KeyboardInterrupt, GeneratorExit])
def test_source_validation_bounds_only_ordinary_errors(tmp_path, monkeypatch, domain, error_type):
    from echelon import mempalace_captured_artifact_audit as captured, mempalace_captured_audit
    root, tree, _, _, collection = _case(tmp_path, monkeypatch, domain)
    def fail(*args, **kwargs):
        raise error_type("private source detail")
    monkeypatch.setattr(captured if domain == "legacy" else mempalace_captured_audit, "snapshot_source_manifest", fail)
    if error_type is not ValueError:
        with pytest.raises(error_type):
            _audit(root, tree)
    else:
        with pytest.raises(SpecMemoryError) as caught:
            _audit(root, tree)
        assert caught.value.__cause__ is caught.value.__context__ is None
        assert "private source detail" not in "".join(traceback.format_exception(caught.value))
    assert collection.calls == []


@pytest.mark.parametrize("domain", ["evidence", "legacy"])
@pytest.mark.parametrize("state,presence", [("present", "present"), ("missing", "missing"), ("stale", "invalid"), ("unavailable", "unavailable")])
def test_actual_report_composes_with_captured_memory_graph(tmp_path, monkeypatch, domain, state, presence):
    from echelon.spec_graph_memory import GraphMemoryAudit, GraphMemorySource, build_memory_graph_contribution
    root, tree, _, snapshots, collection = _case(tmp_path, monkeypatch, domain)
    adapter = (evidence.SpecEvidenceMemoryAdapter if domain == "evidence" else re_memory.ReMemoryAdapter)(root, "audit")
    planner = adapter.plan_spec_evidence_artifact_rows if domain == "evidence" else adapter.plan_re_artifact_rows
    plans = tuple(row for snapshot in snapshots for row in planner(snapshot.content, source=snapshot.source, artifact_metadata=snapshot.artifact_metadata))
    key = plans[0].drawer_id
    if state == "missing":
        del collection.rows[key]
    elif state == "stale":
        collection.rows[key] = ("stale stored text", collection.rows[key][1])
    elif state == "unavailable":
        def fail(**kwargs):
            raise OSError("unavailable")
        monkeypatch.setattr(collection, "get", fail)
    report = _audit(root, tree)
    observation = GraphMemoryAudit(
        origin="returned", schema_version=report.schema_version, wing=report.wing,
        status=report.status, artifact_count=report.artifact_count, expected_count=report.expected_count,
        present_current_count=report.present_current_count,
        **{name: tuple(getattr(report, name)) for name in ("missing", "stale", "wrong_wing", "wrong_room", "duplicate", "non_canonical", "lifecycle_excluded", "errors")},
    )
    result = build_memory_graph_contribution(
        spec_id=SPEC_ID, lifecycle="phase_a", domain="spec-evidence" if domain == "evidence" else "published-re",
        sources=tuple(GraphMemorySource(s.source, s.content, s.artifact_metadata["artifact_kind"], s.artifact_metadata["room"]) for s in snapshots),
        planned_rows=plans, audit=observation, known_node_ids=(),
    )
    drawer = next(n for n in result.nodes if n.type == "MemPalaceDrawer")
    assert drawer.properties["presence"] == presence
    assert drawer.properties["reconciliation_status"] == report.status
    assert result.receipt.status == report.status
    assert "revision" not in drawer.properties and "identity" not in drawer.properties
    if state == "stale":
        assert "stale" in drawer.properties["issue_codes"]
    if state != "present":
        assert all(edge.properties.get("presence") != "present" for edge in result.edges)


@pytest.mark.parametrize("domain,drawer_id,requirement_id,document", [
    ("evidence", "drawer_captured-audit-test_spec-evidence-context_b302298d3c38f850c824f5af648c8bffb19ae726029b1682c8d678fb936492e9",
     "EVID-specs-001-demo-evidence-grades-md-000", "EVID-specs-001-demo-evidence-grades-md-000: Grades: Evidence."),
    ("legacy", "drawer_captured-audit-test_re-source-architecture_5cfcf5f44dc73ab1f7aa4f9bbe1010bdeffa3a8ff0301b66a56fc322f59e9fb4",
     "RE-re-sources-api-architecture-md-000", "RE-re-sources-api-architecture-md-000: Architecture: A service."),
    ("catalog", "drawer_demo-wing_re-source-codegraph_8ffea2272ef14f2e8442bc44051a776ae34b2e1af21f217be7906b13b01524b4",
     "RE-re-sources-api-evidence-echo-json-000", 'RE-re-sources-api-evidence-echo-json-000: echo.json: {"summary":"source"}'),
    ("catalog", "drawer_demo-wing_re-workspace-codegraph_d048607a1e6fd1bf14349d1a9e6d5e70e2b2b70db31ed672b374d6279c96df2e",
     "RE-re-workspace-evidence-lima-json-000", 'RE-re-workspace-evidence-lima-json-000: lima.json: {"summary":"workspace"}'),
])
def test_native_drawer_identity_matches_independent_vectors(tmp_path, monkeypatch, domain, drawer_id, requirement_id, document):
    # Vectors calculated from literal source bytes, literal chunk text and the
    # documented JSON identity, without calling a production planner/ID helper.
    root, tree, descriptors, _, collection = _case(tmp_path, monkeypatch, domain)
    assert collection.rows[drawer_id][0] == document
    assert collection.rows[drawer_id][1]["requirement_id"] == requirement_id
    assert collection.rows[drawer_id][1]["deterministic_identity_schema_version"] == 1
    del collection.rows[drawer_id]
    assert _audit(root, tree, descriptors).missing == [drawer_id]


def test_catalog_order_is_native_string_order(tmp_path, monkeypatch):
    from echelon.mempalace_captured_artifact_audit import _capture_re
    root, _, _, _, collection = _case(tmp_path, monkeypatch, "legacy")
    paths = ("re/workspace/a-note.md", "re/workspace/a/z.md")
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# Context\n\nText.\n")
    (root / "re/index.json").write_bytes(b"presence only")
    descriptors = tuple(ReArtifactDescriptor(kind="re-overview", scope="workspace", path=path,
                         sha256="sha256:" + hashlib.sha256(b"# Context\n\nText.\n").hexdigest()) for path in paths)
    tree = _capture(root, "re")
    selected = _capture_re(root, tree, descriptors, 2000)
    assert [s.source for s in selected] == list(paths)
    assert selected == re_memory._load_descriptor_re_artifact_snapshots(root, descriptors)
    with pytest.raises(SpecMemoryError):
        _audit(root, tree, tuple(reversed(descriptors)))
    assert collection.calls == []


@pytest.mark.parametrize("damage", ["absent", "directory", "invalid_utf8"])
def test_regular_utf8_spec_is_required_before_acquisition(tmp_path, monkeypatch, damage):
    root, _, _, _, collection = _case(tmp_path, monkeypatch)
    path = root / TREE_PATH / "spec.md"
    path.unlink()
    if damage == "directory":
        path.mkdir()
    elif damage == "invalid_utf8":
        path.write_bytes(b"\xff")
    tree = _capture(root)
    monkeypatch.setattr(evidence, "create_spec_evidence_memory_adapter", lambda *a, **k: pytest.fail("acquired"))
    for allow_unlanded in (False, True):
        with pytest.raises(SpecMemoryError):
            _audit(root, tree, allow_unlanded=allow_unlanded)
    assert collection.calls == []


@pytest.mark.parametrize("domain", ["evidence", "legacy"])
def test_budget_exact_int_subclass_and_required_argument(tmp_path, monkeypatch, domain):
    from echelon import mempalace_captured_artifact_audit as captured
    root, tree, _, _, collection = _case(tmp_path, monkeypatch, domain)
    class Budget(int):
        pass
    with pytest.raises(SpecMemoryError):
        _audit(root, tree, maximum_scan_rows=Budget(2000))
    kwargs = dict(project_root=root, tree=tree)
    audit = captured.audit_captured_spec_evidence_memory if domain == "evidence" else captured.audit_captured_re_memory
    kwargs.update(spec_id=SPEC_ID) if domain == "evidence" else kwargs.update(descriptors=None)
    with pytest.raises(TypeError):
        audit(**kwargs)
    assert collection.calls == []


def test_returned_re_warning_preserves_native_projection_policy(tmp_path, monkeypatch):
    from echelon.spec_graph_memory import GraphMemoryAudit, GraphMemorySource, build_memory_graph_contribution
    root, tree, _, snapshots, collection = _case(tmp_path, monkeypatch, "legacy")
    document, metadata = deepcopy(next(iter(collection.rows.values())))
    metadata["lifecycle_status"] = "superseded"
    collection.rows["historical-outside-plan"] = (document, metadata)
    report = _audit(root, tree)
    assert report.status == "warn" and "historical" not in report.to_dict()
    adapter = re_memory.ReMemoryAdapter(root, "audit")
    plans = tuple(row for s in snapshots for row in adapter.plan_re_artifact_rows(s.content, source=s.source, artifact_metadata=s.artifact_metadata))
    observation = GraphMemoryAudit(
        origin="returned", schema_version=report.schema_version, wing=report.wing, status=report.status,
        artifact_count=report.artifact_count, expected_count=report.expected_count, present_current_count=report.present_current_count,
        **{name: tuple(getattr(report, name)) for name in ("missing", "stale", "wrong_wing", "wrong_room", "duplicate", "non_canonical", "lifecycle_excluded", "errors")},
    )
    result = build_memory_graph_contribution(
        spec_id=SPEC_ID, lifecycle="phase_a", domain="published-re",
        sources=tuple(GraphMemorySource(s.source, s.content, s.artifact_metadata["artifact_kind"], s.artifact_metadata["room"]) for s in snapshots),
        planned_rows=plans, audit=observation, known_node_ids=(),
    )
    # Existing RE projection excludes issues outside its selected drawer IDs.
    assert result.receipt.status == "pass"
    assert report.status == "warn"
