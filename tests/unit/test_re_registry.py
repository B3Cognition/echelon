from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_registry import (
    ReRegistryError,
    canonical_re_artifacts,
    ensure_re_layout,
    load_published_index,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _valid_index() -> dict[str, object]:
    return {
        "schema_version": 1,
        "generation": 4,
        "publication_status": "complete",
        "published_at": "2026-07-12T14:30:00Z",
        "published_from_run": "spec-20260712-141500-123456",
        "sources": {
            "api": {
                "path": "sources/api",
                "published_path": "re/sources/api",
                "fingerprint": "abc123",
                "profile_hash": "profile123",
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
    }


@pytest.mark.unit
def test_ensure_re_layout_preserves_custom_ignore_entries(tmp_path: Path) -> None:
    gitignore = tmp_path / "re" / ".gitignore"
    gitignore.parent.mkdir()
    gitignore.write_text("local-notes/\n", encoding="utf-8")

    paths = ensure_re_layout(tmp_path)

    assert paths.root == tmp_path / "re"
    assert paths.sources.is_dir()
    assert paths.workspace.is_dir()
    assert paths.cache.is_dir()
    assert paths.staging.is_dir()
    assert paths.locks.is_dir()
    assert paths.gitignore.read_text(encoding="utf-8").splitlines() == [
        "local-notes/",
        ".cache/",
        ".staging/",
        ".locks/",
    ]
    assert not paths.index.exists()


@pytest.mark.unit
def test_load_published_index_returns_none_before_first_publication(tmp_path: Path) -> None:
    ensure_re_layout(tmp_path)

    assert load_published_index(tmp_path) is None


@pytest.mark.unit
def test_load_published_index_parses_valid_contract(tmp_path: Path) -> None:
    ensure_re_layout(tmp_path)
    _write_json(tmp_path / "re" / "index.json", _valid_index())

    index = load_published_index(tmp_path)

    assert index is not None
    assert index.generation == 4
    assert index.sources["api"].source_path == "sources/api"
    assert index.sources["api"].manifest == "re/sources/api/manifest.json"
    assert index.workspace.overview == "re/workspace/overview.md"


@pytest.mark.unit
def test_load_published_index_rejects_unsafe_source_path(tmp_path: Path) -> None:
    ensure_re_layout(tmp_path)
    payload = _valid_index()
    sources = payload["sources"]
    assert isinstance(sources, dict)
    source = sources["api"]
    assert isinstance(source, dict)
    source["published_path"] = "../outside"
    _write_json(tmp_path / "re" / "index.json", payload)

    with pytest.raises(ReRegistryError, match="published_path"):
        load_published_index(tmp_path)


@pytest.mark.unit
def test_load_published_index_rejects_mismatched_source_manifest(tmp_path: Path) -> None:
    ensure_re_layout(tmp_path)
    payload = _valid_index()
    sources = payload["sources"]
    assert isinstance(sources, dict)
    source = sources["api"]
    assert isinstance(source, dict)
    source["manifest"] = "re/sources/other/manifest.json"
    _write_json(tmp_path / "re" / "index.json", payload)

    with pytest.raises(ReRegistryError, match="manifest"):
        load_published_index(tmp_path)


@pytest.mark.unit
def test_canonical_re_artifacts_reads_only_durable_paths(tmp_path: Path) -> None:
    ensure_re_layout(tmp_path)
    _write_json(tmp_path / "re" / "index.json", _valid_index())
    _write_json(
        tmp_path / "re" / "sources" / "api" / "manifest.json",
        {
            "schema_version": 1,
            "source_id": "api",
            "overview": "re/sources/api/overview.md",
            "specs": ["re/sources/api/specs/search/spec.md"],
        },
    )
    (tmp_path / "re" / "sources" / "api" / "overview.md").write_text(
        "# API\n", encoding="utf-8"
    )
    spec = tmp_path / "re" / "sources" / "api" / "specs" / "search" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Search\n", encoding="utf-8")
    workspace = tmp_path / "re" / "workspace"
    for name in ("manifest.json", "overview.md", "relationships.md", "contracts.md"):
        (workspace / name).write_text("{}\n" if name.endswith(".json") else "# Doc\n")

    index = load_published_index(tmp_path)
    assert index is not None
    artifacts = canonical_re_artifacts(tmp_path, index)

    assert artifacts["manifest"] == str(tmp_path / "re" / "index.json")
    assert artifacts["workspace_manifest"] == str(workspace / "manifest.json")
    assert artifacts["re_overview"] == str(workspace / "overview.md")
    assert artifacts["per_repo"] == [str(tmp_path / "re" / "sources" / "api")]
    assert artifacts["re_specs"] == [str(spec)]
    assert not any(
        runtime in str(value)
        for value in artifacts.values()
        for runtime in ("/.cache/", "/.staging/", "/.locks/")
    )

