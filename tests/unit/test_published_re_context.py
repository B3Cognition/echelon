from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.published_re_context import (
    attach_published_re_context,
    write_canonical_re_context,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _publish_fixture(root: Path) -> Path:
    source_root = root / "re" / "sources" / "api"
    spec = source_root / "specs" / "search" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Search v1\n", encoding="utf-8")
    (source_root / "overview.md").write_text("# API\n", encoding="utf-8")
    (source_root / "architecture.md").write_text("# API Architecture\n", encoding="utf-8")
    (source_root / "contracts.md").write_text("# API Contracts\n", encoding="utf-8")
    (source_root / "components.md").write_text("# API Components\n", encoding="utf-8")
    adrs = source_root / "adrs"
    adrs.mkdir()
    (adrs / "ADR-001-api.md").write_text("# API ADR\n", encoding="utf-8")
    (source_root / "supporting-artifacts.md").write_text("# Support\n", encoding="utf-8")
    _write_json(source_root / "domain-manifest.json", {"source_id": "api"})
    _write_json(source_root / "codegraph-summary.json", {"source_id": "api", "symbols": 2})
    _write_json(source_root / "codegraph-analysis.json", {"source_id": "api", "deep": True})
    _write_json(source_root / "analysis.json", {"source_id": "api", "analysis": True})
    (source_root / "unregistered.txt").write_text("secret\n", encoding="utf-8")
    _write_json(
        source_root / "manifest.json",
        {
            "schema_version": 1,
            "source_id": "api",
            "source_path": "sources/api",
            "overview": "re/sources/api/overview.md",
            "architecture": "re/sources/api/architecture.md",
            "contracts": "re/sources/api/contracts.md",
            "components": "re/sources/api/components.md",
            "specs": ["re/sources/api/specs/search/spec.md"],
            "domain_manifest": "re/sources/api/domain-manifest.json",
            "supporting_artifacts": "re/sources/api/supporting-artifacts.md",
            "codegraph_summary": "re/sources/api/codegraph-summary.json",
            "codegraph_analysis": "re/sources/api/codegraph-analysis.json",
            "extraction_artifacts": {
                "analysis": "re/sources/api/analysis.json",
            },
        },
    )
    workspace = root / "re" / "workspace"
    _write_json(workspace / "manifest.json", {"schema_version": 1})
    for name in ("overview.md", "relationships.md", "contracts.md"):
        (workspace / name).write_text(f"# {name}\n", encoding="utf-8")
    (workspace / "checklist.md").write_text("# Checklist\n", encoding="utf-8")
    _write_json(workspace / "architecture-map.json", {"schema_version": 1, "domains": []})
    _write_json(workspace / "codegraph-summary.json", {"workspace": True})
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
                "codegraph_summary": "re/workspace/codegraph-summary.json",
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
    rendered = context["rendered_briefings"]
    assert isinstance(rendered, dict)
    workspace_brief = Path(str(rendered["workspace"]))
    assert workspace_brief.is_file()
    assert workspace_brief.is_relative_to(snapshot_root)
    workspace_text = workspace_brief.read_text(encoding="utf-8")
    assert "Published RE Workspace Brief" in workspace_text
    assert "# overview.md" in workspace_text
    assert "Available Source RE" in workspace_text
    assert "api" in workspace_text

    canonical_spec.write_text("# Search v2\n", encoding="utf-8")
    assert snapshot_spec.read_text(encoding="utf-8") == "# Search v1\n"


@pytest.mark.unit
def test_attach_published_re_context_selects_source_from_target_path(tmp_path: Path) -> None:
    _publish_fixture(tmp_path)
    run_dir = tmp_path / "runs" / "spec-1"

    context = attach_published_re_context(
        tmp_path,
        run_dir,
        ignore=False,
        implementation_targets=["sources/api/src/search.ts"],
    )

    assert context["selected_sources"] == ["api"]
    assert context["selection_reason"] == {"api": "target matched published source path"}
    rendered = context["rendered_briefings"]
    assert isinstance(rendered, dict)
    sources = rendered["sources"]
    assert isinstance(sources, dict)
    source_brief = Path(str(sources["api"]))
    text = source_brief.read_text(encoding="utf-8")
    assert "Published RE Source Brief: api" in text
    assert "# API" in text
    assert "# API Architecture" in text
    assert "# API Contracts" in text
    assert "# API Components" in text
    assert "# API ADR" in text
    assert "# Search v1" in text
    assert "# Support" in text
    assert '"symbols": 2' in text
    assert "codegraph-analysis.json" not in text
    assert "analysis.json" not in text


@pytest.mark.unit
def test_attach_published_re_context_selects_explicit_re_source(tmp_path: Path) -> None:
    _publish_fixture(tmp_path)

    context = attach_published_re_context(
        tmp_path,
        tmp_path / "runs" / "spec-1",
        ignore=False,
        re_sources=["re/sources/api"],
    )

    assert context["selected_sources"] == ["api"]
    assert context["selection_reason"] == {"api": "explicit --re-source"}


@pytest.mark.unit
def test_write_canonical_re_context_hashes_sorted_snapshot_files(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "runs" / "spec-1" / "context" / "published-re"
    overview = snapshot_root / "workspace" / "overview.md"
    manifest = snapshot_root / "workspace" / "manifest.json"
    overview.parent.mkdir(parents=True)
    overview.write_text("# Overview\n", encoding="utf-8")
    manifest.write_text('{"schema_version": 1}\n', encoding="utf-8")
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    path = write_canonical_re_context(
        tmp_path,
        spec_dir,
        {
            "status": "attached",
            "generation": 7,
            "snapshot_root": str(snapshot_root),
            "artifacts": {
                "overview": str(overview),
                "manifest": str(manifest),
                "duplicate": str(overview),
            },
        },
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["status"] == "attached"
    assert payload["generation"] == 7
    assert payload["artifacts"] == sorted(
        payload["artifacts"],
        key=lambda row: row["path"],
    )
    assert [row["path"] for row in payload["artifacts"]] == [
        "re/workspace/manifest.json",
        "re/workspace/overview.md",
    ]
    assert all(row["hash"].startswith("sha256:") for row in payload["artifacts"])
    assert path.read_bytes().endswith(b"\n")


@pytest.mark.unit
@pytest.mark.parametrize("status", ["ignored", "absent"])
def test_write_canonical_re_context_records_non_attached_status(
    tmp_path: Path,
    status: str,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    path = write_canonical_re_context(
        tmp_path,
        spec_dir,
        {"status": status, "generation": 0, "artifacts": {}},
    )

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "status": status,
        "generation": 0,
        "artifacts": [],
    }


@pytest.mark.unit
def test_write_canonical_re_context_rejects_paths_outside_snapshot(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "runs" / "spec-1" / "context" / "published-re"
    snapshot_root.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="outside published RE snapshot"):
        write_canonical_re_context(
            tmp_path,
            spec_dir,
            {
                "status": "attached",
                "generation": 1,
                "snapshot_root": str(snapshot_root),
                "artifacts": {"outside": str(outside)},
            },
        )
