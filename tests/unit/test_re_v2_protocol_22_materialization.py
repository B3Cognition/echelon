from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.baseline import render_baseline_markdown
from harness.re_v2.protocol_22.controller import Protocol22Controller
from harness.re_v2.protocol_22.materialization import (
    Protocol22MaterializationError,
    materialize_accepted_l1,
    validate_or_repair_materialization,
)
from tests.unit.test_re_v2_protocol_22_controller import _baseline_context


def _completed_context(tmp_path: Path):
    context, _provider = _baseline_context(tmp_path)
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "completed"
    return context


@pytest.mark.unit
def test_controller_materializes_accepted_l1_before_reporting_complete(
    tmp_path: Path,
) -> None:
    context, _provider = _baseline_context(tmp_path)

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "completed"
    materialized = context.paths.root / "materialized" / "L1" / "sources" / "api"
    assert tuple(materialized.joinpath("domains", "001-re-src").iterdir())
    assert tuple(materialized.joinpath("overview").iterdir())
    assert tuple(materialized.joinpath("root").iterdir())


@pytest.mark.unit
def test_budget_paused_continuation_repairs_accepted_l1_before_returning(
    tmp_path: Path,
) -> None:
    context, provider = _baseline_context(tmp_path, token_limit=9_000)
    first = Protocol22Controller(context).run_until_stopped()
    assert first.status == "paused"
    assert provider.calls == 1
    accepted = materialize_accepted_l1(context)
    assert len(accepted.paths) == 1
    projection = accepted.paths[0]
    shutil.rmtree(projection)

    second = Protocol22Controller(context).run_until_stopped()

    assert second.status == "paused"
    assert provider.calls == 1
    assert projection.is_dir()


def _projection_by_fragment(report, fragment: str) -> tuple[Path, str]:
    matches = [
        (path, artifact_hash)
        for path, artifact_hash in zip(report.paths, report.hashes, strict=True)
        if fragment in path.as_posix()
    ]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.unit
def test_materializes_exact_domain_overview_and_root_without_workspace_output(
    tmp_path: Path,
) -> None:
    context = _completed_context(tmp_path)

    report = materialize_accepted_l1(context)

    assert report.rebuilt_count == 0
    assert report.reused_count == 3
    assert report.quarantined_count == 0
    domain, domain_hash = _projection_by_fragment(
        report,
        "/domains/001-re-src/",
    )
    overview, overview_hash = _projection_by_fragment(report, "/overview/")
    root, root_hash = _projection_by_fragment(report, "/root/")
    assert domain.name == domain_hash.removeprefix("sha256:")
    assert overview.name == overview_hash.removeprefix("sha256:")
    assert root.name == root_hash.removeprefix("sha256:") + ".json"
    for directory, artifact_hash in ((domain, domain_hash), (overview, overview_hash)):
        payload = directory.joinpath("baseline.json").read_bytes()
        assert content_digest(payload) == artifact_hash
        assert directory.joinpath("baseline.md").read_bytes() == (
            render_baseline_markdown(payload)
        )
    assert content_digest(root.read_bytes()) == root_hash
    assert not (tmp_path / "re").exists()


@pytest.mark.unit
def test_missing_materialization_rebuilds_from_object_authority(
    tmp_path: Path,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    domain, artifact_hash = _projection_by_fragment(initial, "/domains/")
    shutil.rmtree(domain)

    repaired = validate_or_repair_materialization(context)

    assert repaired.rebuilt_count == 1
    assert repaired.reused_count == 2
    assert repaired.quarantined_count == 0
    assert (
        content_digest(domain.joinpath("baseline.json").read_bytes()) == artifact_hash
    )


@pytest.mark.unit
def test_corrupt_projection_is_quarantined_before_rebuild(tmp_path: Path) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    domain, artifact_hash = _projection_by_fragment(initial, "/domains/")
    markdown = domain / "baseline.md"
    markdown.chmod(0o600)
    markdown.write_text("corrupt\n", encoding="utf-8")

    report = validate_or_repair_materialization(context)

    assert report.quarantined_count == 1
    assert report.rebuilt_count == 1
    assert report.reused_count == 2
    assert (
        content_digest(domain.joinpath("baseline.json").read_bytes()) == artifact_hash
    )
    assert len(report.quarantine_paths) == 1
    quarantined = report.quarantine_paths[0]
    assert quarantined.joinpath("baseline.md").read_text(encoding="utf-8") == (
        "corrupt\n"
    )


@pytest.mark.unit
def test_corrupt_root_file_is_quarantined_before_exact_rebuild(tmp_path: Path) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    root, artifact_hash = _projection_by_fragment(initial, "/root/")
    root.chmod(0o600)
    root.write_text("corrupt\n", encoding="utf-8")

    report = validate_or_repair_materialization(context)

    assert report.quarantined_count == 1
    assert report.rebuilt_count == 1
    assert content_digest(root.read_bytes()) == artifact_hash
    assert report.quarantine_paths[0].read_text(encoding="utf-8") == "corrupt\n"


@pytest.mark.unit
def test_extra_safe_directory_is_quarantined_with_the_altered_projection(
    tmp_path: Path,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    domain, _artifact_hash = _projection_by_fragment(initial, "/domains/")
    extra = domain / "extra"
    extra.mkdir()
    (extra / "note.txt").write_text("recoverable\n", encoding="utf-8")

    report = validate_or_repair_materialization(context)

    assert report.quarantined_count == 1
    assert report.rebuilt_count == 1
    assert (
        report.quarantine_paths[0]
        .joinpath("extra", "note.txt")
        .read_text(encoding="utf-8")
        == "recoverable\n"
    )


@pytest.mark.unit
def test_exact_materialization_is_immutable_reuse(tmp_path: Path) -> None:
    context = _completed_context(tmp_path)
    first = materialize_accepted_l1(context)

    second = materialize_accepted_l1(context)

    assert second.paths == first.paths
    assert second.hashes == first.hashes
    assert second.reused_count == 3
    assert second.rebuilt_count == 0
    assert second.quarantined_count == 0


@pytest.mark.unit
@pytest.mark.parametrize("unsafe_kind", ("symlink", "special"))
def test_unsafe_projection_entry_fails_closed_without_quarantine(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    domain, _artifact_hash = _projection_by_fragment(initial, "/domains/")
    domain.chmod(0o700)
    markdown = domain / "baseline.md"
    markdown.unlink()
    if unsafe_kind == "symlink":
        outside = tmp_path / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        markdown.symlink_to(outside)
    else:
        markdown.parent.joinpath("baseline.md").touch()
        markdown.unlink()
        import os

        os.mkfifo(markdown)

    with pytest.raises(Protocol22MaterializationError, match=unsafe_kind):
        validate_or_repair_materialization(context)

    quarantine = context.paths.root / "quarantine" / "materialized"
    assert not quarantine.exists() or tuple(quarantine.iterdir()) == ()


@pytest.mark.unit
def test_quarantine_failure_preserves_corrupt_projection_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import harness.re_v2.protocol_22.materialization as materialization

    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    domain, _artifact_hash = _projection_by_fragment(initial, "/domains/")
    markdown = domain / "baseline.md"
    markdown.chmod(0o600)
    markdown.write_text("corrupt\n", encoding="utf-8")

    def fail_quarantine(*_args, **_kwargs):
        raise Protocol22MaterializationError("quarantine unavailable")

    monkeypatch.setattr(materialization, "_quarantine_entry", fail_quarantine)

    with pytest.raises(Protocol22MaterializationError, match="quarantine unavailable"):
        validate_or_repair_materialization(context)

    assert markdown.read_text(encoding="utf-8") == "corrupt\n"


@pytest.mark.unit
def test_fault_after_quarantine_leaves_recoverable_bytes_then_rebuilds(
    tmp_path: Path,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    domain, artifact_hash = _projection_by_fragment(initial, "/domains/")
    markdown = domain / "baseline.md"
    markdown.chmod(0o600)
    markdown.write_text("corrupt\n", encoding="utf-8")

    def fail_after_quarantine(boundary: str) -> None:
        if boundary == f"materialization_quarantined:{artifact_hash}":
            raise RuntimeError("fault after quarantine")

    with pytest.raises(RuntimeError, match="fault after quarantine"):
        validate_or_repair_materialization(context, fail_after_quarantine)

    assert not domain.exists()
    quarantined = tuple((context.paths.root / "quarantine" / "materialized").iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].joinpath("baseline.md").read_text(encoding="utf-8") == (
        "corrupt\n"
    )

    repaired = validate_or_repair_materialization(context)

    assert repaired.rebuilt_count == 1
    assert (
        content_digest(domain.joinpath("baseline.json").read_bytes()) == artifact_hash
    )


@pytest.mark.unit
def test_root_staging_fault_replays_without_deleting_durable_bytes(
    tmp_path: Path,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    root, artifact_hash = _projection_by_fragment(initial, "/root/")
    root.unlink()

    def fail_after_staging(boundary: str) -> None:
        if boundary == f"materialization_json_fsynced:{artifact_hash}":
            raise RuntimeError("fault after root staging")

    with pytest.raises(RuntimeError, match="fault after root staging"):
        validate_or_repair_materialization(context, fail_after_staging)

    assert not root.exists()
    staging = root.with_name(f".{root.name}.staging")
    assert staging.is_file()
    assert content_digest(staging.read_bytes()) == artifact_hash

    repaired = validate_or_repair_materialization(context)

    assert repaired.rebuilt_count == 1
    assert content_digest(root.read_bytes()) == artifact_hash
    assert not staging.exists()


@pytest.mark.unit
def test_corrupt_root_staging_is_quarantined_before_exact_rebuild(
    tmp_path: Path,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    root, artifact_hash = _projection_by_fragment(initial, "/root/")
    root.unlink()
    staging = root.with_name(f".{root.name}.staging")
    staging.write_text("partial corrupt staging\n", encoding="utf-8")

    repaired = validate_or_repair_materialization(context)

    assert repaired.quarantined_count == 1
    assert repaired.rebuilt_count == 1
    assert content_digest(root.read_bytes()) == artifact_hash
    assert not staging.exists()
    assert repaired.quarantine_paths[0].read_text(encoding="utf-8") == (
        "partial corrupt staging\n"
    )


@pytest.mark.unit
def test_exact_root_with_stale_corrupt_staging_quarantines_only_staging(
    tmp_path: Path,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    root, artifact_hash = _projection_by_fragment(initial, "/root/")
    staging = root.with_name(f".{root.name}.staging")
    staging.write_text("unrelated stale staging\n", encoding="utf-8")

    repaired = validate_or_repair_materialization(context)

    assert repaired.quarantined_count == 1
    assert repaired.rebuilt_count == 0
    assert repaired.reused_count == 3
    assert content_digest(root.read_bytes()) == artifact_hash
    assert repaired.quarantine_paths[0].read_text(encoding="utf-8") == (
        "unrelated stale staging\n"
    )


@pytest.mark.unit
def test_root_link_fault_finishes_the_no_clobber_commit_on_replay(
    tmp_path: Path,
) -> None:
    context = _completed_context(tmp_path)
    initial = materialize_accepted_l1(context)
    root, artifact_hash = _projection_by_fragment(initial, "/root/")
    root.unlink()

    def fail_after_link(boundary: str) -> None:
        if boundary == f"materialization_root_linked:{artifact_hash}":
            raise RuntimeError("fault after root link")

    with pytest.raises(RuntimeError, match="fault after root link"):
        validate_or_repair_materialization(context, fail_after_link)

    staging = root.with_name(f".{root.name}.staging")
    assert root.is_file()
    assert staging.is_file()
    assert root.stat().st_ino == staging.stat().st_ino

    repaired = validate_or_repair_materialization(context)

    assert repaired.reused_count == 3
    assert content_digest(root.read_bytes()) == artifact_hash
    assert root.stat().st_nlink == 1
    assert not staging.exists()
