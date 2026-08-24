from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2 import (
    RE_V2_ENGINE,
    RE_V2_PROTOCOL,
    RE_V2_SCHEMA_3_PROTOCOLS,
    RE_V2_SUPPORTED_PROTOCOLS,
)
from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.model import BudgetPolicy, RunManifest
from harness.re_v2.protocol_22.model import RunManifestV2
from harness.re_v2.protocol_24.model import RunManifestV3
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    create_run_store,
    detect_re_engine,
    load_run_manifest,
)
from tests.re_v2_protocol_22_fixtures import manifest_v2, manifest_v2_dict
from tests.re_v2_protocol_24_fixtures import manifest_v3


def _manifest(*, run_id: str) -> RunManifest:
    return RunManifest(
        schema_version=1,
        engine=RE_V2_ENGINE,
        engine_protocol_version="2.0",
        run_id=run_id,
        created_at="2026-08-14T12:00:00Z",
        source_snapshot_id="sha256:" + "1" * 64,
        source_snapshot_kind="git-worktree",
        partition_manifest_id="sha256:" + "2" * 64,
        requested_goals=("inventory",),
        initial_budget_policy=BudgetPolicy(
            token_limit=10_000,
            active_ms_limit=60_000,
            provider_attempt_limit=2,
            artifact_generation_attempt_limit=2,
            semantic_repair_round_limit=1,
            result_contract_retry_limit=1,
        ),
        provider_contract={"provider": "fake"},
        artifact_policy_versions={"L0": "egr-164-v1"},
        parent_run_id=None,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("protocol_version", "snapshot_kind"),
    (
        ("2.0", "git-worktree"),
        ("2.0", "content-snapshot"),
        ("2.1", "workspace-git-composite"),
    ),
)
def test_run_store_round_trips_supported_protocol_snapshot_pairs(
    tmp_path: Path,
    protocol_version: str,
    snapshot_kind: str,
) -> None:
    manifest = replace(
        _manifest(run_id="re-1"),
        engine_protocol_version=protocol_version,
        source_snapshot_kind=snapshot_kind,
    )

    create_run_store(tmp_path / "runs" / "re-1", manifest)

    assert load_run_manifest(tmp_path / "runs" / "re-1") == manifest


@pytest.mark.unit
def test_run_manifest_is_create_once(tmp_path: Path) -> None:
    """Replacing a pinned manifest would silently change a run's identity."""
    run_dir = tmp_path / "runs" / "re-1"
    first = _manifest(run_id="re-1")

    create_run_store(run_dir, first)

    with pytest.raises(ReV2RunStoreError, match="already exists"):
        create_run_store(run_dir, first)
    assert load_run_manifest(run_dir) == first


@pytest.mark.unit
def test_create_run_store_materializes_run_local_object_authority(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "re-1"

    paths = create_run_store(run_dir, _manifest(run_id="re-1"))

    assert paths.objects == paths.root / "objects"
    assert paths.objects.is_dir()
    assert not paths.objects.is_symlink()


@pytest.mark.unit
def test_interleaving_creator_cannot_overwrite_pinned_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second creator that wins the final publish race keeps its own bytes."""
    run_dir = tmp_path / "runs" / "re-1"
    first = _manifest(run_id="re-1")
    competing = RunManifest.from_json_dict(
        {**first.to_json_dict(), "requested_goals": ["alternate-inventory"]}
    )
    real_link = os.link

    def publish_competitor(source: str | bytes, destination: str | bytes, *args: object, **kwargs: object) -> None:
        Path(destination).write_bytes(canonical_json_bytes(competing.to_json_dict()))
        real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr("harness.re_v2.run_store.os.link", publish_competitor)

    with pytest.raises(ReV2RunStoreError, match="already exists"):
        create_run_store(run_dir, first)

    assert load_run_manifest(run_dir) == competing


@pytest.mark.unit
def test_engine_detection_never_guesses_from_outer_state(tmp_path: Path) -> None:
    """A legacy outer state marker must not opt a run into a different engine."""
    run_dir = tmp_path / "runs" / "re-legacy"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text('{"engine":"re-v2"}', encoding="utf-8")

    assert detect_re_engine(run_dir) == "v1"


@pytest.mark.unit
def test_engine_detection_defaults_to_v1_without_a_v2_store(tmp_path: Path) -> None:
    """Existing v1 run directories retain their original routing."""
    run_dir = tmp_path / "runs" / "re-legacy"
    run_dir.mkdir(parents=True)

    assert detect_re_engine(run_dir) == "v1"


@pytest.mark.unit
def test_engine_detection_rejects_incomplete_v2_store(tmp_path: Path) -> None:
    """A crashed v2 creation must not be mistaken for a v1 run."""
    run_dir = tmp_path / "runs" / "re-1"
    (run_dir / "v2").mkdir(parents=True)

    with pytest.raises(ReV2RunStoreError, match="incomplete v2 run store"):
        detect_re_engine(run_dir)


@pytest.mark.unit
def test_create_rejects_manifest_for_a_different_run(tmp_path: Path) -> None:
    """A manifest copied from another run cannot be pinned under this run ID."""
    run_dir = tmp_path / "runs" / "re-1"

    with pytest.raises(ReV2RunStoreError, match="does not match"):
        create_run_store(run_dir, _manifest(run_id="re-other"))


@pytest.mark.unit
def test_load_rejects_manifest_with_unsupported_pinned_protocol(tmp_path: Path) -> None:
    """A binary must fail rather than execute a manifest it cannot interpret."""
    run_dir = tmp_path / "runs" / "re-1"
    paths = create_run_store(run_dir, _manifest(run_id="re-1"))
    raw = json.loads(paths.manifest.read_text(encoding="utf-8"))
    raw["engine_protocol_version"] = "999.0"
    paths.manifest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ReV2RunStoreError, match="unsupported"):
        load_run_manifest(run_dir)


@pytest.mark.unit
def test_supported_protocols_activate_23_and_keep_22_readable() -> None:
    assert RE_V2_PROTOCOL == "2.3"
    assert RE_V2_SCHEMA_3_PROTOCOLS == ("2.4",)
    assert RE_V2_SUPPORTED_PROTOCOLS == ("2.0", "2.1", "2.2", "2.3", "2.4")


@pytest.mark.unit
def test_run_store_loads_canonical_schema_2_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "re-v22"
    paths = ReV2Paths.for_run(run_dir)
    paths.root.mkdir(parents=True)
    expected = manifest_v2(run_id=run_dir.name)
    paths.manifest.write_bytes(canonical_json_bytes(expected.to_json_dict()))

    loaded = load_run_manifest(run_dir)

    assert isinstance(loaded, RunManifestV2)
    assert loaded == expected


@pytest.mark.unit
def test_run_store_loads_protocol_23_with_schema_2(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "re-v23"
    paths = ReV2Paths.for_run(run_dir)
    paths.root.mkdir(parents=True)
    raw = manifest_v2_dict(run_id=run_dir.name)
    raw["engine_protocol_version"] = "2.3"
    paths.manifest.write_bytes(canonical_json_bytes(raw))

    loaded = load_run_manifest(run_dir)

    assert isinstance(loaded, RunManifestV2)
    assert loaded.to_json_dict() == raw


@pytest.mark.unit
def test_run_store_loads_protocol_24_with_schema_3(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "re-v24"
    paths = ReV2Paths.for_run(run_dir)
    paths.root.mkdir(parents=True)
    expected = manifest_v3(run_id=run_dir.name)
    paths.manifest.write_bytes(canonical_json_bytes(expected.to_json_dict()))

    loaded = load_run_manifest(run_dir)

    assert isinstance(loaded, RunManifestV3)
    assert loaded == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("schema_version", "protocol_version"),
    (
        (1, "2.2"),
        (2, "2.1"),
        (2, "2.0"),
        (3, "2.2"),
        (3, "2.3"),
        (2, "2.4"),
        (2, "999"),
    ),
)
def test_run_store_rejects_unsupported_schema_protocol_pairs(
    tmp_path: Path,
    schema_version: int,
    protocol_version: str,
) -> None:
    run_dir = tmp_path / "runs" / f"re-{schema_version}-{protocol_version.replace('.', '-')}"
    paths = ReV2Paths.for_run(run_dir)
    paths.root.mkdir(parents=True)
    raw = manifest_v2_dict(run_id=run_dir.name)
    raw["schema_version"] = schema_version
    raw["engine_protocol_version"] = protocol_version
    paths.manifest.write_bytes(canonical_json_bytes(raw))

    with pytest.raises(ReV2RunStoreError, match="unsupported"):
        load_run_manifest(run_dir)
