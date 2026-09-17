from __future__ import annotations

import builtins
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import traceback
from types import SimpleNamespace
from typing import Any

import pytest

from echelon import context_reconciliation as reconciliation
from echelon.spec_memory_miner import plan_canonical_requirement_drawers


@dataclass
class Drawer:
    drawer_id: str
    content: str
    metadata: dict[str, Any]


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _drawer(
    drawer_id: str,
    *,
    path: Any = "specs/001-game/spec.md",
    digest: Any = "sha256:" + "0" * 64,
    status: Any = "active",
    source_file: bool = False,
    writer_status: Any | None = None,
) -> Drawer:
    metadata: dict[str, Any] = {
        "artifact_hash": digest,
        "lifecycle_status": status,
    }
    metadata["source_file" if source_file else "artifact_path"] = path
    if writer_status is not None:
        metadata["status"] = writer_status
    return Drawer(drawer_id=drawer_id, content=drawer_id, metadata=metadata)


def _planned_drawer(content: bytes, source: str) -> Drawer:
    digest = hashlib.sha256(content).hexdigest()
    row = plan_canonical_requirement_drawers(
        content,
        source=source,
        artifact_metadata={
            "canonical": True,
            "artifact_hash": f"sha256:{digest}",
        },
        wing="captured-reconciliation-test",
    )[0]
    return Drawer(
        drawer_id=row.drawer_id,
        content=content.decode("utf-8"),
        metadata={
            "artifact_path": row.source,
            "artifact_hash": row.artifact_hash,
            "lifecycle_status": "active",
        },
    )


def test_captured_reconciliation_uses_candidate_bytes_not_published_disk(
    tmp_path: Path,
) -> None:
    source = "specs/001-game/spec.md"
    old_bytes = b"- **FR-1000000**: Preserve the published behavior.\n"
    candidate_bytes = b"- **FR-1000000**: Use the candidate behavior.\n"
    old_drawer = _planned_drawer(old_bytes, source)
    candidate_drawer = _planned_drawer(candidate_bytes, source)
    root = tmp_path.resolve()
    spec_path = root / source
    spec_path.parent.mkdir(parents=True)
    spec_path.write_bytes(old_bytes)

    disk = reconciliation.reconcile_drawers([old_drawer, candidate_drawer], root)
    assert disk.accepted == [old_drawer]
    assert disk.rejected == [
        {
            "drawer_id": candidate_drawer.drawer_id,
            "reason": "hash_mismatch",
            "artifact_path": source,
        }
    ]

    captured = reconciliation.reconcile_captured_drawers(
        [old_drawer, candidate_drawer], {source: candidate_bytes}
    )
    assert captured.accepted == [candidate_drawer]
    assert captured.rejected == [
        {
            "drawer_id": old_drawer.drawer_id,
            "reason": "hash_mismatch",
            "artifact_path": source,
        }
    ]
    assert spec_path.read_bytes() == old_bytes


def test_disk_and_captured_reconciliation_have_complete_native_parity(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    source = "specs/001-game/spec.md"
    missing_source = "specs/002-missing/spec.md"
    content = b"- **FR-1000000**: Preserve the full identifier.\n"
    spec = root / source
    spec.parent.mkdir(parents=True)
    spec.write_bytes(content)
    digest = _sha256(content)

    matching = _drawer("matching", digest=digest)
    changed_dict = {
        "metadata": {
            "id": "changed-dict",
            "source_file": source,
            "artifact_hash": digest,
            "lifecycle_status": "changed",
        }
    }
    stale = _drawer("stale", digest="sha256:" + "1" * 64)
    missing = _drawer("missing", path=missing_source, digest=digest)
    no_hash = _drawer("no-hash", digest="")
    no_path = _drawer("no-path", path="", digest=digest)
    removed = _drawer("removed", path="", digest="", status="removed")
    lifecycle_wins = _drawer(
        "lifecycle-wins", digest=digest, status="active", writer_status="removed"
    )
    no_metadata = SimpleNamespace(drawer_id="no-metadata")
    drawers = [
        matching,
        matching,
        changed_dict,
        stale,
        missing,
        no_hash,
        no_path,
        removed,
        lifecycle_wins,
        no_metadata,
    ]

    disk = reconciliation.reconcile_drawers(drawers, root)
    captured = reconciliation.reconcile_captured_drawers(
        drawers, {source: content, missing_source: None}
    )

    expected_rejected = [
        {"drawer_id": "stale", "reason": "hash_mismatch", "artifact_path": source},
        {
            "drawer_id": "missing",
            "reason": "artifact_missing",
            "artifact_path": missing_source,
        },
        {
            "drawer_id": "no-hash",
            "reason": "missing_artifact_hash",
            "artifact_path": source,
        },
        {"drawer_id": "no-path", "reason": "missing_artifact_path"},
        {
            "drawer_id": "removed",
            "reason": "lifecycle_excluded",
            "status": "removed",
        },
        {"drawer_id": "no-metadata", "reason": "missing_artifact_path"},
    ]
    assert disk == captured
    assert disk.accepted == [matching, matching, changed_dict, lifecycle_wins]
    assert disk.rejected == expected_rejected
    assert disk.to_dict() == {
        "accepted_count": 4,
        "rejected": expected_rejected,
    }


@pytest.mark.parametrize(
    ("include_statuses", "accepted_ids", "rejected_statuses"),
    [
        (
            None,
            ["active", "changed"],
            ["deprecated", "superseded", "removed", "bespoke"],
        ),
        (
            set(),
            [],
            ["active", "changed", "deprecated", "superseded", "removed", "bespoke"],
        ),
        (
            {"superseded", "bespoke"},
            ["superseded", "bespoke"],
            ["active", "changed", "deprecated", "removed"],
        ),
    ],
)
def test_disk_and_captured_status_filters_have_complete_parity(
    tmp_path: Path,
    include_statuses: set[str] | None,
    accepted_ids: list[str],
    rejected_statuses: list[str],
) -> None:
    source = "specs/001-game/spec.md"
    content = b"FR-001: Status parity.\n"
    spec = tmp_path / source
    spec.parent.mkdir(parents=True)
    spec.write_bytes(content)
    digest = _sha256(content)
    drawers = [
        _drawer(status, digest=digest, status=status)
        for status in (
            "active",
            "changed",
            "deprecated",
            "superseded",
            "removed",
            "bespoke",
        )
    ]

    disk = reconciliation.reconcile_drawers(drawers, tmp_path, include_statuses)
    captured = reconciliation.reconcile_captured_drawers(
        drawers, {source: content}, include_statuses
    )

    assert disk == captured
    assert [drawer.drawer_id for drawer in disk.accepted] == accepted_ids
    assert disk.rejected == [
        {"drawer_id": status, "reason": "lifecycle_excluded", "status": status}
        for status in rejected_statuses
    ]


def test_captured_images_distinguish_unobserved_missing_and_empty_content() -> None:
    empty_digest = _sha256(b"")
    source_unobserved = "specs/001-unobserved/spec.md"
    source_missing = "specs/002-missing/spec.md"
    source_empty = "specs/003-empty/spec.md"
    source_stale_empty = "specs/004-empty-stale/spec.md"
    run_local = "runs/spec-1/specs/005-run-local/spec.md"
    non_spec = "docs/spec.md"
    drawers = [
        _drawer("unobserved", path=source_unobserved, digest=empty_digest),
        _drawer("missing", path=source_missing, digest=empty_digest),
        _drawer("empty", path=source_empty, digest=empty_digest),
        _drawer("stale-empty", path=source_stale_empty, digest="sha256:" + "f" * 64),
        _drawer("run-local", path=run_local, digest=_sha256(b"run")),
        _drawer("non-spec", path=non_spec, digest=_sha256(b"doc")),
    ]

    report = reconciliation.reconcile_captured_drawers(
        drawers,
        {
            source_missing: None,
            source_empty: b"",
            source_stale_empty: b"",
            run_local: b"run",
            non_spec: b"doc",
            "assets/unrelated.bin": b"\x00\xffunrelated",
        },
    )

    assert report.accepted == [drawers[2]]
    assert report.rejected == [
        {
            "drawer_id": "unobserved",
            "reason": "artifact_unobserved",
            "artifact_path": source_unobserved,
        },
        {
            "drawer_id": "missing",
            "reason": "artifact_missing",
            "artifact_path": source_missing,
        },
        {
            "drawer_id": "stale-empty",
            "reason": "hash_mismatch",
            "artifact_path": source_stale_empty,
        },
        {
            "drawer_id": "run-local",
            "reason": "non_canonical_artifact_path",
            "artifact_path": run_local,
        },
        {
            "drawer_id": "non-spec",
            "reason": "non_canonical_artifact_path",
            "artifact_path": non_spec,
        },
    ]


class DictSubclass(dict):
    pass


class BytesSubclass(bytes):
    pass


class StrSubclass(str):
    pass


@pytest.mark.parametrize(
    "artifact_images",
    [
        [],
        DictSubclass(),
        {1: b"value"},
        {StrSubclass("specs/001-game/spec.md"): b"value"},
        {"": b"value"},
        {"..": b"value"},
        {"./": b"value"},
        {"/specs/001-game/spec.md": b"value"},
        {"../specs/001-game/spec.md": b"value"},
        {"specs/../001-game/spec.md": b"value"},
        {"./specs/001-game/spec.md": b"value"},
        {"specs//001-game/spec.md": b"value"},
        {"specs/001-game/spec.md/": b"value"},
        {"specs\\001-game\\spec.md": b"value"},
        {"specs/001-game/spec.md\x00": b"value"},
        {"specs/001-game/\ud800.md": b"value"},
        {"specs/001-game/spec.md": "value"},
        {"specs/001-game/spec.md": bytearray(b"value")},
        {"specs/001-game/spec.md": BytesSubclass(b"value")},
        {"specs/001-game/spec.md": 1},
    ],
)
def test_captured_reconciliation_rejects_every_malformed_image_table(
    artifact_images: Any,
) -> None:
    with pytest.raises(ValueError, match="^invalid captured reconciliation input$"):
        reconciliation.reconcile_captured_drawers([], artifact_images)


def test_captured_reconciliation_validates_unused_images_before_drawer_iteration() -> None:
    class IterationTripwire:
        def __iter__(self):
            raise AssertionError("drawer iteration must not start")

    with pytest.raises(ValueError, match="^invalid captured reconciliation input$"):
        reconciliation.reconcile_captured_drawers(
            IterationTripwire(),  # type: ignore[arg-type]
            {
                "assets/valid.bin": b"valid",
                "unused//malformed.bin": b"sensitive unused bytes",
            },
        )


def test_empty_captured_table_is_valid_and_means_unobserved() -> None:
    drawer = _drawer("unobserved", digest=_sha256(b"bytes"))

    report = reconciliation.reconcile_captured_drawers([drawer], {})

    assert report.accepted == []
    assert report.rejected == [
        {
            "drawer_id": "unobserved",
            "reason": "artifact_unobserved",
            "artifact_path": "specs/001-game/spec.md",
        }
    ]


def test_image_table_validation_precedes_an_exclusive_lifecycle_filter() -> None:
    drawer = _drawer("removed", status="removed")

    with pytest.raises(ValueError, match="^invalid captured reconciliation input$"):
        reconciliation.reconcile_captured_drawers(
            [drawer],
            {"unused//malformed.bin": b"sensitive unused bytes"},
            include_statuses=set(),
        )


def test_captured_reconciliation_rejects_aliases_that_native_disk_resolves(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    source = "specs/001-game/spec.md"
    content = b"FR-001: Native aliases.\n"
    spec = project_root / source
    spec.parent.mkdir(parents=True)
    spec.write_bytes(content)
    digest = _sha256(content)
    absolute = _drawer("absolute", path=str(spec.resolve()), digest=digest)
    parent_alias = _drawer(
        "parent-alias", path="specs/001-game/../001-game/spec.md", digest=digest
    )
    dot_alias = _drawer("dot-alias", path="specs/001-game/./spec.md", digest=digest)
    outside = tmp_path / "outside.md"
    outside.write_bytes(content)
    outside_drawer = _drawer("outside", path="../outside.md", digest=digest)

    disk = reconciliation.reconcile_drawers(
        [absolute, parent_alias, dot_alias, outside_drawer], project_root
    )
    captured = reconciliation.reconcile_captured_drawers(
        [absolute, parent_alias, dot_alias, outside_drawer], {source: content}
    )

    assert disk.accepted == [absolute, parent_alias, dot_alias]
    assert disk.rejected == [
        {
            "drawer_id": "outside",
            "reason": "artifact_outside_project",
            "artifact_path": "../outside.md",
        }
    ]
    assert captured.accepted == []
    assert captured.rejected == [
        {
            "drawer_id": drawer.drawer_id,
            "reason": "non_canonical_artifact_path",
            "artifact_path": drawer.metadata["artifact_path"],
        }
        for drawer in (absolute, parent_alias, dot_alias, outside_drawer)
    ]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_native_disk_resolves_internal_symlink_but_captured_rejects_alias(
    tmp_path: Path,
) -> None:
    source = "specs/001-game/spec.md"
    alias_source = "alias/spec.md"
    content = b"FR-001: Symlink compatibility.\n"
    spec = tmp_path / source
    spec.parent.mkdir(parents=True)
    spec.write_bytes(content)
    (tmp_path / "alias").symlink_to(spec.parent, target_is_directory=True)
    drawer = _drawer("symlink", path=alias_source, digest=_sha256(content))

    disk = reconciliation.reconcile_drawers([drawer], tmp_path)
    captured = reconciliation.reconcile_captured_drawers(
        [drawer], {alias_source: content}
    )

    assert disk.accepted == [drawer]
    assert disk.rejected == []
    assert captured.accepted == []
    assert captured.rejected == [
        {
            "drawer_id": "symlink",
            "reason": "non_canonical_artifact_path",
            "artifact_path": alias_source,
        }
    ]


def test_native_spec_directory_prefix_rule_remains_exact(tmp_path: Path) -> None:
    content = b"FR-001: Prefix compatibility.\n"
    digest = _sha256(content)
    accepted_paths = ["specs/000-game/spec.md", "specs/999-/spec.md"]
    rejected_paths = [
        "specs/01-game/spec.md",
        "specs/0012-game/spec.md",
        "specs/000game/spec.md",
    ]
    drawers = [
        _drawer(path, path=path, digest=digest)
        for path in (*accepted_paths, *rejected_paths)
    ]
    for path in (*accepted_paths, *rejected_paths):
        artifact = tmp_path / path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(content)

    report = reconciliation.reconcile_drawers(drawers, tmp_path)

    assert report.accepted == drawers[:2]
    assert report.rejected == [
        {
            "drawer_id": path,
            "reason": "non_canonical_artifact_path",
            "artifact_path": path,
        }
        for path in rejected_paths
    ]


def test_captured_reconciliation_preserves_a_very_wide_element_label() -> None:
    label = "FR-" + "9" * 5000
    source = "specs/001-game/spec.md"
    content = f"- **{label}**: Preserve the exact wide label.\n".encode()
    row = plan_canonical_requirement_drawers(
        content,
        source=source,
        artifact_metadata={"canonical": True, "artifact_hash": _sha256(content)},
        wing="captured-reconciliation-test",
    )[0]
    drawer = Drawer(
        row.drawer_id,
        label,
        {
            "artifact_path": row.source,
            "artifact_hash": row.artifact_hash,
            "lifecycle_status": "active",
            "requirement_id": row.requirement_id,
        },
    )

    report = reconciliation.reconcile_captured_drawers([drawer], {source: content})

    assert report.accepted == [drawer]
    assert report.accepted[0] is drawer
    assert report.accepted[0].metadata["requirement_id"] == label
    assert report.rejected == []


def test_captured_reconciliation_is_detached_from_disk_and_input_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "specs/001-game/spec.md"
    candidate = b"FR-001: Candidate bytes.\n"
    spec = tmp_path / source
    spec.parent.mkdir(parents=True)
    spec.write_bytes(b"FR-001: Published bytes.\n")
    drawer = _drawer("candidate", digest=_sha256(candidate))
    artifact_images: dict[str, bytes | None] = {source: candidate}

    class MutatingDrawers:
        def __iter__(self):
            artifact_images.clear()
            artifact_images["assets/replacement.bin"] = b"replacement"
            yield drawer

    spec.unlink()
    reads: list[str] = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        reads.append("filesystem access")
        raise AssertionError("captured reconciliation touched the filesystem")

    for method in ("resolve", "read_bytes", "read_text", "open", "exists"):
        monkeypatch.setattr(Path, method, forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(io, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(os, "scandir", forbidden)

    report = reconciliation.reconcile_captured_drawers(
        MutatingDrawers(), artifact_images  # type: ignore[arg-type]
    )

    assert report.accepted == [drawer]
    assert report.accepted[0] is drawer
    assert report.rejected == []
    assert reads == []


def _assert_bounded_input_error(call: Any, sentinel: str) -> None:
    with pytest.raises(ValueError, match="^invalid captured reconciliation input$") as exc_info:
        call()
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    formatted = "".join(
        traceback.format_exception(
            type(exc_info.value), exc_info.value, exc_info.value.__traceback__
        )
    )
    assert sentinel not in formatted


def test_captured_reconciliation_bounds_metadata_access_errors() -> None:
    sentinel = "SENSITIVE-METADATA-CONTENT"

    class ExplodingDrawer:
        @property
        def metadata(self):
            raise RuntimeError(sentinel)

    _assert_bounded_input_error(
        lambda: reconciliation.reconcile_captured_drawers(
            [ExplodingDrawer()], {"specs/001-game/spec.md": b"bytes"}
        ),
        sentinel,
    )


def test_captured_reconciliation_bounds_iteration_errors() -> None:
    sentinel = "SENSITIVE-ITERATION-CONTENT"

    class ExplodingDrawers:
        def __iter__(self):
            raise RuntimeError(sentinel)

    _assert_bounded_input_error(
        lambda: reconciliation.reconcile_captured_drawers(
            ExplodingDrawers(),  # type: ignore[arg-type]
            {"specs/001-game/spec.md": b"bytes"},
        ),
        sentinel,
    )


def test_captured_reconciliation_bounds_metadata_conversion_errors() -> None:
    sentinel = "SENSITIVE-CONVERSION-CONTENT"

    class ExplodingString:
        def __str__(self):
            raise RuntimeError(sentinel)

    drawer = _drawer("conversion", path=ExplodingString())
    _assert_bounded_input_error(
        lambda: reconciliation.reconcile_captured_drawers(
            [drawer], {"specs/001-game/spec.md": b"bytes"}
        ),
        sentinel,
    )


def test_captured_reconciliation_bounds_hash_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "SENSITIVE-HASH-CONTENT"
    drawer = _drawer("hash", digest=_sha256(b"bytes"))

    def exploding_hash(content: bytes):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(reconciliation.hashlib, "sha256", exploding_hash)
    _assert_bounded_input_error(
        lambda: reconciliation.reconcile_captured_drawers(
            [drawer], {"specs/001-game/spec.md": b"bytes"}
        ),
        sentinel,
    )


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_captured_reconciliation_propagates_process_control_exceptions(
    exception_type: type[BaseException],
) -> None:
    class InterruptingDrawers:
        def __iter__(self):
            raise exception_type("stop")

    with pytest.raises(exception_type, match="stop"):
        reconciliation.reconcile_captured_drawers(
            InterruptingDrawers(),  # type: ignore[arg-type]
            {"specs/001-game/spec.md": b"bytes"},
        )


def test_native_disk_hash_failures_still_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "specs/001-game/spec.md"
    spec = tmp_path / source
    spec.parent.mkdir(parents=True)
    spec.write_bytes(b"bytes")
    drawer = _drawer("native-read", digest=_sha256(b"bytes"))
    failure = OSError("native read failed")

    def fail_hash(path: Path) -> str:
        raise failure

    monkeypatch.setattr(reconciliation, "artifact_hash", fail_hash)

    with pytest.raises(OSError) as exc_info:
        reconciliation.reconcile_drawers([drawer], tmp_path)
    assert exc_info.value is failure
