from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from harness.re_v2.protocol_28.lifecycle import (
    create_or_reuse_protocol_28_child,
    run_protocol_28_exhaustive,
)
from tests.unit.test_re_v2_protocol_28_inputs import _fixture
from tests.unit.test_re_v2_protocol_28_lifecycle import _PassingBackend


def _completed_context(tmp_path: Path):  # type: ignore[no-untyped-def]
    _manifest, inputs = _fixture("re-l4-materialized")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    result = run_protocol_28_exhaustive(run_dir, lambda: _PassingBackend())
    assert result.run_root_id is not None
    return load_protocol_28_run_context(run_dir), result.run_root_id


@pytest.mark.unit
def test_l4_materialization_is_run_local_manifest_last_and_exact(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.materialization import materialize_l4_closure

    context, root_id = _completed_context(tmp_path)
    manifest = materialize_l4_closure(context)
    materialized = context.run_dir / "re" / "l4"

    assert manifest.root_id == root_id
    assert (materialized / "materialization.json").read_bytes().endswith(b"\n")
    assert json.loads((materialized / "materialization.json").read_bytes())[
        "root_id"
    ] == root_id
    assert (materialized / "roots" / "run.json").is_file()
    assert (materialized / "catalogs" / "snapshot-evidence.json").is_file()
    assert (materialized / "plans" / "exhaustive-plan.json").is_file()
    assert tuple((materialized / "coverage").glob("*.json"))
    assert tuple((materialized / "verification").glob("*.json"))
    assert tuple((materialized / "acceptance").glob("*.json"))
    assert tuple(materialized.rglob("*.md"))
    assert not (tmp_path / "re").exists()
    assert not (tmp_path / "runs" / "re-l3" / "re").exists()


@pytest.mark.unit
def test_l4_materialization_repairs_tamper_by_quarantining_then_rebuilding(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.materialization import (
        validate_or_repair_l4_materialization,
    )

    context, _root_id = _completed_context(tmp_path)
    first = validate_or_repair_l4_materialization(context)
    markdown = next((context.run_dir / "re" / "l4").rglob("*.md"))
    markdown.write_text("tampered\n", encoding="utf-8")

    second = validate_or_repair_l4_materialization(context)

    assert second == first
    assert markdown.read_text(encoding="utf-8") != "tampered\n"
    quarantine = context.paths.root / "quarantine" / "materialized-l4"
    assert any(quarantine.iterdir())


@pytest.mark.unit
def test_l4_materialization_recovers_after_pre_manifest_crash(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.materialization import (
        materialize_l4_closure,
        validate_or_repair_l4_materialization,
    )

    context, _root_id = _completed_context(tmp_path)

    def crash(point: str) -> None:
        if point == "before_manifest_publish":
            raise RuntimeError(point)

    with pytest.raises(RuntimeError, match="before_manifest_publish"):
        materialize_l4_closure(context, fault_hook=crash)

    assert not (context.run_dir / "re" / "l4" / "materialization.json").exists()
    repaired = validate_or_repair_l4_materialization(context)
    assert repaired.entries
    assert (context.run_dir / "re" / "l4" / "materialization.json").is_file()


@pytest.mark.unit
def test_l4_materialization_is_byte_stable_and_manifest_entries_are_sorted(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.materialization import materialize_l4_closure

    context, _root_id = _completed_context(tmp_path)
    first = materialize_l4_closure(context)
    before = {
        path.relative_to(context.run_dir).as_posix(): path.read_bytes()
        for path in (context.run_dir / "re" / "l4").rglob("*")
        if path.is_file()
    }
    second = materialize_l4_closure(context)
    after = {
        path.relative_to(context.run_dir).as_posix(): path.read_bytes()
        for path in (context.run_dir / "re" / "l4").rglob("*")
        if path.is_file()
    }

    assert second == first
    assert after == before
    assert tuple(item.relative_path for item in first.entries) == tuple(
        sorted(item.relative_path for item in first.entries)
    )


@pytest.mark.unit
def test_l4_materialization_rejects_symlink_without_writing_outside_run(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_28.materialization import (
        Protocol28MaterializationError,
        materialize_l4_closure,
    )

    context, _root_id = _completed_context(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (context.run_dir / "re").symlink_to(outside, target_is_directory=True)

    with pytest.raises(Protocol28MaterializationError, match="unsafe"):
        materialize_l4_closure(context)

    assert tuple(outside.iterdir()) == ()
