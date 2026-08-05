import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def write_evidence_workspace(tmp_path: Path) -> Path:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text(
        "---\nstatus: landed\n---\nFR-001: Import.\n",
        encoding="utf-8",
    )
    spec_dir.joinpath("fulfillment-report.md").write_text(
        "---\nverify_run_id: spec-20260728-120000\n---\n"
        "# Fulfillment Report\n\n| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n| FR-001 | IMPLEMENTED | src/demo.py |\n",
        encoding="utf-8",
    )
    spec_dir.joinpath("verified-fulfillment-ledger.json").write_text(
        '{"FR-001":{"status":"IMPLEMENTED"}}\n',
        encoding="utf-8",
    )
    spec_dir.joinpath("random-note.md").write_text(
        "# Random\n\nDo not mine.\n",
        encoding="utf-8",
    )
    verify_dir = (
        tmp_path
        / "runs"
        / "spec-20260728-120000"
        / "verify-spec"
        / "003-demo"
    )
    verify_dir.mkdir(parents=True)
    verify_dir.joinpath("implementation-map.md").write_text(
        "# Implementation Map\n\nFR-001 maps to src/demo.py.\n",
        encoding="utf-8",
    )
    verify_dir.joinpath("codegraph-evidence-map.json").write_text(
        '{"requirements":{"FR-001":["src/demo.py"]}}\n',
        encoding="utf-8",
    )
    verify_dir.joinpath("codegraph-evidence-map.md").write_text(
        "# CodeGraph Evidence Map\n\nFR-001 -> src/demo.py\n",
        encoding="utf-8",
    )
    verify_dir.joinpath("canonical-requirements.json").write_text(
        '{"requirements":[{"id":"FR-001"}]}\n',
        encoding="utf-8",
    )
    verify_dir.joinpath("canonical-requirements.md").write_text(
        "# Canonical Requirements\n\nFR-001\n",
        encoding="utf-8",
    )
    verify_dir.joinpath("requirement-audit.md").write_text(
        "# Requirement Audit\n\nAll rows accounted for.\n",
        encoding="utf-8",
    )
    verify_dir.joinpath("progress-integrity.md").write_text(
        "# Progress Integrity\n\nValid: True\n",
        encoding="utf-8",
    )
    verify_dir.joinpath("progress-integrity.json").write_text(
        '{"status":"pass"}\n',
        encoding="utf-8",
    )
    verify_dir.joinpath("debug.log").write_text(
        "Do not publish.\n",
        encoding="utf-8",
    )
    verify_dir.joinpath("state.json").write_text(
        json.dumps(
            {
                "spec_id": "003-demo",
                "completed_at": "2026-07-28T12:30:00+00:00",
                "status": "complete",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stale_dir = tmp_path / "runs" / "spec-old" / "verify-spec" / "003-demo"
    stale_dir.mkdir(parents=True)
    stale_dir.joinpath("implementation-map.md").write_text(
        "# Old Map\n\nDo not mine.\n",
        encoding="utf-8",
    )
    return spec_dir


def mark_spec_unlanded(spec_dir: Path) -> None:
    spec_dir.joinpath("spec.md").write_text(
        "---\nstatus: ready_to_land\n---\nFR-001: Import.\n",
        encoding="utf-8",
    )


def write_complete_verify_candidate(
    path: Path,
    marker: str,
    *,
    spec_id: str = "906-cli-output-styling",
    completed_at: str = "2026-08-04T12:00:00+00:00",
) -> Path:
    path.mkdir(parents=True)
    path.joinpath("state.json").write_text(
        json.dumps(
            {
                "spec_id": spec_id,
                "completed_at": completed_at,
                "status": "complete",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    path.joinpath("implementation-map.md").write_text(marker, encoding="utf-8")
    return path


@pytest.mark.unit
def test_verify_evidence_resolver_falls_back_to_numeric_nested_run(
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import _resolve_verify_evidence_run_dir

    expected = write_complete_verify_candidate(
        tmp_path / "runs" / "build-old" / "verify-spec" / "906",
        "old numeric evidence",
    )

    assert _resolve_verify_evidence_run_dir(
        tmp_path,
        "906-cli-output-styling",
        "build-old",
    ) == expected


@pytest.mark.unit
def test_verify_evidence_resolver_selects_latest_complete_alias_candidate(
    tmp_path: Path,
) -> None:
    import os

    from echelon.mempalace_spec_evidence import _resolve_verify_evidence_run_dir

    numeric = write_complete_verify_candidate(
        tmp_path / "runs" / "build-old" / "verify-spec" / "906",
        "old numeric evidence",
        completed_at="2026-08-04T10:00:00+00:00",
    )
    canonical = write_complete_verify_candidate(
        tmp_path
        / "runs"
        / "build-new"
        / "verify-spec"
        / "906-cli-output-styling",
        "new canonical evidence",
        completed_at="2026-08-04T11:00:00+00:00",
    )
    os.utime(numeric / "implementation-map.md", (1, 1))
    os.utime(canonical / "implementation-map.md", (2, 2))
    incomplete = tmp_path / "runs" / "build-incomplete" / "verify-spec" / "906"
    incomplete.mkdir(parents=True)
    incomplete.joinpath("implementation-map.md").write_text(
        "missing state",
        encoding="utf-8",
    )

    assert _resolve_verify_evidence_run_dir(
        tmp_path,
        "906-cli-output-styling",
        None,
    ) == canonical


@pytest.mark.unit
def test_verify_evidence_resolver_merges_artifact_queries_by_utc_completion(
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import _resolve_verify_evidence_run_dir

    earlier = write_complete_verify_candidate(
        tmp_path / "runs/verify-spec-906-earlier",
        "earlier implementation",
        completed_at="2026-08-04T12:00:00+02:00",
    )
    later = write_complete_verify_candidate(
        tmp_path / "runs/verify-spec-906-later",
        "unused implementation",
        completed_at="2026-08-04T11:00:00+00:00",
    )
    (later / "implementation-map.md").unlink()
    (later / "requirement-audit.md").write_text("later audit", encoding="utf-8")

    assert _resolve_verify_evidence_run_dir(
        tmp_path,
        "906-cli-output-styling",
        None,
    ) == later
    assert earlier.is_dir()


@pytest.mark.unit
def test_verify_evidence_resolver_error_lists_attempted_aliases(tmp_path: Path) -> None:
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_spec_evidence import _resolve_verify_evidence_run_dir

    with pytest.raises(
        SpecMemoryError,
        match="906-cli-output-styling, 906",
    ):
        _resolve_verify_evidence_run_dir(
            tmp_path,
            "906-cli-output-styling",
            None,
        )


@pytest.mark.unit
def test_explicit_run_prefers_matching_nested_candidate_over_newer_root(
    tmp_path: Path,
) -> None:
    import os

    from echelon.mempalace_spec_evidence import _resolve_verify_evidence_run_dir

    run_root = write_complete_verify_candidate(
        tmp_path / "runs" / "build-mixed",
        "unrelated root evidence",
        spec_id="other-spec",
        completed_at="2026-08-04T12:00:00+00:00",
    )
    nested = write_complete_verify_candidate(
        run_root / "verify-spec" / "906",
        "matching nested evidence",
        completed_at="2026-08-04T10:00:00+00:00",
    )
    os.utime(nested / "implementation-map.md", (1, 1))
    os.utime(run_root / "implementation-map.md", (2, 2))

    assert _resolve_verify_evidence_run_dir(
        tmp_path,
        "906-cli-output-styling",
        "build-mixed",
    ) == nested


@pytest.mark.unit
def test_explicit_standalone_run_requires_matching_identity(tmp_path: Path) -> None:
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_spec_evidence import _resolve_verify_evidence_run_dir

    run_root = write_complete_verify_candidate(
        tmp_path / "runs" / "manual-run",
        "unrelated evidence",
        spec_id="other-spec",
    )

    with pytest.raises(SpecMemoryError):
        _resolve_verify_evidence_run_dir(
            tmp_path,
            "906-cli-output-styling",
            "manual-run",
        )


@pytest.mark.unit
def test_publish_spec_evidence_package_rejects_unlanded_specs(
    tmp_path: Path,
) -> None:
    spec_dir = write_evidence_workspace(tmp_path)
    mark_spec_unlanded(spec_dir)
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_spec_evidence import publish_spec_evidence_package

    with pytest.raises(SpecMemoryError, match="spec evidence requires landed spec"):
        publish_spec_evidence_package(tmp_path, "003-demo")


@pytest.mark.unit
def test_mine_spec_evidence_memory_rejects_unlanded_specs(
    tmp_path: Path,
) -> None:
    spec_dir = write_evidence_workspace(tmp_path)
    mark_spec_unlanded(spec_dir)
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_spec_evidence import mine_spec_evidence_memory

    with pytest.raises(SpecMemoryError, match="spec evidence requires landed spec"):
        mine_spec_evidence_memory(tmp_path, "003-demo", run_id="manual")


@pytest.mark.unit
def test_load_spec_evidence_snapshots_allows_explicit_unlanded_override(
    tmp_path: Path,
) -> None:
    spec_dir = write_evidence_workspace(tmp_path)
    mark_spec_unlanded(spec_dir)
    from echelon.mempalace_spec_evidence import load_spec_evidence_artifact_snapshots

    snapshots = load_spec_evidence_artifact_snapshots(
        tmp_path,
        "003-demo",
        allow_unlanded=True,
    )

    assert len(snapshots) == 2


@pytest.mark.unit
def test_publish_spec_evidence_package_copies_curated_verify_artifacts(
    tmp_path: Path,
) -> None:
    write_evidence_workspace(tmp_path)
    from echelon.mempalace_spec_evidence import publish_spec_evidence_package

    report = publish_spec_evidence_package(tmp_path, "003-demo")

    evidence_dir = tmp_path / "specs" / "003-demo" / "evidence"
    assert report.status == "published"
    assert report.published_count == 8
    assert sorted(path.name for path in evidence_dir.iterdir()) == [
        "canonical-requirements.json",
        "canonical-requirements.md",
        "codegraph-evidence-map.json",
        "codegraph-evidence-map.md",
        "implementation-map.md",
        "manifest.json",
        "progress-integrity.json",
        "progress-integrity.md",
        "requirement-audit.md",
    ]
    assert not evidence_dir.joinpath("debug.log").exists()


@pytest.mark.unit
def test_load_spec_evidence_snapshots_includes_published_evidence_package(
    tmp_path: Path,
) -> None:
    write_evidence_workspace(tmp_path)
    from echelon.mempalace_spec_evidence import (
        load_spec_evidence_artifact_snapshots,
        publish_spec_evidence_package,
    )

    publish_spec_evidence_package(tmp_path, "003-demo")
    snapshots = load_spec_evidence_artifact_snapshots(tmp_path, "003-demo")

    assert "specs/003-demo/evidence/implementation-map.md" in [
        snapshot.source for snapshot in snapshots
    ]
    assert "specs/003-demo/evidence/manifest.json" in [
        snapshot.source for snapshot in snapshots
    ]


@pytest.mark.unit
def test_load_spec_evidence_snapshots_uses_only_published_canonical_artifacts(
    tmp_path: Path,
) -> None:
    write_evidence_workspace(tmp_path)
    from echelon.mempalace_spec_evidence import load_spec_evidence_artifact_snapshots

    snapshots = load_spec_evidence_artifact_snapshots(tmp_path, "003-demo")

    assert [snapshot.source for snapshot in snapshots] == [
        "specs/003-demo/fulfillment-report.md",
        "specs/003-demo/verified-fulfillment-ledger.json",
    ]
    assert all(
        snapshot.artifact_metadata["artifact_kind"] == "spec-evidence"
        for snapshot in snapshots
    )
    assert {snapshot.artifact_metadata["room"] for snapshot in snapshots} == {
        "spec-fulfillment-evidence",
    }


@pytest.mark.unit
def test_mine_spec_evidence_refresh_cleans_only_matching_spec_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_evidence_workspace(tmp_path)
    deleted = []

    class FakeCollection:
        def get(self, where=None, include=None):
            return {
                "ids": ["old-evidence", "other-spec", "spec-memory"],
                "metadatas": [
                    {
                        "artifact_kind": "spec-evidence",
                        "spec_id": "003-demo",
                        "wing": "demo-wing",
                    },
                    {
                        "artifact_kind": "spec-evidence",
                        "spec_id": "004-other",
                        "wing": "demo-wing",
                    },
                    {
                        "artifact_kind": "supporting-context",
                        "spec_id": "003-demo",
                        "wing": "demo-wing",
                    },
                ],
            }

        def delete(self, ids):
            deleted.extend(ids)

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def open_collection_read_only(self):
            return FakeCollection()

        def mine_spec_evidence_artifact_bytes(self, content, *, source, artifact_metadata):
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
        "echelon.mempalace_spec_evidence.create_spec_evidence_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_spec_evidence import mine_spec_evidence_memory

    report = mine_spec_evidence_memory(tmp_path, "003-demo", run_id="manual")

    assert report.status == "complete"
    assert report.artifact_count == 2
    assert report.written_count == 2
    assert deleted == ["old-evidence"]


@pytest.mark.unit
def test_audit_spec_evidence_memory_reports_stale_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_evidence_workspace(tmp_path)

    class FakeCollection:
        def get(self, ids=None, where=None, include=None, limit=None):
            if ids is not None:
                return {
                    "ids": ["evidence-drawer"],
                    "documents": ["EVID-001: Published evidence fact."],
                    "metadatas": [
                        {
                            "wing": "demo-wing",
                            "room": "spec-fulfillment-evidence",
                            "artifact_kind": "spec-evidence",
                            "scope": "spec-evidence",
                            "spec_id": "003-demo",
                            "canonical": True,
                            "artifact_path": "specs/003-demo/fulfillment-report.md",
                            "source_file": "specs/003-demo/fulfillment-report.md",
                            "artifact_hash": "sha256:old",
                            "canonical_spec_sha256": "old",
                            "requirement_content_sha256": "88217a44e5991b0a2b4e4275a781753c9d7da8f20ac04f4614b9c84842e48a50",
                            "requirement_id": "EVID-001",
                            "deterministic_identity_schema_version": 1,
                            "lifecycle_status": "active",
                        }
                    ],
                }
            return {
                "ids": ["evidence-drawer"],
                "documents": ["EVID-001: Published evidence fact."],
                "metadatas": [{}],
            }

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def open_collection_read_only(self):
            return FakeCollection()

        def plan_spec_evidence_artifact_rows(self, content, *, source, artifact_metadata):
            if source != "specs/003-demo/fulfillment-report.md":
                return []
            return [
                SimpleNamespace(
                    drawer_id="evidence-drawer",
                    requirement_id="EVID-001",
                    room="spec-fulfillment-evidence",
                    source="specs/003-demo/fulfillment-report.md",
                    artifact_hash="sha256:new",
                    canonical_spec_sha256="new",
                    requirement_content_sha256="88217a44e5991b0a2b4e4275a781753c9d7da8f20ac04f4614b9c84842e48a50",
                )
            ]

    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.create_spec_evidence_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_spec_evidence import audit_spec_evidence_memory

    report = audit_spec_evidence_memory(tmp_path, "003-demo")

    assert report.status == "fail"
    assert report.stale == ["evidence-drawer"]
