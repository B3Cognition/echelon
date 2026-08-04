import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _re_descriptor(
    root: Path,
    relative_path: str,
    *,
    kind: str,
    scope: str,
    source_id: str | None = None,
) -> dict[str, object]:
    descriptor: dict[str, object] = {
        "kind": kind,
        "path": relative_path,
        "sha256": "sha256:"
        + hashlib.sha256((root / relative_path).read_bytes()).hexdigest(),
        "scope": scope,
    }
    if source_id is not None:
        descriptor["source_id"] = source_id
    return descriptor


def write_typed_re_workspace_with_misleading_names(tmp_path: Path) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    source_root = tmp_path / "re" / "sources" / "api"
    workspace_root = tmp_path / "re" / "workspace"
    source_root.mkdir(parents=True)
    workspace_root.mkdir(parents=True)

    source_artifacts = {
        "notes/alpha.md": ("re-architecture", "# Typed architecture\n"),
        "notes/bravo.md": ("re-contracts", "# Typed contracts\n"),
        "notes/charlie.md": ("re-components", "# Typed components\n"),
        "notes/delta.md": ("re-decision", "# Typed source decision\n"),
        "evidence/echo.json": ("re-codegraph-summary", '{"summary":"source"}\n'),
        "evidence/foxtrot.json": ("re-codegraph-analysis", "{}\n"),
        "evidence/golf.json": ("re-analysis", "{}\n"),
        "evidence/hotel.json": ("re-structure", "{}\n"),
        "evidence/india.json": ("re-configs", "{}\n"),
        "evidence/juliet.json": ("re-dependencies", "{}\n"),
    }
    source_descriptors = []
    for relative_path, (kind, content) in source_artifacts.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        source_descriptors.append(
            _re_descriptor(
                tmp_path,
                f"re/sources/api/{relative_path}",
                kind=kind,
                scope="source",
                source_id="api",
            )
        )
    _write_json(
        source_root / "manifest.json",
        {
            "schema_version": 1,
            "source_id": "api",
            "artifacts": sorted(source_descriptors, key=lambda row: str(row["path"])),
        },
    )

    workspace_artifacts = {
        "notes/kilo.md": ("re-decision", "# Typed workspace decision\n"),
        "evidence/lima.json": ("re-codegraph-summary", '{"summary":"workspace"}\n'),
    }
    workspace_descriptors = []
    for relative_path, (kind, content) in workspace_artifacts.items():
        path = workspace_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        workspace_descriptors.append(
            _re_descriptor(
                tmp_path,
                f"re/workspace/{relative_path}",
                kind=kind,
                scope="workspace",
            )
        )
    _write_json(
        workspace_root / "manifest.json",
        {
            "schema_version": 1,
            "artifacts": sorted(
                workspace_descriptors, key=lambda row: str(row["path"])
            ),
        },
    )

    _write_json(
        tmp_path / "re" / "index.json",
        {
            "schema_version": 1,
            "generation": 1,
            "publication_status": "complete",
            "published_at": "2026-08-04T12:00:00Z",
            "published_from_run": "re-test",
            "sources": {
                "api": {
                    "path": ".",
                    "published_path": "re/sources/api",
                    "fingerprint": "source-fingerprint",
                    "profile_hash": "profile-hash",
                    "status": "complete",
                    "manifest": "re/sources/api/manifest.json",
                    "manifest_artifact": _re_descriptor(
                        tmp_path,
                        "re/sources/api/manifest.json",
                        kind="re-source-manifest",
                        scope="source",
                        source_id="api",
                    ),
                }
            },
            "workspace": {
                "manifest": "re/workspace/manifest.json",
                "overview": "re/workspace/overview.md",
                "relationships": "re/workspace/relationships.md",
                "contracts": "re/workspace/contracts.md",
                "manifest_artifact": _re_descriptor(
                    tmp_path,
                    "re/workspace/manifest.json",
                    kind="re-workspace-manifest",
                    scope="workspace",
                ),
            },
            "warnings": [],
        },
    )


def write_re_workspace(tmp_path: Path) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    re_root = tmp_path / "re"
    (re_root / "workspace" / "strategy" / "adrs").mkdir(parents=True)
    (re_root / "workspace" / "domains").mkdir(parents=True)
    (re_root / "sources" / "api" / "specs" / "001-re-src-api").mkdir(parents=True)
    (re_root / ".cache").mkdir()
    (re_root / "workspace" / "overview.md").write_text(
        "# Workspace Overview\n\nAPI and frontend architecture.\n",
        encoding="utf-8",
    )
    (re_root / "workspace" / "architecture-map.json").write_text(
        '{"nodes":[{"id":"api"}]}\n',
        encoding="utf-8",
    )
    (re_root / "workspace" / "strategy" / "gap-analysis.md").write_text(
        "# Gap Analysis\n\nContract tests are missing.\n",
        encoding="utf-8",
    )
    (re_root / "workspace" / "strategy" / "adrs" / "ADR-001-platform.md").write_text(
        "# Platform Boundary\n\nKeep source services independently deployable.\n",
        encoding="utf-8",
    )
    (re_root / "workspace" / "domains" / "001-re-src-api.md").write_text(
        "# API Domain\n\nResolvers and persistence.\n",
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "overview.md").write_text(
        "# Source Overview\n\nGraphQL API service.\n",
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "architecture.md").write_text(
        "# Architecture\n\nLayered GraphQL service.\n",
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "contracts.md").write_text(
        "# Contracts\n\nGraphQL query contract.\n",
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "components.md").write_text(
        "# Components\n\nResolver and repository.\n",
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "adrs").mkdir()
    (re_root / "sources" / "api" / "adrs" / "ADR-001-boundary.md").write_text(
        "# API Boundary\n\nKeep transport separate from persistence.\n",
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "domain-manifest.json").write_text(
        '{"domains":["001-re-src-api"]}\n',
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "codegraph-summary.json").write_text(
        '{"source_id":"api","nodes":12}\n',
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "codegraph-analysis.json").write_text(
        '{"large":"raw evidence"}\n',
        encoding="utf-8",
    )
    (re_root / "workspace" / "codegraph-summary.json").write_text(
        '{"sources":["api"]}\n',
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "specs" / "001-re-src-api" / "spec.md").write_text(
        "# Generated Domain Spec\n\nAPI SHALL expose search.\n",
        encoding="utf-8",
    )
    (re_root / ".cache" / "ignored.md").write_text(
        "# Cache\n\nDo not mine.\n",
        encoding="utf-8",
    )


@pytest.mark.unit
def test_resolve_re_root_rejects_unpublished_current_run_when_direct_re_is_operational(
    tmp_path: Path,
) -> None:
    (tmp_path / "re" / ".staging").mkdir(parents=True)
    current_re = tmp_path / "runs" / "re-123" / "re"
    current_re.mkdir(parents=True)
    (tmp_path / "runs" / ".current-re").write_text("re-123\n", encoding="utf-8")
    current_re.joinpath("workspace-manifest.json").write_text("{}\n", encoding="utf-8")
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_re import resolve_re_root

    with pytest.raises(SpecMemoryError, match="published RE artifacts not found"):
        resolve_re_root(tmp_path)


@pytest.mark.unit
def test_load_re_artifact_snapshots_selects_curated_re_outputs(tmp_path: Path) -> None:
    write_re_workspace(tmp_path)
    from echelon.mempalace_re import load_re_artifact_snapshots

    snapshots = load_re_artifact_snapshots(tmp_path)

    assert [snapshot.source for snapshot in snapshots] == [
        "re/sources/api/adrs/ADR-001-boundary.md",
        "re/sources/api/architecture.md",
        "re/sources/api/codegraph-summary.json",
        "re/sources/api/components.md",
        "re/sources/api/contracts.md",
        "re/sources/api/domain-manifest.json",
        "re/sources/api/overview.md",
        "re/sources/api/specs/001-re-src-api/spec.md",
        "re/workspace/architecture-map.json",
        "re/workspace/codegraph-summary.json",
        "re/workspace/domains/001-re-src-api.md",
        "re/workspace/overview.md",
        "re/workspace/strategy/adrs/ADR-001-platform.md",
        "re/workspace/strategy/gap-analysis.md",
    ]
    metadata = {
        snapshot.source: (
            snapshot.artifact_metadata["artifact_kind"],
            snapshot.artifact_metadata["room"],
        )
        for snapshot in snapshots
    }
    assert metadata["re/sources/api/architecture.md"] == (
        "re-architecture",
        "re-source-architecture",
    )
    assert metadata["re/sources/api/contracts.md"] == (
        "re-contracts",
        "re-source-contracts",
    )
    assert metadata["re/sources/api/components.md"] == (
        "re-components",
        "re-source-components",
    )
    assert metadata["re/sources/api/adrs/ADR-001-boundary.md"] == (
        "re-decision",
        "re-source-decisions",
    )
    assert metadata["re/sources/api/codegraph-summary.json"] == (
        "re-codegraph-summary",
        "re-source-codegraph",
    )
    assert metadata["re/workspace/codegraph-summary.json"] == (
        "re-codegraph-summary",
        "re-workspace-codegraph",
    )
    assert metadata["re/workspace/strategy/adrs/ADR-001-platform.md"] == (
        "re-decision",
        "re-workspace-decisions",
    )
    assert "re/sources/api/codegraph-analysis.json" not in metadata
    assert {snapshot.artifact_metadata["room"] for snapshot in snapshots} == {
        "re-domain-context",
        "re-generated-specs",
        "re-source-architecture",
        "re-source-codegraph",
        "re-source-components",
        "re-source-contracts",
        "re-source-context",
        "re-source-decisions",
        "re-strategy",
        "re-workspace-codegraph",
        "re-workspace-context",
        "re-workspace-decisions",
    }


@pytest.mark.unit
def test_load_re_artifact_snapshots_uses_typed_kind_for_misleading_names(
    tmp_path: Path,
) -> None:
    write_typed_re_workspace_with_misleading_names(tmp_path)
    from echelon.mempalace_re import load_re_artifact_snapshots

    snapshots = load_re_artifact_snapshots(tmp_path)

    metadata = {
        snapshot.source: (
            snapshot.artifact_metadata["artifact_kind"],
            snapshot.artifact_metadata["room"],
        )
        for snapshot in snapshots
    }
    assert metadata["re/sources/api/notes/alpha.md"] == (
        "re-architecture",
        "re-source-architecture",
    )
    assert metadata["re/sources/api/notes/bravo.md"] == (
        "re-contracts",
        "re-source-contracts",
    )
    assert metadata["re/sources/api/notes/charlie.md"] == (
        "re-components",
        "re-source-components",
    )
    assert metadata["re/sources/api/notes/delta.md"] == (
        "re-decision",
        "re-source-decisions",
    )
    assert metadata["re/sources/api/evidence/echo.json"] == (
        "re-codegraph-summary",
        "re-source-codegraph",
    )
    assert metadata["re/workspace/notes/kilo.md"] == (
        "re-decision",
        "re-workspace-decisions",
    )
    assert metadata["re/workspace/evidence/lima.json"] == (
        "re-codegraph-summary",
        "re-workspace-codegraph",
    )
    assert {
        snapshot.artifact_metadata["artifact_kind"] for snapshot in snapshots
    }.isdisjoint(
        {
            "re-codegraph-analysis",
            "re-analysis",
            "re-structure",
            "re-configs",
            "re-dependencies",
        }
    )
    architecture = next(
        snapshot
        for snapshot in snapshots
        if snapshot.source == "re/sources/api/notes/alpha.md"
    )
    assert architecture.content == b"# Typed architecture\n"


@pytest.mark.unit
def test_load_re_artifact_snapshots_rejects_changed_registered_bytes(
    tmp_path: Path,
) -> None:
    write_typed_re_workspace_with_misleading_names(tmp_path)
    (tmp_path / "re" / "sources" / "api" / "notes" / "alpha.md").write_text(
        "# Changed after publication\n",
        encoding="utf-8",
    )
    from harness.re_registry import ReRegistryError
    from echelon.mempalace_re import load_re_artifact_snapshots

    with pytest.raises(ReRegistryError, match="artifact hash mismatch"):
        load_re_artifact_snapshots(tmp_path)


@pytest.mark.unit
def test_mine_re_memory_aggregates_curated_artifacts(tmp_path: Path, monkeypatch) -> None:
    write_re_workspace(tmp_path)
    calls = []

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def mine_re_artifact_bytes(self, content, *, source, artifact_metadata):
            calls.append((source, artifact_metadata["room"], artifact_metadata["artifact_kind"]))
            return SimpleNamespace(
                written=1,
                already_present=0,
                skipped=0,
                failed=0,
                drifted=0,
                unavailable=0,
                drawer_ids=[f"drawer-{len(calls)}"],
                expected_drawer_ids=[f"drawer-{len(calls)}"],
                errors=[],
            )

    monkeypatch.setattr(
        "echelon.mempalace_re.create_re_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_re import mine_re_memory

    report = mine_re_memory(tmp_path, run_id="manual")

    assert report.status == "complete"
    assert report.artifact_count == 14
    assert report.expected_count == 14
    assert report.written_count == 14
    assert ("re/workspace/overview.md", "re-workspace-context", "reverse-engineering") in calls


@pytest.mark.unit
def test_mine_re_memory_deletes_existing_re_drawers_before_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_re_workspace(tmp_path)
    deleted = []

    class FakeCollection:
        def get(self, where=None, include=None):
            return {
                "ids": [
                    "old-re",
                    "architecture",
                    "contracts",
                    "components",
                    "decision",
                    "codegraph",
                    "registered-heavy",
                    "scoped-re",
                    "provenance-re",
                    "spec-memory",
                ],
                "metadatas": [
                    {"artifact_kind": "reverse-engineering", "wing": "demo-wing"},
                    {"artifact_kind": "re-architecture", "wing": "demo-wing"},
                    {"artifact_kind": "re-contracts", "wing": "demo-wing"},
                    {"artifact_kind": "re-components", "wing": "demo-wing"},
                    {"artifact_kind": "re-decision", "wing": "demo-wing"},
                    {"artifact_kind": "re-codegraph-summary", "wing": "demo-wing"},
                    {"artifact_kind": "re-analysis", "wing": "demo-wing"},
                    {
                        "artifact_kind": "future-re-kind",
                        "scope": "reverse-engineering",
                        "wing": "demo-wing",
                    },
                    {
                        "artifact_kind": "future-re-kind",
                        "provenance_type": "reverse_engineering_mine",
                        "wing": "demo-wing",
                    },
                    {"artifact_kind": "supporting-context", "wing": "demo-wing"},
                ],
            }

        def delete(self, ids):
            deleted.extend(ids)

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def open_collection_read_only(self):
            return FakeCollection()

        def mine_re_artifact_bytes(self, content, *, source, artifact_metadata):
            return SimpleNamespace(
                written=1,
                already_present=0,
                skipped=0,
                failed=0,
                drifted=0,
                unavailable=0,
                drawer_ids=[source],
                expected_drawer_ids=[source],
                errors=[],
            )

    monkeypatch.setattr(
        "echelon.mempalace_re.create_re_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_re import mine_re_memory

    report = mine_re_memory(tmp_path, run_id="manual")

    assert report.status == "complete"
    assert deleted == [
        "old-re",
        "architecture",
        "contracts",
        "components",
        "decision",
        "codegraph",
        "registered-heavy",
        "scoped-re",
        "provenance-re",
    ]


@pytest.mark.unit
def test_audit_re_memory_reports_exact_pass(tmp_path: Path, monkeypatch) -> None:
    write_re_workspace(tmp_path)

    class FakeCollection:
        def get(self, ids=None, where=None, include=None, limit=None):
            if ids is not None:
                return {
                    "ids": ["drawer-1", "drawer-architecture"],
                    "documents": [
                        "RE-001: Published RE fact.",
                        "RE-ARCH-001: Layered GraphQL service.",
                    ],
                    "metadatas": [
                        {
                            "wing": "demo-wing",
                            "room": "re-workspace-context",
                            "artifact_kind": "reverse-engineering",
                            "scope": "canonical",
                            "canonical": True,
                            "artifact_path": "re/workspace/overview.md",
                            "source_file": "re/workspace/overview.md",
                            "artifact_hash": "sha256:artifact",
                            "canonical_spec_sha256": "artifact",
                            "requirement_content_sha256": "596d231108054d099f4ddba2d1719742cb0d458cfba61fe150eb26a7789464ff",
                            "requirement_id": "RE-001",
                            "deterministic_identity_schema_version": 1,
                            "lifecycle_status": "active",
                        },
                        {
                            "wing": "demo-wing",
                            "room": "re-source-architecture",
                            "artifact_kind": "re-architecture",
                            "scope": "reverse-engineering",
                            "canonical": True,
                            "artifact_path": "re/sources/api/architecture.md",
                            "source_file": "re/sources/api/architecture.md",
                            "artifact_hash": "sha256:architecture",
                            "canonical_spec_sha256": "architecture",
                            "requirement_content_sha256": "1e8238583fd98987938189b0a209722c3b01da9b2323c55b5eb669883f8faf1b",
                            "requirement_id": "RE-ARCH-001",
                            "deterministic_identity_schema_version": 1,
                            "lifecycle_status": "active",
                        },
                    ],
                }
            return {
                "ids": ["drawer-1", "drawer-architecture"],
                "documents": [
                    "RE-001: Published RE fact.",
                    "RE-ARCH-001: Layered GraphQL service.",
                ],
                "metadatas": [
                    {"artifact_kind": "reverse-engineering"},
                    {"artifact_kind": "re-architecture"},
                ],
            }

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def open_collection_read_only(self):
            return FakeCollection()

        def plan_re_artifact_rows(self, content, *, source, artifact_metadata):
            rows = {
                "re/workspace/overview.md": SimpleNamespace(
                    drawer_id="drawer-1",
                    requirement_id="RE-001",
                    room="re-workspace-context",
                    source="re/workspace/overview.md",
                    artifact_hash="sha256:artifact",
                    canonical_spec_sha256="artifact",
                    requirement_content_sha256="596d231108054d099f4ddba2d1719742cb0d458cfba61fe150eb26a7789464ff",
                ),
                "re/sources/api/architecture.md": SimpleNamespace(
                    drawer_id="drawer-architecture",
                    requirement_id="RE-ARCH-001",
                    room="re-source-architecture",
                    source="re/sources/api/architecture.md",
                    artifact_hash="sha256:architecture",
                    canonical_spec_sha256="architecture",
                    requirement_content_sha256="1e8238583fd98987938189b0a209722c3b01da9b2323c55b5eb669883f8faf1b",
                ),
            }
            return [rows[source]] if source in rows else []

    monkeypatch.setattr(
        "echelon.mempalace_re.create_re_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_re import audit_re_memory

    report = audit_re_memory(tmp_path)

    assert report.status == "pass"
    assert report.expected_count == 2
    assert report.present_current_count == 2


@pytest.mark.unit
def test_audit_re_memory_reports_missing_drawers(tmp_path: Path, monkeypatch) -> None:
    write_re_workspace(tmp_path)

    class FakeCollection:
        def get(self, ids=None, where=None, include=None, limit=None):
            return {"ids": [], "documents": [], "metadatas": []}

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def open_collection_read_only(self):
            return FakeCollection()

        def plan_re_artifact_rows(self, content, *, source, artifact_metadata):
            if source != "re/workspace/overview.md":
                return []
            return [
                SimpleNamespace(
                    drawer_id="missing-drawer",
                    requirement_id="RE-001",
                    room="re-workspace-context",
                    source="re/workspace/overview.md",
                    artifact_hash="sha256:artifact",
                    canonical_spec_sha256="artifact",
                    requirement_content_sha256="content",
                )
            ]

    monkeypatch.setattr(
        "echelon.mempalace_re.create_re_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_re import audit_re_memory

    report = audit_re_memory(tmp_path)

    assert report.status == "fail"
    assert report.missing == ["missing-drawer"]


@pytest.mark.unit
def test_audit_re_memory_requires_typed_snapshot_kind(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_typed_re_workspace_with_misleading_names(tmp_path)
    document = "RE-ARCH-001: Typed architecture."
    content_hash = hashlib.sha256(document.encode("utf-8")).hexdigest()

    class FakeCollection:
        def get(self, ids=None, where=None, include=None, limit=None):
            return {
                "ids": ["drawer-architecture"],
                "documents": [document],
                "metadatas": [
                    {
                        "wing": "demo-wing",
                        "room": "re-source-architecture",
                        "artifact_kind": "reverse-engineering",
                        "scope": "reverse-engineering",
                        "canonical": True,
                        "artifact_path": "re/sources/api/notes/alpha.md",
                        "source_file": "re/sources/api/notes/alpha.md",
                        "artifact_hash": "sha256:artifact",
                        "canonical_spec_sha256": "artifact",
                        "requirement_content_sha256": content_hash,
                        "requirement_id": "RE-ARCH-001",
                        "deterministic_identity_schema_version": 1,
                        "lifecycle_status": "active",
                    }
                ],
            }

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def open_collection_read_only(self):
            return FakeCollection()

        def plan_re_artifact_rows(self, content, *, source, artifact_metadata):
            if source != "re/sources/api/notes/alpha.md":
                return []
            return [
                SimpleNamespace(
                    drawer_id="drawer-architecture",
                    requirement_id="RE-ARCH-001",
                    room="re-source-architecture",
                    source=source,
                    artifact_hash="sha256:artifact",
                    canonical_spec_sha256="artifact",
                    requirement_content_sha256=content_hash,
                )
            ]

    monkeypatch.setattr(
        "echelon.mempalace_re.create_re_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_re import audit_re_memory

    report = audit_re_memory(tmp_path)

    assert report.status == "fail"
    assert report.non_canonical == ["drawer-architecture"]


@pytest.mark.unit
def test_re_generated_specs_use_source_path_in_synthetic_identity() -> None:
    import hashlib

    from echelon.spec_memory_miner import plan_re_artifact_drawers

    content = b"# Generated Spec\n\nShared domain wording.\n"
    digest = hashlib.sha256(content).hexdigest()

    first = plan_re_artifact_drawers(
        content,
        source="re/sources/api/specs/001-re-src-api/spec.md",
        artifact_metadata={
            "canonical": True,
            "artifact_hash": f"sha256:{digest}",
            "artifact_kind": "reverse-engineering",
            "scope": "reverse-engineering",
            "room": "re-generated-specs",
        },
        wing="demo-wing",
    )
    second = plan_re_artifact_drawers(
        content,
        source="re/sources/web/specs/001-re-src-web/spec.md",
        artifact_metadata={
            "canonical": True,
            "artifact_hash": f"sha256:{digest}",
            "artifact_kind": "reverse-engineering",
            "scope": "reverse-engineering",
            "room": "re-generated-specs",
        },
        wing="demo-wing",
    )

    assert first[0].requirement_id != second[0].requirement_id
    assert first[0].drawer_id != second[0].drawer_id


@pytest.mark.unit
def test_re_memory_planner_accepts_typed_re_artifact_kind() -> None:
    import hashlib

    from echelon.spec_memory_miner import plan_re_artifact_drawers

    content = b"# Architecture\n\nLayered GraphQL service.\n"
    digest = hashlib.sha256(content).hexdigest()

    rows = plan_re_artifact_drawers(
        content,
        source="re/sources/api/architecture.md",
        artifact_metadata={
            "canonical": True,
            "artifact_hash": f"sha256:{digest}",
            "artifact_kind": "re-architecture",
            "scope": "reverse-engineering",
            "room": "re-source-architecture",
        },
        wing="demo-wing",
    )

    assert len(rows) == 1
    assert rows[0].room == "re-source-architecture"
