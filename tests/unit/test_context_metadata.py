from pathlib import Path

import pytest

from echelon.context_metadata import artifact_hash
from echelon.context_metadata import (
    FeatureMetadata,
    RequirementMetadata,
    UseCaseMetadata,
    read_feature_metadata,
    validate_lifecycle_status,
    write_feature_metadata,
)


def test_artifact_hash_uses_sha256_prefix(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec\n\nFR-001: Upload a photo.\n", encoding="utf-8")

    digest = artifact_hash(spec)

    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_feature_metadata_from_spec_dir_extracts_requirements(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-photo-album"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "# Photo Album\n\n### User Story 1\n\nFR-001: Upload a photo.\nNFR-002: Finish quickly.\n",
        encoding="utf-8",
    )

    metadata = FeatureMetadata.from_spec_dir(spec_dir, run_id="spec-run")

    assert metadata.feature_id == "001-photo-album"
    assert [r.id for r in metadata.requirements] == ["FR-001", "NFR-002"]
    assert metadata.requirements[0].artifact_path == "specs/001-photo-album/spec.md"
    assert metadata.requirements[0].artifact_hash.startswith("sha256:")
    assert metadata.use_cases[0].id == "UC-001"


def test_feature_metadata_from_spec_dir_uses_run_local_relative_path(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "spec-1" / "specs" / "002-share-album"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("FR-001: Share a photo.\n", encoding="utf-8")

    metadata = FeatureMetadata.from_spec_dir(spec_dir, run_id="spec-run")

    assert metadata.requirements[0].artifact_path == "runs/spec-1/specs/002-share-album/spec.md"


def test_feature_metadata_from_spec_dir_raises_for_missing_spec_md(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "004-missing-spec"
    spec_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        FeatureMetadata.from_spec_dir(spec_dir, run_id="spec-run")


def test_feature_metadata_round_trips_yaml(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-photo-album"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")
    metadata = FeatureMetadata.from_spec_dir(spec_dir, run_id="spec-run")

    path = write_feature_metadata(spec_dir, metadata)
    loaded = read_feature_metadata(spec_dir)

    assert path == spec_dir / "feature-metadata.yml"
    assert loaded is not None
    assert loaded.to_dict() == metadata.to_dict()


def test_validate_lifecycle_status_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="unknown lifecycle status"):
        validate_lifecycle_status("archived")


def test_validate_lifecycle_status_accepts_removed() -> None:
    assert validate_lifecycle_status("removed") == "removed"


def test_write_feature_metadata_rejects_invalid_nested_lifecycle_status(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-photo-album"
    spec_dir.mkdir(parents=True)

    metadata = FeatureMetadata(
        schema_version=1,
        feature_id="001-photo-album",
        spec_id="001",
        slug="photo-album",
        use_cases=[
            UseCaseMetadata(
                id="UC-001",
                title="### User Story 1",
                status="archived",
            )
        ],
        requirements=[
            RequirementMetadata(
                id="FR-001",
                status="active",
                artifact_path="specs/001-photo-album/spec.md",
                artifact_hash="sha256:" + "0" * 64,
            )
        ],
    )

    with pytest.raises(ValueError, match="unknown lifecycle status: archived"):
        write_feature_metadata(spec_dir, metadata)
