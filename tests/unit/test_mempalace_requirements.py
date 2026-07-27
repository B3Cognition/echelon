from pathlib import Path

import pytest


def write_workspace(tmp_path: Path) -> Path:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    config_dir = tmp_path / ".specify" / "extensions" / "echelon"
    config_dir.mkdir(parents=True)
    config_dir.joinpath("echelon-config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text(
        "# Demo\n\nFR-001: Upload a photo.\nNFR-001: Respond within 1s.\n",
        encoding="utf-8",
    )
    return spec_dir


@pytest.mark.unit
def test_resolve_spec_dir_accepts_id_slug_and_path(tmp_path: Path) -> None:
    spec_dir = write_workspace(tmp_path)
    from echelon.mempalace_requirements import resolve_spec_dir

    assert resolve_spec_dir(tmp_path, "003") == spec_dir
    assert resolve_spec_dir(tmp_path, "003-demo") == spec_dir
    assert resolve_spec_dir(tmp_path, "specs/003-demo") == spec_dir


@pytest.mark.unit
def test_resolve_spec_dir_rejects_run_local_path(tmp_path: Path) -> None:
    run_spec = tmp_path / "runs" / "abc" / "specs" / "003-demo"
    run_spec.mkdir(parents=True)
    run_spec.joinpath("spec.md").write_text("FR-001: Draft.\n", encoding="utf-8")
    from echelon.mempalace_requirements import SpecMemoryError, resolve_spec_dir

    with pytest.raises(SpecMemoryError, match="run-local specs are not supported"):
        resolve_spec_dir(tmp_path, "runs/abc/specs/003-demo")


@pytest.mark.unit
def test_snapshot_contains_canonical_artifact_metadata(tmp_path: Path) -> None:
    spec_dir = write_workspace(tmp_path)
    from echelon.mempalace_requirements import load_canonical_spec_snapshot

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)

    assert snapshot.source == "specs/003-demo/spec.md"
    assert snapshot.artifact_metadata["canonical"] is True
    assert snapshot.artifact_metadata["scope"] == "canonical"
    assert snapshot.artifact_metadata["artifact_path"] == "specs/003-demo/spec.md"
    assert snapshot.artifact_metadata["artifact_hash"].startswith("sha256:")
    assert snapshot.artifact_metadata["added_by"] == "echelon"


@pytest.mark.unit
def test_adapter_plan_matches_existing_canonical_miner(tmp_path: Path, monkeypatch) -> None:
    spec_dir = write_workspace(tmp_path)
    from codegen.memory.requirements_miner import plan_canonical_requirement_drawer_ids
    from echelon.mempalace_requirements import (
        create_requirement_memory_adapter,
        load_canonical_spec_snapshot,
    )

    snapshot = load_canonical_spec_snapshot(tmp_path, spec_dir)
    adapter = create_requirement_memory_adapter(tmp_path, run_id="manual")

    assert adapter.plan_canonical_bytes(
        snapshot.content,
        source=snapshot.source,
        artifact_metadata=snapshot.artifact_metadata,
    ) == plan_canonical_requirement_drawer_ids(
        snapshot.content,
        source=snapshot.source,
        artifact_metadata=snapshot.artifact_metadata,
        wing="demo-wing",
    )


@pytest.mark.unit
def test_mine_spec_requirements_maps_drift_without_overwrite(tmp_path: Path, monkeypatch) -> None:
    spec_dir = write_workspace(tmp_path)

    class FakeResult:
        total = 2
        written = 1
        already_present = 0
        skipped = 0
        failed = 1
        unavailable = 0
        drawer_ids = ["drawer-ok"]
        expected_drawer_ids = ["drawer-ok", "drawer-drift"]
        errors = ["deterministic_write_failed"]

    class FakeAdapter:
        wing = "demo-wing"
        palace_path = tmp_path / ".mempalace"

        def mine_canonical_bytes(self, content, *, source, artifact_metadata):
            return FakeResult()

    monkeypatch.setattr(
        "echelon.mempalace_requirements.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(),
    )
    from echelon.mempalace_requirements import mine_spec_requirements

    report = mine_spec_requirements(tmp_path, spec_dir, run_id="manual")

    assert report.status == "partial"
    assert report.written_count == 1
    assert report.drifted_count == 1
    assert report.expected_drawer_ids == ["drawer-ok", "drawer-drift"]
