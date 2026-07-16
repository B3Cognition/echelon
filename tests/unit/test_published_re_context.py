from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.published_re_context import attach_published_re_context


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _publish_fixture(root: Path) -> Path:
    source_root = root / "re" / "sources" / "api"
    spec = source_root / "specs" / "search" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Search v1\n", encoding="utf-8")
    (source_root / "overview.md").write_text("# API\n", encoding="utf-8")
    (source_root / "unregistered.txt").write_text("secret\n", encoding="utf-8")
    _write_json(
        source_root / "manifest.json",
        {
            "schema_version": 1,
            "source_id": "api",
            "overview": "re/sources/api/overview.md",
            "specs": ["re/sources/api/specs/search/spec.md"],
        },
    )
    workspace = root / "re" / "workspace"
    _write_json(workspace / "manifest.json", {"schema_version": 1})
    for name in ("overview.md", "relationships.md", "contracts.md"):
        (workspace / name).write_text(f"# {name}\n", encoding="utf-8")
    _write_json(
        root / "re" / "index.json",
        {
            "schema_version": 1,
            "generation": 3,
            "publication_status": "complete",
            "published_at": "2026-07-16T12:00:00Z",
            "published_from_run": "re-fixture",
            "sources": {
                "api": {
                    "path": "sources/api",
                    "published_path": "re/sources/api",
                    "fingerprint": "abc",
                    "profile_hash": "profile",
                    "status": "complete",
                    "manifest": "re/sources/api/manifest.json",
                }
            },
            "workspace": {
                "manifest": "re/workspace/manifest.json",
                "overview": "re/workspace/overview.md",
                "relationships": "re/workspace/relationships.md",
                "contracts": "re/workspace/contracts.md",
            },
            "warnings": [],
        },
    )
    return spec


@pytest.mark.unit
def test_attach_published_re_context_records_ignored_without_reading_registry(
    tmp_path: Path,
) -> None:
    context = attach_published_re_context(
        tmp_path,
        tmp_path / "runs" / "spec-1",
        ignore=True,
    )

    assert context == {"status": "ignored", "generation": 0, "artifacts": {}}
    assert not (tmp_path / "runs" / "spec-1" / "context" / "published-re").exists()


@pytest.mark.unit
def test_attach_published_re_context_records_absent_publication(tmp_path: Path) -> None:
    context = attach_published_re_context(
        tmp_path,
        tmp_path / "runs" / "spec-1",
        ignore=False,
    )

    assert context == {"status": "absent", "generation": 0, "artifacts": {}}


@pytest.mark.unit
def test_attach_published_re_context_snapshots_only_registered_artifacts(
    tmp_path: Path,
) -> None:
    canonical_spec = _publish_fixture(tmp_path)
    run_dir = tmp_path / "runs" / "spec-1"

    context = attach_published_re_context(tmp_path, run_dir, ignore=False)

    assert context["status"] == "attached"
    assert context["generation"] == 3
    assert context["publication_status"] == "complete"
    snapshot_root = Path(str(context["snapshot_root"]))
    assert snapshot_root == run_dir / "context" / "published-re"
    artifacts = context["artifacts"]
    assert isinstance(artifacts, dict)
    snapshot_specs = artifacts["re_specs"]
    assert isinstance(snapshot_specs, list)
    snapshot_spec = Path(snapshot_specs[0])
    assert snapshot_spec.read_text(encoding="utf-8") == "# Search v1\n"
    assert snapshot_spec.is_relative_to(snapshot_root)
    assert not (snapshot_root / "sources" / "api" / "unregistered.txt").exists()

    canonical_spec.write_text("# Search v2\n", encoding="utf-8")
    assert snapshot_spec.read_text(encoding="utf-8") == "# Search v1\n"

