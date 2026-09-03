from __future__ import annotations

import shutil
import os
from pathlib import Path

import pytest

from harness.re_v2.canonical import content_digest
from tests.unit.test_re_v2_protocol_27_controller import (
    _ScriptedProvider,
    _validated_controller_inputs,
)


def _completed_context(tmp_path: Path):
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.recovery import load_protocol_27_run_context

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider()
    result = Protocol27Controller(
        inputs,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    ).run_to_closure()
    assert result.synthesis_closure_complete
    return load_protocol_27_run_context(inputs.paths.root.parent), provider


def _tree_digest(root: Path) -> str:
    return content_digest(
        [
            (path.relative_to(root).as_posix(), content_digest(path.read_bytes()))
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]
    )


@pytest.mark.unit
def test_materialization_preserves_public_paths(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.materialization import (
        materialize_synthesis_closure,
    )

    context, _provider = _completed_context(tmp_path)
    manifest = materialize_synthesis_closure(context)
    paths = {entry.relative_path for entry in manifest.entries}

    assert "sources/api/overview.md" in paths
    assert "sources/api/architecture.md" in paths
    assert "workspace/overview.md" in paths
    assert "workspace/relationships.md" in paths
    assert "workspace/contracts.md" in paths


@pytest.mark.unit
def test_source_overview_is_exact_embedded_lower_projection(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.materialization import (
        canonical_source_overview_bytes,
        materialize_synthesis_closure,
    )

    context, _provider = _completed_context(tmp_path)
    expected = canonical_source_overview_bytes(context, "api")
    materialize_synthesis_closure(context)
    published = context.paths.root.parent / "re" / "published"

    assert (published / "sources/api/overview.md").read_bytes() == expected


@pytest.mark.unit
def test_deleted_projection_rebuilds_byte_identically_without_provider(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.materialization import (
        materialize_synthesis_closure,
        validate_or_repair_synthesis_materialization,
    )

    context, provider = _completed_context(tmp_path)
    first = materialize_synthesis_closure(context)
    published = context.paths.root.parent / "re" / "published"
    before = _tree_digest(published)
    calls = len(provider.calls)
    shutil.rmtree(published)

    repaired = validate_or_repair_synthesis_materialization(context)

    assert repaired == first
    assert _tree_digest(published) == before
    assert len(provider.calls) == calls


@pytest.mark.unit
def test_unexpected_or_unsafe_projection_fails_closed(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.materialization import (
        Protocol27MaterializationError,
        materialize_synthesis_closure,
        validate_or_repair_synthesis_materialization,
    )

    context, _provider = _completed_context(tmp_path)
    materialize_synthesis_closure(context)
    published = context.paths.root.parent / "re" / "published"
    (published / "unexpected.txt").write_text("unowned", encoding="utf-8")

    with pytest.raises(Protocol27MaterializationError, match="unexpected"):
        validate_or_repair_synthesis_materialization(context)


@pytest.mark.unit
def test_modified_regular_projection_is_quarantined_and_rebuilt(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.materialization import (
        materialize_synthesis_closure,
        validate_or_repair_synthesis_materialization,
    )

    context, _provider = _completed_context(tmp_path)
    manifest = materialize_synthesis_closure(context)
    published = context.paths.root.parent / "re" / "published"
    target = published / "workspace/overview.md"
    expected = next(
        item.content_hash
        for item in manifest.entries
        if item.relative_path == "workspace/overview.md"
    )
    target.chmod(0o600)
    target.write_bytes(b"altered\n")

    validate_or_repair_synthesis_materialization(context)

    assert content_digest(target.read_bytes()) == expected
    assert target.stat().st_mode & 0o777 == 0o400
    assert any(
        path.is_file()
        for path in (context.paths.root.parent / "quarantine/materialized").iterdir()
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("attack", "message"),
    (("symlink", "symlink"), ("hardlink", "hard link")),
)
def test_linked_projection_fails_closed(
    tmp_path: Path,
    attack: str,
    message: str,
) -> None:
    from harness.re_v2.protocol_27.materialization import (
        Protocol27MaterializationError,
        materialize_synthesis_closure,
        validate_or_repair_synthesis_materialization,
    )

    context, _provider = _completed_context(tmp_path)
    materialize_synthesis_closure(context)
    published = context.paths.root.parent / "re" / "published"
    target = published / "workspace/overview.md"
    if attack == "symlink":
        target.unlink()
        target.symlink_to("contracts.md")
    else:
        os.link(target, published / "workspace/overview-hardlink.md")

    with pytest.raises(Protocol27MaterializationError, match=message):
        validate_or_repair_synthesis_materialization(context)


class _MaterializationCrash(RuntimeError):
    pass


class _CrashMaterializationBoundary:
    def __init__(self, boundary: str, occurrence: int = 1) -> None:
        self.boundary = boundary
        self.occurrence = occurrence
        self.seen = 0

    def __call__(self, observed: str) -> None:
        if not observed.startswith(self.boundary):
            return
        self.seen += 1
        if self.seen == self.occurrence:
            raise _MaterializationCrash(observed)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("boundary", "occurrence"),
    (
        *(("materialization_published:", index) for index in range(1, 17)),
        ("synthesis_materialization_ledger", 1),
        ("synthesis_materialization_event", 1),
    ),
)
def test_materialization_crash_resumes_without_provider_or_authority_change(
    tmp_path: Path,
    boundary: str,
    occurrence: int,
) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.materialization import (
        materialize_synthesis_closure,
        validate_or_repair_synthesis_materialization,
    )
    from harness.re_v2.protocol_27.recovery import load_protocol_27_run_context

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider()
    with pytest.raises(RuntimeError, match="after_root"):
        Protocol27Controller(
            inputs,
            provider_factory=lambda: provider,  # type: ignore[arg-type]
            fault_hook=lambda observed: (
                (_ for _ in ()).throw(RuntimeError(observed))
                if observed == "after_root"
                else None
            ),
        ).run_to_closure()
    context = load_protocol_27_run_context(inputs.paths.root.parent)
    accepted_before = dict(context.ledger.replay().accepted_artifacts)
    calls = len(provider.calls)

    with pytest.raises(_MaterializationCrash):
        materialize_synthesis_closure(
            context,
            _CrashMaterializationBoundary(boundary, occurrence),
        )
    manifest = validate_or_repair_synthesis_materialization(context)

    assert len(provider.calls) == calls
    assert dict(context.ledger.replay().accepted_artifacts) == accepted_before
    assert context.ledger.replay().materialization is not None
    assert context.ledger.replay().materialization.materialization_manifest_id == manifest.identity
