from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness import re_registry
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


def _descriptor(
    root: Path,
    relative_path: str,
    *,
    kind: str,
    scope: str,
    source_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": kind,
        "path": relative_path,
        "sha256": "sha256:"
        + hashlib.sha256((root / relative_path).read_bytes()).hexdigest(),
        "scope": scope,
        "future_metadata": {"retained": True},
    }
    if source_id is not None:
        payload["source_id"] = source_id
    return payload


def _typed_publication(root: Path) -> None:
    ensure_re_layout(root)
    source_root = root / "re" / "sources" / "api"
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "overview.md").write_text("# API\n", encoding="utf-8")
    spec = source_root / "specs" / "search" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Search\n", encoding="utf-8")
    source_artifacts = [
        _descriptor(
            root,
            "re/sources/api/overview.md",
            kind="re-overview",
            scope="source",
            source_id="api",
        ),
        _descriptor(
            root,
            "re/sources/api/specs/search/spec.md",
            kind="re-generated-spec",
            scope="source",
            source_id="api",
        ),
    ]
    _write_json(
        source_root / "manifest.json",
        {
            "schema_version": 1,
            "source_id": "api",
            "overview": "re/sources/api/overview.md",
            "specs": ["re/sources/api/specs/search/spec.md"],
            "artifacts": source_artifacts,
        },
    )

    workspace = root / "re" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    for name in ("contracts.md", "overview.md", "relationships.md"):
        (workspace / name).write_text(f"# {name}\n", encoding="utf-8")
    workspace_artifacts = [
        _descriptor(
            root,
            "re/workspace/contracts.md",
            kind="re-contracts",
            scope="workspace",
        ),
        _descriptor(
            root,
            "re/workspace/overview.md",
            kind="re-overview",
            scope="workspace",
        ),
        _descriptor(
            root,
            "re/workspace/relationships.md",
            kind="re-relationships",
            scope="workspace",
        ),
    ]
    _write_json(
        workspace / "manifest.json",
        {"schema_version": 1, "artifacts": workspace_artifacts},
    )

    payload = _valid_index()
    sources = payload["sources"]
    assert isinstance(sources, dict)
    source = sources["api"]
    assert isinstance(source, dict)
    source["manifest_artifact"] = _descriptor(
        root,
        "re/sources/api/manifest.json",
        kind="re-source-manifest",
        scope="source",
        source_id="api",
    )
    workspace_index = payload["workspace"]
    assert isinstance(workspace_index, dict)
    workspace_index["manifest_artifact"] = _descriptor(
        root,
        "re/workspace/manifest.json",
        kind="re-workspace-manifest",
        scope="workspace",
    )
    _write_json(root / "re" / "index.json", payload)


def _rewrite_manifest_descriptor(root: Path, *, scope: str) -> None:
    payload = json.loads((root / "re" / "index.json").read_text(encoding="utf-8"))
    if scope == "source":
        payload["sources"]["api"]["manifest_artifact"] = _descriptor(
            root,
            "re/sources/api/manifest.json",
            kind="re-source-manifest",
            scope="source",
            source_id="api",
        )
    else:
        payload["workspace"]["manifest_artifact"] = _descriptor(
            root,
            "re/workspace/manifest.json",
            kind="re-workspace-manifest",
            scope="workspace",
        )
    _write_json(root / "re" / "index.json", payload)


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
def test_canonical_re_artifact_descriptors_reads_complete_typed_catalog(
    tmp_path: Path,
) -> None:
    _typed_publication(tmp_path)
    index = load_published_index(tmp_path)
    assert index is not None

    descriptors = re_registry.canonical_re_artifact_descriptors(tmp_path, index)

    assert [descriptor.path for descriptor in descriptors] == [
        "re/sources/api/manifest.json",
        "re/sources/api/overview.md",
        "re/sources/api/specs/search/spec.md",
        "re/workspace/contracts.md",
        "re/workspace/manifest.json",
        "re/workspace/overview.md",
        "re/workspace/relationships.md",
    ]
    assert len({descriptor.path for descriptor in descriptors}) == len(descriptors)


@pytest.mark.unit
def test_canonical_re_artifact_descriptors_rejects_partial_typed_index(
    tmp_path: Path,
) -> None:
    _typed_publication(tmp_path)
    payload = json.loads((tmp_path / "re" / "index.json").read_text(encoding="utf-8"))
    payload["sources"]["api"].pop("manifest_artifact")
    _write_json(tmp_path / "re" / "index.json", payload)
    index = load_published_index(tmp_path)
    assert index is not None

    with pytest.raises(ReRegistryError, match="manifest_artifact"):
        re_registry.canonical_re_artifact_descriptors(tmp_path, index)


@pytest.mark.unit
def test_canonical_re_artifact_descriptors_rejects_untyped_child_catalog(
    tmp_path: Path,
) -> None:
    _typed_publication(tmp_path)
    manifest_path = tmp_path / "re" / "workspace" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("artifacts")
    _write_json(manifest_path, manifest)
    _rewrite_manifest_descriptor(tmp_path, scope="workspace")
    index = load_published_index(tmp_path)
    assert index is not None

    with pytest.raises(ReRegistryError, match="artifact catalog"):
        re_registry.canonical_re_artifact_descriptors(tmp_path, index)


@pytest.mark.unit
def test_canonical_re_artifact_descriptors_rejects_duplicate_child_path(
    tmp_path: Path,
) -> None:
    _typed_publication(tmp_path)
    manifest_path = tmp_path / "re" / "sources" / "api" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].append(dict(manifest["artifacts"][0]))
    _write_json(manifest_path, manifest)
    _rewrite_manifest_descriptor(tmp_path, scope="source")
    index = load_published_index(tmp_path)
    assert index is not None

    with pytest.raises(ReRegistryError, match="duplicate artifact path"):
        re_registry.canonical_re_artifact_descriptors(tmp_path, index)


@pytest.mark.unit
def test_load_published_index_rejects_manifest_descriptor_hash_mismatch(
    tmp_path: Path,
) -> None:
    _typed_publication(tmp_path)
    payload = json.loads((tmp_path / "re" / "index.json").read_text(encoding="utf-8"))
    payload["workspace"]["manifest_artifact"]["sha256"] = "sha256:" + "0" * 64
    _write_json(tmp_path / "re" / "index.json", payload)

    with pytest.raises(ReRegistryError, match="artifact hash mismatch"):
        load_published_index(tmp_path)


@pytest.mark.unit
def test_canonical_re_artifact_descriptors_rejects_child_source_id_mismatch(
    tmp_path: Path,
) -> None:
    _typed_publication(tmp_path)
    manifest_path = tmp_path / "re" / "sources" / "api" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["source_id"] = "other"
    _write_json(manifest_path, manifest)
    _rewrite_manifest_descriptor(tmp_path, scope="source")
    index = load_published_index(tmp_path)
    assert index is not None

    with pytest.raises(ReRegistryError, match="source_id does not match owner"):
        re_registry.canonical_re_artifact_descriptors(tmp_path, index)


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
    descriptors = re_registry.canonical_re_artifact_descriptors(tmp_path, index)
    artifacts = canonical_re_artifacts(tmp_path, index)

    assert [(descriptor.kind, descriptor.path) for descriptor in descriptors] == [
        ("re-source-manifest", "re/sources/api/manifest.json"),
        ("re-overview", "re/sources/api/overview.md"),
        ("re-generated-spec", "re/sources/api/specs/search/spec.md"),
        ("re-contracts", "re/workspace/contracts.md"),
        ("re-workspace-manifest", "re/workspace/manifest.json"),
        ("re-overview", "re/workspace/overview.md"),
        ("re-relationships", "re/workspace/relationships.md"),
    ]
    assert all(
        descriptor.sha256
        == "sha256:"
        + hashlib.sha256((tmp_path / descriptor.path).read_bytes()).hexdigest()
        for descriptor in descriptors
    )
    assert set(artifacts) == {
        "architecture_map",
        "artifact_descriptors",
        "codegraph_analyses",
        "codegraph_summaries",
        "contracts",
        "cross_repo",
        "domain_catalog",
        "manifest",
        "per_repo",
        "re_contexts",
        "re_overview",
        "re_specs",
        "source_adrs",
        "source_architecture",
        "source_components",
        "source_contracts",
        "source_domain_manifests",
        "source_extraction_artifacts",
        "source_index",
        "source_manifests",
        "source_supporting_artifacts",
        "workspace_checklist",
        "workspace_codegraph_summary",
        "workspace_manifest",
        "workspace_strategy",
    }
    assert artifacts["manifest"] == str(tmp_path / "re" / "index.json")
    assert artifacts["workspace_manifest"] == str(workspace / "manifest.json")
    assert artifacts["re_overview"] == str(workspace / "overview.md")
    assert artifacts["per_repo"] == [str(tmp_path / "re" / "sources" / "api")]
    assert artifacts["re_specs"] == [str(spec)]
    assert artifacts["re_contexts"] == [
        str(tmp_path / "re" / "sources" / "api" / "overview.md"),
        str(spec),
        str(workspace / "overview.md"),
        str(workspace / "relationships.md"),
        str(workspace / "contracts.md"),
    ]
    assert artifacts["artifact_descriptors"] == [
        descriptor.to_json_dict() for descriptor in descriptors
    ]
    assert not any(
        runtime in str(value)
        for value in artifacts.values()
        for runtime in ("/.cache/", "/.staging/", "/.locks/")
    )
