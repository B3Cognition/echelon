from dataclasses import dataclass
from pathlib import Path

from echelon.context_metadata import artifact_hash
from echelon.context_reconciliation import reconcile_drawers


@dataclass
class Drawer:
    drawer_id: str
    content: str
    metadata: dict
    room: str = "functional-requirements"
    distance: float = 0.1


def test_reconcile_keeps_matching_artifact_hash(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Upload a photo.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": artifact_hash(spec),
            "status": "active",
            "wing": "demo",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert [d.drawer_id for d in report.accepted] == ["d1"]
    assert report.rejected == []


def test_reconcile_prefers_lifecycle_status_over_writer_status(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Upload a photo.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": artifact_hash(spec),
            "status": "pending",
            "lifecycle_status": "active",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert [d.drawer_id for d in report.accepted] == ["d1"]
    assert report.rejected == []


def test_reconcile_rejects_stale_hash(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Old wording.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": "sha256:" + "0" * 64,
            "status": "active",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert report.accepted == []
    assert report.rejected[0]["reason"] == "hash_mismatch"


def test_reconcile_rejects_missing_artifact_hash(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Upload a photo.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "status": "active",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert report.accepted == []
    assert report.rejected[0]["reason"] == "missing_artifact_hash"


def test_reconcile_excludes_removed_by_default(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Upload a photo.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": artifact_hash(spec),
            "status": "removed",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert report.accepted == []
    assert report.rejected[0]["reason"] == "lifecycle_excluded"


def test_reconcile_rejects_runs_artifacts_even_when_hash_matches(tmp_path: Path) -> None:
    spec = tmp_path / "runs" / "spec-1" / "specs" / "002-share-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Share a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Share a photo.",
        metadata={
            "artifact_path": "runs/spec-1/specs/002-share-album/spec.md",
            "artifact_hash": artifact_hash(spec),
            "status": "active",
        },
    )

    report = reconcile_drawers([drawer], tmp_path)

    assert report.accepted == []
    assert report.rejected[0]["reason"] == "non_canonical_artifact_path"


def test_reconcile_treats_empty_status_filter_as_exclusive(tmp_path: Path) -> None:
    spec = tmp_path / "specs" / "001-photo-album" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    drawer = Drawer(
        drawer_id="d1",
        content="FR-001: Upload a photo.",
        metadata={
            "artifact_path": "specs/001-photo-album/spec.md",
            "artifact_hash": artifact_hash(spec),
            "status": "active",
        },
    )

    report = reconcile_drawers([drawer], tmp_path, include_statuses=set())

    assert report.accepted == []
    assert report.rejected[0]["reason"] == "lifecycle_excluded"
    assert report.rejected[0]["status"] == "active"
