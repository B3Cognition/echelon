from pathlib import Path

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

    def get(self, ids=None, where=None, include=None):
        if ids is not None:
            found = [(drawer_id, self.rows[drawer_id]) for drawer_id in ids if drawer_id in self.rows]
            return {
                "ids": [drawer_id for drawer_id, _row in found],
                "documents": [row["document"] for _drawer_id, row in found],
                "metadatas": [row["metadata"] for _drawer_id, row in found],
            }
        return {"ids": [], "documents": [], "metadatas": []}


class FakeAdapter:
    wing = "demo-wing"
    palace_path = Path(".mempalace")

    def __init__(self, collection):
        self.collection = collection

    def plan_canonical_bytes(self, content, *, source, artifact_metadata):
        return ["drawer-fr-001"]


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
    rows = {
        "drawer-fr-001": {
            "document": "FR-001: Upload a photo.",
            "metadata": {
                "wing": "demo-wing",
                "room": "functional-requirements",
                "canonical": True,
                "artifact_path": snapshot.source,
                "artifact_hash": snapshot.artifact_metadata["artifact_hash"],
                "requirement_id": "FR-001",
                "requirement_content_sha256": "content-hash",
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

    assert report.status == "pass"
    assert report.present_current_count == 1
    assert report.missing == []


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
