from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from echelon.spec_graph import build_spec_graph
from harness.re_artifacts import SUPPORTED_RE_ARTIFACT_KINDS
from harness.published_re_context import (
    attach_published_re_context,
    write_canonical_re_context,
)
from harness.squad_executors import _render_published_re_context


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _descriptor(
    root: Path,
    relative_path: str,
    *,
    kind: str,
    scope: str,
    source_id: str | None = None,
) -> dict[str, str]:
    payload = {
        "kind": kind,
        "path": relative_path,
        "sha256": "sha256:"
        + hashlib.sha256((root / relative_path).read_bytes()).hexdigest(),
        "scope": scope,
    }
    if source_id is not None:
        payload["source_id"] = source_id
    return payload


def _publish_fixture(root: Path) -> Path:
    source_root = root / "re" / "sources" / "api"
    spec = source_root / "specs" / "search" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Search v1\n", encoding="utf-8")
    checklist = source_root / "specs" / "search" / "checklist.md"
    checklist.write_text("# Search Checklist Policy Marker\n", encoding="utf-8")
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
    _write_json(source_root / "structure.json", {"registered_only": "structure"})
    _write_json(source_root / "configs.json", {"registered_only": "configs"})
    _write_json(source_root / "dependencies.json", {"registered_only": "dependencies"})
    quality = source_root / "quality" / "report.md"
    quality.parent.mkdir()
    quality.write_text("# Registered Only Quality Evidence\n", encoding="utf-8")
    (source_root / "unregistered.txt").write_text("secret\n", encoding="utf-8")
    source_artifacts = [
        _descriptor(
            root,
            path,
            kind=kind,
            scope="source",
            source_id="api",
        )
        for path, kind in sorted(
            {
                "re/sources/api/adrs/ADR-001-api.md": "re-decision",
                "re/sources/api/analysis.json": "re-analysis",
                "re/sources/api/architecture.md": "re-architecture",
                "re/sources/api/codegraph-analysis.json": "re-codegraph-analysis",
                "re/sources/api/codegraph-summary.json": "re-codegraph-summary",
                "re/sources/api/components.md": "re-components",
                "re/sources/api/contracts.md": "re-contracts",
                "re/sources/api/configs.json": "re-configs",
                "re/sources/api/dependencies.json": "re-dependencies",
                "re/sources/api/domain-manifest.json": "re-domain-manifest",
                "re/sources/api/overview.md": "re-overview",
                "re/sources/api/quality/report.md": "re-quality-report",
                "re/sources/api/specs/search/checklist.md": "re-generated-checklist",
                "re/sources/api/specs/search/spec.md": "re-generated-spec",
                "re/sources/api/structure.json": "re-structure",
                "re/sources/api/supporting-artifacts.md": "re-supporting-artifacts",
            }.items()
        )
    ]
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
            "artifacts": source_artifacts,
        },
    )
    workspace = root / "re" / "workspace"
    _write_json(workspace / "manifest.json", {"schema_version": 1})
    for name in ("overview.md", "relationships.md", "contracts.md"):
        (workspace / name).write_text(f"# {name}\n", encoding="utf-8")
    (workspace / "checklist.md").write_text("# Checklist\n", encoding="utf-8")
    _write_json(workspace / "architecture-map.json", {"schema_version": 1, "domains": []})
    _write_json(workspace / "codegraph-summary.json", {"workspace": True})
    (workspace / "current-domain.md").write_text(
        "# Workspace Domain Policy Marker\n", encoding="utf-8"
    )
    (workspace / "current-strategy.md").write_text(
        "# Workspace Strategy Policy Marker\n", encoding="utf-8"
    )
    decision = workspace / "decisions" / "current.md"
    decision.parent.mkdir()
    decision.write_text("# Workspace Decision Policy Marker\n", encoding="utf-8")
    workspace_artifacts = [
        _descriptor(root, path, kind=kind, scope="workspace")
        for path, kind in sorted(
            {
                "re/workspace/architecture-map.json": "re-architecture-map",
                "re/workspace/checklist.md": "re-workspace-checklist",
                "re/workspace/codegraph-summary.json": "re-codegraph-summary",
                "re/workspace/contracts.md": "re-contracts",
                "re/workspace/current-domain.md": "re-domain",
                "re/workspace/current-strategy.md": "re-strategy",
                "re/workspace/decisions/current.md": "re-decision",
                "re/workspace/overview.md": "re-overview",
                "re/workspace/relationships.md": "re-relationships",
            }.items()
        )
    ]
    _write_json(
        workspace / "manifest.json",
        {"schema_version": 1, "artifacts": workspace_artifacts},
    )
    source_manifest_artifact = _descriptor(
        root,
        "re/sources/api/manifest.json",
        kind="re-source-manifest",
        scope="source",
        source_id="api",
    )
    workspace_manifest_artifact = _descriptor(
        root,
        "re/workspace/manifest.json",
        kind="re-workspace-manifest",
        scope="workspace",
    )
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
                    "manifest_artifact": source_manifest_artifact,
                }
            },
            "workspace": {
                "manifest": "re/workspace/manifest.json",
                "manifest_artifact": workspace_manifest_artifact,
                "overview": "re/workspace/overview.md",
                "relationships": "re/workspace/relationships.md",
                "contracts": "re/workspace/contracts.md",
                "codegraph_summary": "re/workspace/codegraph-summary.json",
            },
            "warnings": [],
        },
    )
    return spec


def _add_source_to_publication(root: Path, source_id: str) -> None:
    source_root = root / "re" / "sources" / source_id
    source_root.mkdir(parents=True)
    overview_path = f"re/sources/{source_id}/overview.md"
    (root / overview_path).write_text(f"# {source_id}\n", encoding="utf-8")
    _write_json(
        source_root / "manifest.json",
        {
            "schema_version": 1,
            "source_id": source_id,
            "source_path": f"sources/{source_id}",
            "overview": overview_path,
            "specs": [],
            "artifacts": [
                _descriptor(
                    root,
                    overview_path,
                    kind="re-overview",
                    scope="source",
                    source_id=source_id,
                )
            ],
        },
    )
    index_path = root / "re" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["sources"][source_id] = {
        "path": f"sources/{source_id}",
        "published_path": f"re/sources/{source_id}",
        "fingerprint": f"{source_id}-fingerprint",
        "profile_hash": "profile",
        "status": "complete",
        "manifest": f"re/sources/{source_id}/manifest.json",
        "manifest_artifact": _descriptor(
            root,
            f"re/sources/{source_id}/manifest.json",
            kind="re-source-manifest",
            scope="source",
            source_id=source_id,
        ),
    }
    _write_json(index_path, index)


def _add_workspace_artifacts(
    root: Path,
    artifacts: dict[str, tuple[str, str]],
) -> None:
    manifest_path = root / "re" / "workspace" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptors = list(manifest["artifacts"])
    for relative_path, (kind, content) in artifacts.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        descriptors.append(
            _descriptor(root, relative_path, kind=kind, scope="workspace")
        )
    manifest["artifacts"] = sorted(descriptors, key=lambda row: row["path"])
    _write_json(manifest_path, manifest)

    index_path = root / "re" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["workspace"]["manifest_artifact"] = _descriptor(
        root,
        "re/workspace/manifest.json",
        kind="re-workspace-manifest",
        scope="workspace",
    )
    _write_json(index_path, index)


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

    context = attach_published_re_context(
        tmp_path,
        run_dir,
        ignore=False,
        implementation_targets=["sources/api/src/search.ts"],
    )

    assert context["status"] == "attached"
    assert context["generation"] == 3
    assert context["publication_status"] == "complete"
    snapshot_root = Path(str(context["snapshot_root"]))
    assert snapshot_root == run_dir / "context" / "published-re"
    artifacts = context["artifacts"]
    assert isinstance(artifacts, dict)
    descriptors = artifacts["artifact_descriptors"]
    assert isinstance(descriptors, list)
    assert [row["path"] for row in descriptors] == sorted(
        row["path"] for row in descriptors
    )
    registered_only = {
        "re-codegraph-analysis",
        "re-analysis",
        "re-structure",
        "re-configs",
        "re-dependencies",
        "re-quality-report",
    }
    assert {row["kind"] for row in descriptors} == (
        SUPPORTED_RE_ARTIFACT_KINDS - registered_only
    )
    assert not any(row["path"].endswith("unregistered.txt") for row in descriptors)
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
    assert "# relationships.md" in workspace_text
    assert "# contracts.md" in workspace_text
    assert '"domains": []' in workspace_text
    assert '"workspace": true' in workspace_text
    assert "# Checklist" in workspace_text
    assert "Workspace Domain Policy Marker" in workspace_text
    assert "Workspace Strategy Policy Marker" in workspace_text
    assert "Workspace Decision Policy Marker" in workspace_text

    registered_only_paths = {
        "re/sources/api/analysis.json",
        "re/sources/api/codegraph-analysis.json",
        "re/sources/api/configs.json",
        "re/sources/api/dependencies.json",
        "re/sources/api/quality/report.md",
        "re/sources/api/structure.json",
    }
    assert registered_only_paths
    assert all(
        not (snapshot_root / Path(path).relative_to("re")).exists()
        for path in registered_only_paths
    )
    assert all(Path(path).name not in workspace_text for path in registered_only_paths)

    spec_dir = tmp_path / "specs" / "001-search"
    spec_dir.mkdir(parents=True)
    canonical_context = json.loads(
        write_canonical_re_context(tmp_path, spec_dir, context).read_text(
            encoding="utf-8"
        )
    )
    assert all(set(row) == {"path", "hash"} for row in canonical_context["artifacts"])
    canonical_paths = {row["path"] for row in canonical_context["artifacts"]}
    assert "re/sources/api/specs/search/checklist.md" in canonical_paths
    assert "re/workspace/decisions/current.md" in canonical_paths
    assert all(path not in canonical_paths for path in registered_only_paths)
    assert "re/RE-WORKSPACE-BRIEF.md" not in canonical_paths
    assert "re/RE-SOURCE-api-BRIEF.md" not in canonical_paths

    prompt = _render_published_re_context({"published_re_context": context})
    assert "re/sources/api/architecture.md" in prompt
    assert "Published RE Workspace Brief" in prompt
    assert all(Path(path).name not in prompt for path in registered_only_paths)

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
    assert "Search Checklist Policy Marker" in text
    assert '"source_id": "api"' in text
    assert "# Support" in text
    assert '"symbols": 2' in text
    assert "codegraph-analysis.json" not in text
    assert "analysis.json" not in text
    assert "structure.json" not in text
    assert "configs.json" not in text
    assert "dependencies.json" not in text
    assert "Registered Only Quality Evidence" not in text


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
def test_workspace_brief_preserves_strategy_and_all_decisions_before_domain_bulk(
    tmp_path: Path,
) -> None:
    _publish_fixture(tmp_path)
    domain_body = "domain evidence\n" * 3_000
    strategy_body = "strategy evidence\n" * 3_000
    additions = {
        **{
            f"re/workspace/domains/domain-{index}.md": (
                "re-domain",
                f"# Oversized Domain {index}\n{domain_body}",
            )
            for index in range(5)
        },
        **{
            f"re/workspace/strategy/strategy-{index}.md": (
                "re-strategy",
                f"# Oversized Strategy {index}\n{strategy_body}",
            )
            for index in range(4)
        },
        **{
            f"re/workspace/decisions/ADR-00{index}-marker.md": (
                "re-decision",
                f"# WORKSPACE-ADR-MARKER-{index}\nDecision {index}.\n",
            )
            for index in range(2, 5)
        },
    }
    _add_workspace_artifacts(tmp_path, additions)

    context = attach_published_re_context(
        tmp_path,
        tmp_path / "runs" / "spec-oversized",
        ignore=False,
        re_sources=["api"],
    )

    workspace_brief = Path(str(context["rendered_briefings"]["workspace"]))
    text = workspace_brief.read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) <= 96 * 1024
    assert "Workspace Strategy Policy Marker" in text
    assert "Workspace Decision Policy Marker" in text
    for index in range(2, 5):
        assert f"WORKSPACE-ADR-MARKER-{index}" in text


@pytest.mark.unit
def test_selected_source_manifest_bounds_prompt_and_graph_source_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _publish_fixture(tmp_path)
    _add_source_to_publication(tmp_path, "web")
    run_dir = tmp_path / "runs" / "spec-1"

    context = attach_published_re_context(
        tmp_path,
        run_dir,
        ignore=False,
        re_sources=["api"],
    )

    artifacts = context["artifacts"]
    assert isinstance(artifacts, dict)
    descriptors = artifacts["artifact_descriptors"]
    assert isinstance(descriptors, list)
    descriptor_paths = {row["path"] for row in descriptors}
    assert "re/workspace/manifest.json" in descriptor_paths
    assert "re/sources/api/manifest.json" in descriptor_paths
    assert "re/sources/web/manifest.json" not in descriptor_paths
    assert "re/sources/web/overview.md" not in descriptor_paths
    assert not any(
        row["kind"] in {
            "re-codegraph-analysis",
            "re-analysis",
            "re-structure",
            "re-configs",
            "re-dependencies",
            "re-quality-report",
        }
        for row in descriptors
    )

    prompt = _render_published_re_context({"published_re_context": context})
    assert "re/sources/api/manifest.json" in prompt
    assert "Published RE Source Brief: api" in prompt
    assert "re/sources/web" not in prompt
    assert "codegraph-analysis.json" not in prompt

    spec_dir = tmp_path / "specs" / "001-selected-api"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "# Selected API\n\n- **FR-001**: Use the selected API.\n",
        encoding="utf-8",
    )
    write_canonical_re_context(tmp_path, spec_dir, context)
    monkeypatch.setattr("echelon.spec_graph._add_re_memory", lambda *args: None)

    graph = build_spec_graph(tmp_path, spec_dir).to_dict()
    edges = {
        (edge["source"], edge["type"], edge["target"])
        for edge in graph["edges"]
    }
    assert (
        "spec:001-selected-api",
        "USES_RE_SOURCE",
        "re-source:api",
    ) in edges
    assert not any(
        edge_type == "USES_RE_SOURCE" and target == "re-source:web"
        for _, edge_type, target in edges
    )


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
    workspace_brief = snapshot_root / "RE-WORKSPACE-BRIEF.md"
    workspace_brief.write_text("# Generated briefing\n", encoding="utf-8")
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
                "context_artifacts": [str(overview), str(manifest)],
                "rendered_briefings": {"workspace": str(workspace_brief)},
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
                "artifacts": {"context_artifacts": [str(outside)]},
            },
        )
