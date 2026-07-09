from pathlib import Path
import json

from echelon.context_builder import build_run_context
from echelon.context_metadata import artifact_hash


class Drawer:
    def __init__(
        self,
        drawer_id: str,
        artifact_path: str,
        artifact_hash_value: str | None = None,
        status: str = "active",
        content: str = "",
    ):
        metadata = {"artifact_path": artifact_path}
        if artifact_hash_value is not None:
            metadata["artifact_hash"] = artifact_hash_value
        metadata["status"] = status
        self.drawer_id = drawer_id
        self.metadata = metadata
        self.content = content


def test_build_run_context_writes_prior_and_current_files(tmp_path: Path) -> None:
    canonical = tmp_path / "specs" / "001-photo-album"
    canonical.mkdir(parents=True)
    (canonical / "spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "spec-1"
    wip = run_dir / "specs" / "002-share-album"
    wip.mkdir(parents=True)
    (wip / "spec.md").write_text("FR-002: Share an album.\n", encoding="utf-8")
    (run_dir / "staging").mkdir(parents=True)
    (run_dir / "staging" / "mental-model.md").write_text("Album has photos.\n", encoding="utf-8")

    result = build_run_context(tmp_path, run_dir, user_request="share albums")

    assert result.context_dir == run_dir / "context"
    assert (run_dir / "context" / "prior-spec-context.md").read_text(encoding="utf-8").count("## 001-photo-album") == 1
    current_context = (run_dir / "context" / "current-feature-context.md").read_text(encoding="utf-8")
    assert "FR-002" in current_context
    assert "Share an album." in current_context
    assert "### mental-model.md" in current_context
    assert "Album has photos." in current_context
    assert (run_dir / "context" / "feature-registry.snapshot.json").exists()


def test_build_run_context_resolves_run_local_requirement_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "spec-1"
    wip = run_dir / "specs" / "002-share-album"
    wip.mkdir(parents=True)
    (wip / "spec.md").write_text("FR-002: Share an album.\n", encoding="utf-8")

    result = build_run_context(tmp_path, run_dir, user_request="share albums")

    current_context = (result.context_dir / "current-feature-context.md").read_text(encoding="utf-8")
    assert "FR-002: Share an album." in current_context
    assert "Requirement FR-002 is not linked to any run-local spec file." not in current_context


def test_build_run_context_skips_canonical_dirs_without_spec_md(tmp_path: Path) -> None:
    re_overview = tmp_path / "specs" / "000-re-overview"
    re_overview.mkdir(parents=True)
    (re_overview / "overview.md").write_text("# Reverse-engineering overview\n", encoding="utf-8")
    canonical = tmp_path / "specs" / "001-photo-album"
    canonical.mkdir(parents=True)
    (canonical / "spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "spec-1"
    wip = run_dir / "specs" / "002-share-album"
    wip.mkdir(parents=True)
    (wip / "spec.md").write_text("FR-002: Share an album.\n", encoding="utf-8")

    result = build_run_context(tmp_path, run_dir)

    prior_context = (result.context_dir / "prior-spec-context.md").read_text(encoding="utf-8")
    assert "## 001-photo-album" in prior_context
    assert "000-re-overview" not in prior_context


def test_stale_drawers_are_omitted_from_prior_context_and_reported_as_stale(tmp_path: Path) -> None:
    canonical = tmp_path / "specs" / "001-photo-album"
    canonical.mkdir(parents=True)
    spec_file = canonical / "spec.md"
    spec_file.write_text("FR-001: Upload a photo.\n", encoding="utf-8")

    run_dir = tmp_path / "runs" / "spec-1"
    wip = run_dir / "specs" / "002-share-album"
    wip.mkdir(parents=True)
    (wip / "spec.md").write_text("FR-002: Share an album.\n", encoding="utf-8")

    valid_drawer = Drawer(
        drawer_id="drawer-valid",
        artifact_path="specs/001-photo-album/spec.md",
        artifact_hash_value=artifact_hash(spec_file),
    )
    rejected_drawer = Drawer(
        drawer_id="drawer-stale-hash",
        artifact_path="specs/001-photo-album/spec.md",
        artifact_hash_value="sha256:" + "0" * 64,
        content="stale drawer content",
    )

    result = build_run_context(
        tmp_path,
        run_dir,
        drawers=[valid_drawer, rejected_drawer],
    )

    prior_context = (result.context_dir / "prior-spec-context.md").read_text(encoding="utf-8")
    stale_report = (result.context_dir / "stale-memory-report.md").read_text(encoding="utf-8")

    assert "drawer-valid" in prior_context
    assert "drawer-stale-hash" not in prior_context
    assert "drawer-stale-hash: hash_mismatch" in stale_report


def test_build_run_context_keeps_canonical_sidecar_unchanged_and_carries_lifecycle_only_records(tmp_path: Path) -> None:
    canonical = tmp_path / "specs" / "001-photo-album"
    canonical.mkdir(parents=True)
    spec_file = canonical / "spec.md"
    spec_file.write_text(
        "# Photo Album\n\n### User Story 1\n\nFR-002: Share an album.\n",
        encoding="utf-8",
    )

    stale_metadata = canonical / "feature-metadata.yml"
    stale_metadata.write_text(
        """
schema_version: 1
feature_id: 001-photo-album
spec_id: 001
slug: photo-album
status: changed
created_in_run: old
last_changed_in_run: old
supersedes:
  - 000-legacy-album
superseded_by:
  - 002-future-album
related_features:
  - 099-shared-gallery
use_cases:
  - id: UC-001
    title: Old user story
    status: changed
    source_requirements:
      - FR-001
    supersedes:
      - UC-000
    superseded_by:
      - UC-010
  - id: UC-999
    title: Removed legacy story
    status: removed
    source_requirements:
      - FR-001
requirements:
  - id: FR-001
    status: removed
    artifact_path: specs/001-photo-album/spec.md
    artifact_hash: sha256:0000
    use_cases:
      - UC-999
  - id: FR-002
    status: removed
    artifact_path: specs/001-photo-album/spec.md
    artifact_hash: sha256:1111
    use_cases:
      - UC-001
""",
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "spec-1"
    (run_dir / "specs" / "002-share-album").mkdir(parents=True)
    (run_dir / "specs" / "002-share-album" / "spec.md").write_text("FR-010: Another change.\n", encoding="utf-8")

    before = stale_metadata.read_text(encoding="utf-8")
    result = build_run_context(tmp_path, run_dir)
    after = stale_metadata.read_text(encoding="utf-8")

    prior_context = (result.context_dir / "prior-spec-context.md").read_text(encoding="utf-8")
    snapshot = json.loads((result.context_dir / "feature-registry.snapshot.json").read_text(encoding="utf-8"))

    assert "FR-002" in prior_context
    assert "FR-001 (removed)" in prior_context
    assert "UC-999 (removed): Removed legacy story" in prior_context
    assert before == after

    feature = snapshot["features"][0]
    assert [requirement["id"] for requirement in feature["requirements"]] == ["FR-002", "FR-001"]
    assert feature["status"] == "changed"
    assert feature["created_in_run"] == "old"
    assert feature["last_changed_in_run"] == "old"
    assert feature["supersedes"] == ["000-legacy-album"]
    assert feature["superseded_by"] == ["002-future-album"]
    assert feature["related_features"] == ["099-shared-gallery"]
    assert feature["requirements"][0]["status"] == "removed"
    assert feature["requirements"][0]["use_cases"] == []
    assert feature["requirements"][0]["artifact_hash"] == artifact_hash(spec_file)
    assert feature["requirements"][1]["status"] == "removed"
    assert feature["requirements"][1]["use_cases"] == ["UC-999"]
    assert feature["requirements"][1]["artifact_hash"] == "sha256:0000"
    assert [use_case["id"] for use_case in feature["use_cases"]] == ["UC-001", "UC-999"]
    assert feature["use_cases"][0]["title"] == "User Story 1"
    assert feature["use_cases"][0]["status"] == "changed"
    assert feature["use_cases"][0]["source_requirements"] == ["FR-002"]
    assert feature["use_cases"][0]["supersedes"] == ["UC-000"]
    assert feature["use_cases"][0]["superseded_by"] == ["UC-010"]
    assert feature["use_cases"][1]["title"] == "Removed legacy story"
    assert feature["use_cases"][1]["status"] == "removed"
    assert feature["use_cases"][1]["source_requirements"] == ["FR-001"]
    assert feature["use_cases"][1]["supersedes"] == []
    assert feature["use_cases"][1]["superseded_by"] == []


def test_invalid_stale_sidecar_statuses_fall_back_to_generated_values(tmp_path: Path) -> None:
    canonical = tmp_path / "specs" / "001-photo-album"
    canonical.mkdir(parents=True)
    spec_file = canonical / "spec.md"
    spec_file.write_text(
        "# Photo Album\n\n### User Story 1\n\nFR-002: Share an album.\n",
        encoding="utf-8",
    )

    (canonical / "feature-metadata.yml").write_text(
        """
schema_version: 1
feature_id: 001-photo-album
spec_id: 001
slug: photo-album
status: stale
use_cases:
  - id: UC-001
    title: Old user story
    status: invalid
    source_requirements:
      - FR-999
requirements:
  - id: FR-002
    status: retired
    artifact_path: specs/001-photo-album/spec.md
    artifact_hash: sha256:1111
    use_cases:
      - UC-999
""",
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "spec-1"
    (run_dir / "specs" / "002-share-album").mkdir(parents=True)
    (run_dir / "specs" / "002-share-album" / "spec.md").write_text("FR-010: Another change.\n", encoding="utf-8")

    result = build_run_context(tmp_path, run_dir)

    snapshot = json.loads((result.context_dir / "feature-registry.snapshot.json").read_text(encoding="utf-8"))
    prior_context = (result.context_dir / "prior-spec-context.md").read_text(encoding="utf-8")

    feature = snapshot["features"][0]
    assert feature["status"] == "active"
    assert feature["use_cases"][0]["status"] == "active"
    assert feature["requirements"][0]["status"] == "active"
    assert "Status: active" in prior_context
    assert "UC-001 (active): User Story 1" in prior_context
    assert "FR-002 (active)" in prior_context
