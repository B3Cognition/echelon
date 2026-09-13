"""Native captured audits with only the read-only storage boundary simulated."""

from copy import deepcopy
import hashlib
import importlib
from pathlib import Path
import traceback

import pytest

from echelon import mempalace_audit, mempalace_requirements
from echelon.spec_memory_miner import (
    _canonical_requirements_from_bytes, _canonical_support_from_bytes, scrub_secrets,
)
from harness.squad_publication import SquadPublicationTransaction
from harness.squad_source_projection import project_publication_source_images
from harness.squad_source_snapshot import inspect_project_tree
from tests.unit.test_squad_source_projection_images import secure_posix


pytestmark = pytest.mark.unit
SPEC_ID = "001-demo"
TREE_PATH = "specs/001-demo"
OLD_SPEC = b"FR-1000000: Preserve old behavior.\n"
NEW_SPEC = b"FR-1000000: Use candidate behavior.\n"
OLD_SUPPORT = b"# Plan\n\nPreserve old implementation.\n"
NEW_SUPPORT = b"# Plan\n\nUse candidate implementation.\n"


class ReadOnlyCollection:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.calls = []
        self.writes = []

    def get(self, *, include, ids=None, where=None, limit=None, offset=0):
        assert include == ["documents", "metadatas"]
        self.calls.append(dict(ids=ids, where=where, limit=limit, offset=offset))
        selected = list(self.rows)
        if ids is not None:
            assert where is None and limit is None and offset == 0
            selected = [key for key in ids if key in self.rows]
        else:
            assert where == {"wing": "captured-audit-test"}
            selected = [key for key in selected if self.rows[key][1].get("wing") == where["wing"]]
            selected = selected[offset:offset + limit]
        # Deliberately return backend-owned nested objects; production must detach.
        return {"ids": selected, "documents": [self.rows[key][0] for key in selected],
                "metadatas": [self.rows[key][1] for key in selected]}

    def _write(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("audit attempted storage mutation")

    add = upsert = update = delete = create_collection = get_or_create_collection = _write


def _project(tmp_path, monkeypatch, *, spec=OLD_SPEC, support=OLD_SUPPORT):
    root = tmp_path.resolve()
    (root / ".echelon").mkdir()
    (root / ".echelon/config.yml").write_text("mempalace:\n  wing: captured-audit-test\n")
    spec_dir = root / TREE_PATH
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_bytes(spec)
    if support is not None:
        (spec_dir / "plan.md").write_bytes(support)
    monkeypatch.setattr("codegen.memory.context._get_palace_path", lambda: str(root / "palace"))
    return root, spec_dir


def _native_rows(root, tree):
    adapter = mempalace_requirements.RequirementMemoryAdapter(root, "audit")
    rows, plans = {}, []
    for item in tree.files:
        suffix = Path(item.path).relative_to(tree.path).as_posix()
        if suffix != "spec.md" and suffix not in mempalace_requirements.SUPPORTING_MEMORY_ARTIFACTS:
            continue
        support = suffix != "spec.md"
        source = TREE_PATH + "/" + suffix
        metadata = dict(scope="canonical-support" if support else "canonical", canonical=True,
                        artifact_path=source, source_file=source,
                        artifact_hash="sha256:" + hashlib.sha256(item.content).hexdigest(),
                        lifecycle_status="active", provenance_type="requirements_mine", added_by="echelon")
        if support:
            metadata["artifact_kind"] = "supporting-context"
        planner = adapter.plan_canonical_support_rows if support else adapter.plan_canonical_rows
        parser = _canonical_support_from_bytes if support else _canonical_requirements_from_bytes
        planned = planner(item.content, source=source, artifact_metadata=metadata)
        _, requirements = parser(item.content, source=source, artifact_metadata=metadata)
        plans.extend(planned)
        for plan, requirement in zip(planned, requirements, strict=True):
            rows[plan.drawer_id] = (scrub_secrets(requirement.content), {
                **metadata, "wing": adapter.wing, "room": plan.room,
                "deterministic_identity_schema_version": 1,
                "requirement_id": plan.requirement_id,
                "canonical_spec_sha256": plan.canonical_spec_sha256,
                "requirement_content_sha256": plan.requirement_content_sha256,
            })
    return rows, plans


def _storage(monkeypatch, root, collection):
    class Writer:
        def __init__(self, context):
            assert context.palace_path == str(root / "palace")
            assert context.run_id == "audit"

        def get_collection_read_only(self):
            return collection

        def forbidden(self, *args, **kwargs):
            raise AssertionError("creating/writing storage access")

        get_collection = write = write_exact = delete = forbidden

    monkeypatch.setattr("codegen.memory.mempalace_writer.MemPalaceWriter", Writer)


def _capture(root, tree_path=TREE_PATH):
    with inspect_project_tree(root, tree_path) as tree:
        pass
    return tree


def _audit(root, tree, **kwargs):
    captured = importlib.import_module("echelon.mempalace_captured_audit")
    return captured.audit_captured_spec_memory(
        root, spec_id=SPEC_ID, tree=tree, maximum_scan_rows=kwargs.pop("maximum_scan_rows", 2000), **kwargs,
    )


def test_captured_audit_reads_candidate_tree_and_actual_collection(tmp_path, monkeypatch, secure_posix):
    root, spec_dir = _project(tmp_path, monkeypatch)
    squad = root / "runs/spec-test"
    squad.mkdir(parents=True)
    transaction = SquadPublicationTransaction.begin(root, squad, "a" * 32)
    for filename, content in (("spec.md", NEW_SPEC), ("plan.md", NEW_SUPPORT)):
        stage = transaction.build_path(filename)
        stage.write_bytes(content)
        target = Path(TREE_PATH) / filename
        transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=(TREE_PATH,)) as initial:
        pass
    projected_tree, = project_publication_source_images(initial).trees
    candidate_rows, plans = _native_rows(root, projected_tree)
    assert len(plans) == 2
    collection = ReadOnlyCollection(candidate_rows)
    _storage(monkeypatch, root, collection)

    old_rows, _ = _native_rows(root, initial.trees[0])
    collection.rows = deepcopy(old_rows)
    old_control = mempalace_audit.audit_spec_memory(root, spec_dir)
    assert old_control.status == "pass" and old_control.present_current_count == 2
    collection.rows = deepcopy(candidate_rows)

    legacy = mempalace_audit.audit_spec_memory(root, spec_dir)
    assert legacy.status == "fail"
    assert legacy.present_current_count == 0
    report = _audit(root, projected_tree)
    assert report.status == "pass", report.to_dict()
    assert report.expected_count == len(candidate_rows)
    assert report.present_current_count == len(candidate_rows)
    assert report.missing == report.stale == report.non_canonical == []
    assert (spec_dir / "spec.md").read_bytes() == OLD_SPEC
    assert (spec_dir / "plan.md").read_bytes() == OLD_SUPPORT
    assert collection.writes == []


def _case(tmp_path, monkeypatch, **kwargs):
    root, spec_dir = _project(tmp_path, monkeypatch, **kwargs)
    tree = _capture(root)
    rows, plans = _native_rows(root, tree)
    collection = ReadOnlyCollection(rows)
    _storage(monkeypatch, root, collection)
    return root, spec_dir, tree, collection, plans


@pytest.mark.parametrize("change", [
    "present", "missing", "document", "artifact_hash", "canonical_spec_sha256",
    "requirement_content_sha256", "wing", "room", "artifact_path", "scope",
    "canonical", "requirement_id", "deterministic_identity_schema_version",
    "deprecated", "superseded", "removed", "delivered", "artifact_kind",
    "historical", "active_duplicate", "evidence", "malformed_document",
    "malformed_metadata", "duplicate_response_id",
])
@pytest.mark.parametrize("probe", [False, True])
def test_complete_native_report_parity(tmp_path, monkeypatch, change, probe):
    # Catches drift in any shared classification, count, probe or report field.
    root, spec_dir, tree, collection, plans = _case(tmp_path, monkeypatch)
    main = next(row for row in plans if row.requirement_id == "FR-1000000")
    support = next(row for row in plans if row.requirement_id.startswith("CTX-"))
    key = main.drawer_id
    document, metadata = collection.rows[key]
    if change == "missing":
        del collection.rows[key]
    elif change == "document":
        collection.rows[key] = ("changed document", metadata)
    elif change in {"deprecated", "superseded", "removed", "delivered"}:
        metadata["lifecycle_status"] = change
    elif change == "artifact_kind":
        collection.rows[support.drawer_id][1]["artifact_kind"] = "invalid"
    elif change in {"historical", "active_duplicate", "evidence"}:
        extra = deepcopy(metadata)
        if change == "historical":
            extra["lifecycle_status"] = "superseded"
        elif change == "evidence":
            extra.update(scope="spec-evidence", artifact_kind="spec-evidence", requirement_id="EVID-1000000")
        collection.rows["extra"] = (document, extra)
    elif change not in {"present", "malformed_document", "malformed_metadata", "duplicate_response_id"}:
        metadata[change] = False if change == "canonical" else "invalid"
    if change.startswith("malformed_") or change == "duplicate_response_id":
        # Malformed expected responses keep native classification when the full
        # wing observation consistently contains no valid row for that ID.
        del collection.rows[key]
        original = collection.get

        def malformed_get(**kwargs):
            raw = original(**kwargs)
            if kwargs.get("ids") is not None:
                raw["ids"].append(key)
                raw["documents"].append(None if change == "malformed_document" else document)
                raw["metadatas"].append(None if change == "malformed_metadata" else metadata)
                if change == "duplicate_response_id":
                    raw["ids"].append(key)
                    raw["documents"].append(document)
                    raw["metadatas"].append(metadata)
            return raw

        monkeypatch.setattr(collection, "get", malformed_get)
    before = deepcopy(collection.rows)
    native = mempalace_audit.audit_spec_memory(root, spec_dir, probe_retrieval=probe)
    captured = _audit(root, tree, probe_retrieval=probe)
    assert captured.to_dict() == native.to_dict()
    assert captured.expected_count == 2
    if change in {"present", "evidence"}:
        assert captured.status == ("warn" if probe else "pass")
        assert captured.present_current_count == 2
    elif change == "historical":
        assert captured.status == "warn" and captured.historical == ["extra"]
    else:
        assert captured.status == "fail"
    assert collection.rows == before and collection.writes == []


@pytest.mark.parametrize("physical", [TREE_PATH, "runs/spec-test/specs/001-demo", "staging/selected"])
def test_explicit_physical_selection_uses_canonical_keys_for_all_supports(tmp_path, monkeypatch, physical):
    root, spec_dir = _project(tmp_path, monkeypatch)
    target = root / physical
    target.mkdir(parents=True, exist_ok=True)
    (target / "spec.md").write_bytes(NEW_SPEC)
    for name in mempalace_requirements.SUPPORTING_MEMORY_ARTIFACTS:
        (target / name).write_bytes(b"# Context\n\nSelected native supporting context.\n")
    (target / "nested").mkdir()
    (target / "nested/plan.md").write_bytes(b"\xffignored nested support")
    (target / "random.md").write_bytes(b"\xffignored nonselected artifact")
    (target / ".opaque.bin").write_bytes(b"\x00\xffignored binary")
    tree = _capture(root, physical)
    before = deepcopy(tree)
    rows, plans = _native_rows(root, tree)
    collection = ReadOnlyCollection(rows)
    _storage(monkeypatch, root, collection)
    report = _audit(root, tree)
    assert report.status == "pass"
    assert report.expected_count == report.present_current_count == 14
    assert report.spec_dir == str(spec_dir)
    assert {row.source for row in plans} == {
        TREE_PATH + "/" + name for name in {"spec.md", *mempalace_requirements.SUPPORTING_MEMORY_ARTIFACTS}
    }
    assert tree == before


def test_detaches_original_tree_and_never_rereads_source(tmp_path, monkeypatch):
    root, spec_dir, tree, collection, _ = _case(tmp_path, monkeypatch)
    captured = importlib.import_module("echelon.mempalace_captured_audit")
    factory = captured.create_requirement_memory_adapter

    def detached_factory(project_root, run_id):
        for item in tree.files:
            object.__setattr__(item, "content", b"corrupted after acquisition")
            object.__setattr__(item, "path", "outside/source")
        object.__setattr__(tree, "files", ())
        return factory(project_root, run_id)

    monkeypatch.setattr(captured, "create_requirement_memory_adapter", detached_factory)
    for name in ("spec.md", "plan.md"):
        (spec_dir / name).unlink()

    def forbidden(*args, **kwargs):
        raise AssertionError("source reread or source path resolution")

    for owner in (mempalace_audit, mempalace_requirements):
        monkeypatch.setattr(owner, "load_canonical_spec_snapshot", forbidden)
        monkeypatch.setattr(owner, "load_supporting_artifact_snapshots", forbidden)
    monkeypatch.setattr(mempalace_audit, "reconcile_drawers", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    read_text = Path.read_text

    def config_only(path, *args, **kwargs):
        assert path == root / ".echelon/config.yml"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", config_only)
    report = _audit(root, tree)
    assert report.status == "pass" and report.present_current_count == 2
    assert collection.writes == []


@pytest.mark.parametrize("field,value", [
    ("maximum_scan_rows", 0), ("maximum_scan_rows", -1), ("maximum_scan_rows", True),
    ("maximum_scan_rows", 2.0), ("maximum_scan_rows", "2000"),
    ("probe_retrieval", 0), ("probe_retrieval", 1), ("probe_retrieval", None),
    ("project_root", "absolute-looking-string"), ("project_root", Path("relative")),
    ("spec_id", 1), ("spec_id", ""), ("spec_id", "../001-demo"),
    ("spec_id", "001-demo/child"), ("spec_id", "001-demo\\child"),
    ("spec_id", " 001-demo"), ("spec_id", "\ud800"), ("spec_id", "bad\ncomponent"),
    ("tree", None), ("tree", {}),
])
def test_invalid_input_is_bounded_before_adapter_acquisition(tmp_path, monkeypatch, field, value):
    root, _, tree, _, _ = _case(tmp_path, monkeypatch)
    captured = importlib.import_module("echelon.mempalace_captured_audit")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid input acquired adapter")

    monkeypatch.setattr(captured, "create_requirement_memory_adapter", forbidden)
    kwargs = dict(project_root=root, spec_id=SPEC_ID, tree=tree, maximum_scan_rows=2000)
    kwargs[field] = value
    with pytest.raises(mempalace_requirements.SpecMemoryError) as caught:
        captured.audit_captured_spec_memory(**kwargs)
    assert str(caught.value) == "invalid captured spec memory input"
    assert caught.value.__cause__ is caught.value.__context__ is None
    formatted = "".join(traceback.format_exception(caught.value))
    assert "manifest_invalid" not in formatted and "invalid spec component" not in formatted


@pytest.mark.parametrize("damage", ["hash", "content", "file_mode", "directory_mode", "membership", "missing", "empty", "spec_directory"])
def test_validates_ignored_tree_entries_and_requires_regular_spec(tmp_path, monkeypatch, damage):
    root, spec_dir = _project(tmp_path, monkeypatch)
    (spec_dir / ".opaque.bin").write_bytes(b"\xff\x00")
    tree = _capture(root)
    opaque = next(item for item in tree.files if item.path.endswith(".opaque.bin"))
    if damage == "hash":
        object.__setattr__(opaque.image, "sha256", "0" * 64)
    elif damage == "content":
        object.__setattr__(opaque, "content", b"other binary")
    elif damage == "file_mode":
        object.__setattr__(opaque.image, "mode", -1)
    elif damage == "directory_mode":
        object.__setattr__(tree.directories[0], "mode", -1)
    elif damage == "membership":
        object.__setattr__(opaque, "path", TREE_PATH + "/missing-parent/opaque.bin")
    else:
        for item in spec_dir.iterdir():
            item.unlink()
        if damage == "missing":
            spec_dir.rmdir()
        elif damage == "spec_directory":
            (spec_dir / "spec.md").mkdir()
        tree = _capture(root)
    captured = importlib.import_module("echelon.mempalace_captured_audit")
    monkeypatch.setattr(captured, "create_requirement_memory_adapter", lambda *a, **k: pytest.fail("acquired adapter"))
    with pytest.raises(mempalace_requirements.SpecMemoryError, match="^invalid captured spec memory input$") as caught:
        _audit(root, tree)
    assert caught.value.__cause__ is caught.value.__context__ is None


def _extras(collection, count):
    for index in range(count):
        collection.rows[f"unrelated-{index:04}"] = ("unrelated", {"wing": "captured-audit-test"})


def test_complete_scan_sees_active_duplicate_beyond_native_window(tmp_path, monkeypatch):
    root, spec_dir, tree, collection, plans = _case(tmp_path, monkeypatch)
    _extras(collection, 1000)
    main = next(row for row in plans if row.requirement_id == "FR-1000000")
    collection.rows["late-active-duplicate"] = deepcopy(collection.rows[main.drawer_id])
    legacy = mempalace_audit.audit_spec_memory(root, spec_dir)
    assert legacy.status == "pass" and legacy.duplicate_canonical == []
    collection.calls.clear()
    strict = _audit(root, tree, maximum_scan_rows=1003)
    assert strict.status == "fail" and strict.duplicate_canonical == ["late-active-duplicate"]
    assert [call["offset"] for call in collection.calls if call["where"]] == [0, 512, 1003, 0, 512, 1003]
    assert _audit(root, tree, maximum_scan_rows=1002).status == "unavailable"
    assert collection.writes == []


@pytest.mark.parametrize("count,budget", [(0, 1), (2, 2), (512, 512), (513, 514)])
def test_empty_exact_budget_and_paged_scan_controls(tmp_path, monkeypatch, count, budget):
    root, spec_dir, tree, collection, _ = _case(tmp_path, monkeypatch, spec=b"", support=None)
    assert collection.rows == {}
    _extras(collection, count)
    native = mempalace_audit.audit_spec_memory(root, spec_dir)
    collection.calls.clear()
    report = _audit(root, tree, maximum_scan_rows=budget)
    assert report.to_dict() == native.to_dict()
    assert report.status == "pass" and report.expected_count == report.present_current_count == 0
    assert collection.calls and all(call["ids"] is None for call in collection.calls)


@pytest.mark.parametrize("fault", ["unsupported", "truncated", "excess", "duplicate", "duplicate_page", "wrong_wing", "order", "rows", "nested_reuse", "malformed", "shape"])
def test_incomplete_or_changing_scan_is_unavailable(tmp_path, monkeypatch, fault):
    root, _, tree, collection, _ = _case(tmp_path, monkeypatch)
    _extras(collection, 511)
    original = collection.get
    starts = 0

    def bad_get(**kwargs):
        nonlocal starts
        if kwargs.get("where") and kwargs.get("offset", 0) == 0:
            starts += 1
        if kwargs.get("where") and fault == "unsupported":
            raise TypeError("sensitive pagination details")
        if kwargs.get("where") and starts == 2 and fault == "nested_reuse":
            collection.rows["unrelated-0000"][1]["nested"]["values"].append("changed")
        raw = original(**kwargs)
        if not kwargs.get("where"):
            return raw
        if fault == "truncated" and kwargs.get("offset", 0) == 0:
            return {field: values[:2] for field, values in raw.items()}
        if fault == "excess" and kwargs.get("offset", 0) == 0:
            key = list(collection.rows)[-1]
            raw["ids"].append(key)
            raw["documents"].append(collection.rows[key][0])
            raw["metadatas"].append(collection.rows[key][1])
        if fault == "duplicate_page" and len(raw["ids"]) > 1:
            raw["ids"][1] = raw["ids"][0]
        if fault == "duplicate" and kwargs.get("offset", 0) == 512:
            key = next(iter(collection.rows))
            return {"ids": [key], "documents": [collection.rows[key][0]], "metadatas": [collection.rows[key][1]]}
        if fault == "wrong_wing" and raw["ids"]:
            raw["metadatas"] = deepcopy(raw["metadatas"])
            raw["metadatas"][0]["wing"] = "other-wing"
        if fault == "order" and starts == 2:
            return {field: list(reversed(values)) for field, values in raw.items()}
        if fault == "rows" and starts == 2 and raw["ids"]:
            raw["documents"][0] = "changed scan document"
        if fault == "malformed" and raw["ids"]:
            raw["documents"][0] = None
        if fault == "shape":
            return {"ids": []}
        return raw

    collection.rows["unrelated-0000"][1]["nested"] = {"values": ["before"]}
    monkeypatch.setattr(collection, "get", bad_get)
    report = _audit(root, tree)
    assert report.status == "unavailable" and report.expected_count == 2
    assert report.present_current_count == 0 and report.errors == ["SpecMemoryError"]


@pytest.mark.parametrize("fault", ["added", "removed", "document", "metadata", "nested", "unrequested", "unrequested_malformed"])
def test_expected_fetch_and_full_scan_require_one_cohort(tmp_path, monkeypatch, fault):
    root, _, tree, collection, plans = _case(tmp_path, monkeypatch)
    key = plans[0].drawer_id
    saved = deepcopy(collection.rows[key])
    if fault == "added":
        del collection.rows[key]
    if fault == "nested":
        collection.rows[key][1]["nested"] = {"values": ["before"]}
    original = collection.get
    transitioned = False

    def drifting_get(**kwargs):
        nonlocal transitioned
        if kwargs.get("where") and not transitioned:
            transitioned = True
            if fault == "added":
                collection.rows[key] = saved
            elif fault == "removed":
                del collection.rows[key]
            elif fault == "document":
                collection.rows[key] = ("changed", collection.rows[key][1])
            elif fault == "metadata":
                collection.rows[key][1]["room"] = "changed"
            elif fault == "nested":
                collection.rows[key][1]["nested"]["values"].append("changed")
        raw = original(**kwargs)
        if kwargs.get("ids") and fault.startswith("unrequested"):
            raw["ids"].append("unrequested")
            raw["documents"].append(None if fault.endswith("malformed") else "unexpected")
            raw["metadatas"].append({"wing": "captured-audit-test"})
        return raw

    monkeypatch.setattr(collection, "get", drifting_get)
    report = _audit(root, tree)
    assert report.status == "unavailable" and report.expected_count == 2
    assert report.errors == ["SpecMemoryError"]
    if fault.startswith("unrequested"):
        assert all(call["where"] is None for call in collection.calls)


@pytest.mark.parametrize("seam", ["adapter", "main_plan", "support_plan", "open", "get", "copy", "reconciliation"])
@pytest.mark.parametrize("error_type", [RuntimeError, SystemExit, KeyboardInterrupt])
def test_operational_failures_are_bounded_and_interrupts_propagate(tmp_path, monkeypatch, seam, error_type):
    root, _, tree, collection, _ = _case(tmp_path, monkeypatch)
    captured = importlib.import_module("echelon.mempalace_captured_audit")

    def fail(*args, **kwargs):
        raise error_type("private-source-and-backend-details")

    if seam == "adapter":
        monkeypatch.setattr(captured, "create_requirement_memory_adapter", fail)
    elif seam == "main_plan":
        monkeypatch.setattr(mempalace_requirements.RequirementMemoryAdapter, "plan_canonical_rows", fail)
    elif seam == "support_plan":
        monkeypatch.setattr(mempalace_requirements.RequirementMemoryAdapter, "plan_canonical_support_rows", fail)
    elif seam == "open":
        monkeypatch.setattr(mempalace_requirements.RequirementMemoryAdapter, "open_collection_read_only", fail)
    elif seam == "get":
        monkeypatch.setattr(collection, "get", fail)
    elif seam == "copy":
        class Uncopyable:
            __deepcopy__ = fail

        collection.rows[next(iter(collection.rows))][1]["nested"] = Uncopyable()
    else:
        monkeypatch.setattr(captured, "reconcile_captured_drawers", fail)
    if error_type is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            _audit(root, tree)
        return
    report = _audit(root, tree)
    assert report.status == ("fail" if seam in {"main_plan", "support_plan", "reconciliation"} else "unavailable")
    assert report.expected_count == (0 if seam in {"adapter", "main_plan", "support_plan"} else 2)
    assert report.present_current_count == 0
    assert report.errors == [error_type.__name__]
    assert report.recommendations == (["reconciliation_failed"] if seam == "reconciliation" else [])
    assert "private-source-and-backend-details" not in repr(report.to_dict())


def test_native_planning_failure_for_invalid_utf8_and_missing_config(tmp_path, monkeypatch):
    root, spec_dir = _project(tmp_path, monkeypatch, spec=b"\xff", support=None)
    tree = _capture(root)
    collection = ReadOnlyCollection({})
    _storage(monkeypatch, root, collection)
    report = _audit(root, tree)
    native = mempalace_audit.audit_spec_memory(root, spec_dir)
    assert report.to_dict() == native.to_dict()
    assert report.status == "fail" and report.errors == ["ValueError"]
    assert collection.calls == []
    (root / ".echelon/config.yml").unlink()
    unavailable = _audit(root, tree)
    assert unavailable.status == "unavailable" and unavailable.expected_count == 0
    assert unavailable.wing is None and unavailable.errors == ["SpecMemoryError"]


@pytest.mark.parametrize("error_type", [RuntimeError, SystemExit, KeyboardInterrupt])
def test_source_validation_bounds_ordinary_errors_only(tmp_path, monkeypatch, error_type):
    root, _, tree, _, _ = _case(tmp_path, monkeypatch)
    captured = importlib.import_module("echelon.mempalace_captured_audit")

    class ExceptionalPath(type(root)):
        def is_absolute(self):
            raise error_type("private-selected-source")

    monkeypatch.setattr(captured, "create_requirement_memory_adapter", lambda *a, **k: pytest.fail("acquired adapter"))
    if error_type is not RuntimeError:
        with pytest.raises(error_type):
            _audit(ExceptionalPath(root), tree)
    else:
        with pytest.raises(mempalace_requirements.SpecMemoryError) as caught:
            _audit(ExceptionalPath(root), tree)
        assert caught.value.__context__ is caught.value.__cause__ is None
        assert "private-selected-source" not in "".join(traceback.format_exception(caught.value))


def test_required_budget_and_exact_scalar_subclasses(tmp_path, monkeypatch):
    root, _, tree, _, _ = _case(tmp_path, monkeypatch)
    captured = importlib.import_module("echelon.mempalace_captured_audit")
    monkeypatch.setattr(captured, "create_requirement_memory_adapter", lambda *a, **k: pytest.fail("acquired adapter"))
    with pytest.raises(TypeError):
        captured.audit_captured_spec_memory(root, spec_id=SPEC_ID, tree=tree)

    class IntBudget(int):
        pass

    class SpecString(str):
        pass

    with pytest.raises(mempalace_requirements.SpecMemoryError):
        _audit(root, tree, maximum_scan_rows=IntBudget(2000))
    with pytest.raises(mempalace_requirements.SpecMemoryError):
        captured.audit_captured_spec_memory(root, spec_id=SpecString(SPEC_ID), tree=tree, maximum_scan_rows=2000)


def test_returned_audit_cannot_replace_selected_source_tree(tmp_path, monkeypatch):
    root, _, tree, _, _ = _case(tmp_path, monkeypatch)
    report = _audit(root, tree)
    assert report.status == "pass"
    captured = importlib.import_module("echelon.mempalace_captured_audit")
    monkeypatch.setattr(captured, "create_requirement_memory_adapter", lambda *a, **k: pytest.fail("acquired adapter"))
    with pytest.raises(mempalace_requirements.SpecMemoryError):
        _audit(root, report)


def test_zero_native_plan_still_classifies_relevant_extras(tmp_path, monkeypatch):
    root, spec_dir, tree, collection, _ = _case(tmp_path, monkeypatch, spec=b"", support=None)
    collection.rows["old-active-row"] = ("old", dict(
        wing="captured-audit-test", artifact_path=TREE_PATH + "/spec.md",
        artifact_hash="sha256:" + "0" * 64, requirement_id="FR-1000000", canonical=True,
    ))
    native = mempalace_audit.audit_spec_memory(root, spec_dir)
    collection.calls.clear()
    report = _audit(root, tree)
    assert report.to_dict() == native.to_dict()
    assert report.status == "fail" and report.stale == ["old-active-row"]
    assert report.expected_count == 0 and all(call["ids"] is None for call in collection.calls)


@pytest.mark.parametrize("state,presence", [("missing", "missing"), ("stale", "invalid"), ("unavailable", "unavailable")])
def test_actual_audit_observation_is_preserved_in_graph_contribution(tmp_path, monkeypatch, state, presence):
    from echelon.spec_graph_memory import GraphMemoryAudit, GraphMemorySource, build_memory_graph_contribution

    root, _, tree, collection, plans = _case(tmp_path, monkeypatch, support=None)
    key = plans[0].drawer_id
    if state == "missing":
        del collection.rows[key]
    elif state == "stale":
        collection.rows[key] = ("stale stored text", collection.rows[key][1])
    else:
        def unavailable(**kwargs):
            raise OSError("storage unavailable")
        monkeypatch.setattr(collection, "get", unavailable)
    report = _audit(root, tree)
    observation = GraphMemoryAudit(
        origin="returned", schema_version=report.schema_version, wing=report.wing,
        status=report.status, artifact_count=1, expected_count=report.expected_count,
        present_current_count=report.present_current_count,
        **{name: tuple(getattr(report, name)) for name in (
            "missing", "stale", "wrong_wing", "wrong_room", "duplicate", "non_canonical",
            "lifecycle_excluded", "errors",
        )},
    )
    result = build_memory_graph_contribution(
        spec_id=SPEC_ID, lifecycle="phase_a", domain="canonical-spec",
        sources=(GraphMemorySource(TREE_PATH + "/spec.md", OLD_SPEC, "requirement", ""),),
        planned_rows=tuple(plans), audit=observation,
        known_node_ids=(f"req:{SPEC_ID}:FR-1000000",),
    )
    drawer = next(node for node in result.nodes if node.type == "MemPalaceDrawer")
    assert drawer.properties["presence"] == presence
    assert drawer.properties["reconciliation_status"] == report.status
    if state == "stale":
        assert report.stale == [key] and "stale" in drawer.properties["issue_codes"]
    assert result.receipt.status == report.status
    assert "identity" not in drawer.properties and "revision" not in drawer.properties
    assert all(edge.properties.get("presence") != "present" for edge in result.edges)
