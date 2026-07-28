from pathlib import Path
from types import SimpleNamespace

import pytest


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
    (re_root / "workspace" / "domains" / "001-re-src-api.md").write_text(
        "# API Domain\n\nResolvers and persistence.\n",
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "overview.md").write_text(
        "# Source Overview\n\nGraphQL API service.\n",
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "domain-manifest.json").write_text(
        '{"domains":["001-re-src-api"]}\n',
        encoding="utf-8",
    )
    (re_root / "sources" / "api" / "codegraph-analysis.json").write_text(
        '{"large":"raw evidence"}\n',
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
        "re/sources/api/domain-manifest.json",
        "re/sources/api/overview.md",
        "re/sources/api/specs/001-re-src-api/spec.md",
        "re/workspace/architecture-map.json",
        "re/workspace/domains/001-re-src-api.md",
        "re/workspace/overview.md",
        "re/workspace/strategy/gap-analysis.md",
    ]
    assert all(snapshot.artifact_metadata["artifact_kind"] == "reverse-engineering" for snapshot in snapshots)
    assert {snapshot.artifact_metadata["room"] for snapshot in snapshots} == {
        "re-domain-context",
        "re-generated-specs",
        "re-source-context",
        "re-strategy",
        "re-workspace-context",
    }


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
    assert report.artifact_count == 7
    assert report.expected_count == 7
    assert report.written_count == 7
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
                "ids": ["old-re", "spec-memory"],
                "metadatas": [
                    {"artifact_kind": "reverse-engineering", "wing": "demo-wing"},
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
    assert deleted == ["old-re"]


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
