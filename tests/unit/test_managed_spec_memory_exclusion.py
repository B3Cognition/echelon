from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import stat

import pytest

from echelon.mempalace_requirements import SpecMemoryError
from echelon.mempalace_spec_evidence import mine_spec_evidence_memory
from harness.element_identity_legacy_guard import LEGACY_IDENTITY_EXECUTION_BLOCKED
from harness.element_identity_managed import ManagedIdentityRequest
from harness.element_identity_store import IdentityStore
from harness.squad_source_manifest import snapshot_source_manifest
from harness.squad_source_snapshot import inspect_project_tree
from tests.unit.test_mempalace_spec_evidence import write_evidence_workspace
from tests.unit.test_mempalace_requirements import write_workspace


def snapshot(root):
    entries = []
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        payload = None
        if path.is_symlink():
            payload = str(path.readlink())
        elif stat.S_ISREG(mode):
            payload = path.read_bytes()
        entries.append((path.relative_to(root).as_posix(), stat.S_IFMT(mode), payload))
    database = root / ".echelon/identity/registry.sqlite3"
    sql = None
    if database.is_file():
        with closing(sqlite3.connect(database)) as connection:
            sql = tuple(connection.iterdump())
    return tuple(entries), sql


def enroll_managed_spec(root: Path, spec_id: str, *, run_id: str | None = None):
    run_id = run_id or f"owner-{spec_id}"
    store = (
        IdentityStore.open(root)
        if (root / ".echelon/identity").exists()
        else IdentityStore.initialize(root)
    )
    selected = f"runs/{run_id}/specs/{spec_id}"
    selected_dir = root / selected
    selected_dir.mkdir(parents=True)
    with inspect_project_tree(root, selected) as tree:
        manifest = snapshot_source_manifest(trees=(tree,), files=())
    source_operation = f"source-{spec_id}"
    source = store.register_source_context(
        spec_id=spec_id,
        context_id="source",
        operation_id=source_operation,
        manifest=manifest,
    )
    return store.register_managed_identity(
        spec_id=spec_id,
        operation_id=f"managed-{spec_id}",
        request=ManagedIdentityRequest(
            source["workspace_uuid"],
            source["epoch_uuid"],
            run_id,
            "source",
            selected,
            source_operation,
            manifest.sha256,
        ),
    )


def assert_bounded(action, error=SpecMemoryError):
    with pytest.raises(error) as raised:
        action()
    assert str(raised.value) == LEGACY_IDENTITY_EXECUTION_BLOCKED
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    if hasattr(raised.value, "receipt"):
        assert raised.value.receipt is None


def acquisition_tripwire(effects, label):
    def forbidden(*args, **kwargs):
        effects.append(label)
        raise AssertionError(f"managed owner reached {label}")

    return forbidden


class LocalCollection:
    def __init__(self, rows):
        self.rows = dict(rows)
        self.deleted = []

    def get(self, ids=None, where=None, include=None, limit=None, offset=None):
        rows = list(self.rows.items())
        if ids is not None:
            rows = [(drawer_id, self.rows[drawer_id]) for drawer_id in ids if drawer_id in self.rows]
        if where is not None:
            def selected(row):
                return all(
                    row[1].get(key) == (value.get("$eq") if isinstance(value, dict) else value)
                    for key, value in where.items()
                )

            rows = [(drawer_id, row) for drawer_id, row in rows if selected(row)]
        if limit is not None:
            start = offset or 0
            rows = rows[start : start + limit]
        return {
            "ids": [drawer_id for drawer_id, _row in rows],
            "documents": [row[0] for _drawer_id, row in rows],
            "metadatas": [row[1] for _drawer_id, row in rows],
        }

    def add(self, *, documents, ids, metadatas):
        if not (len(documents) == len(ids) == len(metadatas)):
            raise ValueError("mismatched local collection rows")
        if any(drawer_id in self.rows for drawer_id in ids):
            raise ValueError("duplicate local collection drawer")
        for drawer_id, document, metadata in zip(ids, documents, metadatas):
            self.rows[drawer_id] = (document, dict(metadata))

    def delete(self, ids=None, **kwargs):
        selected = list(ids if ids is not None else kwargs["ids"])
        self.deleted.extend(selected)
        for drawer_id in selected:
            self.rows.pop(drawer_id, None)
        return {"deleted": len(selected)}


def install_local_mempalace(monkeypatch, collection):
    from codegen.memory import collision, mempalace_writer
    from codegen.memory.mempalace_writer import MemPalaceWriter

    monkeypatch.setattr(collision, "_get_collection", lambda _path: collection)
    monkeypatch.setattr(mempalace_writer, "add_drawer", object())
    monkeypatch.setattr(MemPalaceWriter, "_get_collection", lambda self: collection)
    monkeypatch.setattr(
        MemPalaceWriter,
        "get_collection_read_only",
        lambda self: collection,
    )


def add_verify_evidence_alias(root: Path, alias: str) -> None:
    verify_root = root / "runs/spec-20260728-120000/verify-spec"
    shutil.copytree(verify_root / "003-demo", verify_root / alias)
    state_path = verify_root / alias / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["spec_id"] = alias
    state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")


def test_managed_evidence_mining_rejects_before_adapter_acquisition(tmp_path, monkeypatch):
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    store = IdentityStore.initialize(tmp_path)
    selected = "runs/managed-source/specs/003-demo"
    selected_dir = tmp_path / selected
    selected_dir.mkdir(parents=True)
    with inspect_project_tree(tmp_path, selected) as tree:
        manifest = snapshot_source_manifest(trees=(tree,), files=())
    source = store.register_source_context(
        spec_id="003-demo",
        context_id="source",
        operation_id="source-003-demo",
        manifest=manifest,
    )
    store.register_managed_identity(
        spec_id="003-demo",
        operation_id="managed-003-demo",
        request=ManagedIdentityRequest(
            source["workspace_uuid"],
            source["epoch_uuid"],
            "managed-source",
            "source",
            selected,
            "source-003-demo",
            manifest.sha256,
        ),
    )
    assert spec_dir == tmp_path / "specs/003-demo"

    effects = []

    def forbidden(*args, **kwargs):
        effects.append("create_spec_evidence_memory_adapter")
        raise AssertionError("managed evidence mining reached adapter acquisition")

    monkeypatch.setattr(evidence, "create_spec_evidence_memory_adapter", forbidden)
    before = snapshot(tmp_path)
    with pytest.raises(SpecMemoryError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
        mine_spec_evidence_memory(tmp_path, "003-demo", run_id="manual")
    assert effects == []
    assert snapshot(tmp_path) == before


def test_managed_requirement_mining_numeric_selector_rejects_before_adapter(tmp_path, monkeypatch):
    import echelon.mempalace_requirements as requirements

    write_workspace(tmp_path)
    enroll_managed_spec(tmp_path, "003-demo")
    effects = []
    monkeypatch.setattr(
        requirements,
        "create_requirement_memory_adapter",
        acquisition_tripwire(effects, "requirement adapter"),
    )
    before = snapshot(tmp_path)
    assert_bounded(lambda: requirements.mine_spec_requirements(tmp_path, "003", run_id="manual"))
    assert effects == []
    assert snapshot(tmp_path) == before


def test_managed_cleanup_path_selector_rejects_before_planning_or_adapter(tmp_path, monkeypatch):
    import echelon.mempalace_audit as audit

    write_workspace(tmp_path)
    enroll_managed_spec(tmp_path, "003-demo")
    effects = []
    monkeypatch.setattr(
        audit,
        "create_requirement_memory_adapter",
        acquisition_tripwire(effects, "cleanup adapter"),
    )
    before = snapshot(tmp_path)
    assert_bounded(lambda: audit.cleanup_stale_spec_memory(tmp_path, Path("specs/003-demo")))
    assert effects == []
    assert snapshot(tmp_path) == before


def test_managed_zero_evidence_is_not_admitted(tmp_path, monkeypatch):
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    spec_dir.joinpath("fulfillment-report.md").unlink()
    spec_dir.joinpath("verified-fulfillment-ledger.json").unlink()
    enroll_managed_spec(tmp_path, "003-demo")
    effects = []
    monkeypatch.setattr(
        evidence,
        "create_spec_evidence_memory_adapter",
        acquisition_tripwire(effects, "evidence adapter"),
    )
    before = snapshot(tmp_path)
    assert_bounded(lambda: evidence.mine_spec_evidence_memory(tmp_path, "003-demo", run_id="manual"))
    assert effects == []
    assert snapshot(tmp_path) == before


def test_managed_publication_preserves_existing_package_before_mkdir_copy_or_manifest(
    tmp_path, monkeypatch,
):
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    evidence_dir = spec_dir / "evidence"
    evidence_dir.mkdir()
    evidence_dir.joinpath("manifest.json").write_text('{"retained":true}\n', encoding="utf-8")
    evidence_dir.joinpath("implementation-map.md").write_text("retained\n", encoding="utf-8")
    enroll_managed_spec(tmp_path, "003-demo")
    effects = []
    real_mkdir = Path.mkdir

    def observed_mkdir(path, *args, **kwargs):
        if path == evidence_dir:
            effects.append("evidence mkdir")
            raise AssertionError("managed publication reached evidence mkdir")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", observed_mkdir)
    monkeypatch.setattr(
        evidence.shutil,
        "copy2",
        acquisition_tripwire(effects, "evidence copy"),
    )
    before = snapshot(tmp_path)
    assert_bounded(lambda: evidence.publish_spec_evidence_package(tmp_path, "003-demo"))
    assert effects == []
    assert snapshot(tmp_path) == before


def test_managed_purge_without_config_refuses_before_not_applicable_receipt(tmp_path, monkeypatch):
    import echelon.mempalace_retarget as retarget

    enroll_managed_spec(tmp_path, "003-demo")
    effects = []
    monkeypatch.setattr(
        retarget,
        "_configured_mempalace_wing",
        acquisition_tripwire(effects, "retarget config"),
    )
    before = snapshot(tmp_path)
    assert_bounded(
        lambda: retarget.purge_retarget_spec_memory(tmp_path, "003-demo"),
        retarget.RetargetMemoryError,
    )
    assert effects == []
    assert snapshot(tmp_path) == before


def test_managed_refresh_refuses_before_config_adapter_or_report_recovery(tmp_path, monkeypatch):
    import echelon.mempalace_retarget as retarget

    spec_dir = write_workspace(tmp_path)
    enroll_managed_spec(tmp_path, "003-demo")
    effects = []
    monkeypatch.setattr(
        retarget,
        "_configured_mempalace_wing",
        acquisition_tripwire(effects, "retarget config"),
    )
    before = snapshot(tmp_path)
    assert_bounded(
        lambda: retarget.refresh_retarget_spec_memory(tmp_path, spec_dir),
        retarget.RetargetMemoryError,
    )
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("managed_id", ["004-alias", "003-demo"])
def test_requirement_symlink_selector_checks_selected_and_physical_identities(
    tmp_path, monkeypatch, managed_id,
):
    import echelon.mempalace_requirements as requirements

    spec_dir = write_workspace(tmp_path)
    alias = spec_dir.with_name("004-alias")
    alias.symlink_to(spec_dir.name, target_is_directory=True)
    enroll_managed_spec(tmp_path, managed_id)
    effects = []
    monkeypatch.setattr(
        requirements,
        "create_requirement_memory_adapter",
        acquisition_tripwire(effects, "requirement adapter"),
    )
    before = snapshot(tmp_path)
    assert_bounded(lambda: requirements.mine_spec_requirements(tmp_path, "004-alias", run_id="manual"))
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("managed_id", ["004-alias", "003-demo"])
def test_cleanup_symlink_selector_checks_selected_and_physical_identities(
    tmp_path, monkeypatch, managed_id,
):
    import echelon.mempalace_audit as audit

    spec_dir = write_workspace(tmp_path)
    alias = spec_dir.with_name("004-alias")
    alias.symlink_to(spec_dir.name, target_is_directory=True)
    enroll_managed_spec(tmp_path, managed_id)
    effects = []
    monkeypatch.setattr(
        audit,
        "create_requirement_memory_adapter",
        acquisition_tripwire(effects, "cleanup adapter"),
    )
    before = snapshot(tmp_path)
    assert_bounded(lambda: audit.cleanup_stale_spec_memory(tmp_path, alias.name))
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("managed_id", ["004-alias", "003-demo"])
def test_evidence_mining_symlink_selector_checks_selected_and_physical_identities(
    tmp_path, monkeypatch, managed_id,
):
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    alias = spec_dir.with_name("004-alias")
    alias.symlink_to(spec_dir.name, target_is_directory=True)
    enroll_managed_spec(tmp_path, managed_id)
    effects = []
    monkeypatch.setattr(
        evidence,
        "create_spec_evidence_memory_adapter",
        acquisition_tripwire(effects, "evidence adapter"),
    )
    before = snapshot(tmp_path)
    assert_bounded(
        lambda: evidence.mine_spec_evidence_memory(
            tmp_path,
            alias.name,
            run_id="manual",
        )
    )
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("managed_id", ["004-alias", "003-demo"])
def test_evidence_publication_symlink_selector_checks_selected_and_physical_identities(
    tmp_path, monkeypatch, managed_id,
):
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    alias = spec_dir.with_name("004-alias")
    alias.symlink_to(spec_dir.name, target_is_directory=True)
    add_verify_evidence_alias(tmp_path, alias.name)
    enroll_managed_spec(tmp_path, managed_id)
    effects = []
    real_mkdir = Path.mkdir

    def observed_mkdir(path, *args, **kwargs):
        if path == alias / "evidence":
            effects.append("evidence mkdir")
            raise AssertionError("managed alias publication reached evidence mkdir")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", observed_mkdir)
    monkeypatch.setattr(
        evidence.shutil,
        "copy2",
        acquisition_tripwire(effects, "evidence copy"),
    )
    before = snapshot(tmp_path)
    assert_bounded(
        lambda: evidence.publish_spec_evidence_package(tmp_path, alias.name)
    )
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("managed_id", ["004-alias", "003-demo"])
def test_retarget_refresh_symlink_selector_checks_selected_and_physical_identities(
    tmp_path, monkeypatch, managed_id,
):
    import echelon.mempalace_retarget as retarget

    spec_dir = write_workspace(tmp_path)
    alias = spec_dir.with_name("004-alias")
    alias.symlink_to(spec_dir.name, target_is_directory=True)
    enroll_managed_spec(tmp_path, managed_id)
    effects = []
    monkeypatch.setattr(
        retarget,
        "_configured_mempalace_wing",
        acquisition_tripwire(effects, "retarget config"),
    )
    before = snapshot(tmp_path)
    assert_bounded(
        lambda: retarget.refresh_retarget_spec_memory(tmp_path, alias),
        retarget.RetargetMemoryError,
    )
    assert effects == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("owner", "damage"),
    [
        ("evidence", "malformed-managed"),
        ("cleanup", "orphan-genesis"),
        ("publication", "missing-database"),
        ("requirements", "missing-marker"),
    ],
)
def test_invalid_retained_authority_is_bounded_before_leaf_effect(
    tmp_path, monkeypatch, owner, damage,
):
    import echelon.mempalace_audit as audit
    import echelon.mempalace_requirements as requirements
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    enroll_managed_spec(tmp_path, "003-demo")
    database = tmp_path / ".echelon/identity/registry.sqlite3"
    if damage in {"malformed-managed", "orphan-genesis"}:
        with closing(sqlite3.connect(database)) as connection:
            if damage == "malformed-managed":
                connection.execute(
                    "UPDATE managed_identity_specs SET request='{}',request_sha256='bad' "
                    "WHERE spec_id='003-demo'"
                )
            else:
                connection.execute("DELETE FROM managed_identity_specs WHERE spec_id='003-demo'")
            connection.commit()
    elif damage == "missing-database":
        database.unlink()
    else:
        (tmp_path / ".echelon/identity/authority.json").unlink()

    effects = []
    if owner == "evidence":
        monkeypatch.setattr(
            evidence,
            "create_spec_evidence_memory_adapter",
            acquisition_tripwire(effects, "evidence adapter"),
        )
        action = lambda: evidence.mine_spec_evidence_memory(tmp_path, "003-demo", run_id="manual")
    elif owner == "cleanup":
        monkeypatch.setattr(
            audit,
            "create_requirement_memory_adapter",
            acquisition_tripwire(effects, "cleanup adapter"),
        )
        action = lambda: audit.cleanup_stale_spec_memory(tmp_path, "003-demo")
    elif owner == "publication":
        monkeypatch.setattr(
            evidence.shutil,
            "copy2",
            acquisition_tripwire(effects, "evidence copy"),
        )
        action = lambda: evidence.publish_spec_evidence_package(tmp_path, "003-demo")
    else:
        monkeypatch.setattr(
            requirements,
            "create_requirement_memory_adapter",
            acquisition_tripwire(effects, "requirement adapter"),
        )
        action = lambda: requirements.mine_spec_requirements(tmp_path, "003-demo", run_id="manual")
    before = snapshot(tmp_path)
    assert_bounded(action)
    assert effects == []
    assert snapshot(tmp_path) == before


def test_direct_translation_bounds_identity_errors_and_propagates_process_control(
    tmp_path, monkeypatch,
):
    import echelon.mempalace_requirements as requirements
    from harness.element_identity_store import IdentityStoreError

    def identity_failure(**kwargs):
        raise IdentityStoreError("private identity detail")

    monkeypatch.setattr(requirements, "require_legacy_identity_spec", identity_failure)
    assert_bounded(
        lambda: requirements._require_legacy_spec_memory(tmp_path, spec_id="003-demo")
    )

    for exception in (KeyboardInterrupt(), GeneratorExit(), SystemExit()):
        def process_control(**kwargs):
            raise exception

        monkeypatch.setattr(requirements, "require_legacy_identity_spec", process_control)
        with pytest.raises(type(exception)):
            requirements._require_legacy_spec_memory(tmp_path, spec_id="003-demo")


def test_unrelated_authority_preserves_legacy_requirement_alias_mining(
    tmp_path, monkeypatch,
):
    import echelon.mempalace_requirements as requirements

    spec_dir = write_workspace(tmp_path)
    alias = spec_dir.with_name("004-alias")
    alias.symlink_to(spec_dir.name, target_is_directory=True)
    IdentityStore.initialize(tmp_path)
    enroll_managed_spec(tmp_path, "999-unrelated", run_id="manual")
    collection = LocalCollection({})
    install_local_mempalace(monkeypatch, collection)
    report = requirements.mine_spec_requirements(tmp_path, alias, run_id="manual")
    assert report.status == "complete"
    assert report.spec_id == "003-demo"
    assert report.written_count == 2
    assert report.adopted_count == 0
    assert report.failed_count == 0
    assert report.drawer_ids == [
        "drawer_demo-wing_functional-requirements_"
        "030f38098da74edce33f15481ef195007e647987561cc1230cca023d54b4f602",
        "drawer_demo-wing_non-functional-requirements_"
        "94c4c6283c516412cbcad68cf6acf48839251207cb72832db311a3a10136c16b",
    ]
    assert report.expected_drawer_ids == report.drawer_ids
    assert sorted(collection.rows) == report.drawer_ids
    rows_by_requirement = {
        metadata["requirement_id"]: (drawer_id, document, metadata)
        for drawer_id, (document, metadata) in collection.rows.items()
    }
    assert set(rows_by_requirement) == {"FR-001", "NFR-001"}
    functional = rows_by_requirement["FR-001"]
    assert functional[1] == "FR-001: Upload a photo."
    assert functional[2]["room"] == "functional-requirements"
    assert functional[2]["source_file"] == "specs/003-demo/spec.md"
    assert functional[2]["artifact_path"] == "specs/003-demo/spec.md"
    assert functional[2]["canonical_spec_sha256"] == (
        "c9698026144b9653999c75bcb3dd29e9dd585d6e05ef9f3ba49e0229b4bc6fcf"
    )
    assert functional[2]["requirement_content_sha256"] == (
        "4b84c42d63c891e7827e88fb598c5b809c69c2b28cd3861fde0aeb3a6b43d14d"
    )
    nonfunctional = rows_by_requirement["NFR-001"]
    assert nonfunctional[1] == "NFR-001: Respond within 1s."
    assert nonfunctional[2]["room"] == "non-functional-requirements"
    assert all(
        metadata["wing"] == "demo-wing"
        and metadata["run_id"] == "manual"
        and metadata["scope"] == "canonical"
        and metadata["canonical"] is True
        and metadata["provenance_type"] == "requirements_mine"
        for _drawer_id, _document, metadata in rows_by_requirement.values()
    )


def test_legacy_evidence_mining_uses_native_adapter_and_local_collection_seam(
    tmp_path, monkeypatch,
):
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    spec_dir.joinpath("fulfillment-report.md").unlink()
    IdentityStore.initialize(tmp_path)
    enroll_managed_spec(tmp_path, "999-unrelated")
    collection = LocalCollection(
        {
            "old-evidence": (
                "old",
                {"artifact_kind": "spec-evidence", "spec_id": "003-demo", "wing": "demo-wing"},
            ),
            "other": (
                "other",
                {"artifact_kind": "spec-evidence", "spec_id": "004-other", "wing": "demo-wing"},
            ),
        }
    )
    install_local_mempalace(monkeypatch, collection)
    report = evidence.mine_spec_evidence_memory(tmp_path, "003-demo", run_id="manual")
    assert report.status == "complete"
    assert report.artifact_count == 1
    assert report.written_count == 1
    assert report.adopted_count == 0
    assert report.failed_count == 0
    expected_id = (
        "drawer_demo-wing_spec-fulfillment-evidence_"
        "427895e988fd1caeed70b3627092d690383ecf631d1ad52d6812e31c1078d608"
    )
    assert report.drawer_ids == [expected_id]
    assert report.expected_drawer_ids == [expected_id]
    assert collection.deleted == ["old-evidence"]
    assert "other" in collection.rows
    document, metadata = collection.rows[expected_id]
    assert document == (
        "EVID-specs-003-demo-verified-fulfillment-ledger-json-000: "
        'verified-fulfillment-ledger.json: {"FR-001":{"status":"IMPLEMENTED"}}'
    )
    assert metadata["requirement_id"] == (
        "EVID-specs-003-demo-verified-fulfillment-ledger-json-000"
    )
    assert metadata["wing"] == "demo-wing"
    assert metadata["room"] == "spec-fulfillment-evidence"
    assert metadata["run_id"] == "manual"
    assert metadata["phase"] == "VERIFY"
    assert metadata["scope"] == "canonical"
    assert metadata["artifact_kind"] == "spec-evidence"
    assert metadata["artifact_path"] == (
        "specs/003-demo/verified-fulfillment-ledger.json"
    )
    assert metadata["canonical_spec_sha256"] == (
        "7fd572f7e9e21be49949714103185da38bf91a4ee4443abce48520db98140d8a"
    )
    assert metadata["requirement_content_sha256"] == (
        "aea4ee162608d284500b6e7aa4b1670a363f4567a3a53861a95b4968e32c59dd"
    )


def test_legacy_cleanup_uses_native_adapter_planner_and_local_collection_seam(
    tmp_path, monkeypatch,
):
    from echelon.spec_memory_miner import SpecMemoryMiner
    import echelon.mempalace_audit as audit

    spec_dir = write_workspace(tmp_path)
    collection = LocalCollection(
        {
            "stale": (
                "old",
                {
                    "wing": "demo-wing",
                    "canonical": True,
                    "artifact_path": "specs/003-demo/spec.md",
                    "source_file": "specs/003-demo/spec.md",
                },
            ),
            "other": (
                "other",
                {
                    "wing": "demo-wing",
                    "canonical": True,
                    "artifact_path": "specs/004-other/spec.md",
                    "source_file": "specs/004-other/spec.md",
                },
            ),
        }
    )
    monkeypatch.setattr(SpecMemoryMiner, "open_collection_read_only", lambda self: collection)
    report = audit.cleanup_stale_spec_memory(tmp_path, spec_dir)
    assert report.deleted_count == 1
    assert report.deleted_ids == ["stale"]
    assert collection.deleted == ["stale"]
    assert list(collection.rows) == ["other"]


def test_publish_all_keeps_managed_package_and_publishes_real_legacy_package(tmp_path):
    import echelon.mempalace_spec_evidence as evidence

    managed = write_evidence_workspace(tmp_path)
    legacy = managed.with_name("004-legacy")
    shutil.copytree(managed, legacy)
    verify_root = tmp_path / "runs/spec-20260728-120000/verify-spec"
    shutil.copytree(verify_root / "003-demo", verify_root / "004-legacy")
    state_path = verify_root / "004-legacy/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["spec_id"] = "004-legacy"
    state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    retained = managed / "evidence"
    retained.mkdir()
    retained.joinpath("manifest.json").write_text('{"retained":true}\n', encoding="utf-8")
    enroll_managed_spec(tmp_path, "003-demo")
    before_managed = snapshot(tmp_path)[0]

    report = evidence.publish_all_spec_evidence_packages(tmp_path)

    assert report.status == "partial"
    assert report.total_count == 2
    assert report.published_count == 1
    assert report.failed_count == 1
    assert [item.spec_id for item in report.reports] == ["004-legacy"]
    assert report.errors == [f"003-demo:{LEGACY_IDENTITY_EXECUTION_BLOCKED}"]
    assert json.loads((retained / "manifest.json").read_text()) == {"retained": True}
    assert (legacy / "evidence/implementation-map.md").is_file()
    after_paths = snapshot(tmp_path)[0]
    managed_before = [entry for entry in before_managed if entry[0].startswith("specs/003-demo/")]
    managed_after = [entry for entry in after_paths if entry[0].startswith("specs/003-demo/")]
    assert managed_after == managed_before


def test_unmanaged_retarget_no_config_controls_remain_not_applicable(tmp_path):
    import echelon.mempalace_retarget as retarget

    spec_dir = tmp_path / "specs/003-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text("FR-001: Legacy.\n", encoding="utf-8")
    purge = retarget.purge_retarget_spec_memory(tmp_path, "003-demo")
    refresh = retarget.refresh_retarget_spec_memory(tmp_path, spec_dir)
    assert purge.status == "not_applicable"
    assert purge.deleted_ids == ()
    assert refresh.status == "not_applicable"
    assert refresh.mine_status == "not_applicable"
    assert refresh.audit_status == "not_applicable"


def test_native_validation_precedes_managed_admission(tmp_path):
    import echelon.mempalace_requirements as requirements
    import echelon.mempalace_retarget as retarget
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    enroll_managed_spec(tmp_path, "003-demo")
    with pytest.raises(SpecMemoryError, match="could not resolve"):
        requirements.mine_spec_requirements(tmp_path, "missing", run_id="manual")
    spec_dir.joinpath("spec.md").write_text(
        "---\nstatus: ready_to_land\n---\nFR-001: Import.\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecMemoryError, match="requires landed spec"):
        evidence.mine_spec_evidence_memory(tmp_path, "003-demo", run_id="manual")
    with pytest.raises(retarget.RetargetMemoryError, match="invalid retarget spec identity"):
        retarget.purge_retarget_spec_memory(tmp_path, "003")
    outside = tmp_path.parent / "003-demo"
    with pytest.raises(retarget.RetargetMemoryError, match="outside the project"):
        retarget.refresh_retarget_spec_memory(tmp_path, outside)


def test_publication_source_selection_error_precedes_managed_admission(tmp_path):
    import echelon.mempalace_spec_evidence as evidence

    spec_dir = write_evidence_workspace(tmp_path)
    shutil.rmtree(tmp_path / "runs")
    enroll_managed_spec(tmp_path, "003-demo")
    before = snapshot(tmp_path)
    with pytest.raises(SpecMemoryError, match="published verify evidence source not found"):
        evidence.publish_spec_evidence_package(tmp_path, spec_dir)
    assert snapshot(tmp_path) == before
