import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def make_spec(tmp_path: Path) -> Path:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    return spec_dir


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.deleted_ids = []

    def get(self, ids=None, where=None, include=None, limit=None):
        self.calls.append(
            {"ids": ids, "where": where, "include": include, "limit": limit}
        )
        if ids is not None:
            found = [(drawer_id, self.rows[drawer_id]) for drawer_id in ids if drawer_id in self.rows]
        else:
            found = [
                (drawer_id, row)
                for drawer_id, row in self.rows.items()
                if where is None
                or all(row.get("metadata", {}).get(key) == value for key, value in where.items())
            ][:limit]
        return {
            "ids": [drawer_id for drawer_id, _row in found],
            "documents": [row["document"] for _drawer_id, row in found],
            "metadatas": [row["metadata"] for _drawer_id, row in found],
        }

    def delete(self, ids):
        self.deleted_ids.extend(ids)
        for drawer_id in ids:
            self.rows.pop(drawer_id, None)


class FakeAdapter:
    wing = "demo-wing"
    palace_path = Path(".mempalace")

    def __init__(self, collection):
        self.collection = collection

    def plan_canonical_rows(self, content, *, source, artifact_metadata):
        document = "FR-001: Upload a photo."
        return [
            SimpleNamespace(
                drawer_id="drawer-fr-001",
                requirement_id="FR-001",
                room="functional-requirements",
                source=source,
                artifact_hash=artifact_metadata["artifact_hash"],
                canonical_spec_sha256=hashlib.sha256(content).hexdigest(),
                requirement_content_sha256=hashlib.sha256(
                    document.encode("utf-8")
                ).hexdigest(),
            )
        ]

    def plan_canonical_support_rows(self, content, *, source, artifact_metadata):
        document = "CTX-plan-000: Plan: Implement FR-001. [linked_requirements: FR-001]"
        return [
            SimpleNamespace(
                drawer_id="drawer-plan-000",
                requirement_id="CTX-plan-000",
                room="implementation-plan",
                source=source,
                artifact_hash=artifact_metadata["artifact_hash"],
                canonical_spec_sha256=hashlib.sha256(content).hexdigest(),
                requirement_content_sha256=hashlib.sha256(
                    document.encode("utf-8")
                ).hexdigest(),
            )
        ]

    def open_collection_read_only(self):
        return self.collection

    def verify_canonical_bytes(self, content, *, source, artifact_metadata, drawer_ids):
        raw = self.collection.get(ids=drawer_ids, include=["documents", "metadatas"])
        if raw.get("ids") != drawer_ids or len(drawer_ids) != 1:
            return False
        document = content.decode("utf-8").strip()
        metadata = raw["metadatas"][0]
        digest = hashlib.sha256(content).hexdigest()
        return raw["documents"] == [document] and all(
            metadata.get(key) == value
            for key, value in {
                "deterministic_identity_schema_version": 1,
                "wing": self.wing,
                "room": "functional-requirements",
                "scope": "canonical",
                "canonical": True,
                "artifact_hash": f"sha256:{digest}",
                "canonical_spec_sha256": digest,
                "requirement_id": "FR-001",
                "requirement_content_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
            }.items()
        )


def current_row(snapshot) -> dict:
    document = "FR-001: Upload a photo."
    return {
        "document": document,
        "metadata": {
            "deterministic_identity_schema_version": 1,
            "wing": "demo-wing",
            "room": "functional-requirements",
            "scope": "canonical",
            "canonical": True,
            "artifact_path": snapshot.source,
            "artifact_hash": snapshot.artifact_metadata["artifact_hash"],
            "canonical_spec_sha256": snapshot.spec_sha256,
            "requirement_id": "FR-001",
            "requirement_content_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
            "lifecycle_status": "active",
        },
    }


def current_support_row(snapshot) -> dict:
    document = "CTX-plan-000: Plan: Implement FR-001. [linked_requirements: FR-001]"
    return {
        "document": document,
        "metadata": {
            "deterministic_identity_schema_version": 1,
            "wing": "demo-wing",
            "room": "implementation-plan",
            "scope": "canonical-support",
            "canonical": True,
            "artifact_kind": "supporting-context",
            "artifact_path": snapshot.source,
            "artifact_hash": snapshot.artifact_metadata["artifact_hash"],
            "canonical_spec_sha256": snapshot.spec_sha256,
            "requirement_id": "CTX-plan-000",
            "requirement_content_sha256": hashlib.sha256(
                document.encode("utf-8")
            ).hexdigest(),
            "lifecycle_status": "active",
        },
    }


@pytest.mark.unit
def test_audit_reports_missing_exact_drawer(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection({})),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.expected_count == 1
    assert report.missing == ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_passes_matching_exact_drawer(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    rows = {"drawer-fr-001": current_row(snapshot)}
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection(rows)),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "pass"
    assert report.present_current_count == 1
    assert report.missing == []


@pytest.mark.unit
def test_audit_ignores_separately_reconciled_spec_evidence_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_audit import audit_spec_memory
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    rows = {
        "drawer-fr-001": current_row(snapshot),
        "drawer-evidence": {
            "document": "EVID-001: Published verification evidence.",
            "metadata": {
                "artifact_kind": "spec-evidence",
                "artifact_path": "specs/003-demo/evidence/manifest.json",
                "canonical": True,
                "scope": "spec-evidence",
                "wing": "demo-wing",
            },
        },
    }
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection(rows)),
    )

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "pass"
    assert report.stale == []
    assert report.non_canonical == []


@pytest.mark.unit
def test_audit_includes_support_artifact_rows_in_expected_set(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = make_spec(tmp_path)
    spec_dir.joinpath("plan.md").write_text(
        "# Plan\n\nImplement FR-001.\n",
        encoding="utf-8",
    )
    from echelon.mempalace_requirements import (
        load_canonical_spec_snapshot,
        load_supporting_artifact_snapshots,
    )

    spec_snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    support_snapshot = load_supporting_artifact_snapshots(tmp_path, spec_dir)[0]
    rows = {
        "drawer-fr-001": current_row(spec_snapshot),
        "drawer-plan-000": current_support_row(support_snapshot),
    }
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection(rows)),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "pass"
    assert report.expected_count == 2
    assert report.present_current_count == 2
    assert report.stale == []


@pytest.mark.unit
def test_audit_rejects_run_local_scope_on_otherwise_exact_drawer(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    row = current_row(load_canonical_spec_snapshot(tmp_path, spec_dir))
    row["metadata"]["scope"] = "run-local"
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(
            FakeCollection({"drawer-fr-001": row})
        ),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.present_current_count == 0
    assert report.non_canonical == ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_uses_only_non_creating_collection_path(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    collection = FakeCollection({})

    class ReadOnlyAdapter(FakeAdapter):
        def __init__(self):
            super().__init__(collection)
            self.miner = SimpleNamespace(
                _get_writer=lambda: SimpleNamespace(
                    _get_collection=lambda: pytest.fail("creating path called")
                )
            )

    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: ReadOnlyAdapter(),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert collection.calls[0]["ids"] == ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_classifies_wrong_wing_and_stale_hash(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    rows = {
        "drawer-fr-001": {
            "document": "FR-001: Upload a photo.",
            "metadata": {
                "wing": "wrong-wing",
                "room": "functional-requirements",
                "canonical": True,
                "artifact_path": "specs/003-demo/spec.md",
                "artifact_hash": "sha256:" + "0" * 64,
                "requirement_id": "FR-001",
                "lifecycle_status": "active",
            },
        }
    }
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection(rows)),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.wrong_wing == ["drawer-fr-001"]
    assert report.stale == ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_accepts_exact_security_requirement_room(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    spec_dir.joinpath("spec.md").write_text(
        "SEC-001: Encrypt uploaded photos.\n",
        encoding="utf-8",
    )
    from echelon.spec_memory_miner import plan_canonical_requirement_drawers
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    planned = plan_canonical_requirement_drawers(
        snapshot.content,
        source=snapshot.source,
        artifact_metadata=snapshot.artifact_metadata,
        wing="demo-wing",
    )[0]
    row = {
        "document": "SEC-001: Encrypt uploaded photos.",
        "metadata": {
            "deterministic_identity_schema_version": 1,
            "wing": "demo-wing",
            "room": planned.room,
            "scope": "canonical",
            "canonical": True,
            "artifact_path": snapshot.source,
            "artifact_hash": snapshot.artifact_metadata["artifact_hash"],
            "canonical_spec_sha256": snapshot.spec_sha256,
            "requirement_id": planned.requirement_id,
            "requirement_content_sha256": planned.requirement_content_sha256,
            "lifecycle_status": "active",
        },
    }

    class SecurityAdapter(FakeAdapter):
        def plan_canonical_rows(self, content, *, source, artifact_metadata):
            return [planned]

    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: SecurityAdapter(
            FakeCollection({planned.drawer_id: row})
        ),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "pass"
    assert report.wrong_room == []


@pytest.mark.unit
def test_audit_reports_security_requirement_in_wrong_room(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    spec_dir.joinpath("spec.md").write_text(
        "SEC-001: Encrypt uploaded photos.\n",
        encoding="utf-8",
    )
    from echelon.spec_memory_miner import plan_canonical_requirement_drawers
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    planned = plan_canonical_requirement_drawers(
        snapshot.content,
        source=snapshot.source,
        artifact_metadata=snapshot.artifact_metadata,
        wing="demo-wing",
    )[0]
    row = {
        "document": "SEC-001: Encrypt uploaded photos.",
        "metadata": {
            "deterministic_identity_schema_version": 1,
            "wing": "demo-wing",
            "room": "functional-requirements",
            "scope": "canonical",
            "canonical": True,
            "artifact_path": snapshot.source,
            "artifact_hash": snapshot.artifact_metadata["artifact_hash"],
            "canonical_spec_sha256": snapshot.spec_sha256,
            "requirement_id": planned.requirement_id,
            "requirement_content_sha256": planned.requirement_content_sha256,
            "lifecycle_status": "active",
        },
    }

    class SecurityAdapter(FakeAdapter):
        def plan_canonical_rows(self, content, *, source, artifact_metadata):
            return [planned]

    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: SecurityAdapter(
            FakeCollection({planned.drawer_id: row})
        ),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.wrong_room == [planned.drawer_id]


@pytest.mark.unit
def test_audit_reports_duplicate_stale_and_run_local_extras(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    current = current_row(snapshot)
    duplicate = current_row(snapshot)
    stale = current_row(snapshot)
    stale["metadata"]["requirement_id"] = "FR-REMOVED"
    stale["metadata"]["artifact_hash"] = "sha256:" + "0" * 64
    run_local = current_row(snapshot)
    run_local["metadata"]["canonical"] = False
    run_local["metadata"]["artifact_path"] = "runs/run-1/specs/003-demo/spec.md"
    rows = {
        "drawer-fr-001": current,
        "drawer-duplicate": duplicate,
        "drawer-stale": stale,
        "drawer-run-local": run_local,
    }
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection(rows)),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.duplicate == ["drawer-duplicate"]
    assert "drawer-stale" in report.stale
    assert "drawer-run-local" in report.non_canonical


@pytest.mark.unit
def test_cleanup_deletes_only_stale_canonical_rows_for_selected_spec(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    current = current_row(snapshot)
    stale = current_row(snapshot)
    stale["metadata"]["artifact_hash"] = "sha256:" + "0" * 64
    other_spec = current_row(snapshot)
    other_spec["metadata"]["artifact_path"] = "specs/004-other/spec.md"
    other_spec["metadata"]["source_file"] = "specs/004-other/spec.md"
    rows = {
        "drawer-fr-001": current,
        "drawer-stale": stale,
        "drawer-other-spec": other_spec,
    }
    collection = FakeCollection(rows)
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(collection),
    )
    from echelon.mempalace_audit import cleanup_stale_spec_memory

    report = cleanup_stale_spec_memory(tmp_path, spec_dir)

    assert report.deleted_count == 1
    assert report.deleted_ids == ["drawer-stale"]
    assert collection.deleted_ids == ["drawer-stale"]
    assert sorted(collection.rows) == ["drawer-fr-001", "drawer-other-spec"]


@pytest.mark.unit
def test_cleanup_deletes_stale_support_artifact_rows(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = make_spec(tmp_path)
    spec_dir.joinpath("plan.md").write_text(
        "# Plan\n\nImplement FR-001.\n",
        encoding="utf-8",
    )
    from echelon.mempalace_requirements import (
        load_canonical_spec_snapshot,
        load_supporting_artifact_snapshots,
    )

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    support = load_supporting_artifact_snapshots(tmp_path, spec_dir)[0]
    current = current_row(snapshot)
    stale_support = {
        "document": "old plan",
        "metadata": {
            "wing": "demo-wing",
            "room": "implementation-plan",
            "scope": "canonical-support",
            "canonical": True,
            "artifact_path": support.source,
            "artifact_hash": "sha256:" + "0" * 64,
            "requirement_id": "CTX-plan-000",
            "lifecycle_status": "active",
        },
    }
    unrelated_support = {
        "document": "other",
        "metadata": {
            "wing": "demo-wing",
            "scope": "canonical-support",
            "canonical": True,
            "artifact_path": "specs/003-demo/random-note.md",
        },
    }
    collection = FakeCollection(
        {
            "drawer-fr-001": current,
            "drawer-plan-stale": stale_support,
            "drawer-unrelated-support": unrelated_support,
        }
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(collection),
    )
    from echelon.mempalace_audit import cleanup_stale_spec_memory

    report = cleanup_stale_spec_memory(tmp_path, spec_dir)

    assert report.deleted_ids == ["drawer-plan-stale"]
    assert sorted(collection.rows) == ["drawer-fr-001", "drawer-unrelated-support"]


@pytest.mark.unit
def test_write_audit_reports_are_stable(tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport, write_audit_reports

    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    report = SpecMemoryAuditReport(
        schema_version=1,
        spec_id="003-demo",
        spec_dir=str(spec_dir),
        wing="demo-wing",
        palace_path=".mempalace",
        status="pass",
        expected_count=1,
        present_current_count=1,
    )

    json_path, md_path = write_audit_reports(report, spec_dir)

    assert json_path.read_text(encoding="utf-8").startswith("{\n")
    assert "MemPalace Audit: 003-demo" in md_path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_audit_rejects_corrupted_document_and_stable_metadata(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    row = current_row(load_canonical_spec_snapshot(tmp_path, spec_dir))
    row["document"] = "FR-001: Corrupted photo upload."
    row["metadata"]["requirement_content_sha256"] = "0" * 64
    row["metadata"]["canonical_spec_sha256"] = "0" * 64
    row["metadata"]["deterministic_identity_schema_version"] = 999
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection({"drawer-fr-001": row})),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.present_current_count == 0
    assert report.stale == ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_rejects_wrong_artifact_path_via_reconciliation(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    row = current_row(load_canonical_spec_snapshot(tmp_path, spec_dir))
    row["metadata"]["artifact_path"] = "runs/audit/specs/003-demo/spec.md"
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection({"drawer-fr-001": row})),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.present_current_count == 0
    assert report.non_canonical == ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_excludes_lifecycle_status_via_reconciliation(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    row = current_row(load_canonical_spec_snapshot(tmp_path, spec_dir))
    row["metadata"]["lifecycle_status"] = "removed"
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection({"drawer-fr-001": row})),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.present_current_count == 0
    assert report.lifecycle_excluded == ["drawer-fr-001"]


@pytest.mark.unit
def test_audit_bounds_reconciliation_fault_as_deterministic_failure(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    row = current_row(load_canonical_spec_snapshot(tmp_path, spec_dir))
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(
            FakeCollection({"drawer-fr-001": row})
        ),
    )

    def fail_reconciliation(drawers, project_root):
        raise RuntimeError("internal reconciliation fault")

    monkeypatch.setattr(
        "echelon.mempalace_audit.reconcile_drawers",
        fail_reconciliation,
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.expected_count == 1
    assert report.present_current_count == 0
    assert report.errors == ["RuntimeError"]
    assert report.recommendations == ["reconciliation_failed"]


@pytest.mark.unit
def test_audit_marks_malformed_collection_response_unavailable(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)

    class MalformedCollection:
        def get(self, ids=None, where=None, include=None):
            return {"ids": "drawer-fr-001", "documents": [], "metadatas": []}

    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(MalformedCollection()),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "unavailable"
    assert report.errors == ["SpecMemoryError"]


@pytest.mark.unit
def test_audit_classifies_malformed_row_fields_without_backend_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = make_spec(tmp_path)
    malformed = {
        "drawer-fr-001": {
            "document": None,
            "metadata": {"wing": "demo-wing"},
        }
    }
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(FakeCollection(malformed)),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.stale == ["drawer-fr-001"]
    assert "drawer-fr-001:invalid_document" in report.errors


@pytest.mark.unit
def test_audit_marks_bounded_scan_backend_failure_unavailable(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    class SecondReadFailureCollection(FakeCollection):
        def __init__(self, rows):
            super().__init__(rows)
            self.call_count = 0

        def get(self, ids=None, where=None, include=None, limit=None):
            self.call_count += 1
            if self.call_count > 1:
                raise OSError("MemPalace is unavailable")
            return super().get(
                ids=ids,
                where=where,
                include=include,
                limit=limit,
            )

    class VerificationBackendFailureAdapter(FakeAdapter):
        def verify_canonical_bytes(self, content, *, source, artifact_metadata, drawer_ids):
            return False

        def verify_canonical_bytes_outcome(self, content, *, source, artifact_metadata, drawer_ids):
            try:
                self.collection.get(ids=drawer_ids, include=["documents", "metadatas"])
            except OSError:
                return "unavailable"
            return "exact"

    row = current_row(load_canonical_spec_snapshot(tmp_path, spec_dir))
    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: VerificationBackendFailureAdapter(
            SecondReadFailureCollection({"drawer-fr-001": row})
        ),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "unavailable"
    assert report.errors == ["OSError"]


@pytest.mark.unit
def test_unavailable_audit_reports_error_class_without_traceback(tmp_path: Path, monkeypatch) -> None:
    spec_dir = make_spec(tmp_path)

    def boom(project_root, run_id):
        raise RuntimeError("backend details")

    monkeypatch.setattr("echelon.mempalace_audit.create_requirement_memory_adapter", boom)
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "unavailable"
    assert report.errors == ["RuntimeError"]


@pytest.mark.unit
def test_audit_uses_canonical_config_without_legacy_config(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = make_spec(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_requirements.RequirementMemoryAdapter.open_collection_read_only",
        lambda self: FakeCollection({}),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.wing == "demo-wing"
    assert report.missing


@pytest.mark.unit
@pytest.mark.parametrize("fault_type", (ValueError, RuntimeError))
def test_audit_bounds_planner_fault_as_deterministic_failure(
    tmp_path: Path, monkeypatch, fault_type: type[Exception]
) -> None:
    spec_dir = make_spec(tmp_path)

    class FaultyPlannerAdapter(FakeAdapter):
        def plan_canonical_rows(self, content, *, source, artifact_metadata):
            raise fault_type("canonical planner fault")

    monkeypatch.setattr(
        "echelon.mempalace_audit.create_requirement_memory_adapter",
        lambda project_root, run_id: FaultyPlannerAdapter(FakeCollection({})),
    )
    from echelon.mempalace_audit import audit_spec_memory

    report = audit_spec_memory(tmp_path, spec_dir)

    assert report.status == "fail"
    assert report.errors == [fault_type.__name__]
