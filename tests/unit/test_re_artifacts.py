from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

import pytest

from harness.re_artifacts import (
    ReArtifactCatalogError,
    ReArtifactDescriptor,
    build_re_artifact_catalog,
    classify_re_artifact,
    validate_re_artifact_descriptor,
)


def _write_current_source_outputs(source: Path) -> None:
    files = {
        "manifest.json": "{}\n",
        "supporting-artifacts.md": "# Supporting artifacts\n",
        "specs/001-api/checklist.md": "- [ ] verify\n",
        "specs/001-api/spec.md": "# API\n",
        "structure.json": '{"files": []}\n',
        "overview.md": "# API\n",
        "domain-manifest.json": '{"source_id": "api"}\n',
        "dependencies.json": '{"dependencies": []}\n',
        "contracts.md": "# Contracts\n",
        "configs.json": '{"configs": []}\n',
        "components.md": "# Components\n",
        "codegraph-summary.json": '{"nodes": 1}\n',
        "codegraph-analysis.json": '{"analysis": true}\n',
        "architecture.md": "# Architecture\n",
        "analysis.json": '{"analysis": true}\n',
        "adrs/ADR-001.md": "# Decision\n",
    }
    for relative_path, content in files.items():
        path = source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_build_source_catalog_types_every_child(tmp_path: Path) -> None:
    source = tmp_path / "published"
    _write_current_source_outputs(source)

    rows = build_re_artifact_catalog(
        source,
        published_prefix=PurePosixPath("re/sources/api"),
        scope="source",
        source_id="api",
    )

    assert [(row.kind, row.path) for row in rows] == [
        ("re-decision", "re/sources/api/adrs/ADR-001.md"),
        ("re-analysis", "re/sources/api/analysis.json"),
        ("re-architecture", "re/sources/api/architecture.md"),
        ("re-codegraph-analysis", "re/sources/api/codegraph-analysis.json"),
        ("re-codegraph-summary", "re/sources/api/codegraph-summary.json"),
        ("re-components", "re/sources/api/components.md"),
        ("re-configs", "re/sources/api/configs.json"),
        ("re-contracts", "re/sources/api/contracts.md"),
        ("re-dependencies", "re/sources/api/dependencies.json"),
        ("re-domain-manifest", "re/sources/api/domain-manifest.json"),
        ("re-overview", "re/sources/api/overview.md"),
        ("re-generated-checklist", "re/sources/api/specs/001-api/checklist.md"),
        ("re-generated-spec", "re/sources/api/specs/001-api/spec.md"),
        ("re-structure", "re/sources/api/structure.json"),
        ("re-supporting-artifacts", "re/sources/api/supporting-artifacts.md"),
    ]
    assert all(row.source_id == "api" for row in rows)
    assert all(
        row.sha256
        == "sha256:"
        + hashlib.sha256(
            (source / PurePosixPath(row.path).relative_to("re/sources/api")).read_bytes()
        ).hexdigest()
        for row in rows
    )


def test_build_workspace_catalog_types_nested_children_and_excludes_manifest(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    files = {
        "manifest.json": "{}\n",
        "overview.md": "# Overview\n",
        "relationships.md": "# Relationships\n",
        "contracts.md": "# Contracts\n",
        "architecture-map.json": "{}\n",
        "codegraph-analysis.json": "{}\n",
        "codegraph-summary.json": "{}\n",
        "domain-catalog.md": "# Domains\n",
        "checklist.md": "- [ ] verify\n",
        "domains/001-api.md": "# API\n",
        "quality/review.json": "{}\n",
        "strategy/migration.md": "# Migration\n",
        "strategy/adrs/ADR-002.md": "# Decision\n",
    }
    for relative_path, content in files.items():
        path = workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    rows = build_re_artifact_catalog(
        workspace,
        published_prefix=PurePosixPath("re/workspace"),
        scope="workspace",
    )

    assert [row.path for row in rows] == sorted(row.path for row in rows)
    assert "re/workspace/manifest.json" not in {row.path for row in rows}
    assert [(row.kind, row.path) for row in rows] == [
        ("re-architecture-map", "re/workspace/architecture-map.json"),
        ("re-workspace-checklist", "re/workspace/checklist.md"),
        ("re-codegraph-analysis", "re/workspace/codegraph-analysis.json"),
        ("re-codegraph-summary", "re/workspace/codegraph-summary.json"),
        ("re-contracts", "re/workspace/contracts.md"),
        ("re-domain", "re/workspace/domain-catalog.md"),
        ("re-domain", "re/workspace/domains/001-api.md"),
        ("re-overview", "re/workspace/overview.md"),
        ("re-quality-report", "re/workspace/quality/review.json"),
        ("re-relationships", "re/workspace/relationships.md"),
        ("re-decision", "re/workspace/strategy/adrs/ADR-002.md"),
        ("re-strategy", "re/workspace/strategy/migration.md"),
    ]
    assert all(row.source_id is None for row in rows)


@pytest.mark.parametrize(
    ("scope", "relative_path", "expected"),
    [
        ("source", "re/sources/api/manifest.json", "re-source-manifest"),
        ("source", "re/sources/api/adrs/ADR-001.md", "re-decision"),
        ("source", "re/sources/api/analysis.json", "re-analysis"),
        ("source", "re/sources/api/architecture.md", "re-architecture"),
        ("source", "re/sources/api/codegraph-analysis.json", "re-codegraph-analysis"),
        ("source", "re/sources/api/codegraph-summary.json", "re-codegraph-summary"),
        ("source", "re/sources/api/components.md", "re-components"),
        ("source", "re/sources/api/configs.json", "re-configs"),
        ("source", "re/sources/api/contracts.md", "re-contracts"),
        ("source", "re/sources/api/dependencies.json", "re-dependencies"),
        ("source", "re/sources/api/domain-manifest.json", "re-domain-manifest"),
        ("source", "re/sources/api/overview.md", "re-overview"),
        ("source", "re/sources/api/quality/review.json", "re-quality-report"),
        ("source", "re/sources/api/specs/001/spec.md", "re-generated-spec"),
        ("source", "re/sources/api/specs/001/checklist.md", "re-generated-checklist"),
        ("source", "re/sources/api/structure.json", "re-structure"),
        ("source", "re/sources/api/supporting-artifacts.md", "re-supporting-artifacts"),
        ("workspace", "re/workspace/manifest.json", "re-workspace-manifest"),
        ("workspace", "re/workspace/architecture-map.json", "re-architecture-map"),
        ("workspace", "re/workspace/checklist.md", "re-workspace-checklist"),
        ("workspace", "re/workspace/codegraph-analysis.json", "re-codegraph-analysis"),
        ("workspace", "re/workspace/codegraph-summary.json", "re-codegraph-summary"),
        ("workspace", "re/workspace/contracts.md", "re-contracts"),
        ("workspace", "re/workspace/domains/001-api.md", "re-domain"),
        ("workspace", "re/workspace/overview.md", "re-overview"),
        ("workspace", "re/workspace/quality/review.json", "re-quality-report"),
        ("workspace", "re/workspace/relationships.md", "re-relationships"),
        ("workspace", "re/workspace/strategy/adrs/ADR-002.md", "re-decision"),
        ("workspace", "re/workspace/strategy/migration.md", "re-strategy"),
    ],
)
def test_classify_re_artifact_uses_explicit_taxonomy(
    scope: str,
    relative_path: str,
    expected: str,
) -> None:
    assert classify_re_artifact(PurePosixPath(relative_path), scope=scope) == expected


def test_descriptor_json_omits_source_id_for_workspace_scope() -> None:
    descriptor = ReArtifactDescriptor(
        kind="re-overview",
        path="re/workspace/overview.md",
        sha256="sha256:" + "a" * 64,
        scope="workspace",
    )

    assert descriptor.to_json_dict() == {
        "kind": "re-overview",
        "path": "re/workspace/overview.md",
        "sha256": "sha256:" + "a" * 64,
        "scope": "workspace",
    }


def test_workspace_descriptor_json_omits_directly_supplied_source_id() -> None:
    descriptor = ReArtifactDescriptor(
        kind="re-overview",
        path="re/workspace/overview.md",
        sha256="sha256:" + "a" * 64,
        scope="workspace",
        source_id="api",
    )

    assert "source_id" not in descriptor.to_json_dict()


def _write_descriptor_target(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "workspace-root"
    target = root / "re/sources/api/architecture.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Architecture\n", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    return root, digest


def _valid_source_descriptor(digest: str) -> dict[str, str]:
    return {
        "kind": "re-architecture",
        "path": "re/sources/api/architecture.md",
        "sha256": digest,
        "scope": "source",
        "source_id": "api",
    }


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda raw: raw.update({"path": "re/../outside.md"}), "traversal"),
        (lambda raw: raw.update({"path": "/re/sources/api/architecture.md"}), "relative"),
        (lambda raw: raw.update({"path": "re/workspace/overview.md"}), "owner scope"),
        (lambda raw: raw.pop("source_id"), "requires source_id"),
        (lambda raw: raw.update({"source_id": "other"}), "source_id does not match"),
        (lambda raw: raw.update({"kind": "re-unknown"}), "unsupported artifact kind"),
        (lambda raw: raw.update({"scope": "workspace"}), "owner scope"),
        (lambda raw: raw.update({"sha256": "SHA256:" + "a" * 64}), "lowercase hex"),
        (lambda raw: raw.update({"sha256": "sha256:" + "0" * 64}), "hash mismatch"),
    ],
)
def test_validate_descriptor_rejects_invalid_inputs(
    tmp_path: Path,
    mutate,
    reason: str,
) -> None:
    root, digest = _write_descriptor_target(tmp_path)
    raw = _valid_source_descriptor(digest)
    mutate(raw)

    with pytest.raises(ReArtifactCatalogError, match=reason):
        validate_re_artifact_descriptor(
            raw,
            workspace_root=root,
            owner_scope="source",
            owner_source_id="api",
        )


def test_validate_workspace_descriptor_rejects_extra_source_id(tmp_path: Path) -> None:
    root = tmp_path / "workspace-root"
    target = root / "re/workspace/overview.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Overview\n", encoding="utf-8")
    raw = {
        "kind": "re-overview",
        "path": "re/workspace/overview.md",
        "sha256": "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
        "scope": "workspace",
        "source_id": "api",
    }

    with pytest.raises(ReArtifactCatalogError, match="forbids source_id"):
        validate_re_artifact_descriptor(
            raw,
            workspace_root=root,
            owner_scope="workspace",
        )


def test_validate_descriptor_rejects_missing_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace-root"
    raw = _valid_source_descriptor("sha256:" + "a" * 64)

    with pytest.raises(ReArtifactCatalogError, match="does not exist"):
        validate_re_artifact_descriptor(
            raw,
            workspace_root=root,
            owner_scope="source",
            owner_source_id="api",
        )


def test_validate_descriptor_trusts_typed_kind_over_filename(tmp_path: Path) -> None:
    root = tmp_path / "workspace-root"
    target = root / "re/sources/api/renamed-output.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"typed artifact\n")
    raw = {
        "kind": "re-architecture",
        "path": "re/sources/api/renamed-output.bin",
        "sha256": "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
        "scope": "source",
        "source_id": "api",
        "future_field": "tolerated",
    }

    descriptor = validate_re_artifact_descriptor(
        raw,
        workspace_root=root,
        owner_scope="source",
        owner_source_id="api",
    )

    assert descriptor.kind == "re-architecture"
    assert descriptor.path == "re/sources/api/renamed-output.bin"


@pytest.mark.parametrize("source_id", [".", ".."])
def test_validate_descriptor_rejects_noncanonical_source_id(
    tmp_path: Path,
    source_id: str,
) -> None:
    root, digest = _write_descriptor_target(tmp_path)
    raw = _valid_source_descriptor(digest)
    raw["source_id"] = source_id

    with pytest.raises(ReArtifactCatalogError, match="source_id is not safe"):
        validate_re_artifact_descriptor(
            raw,
            workspace_root=root,
            owner_scope="source",
            owner_source_id=source_id,
        )


def test_build_catalog_rejects_duplicate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "published"
    target = source / "architecture.md"
    source.mkdir()
    target.write_text("# Architecture\n", encoding="utf-8")
    monkeypatch.setattr(Path, "rglob", lambda self, pattern: iter((target, target)))

    with pytest.raises(ReArtifactCatalogError, match="duplicate artifact path"):
        build_re_artifact_catalog(
            source,
            published_prefix=PurePosixPath("re/sources/api"),
            scope="source",
            source_id="api",
        )


def test_build_catalog_rejects_unknown_suffix(tmp_path: Path) -> None:
    source = tmp_path / "published"
    source.mkdir()
    (source / "notes.txt").write_text("notes\n", encoding="utf-8")

    with pytest.raises(ReArtifactCatalogError, match="unsupported artifact path"):
        build_re_artifact_catalog(
            source,
            published_prefix=PurePosixPath("re/sources/api"),
            scope="source",
            source_id="api",
        )
