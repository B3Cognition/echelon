from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.publication import EMPTY_INDEX_HASH, load_published_v2_index, publish_generation
from tests.unit.test_re_v2_protocol_27_controller import (
    _ScriptedProvider,
)
from tests.unit.test_re_v2_protocol_27_inputs import _input_set
from tests.re_v2_protocol_27_fixtures import synthesis_budget_policy_v1


def _completed_context(
    tmp_path: Path,
    *,
    expected_v2: str = EMPTY_INDEX_HASH,
    expected_compatibility: int = 0,
    run_id: str = "re-synthesis-child",
):
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.inputs import (
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )
    from harness.re_v2.protocol_27.lifecycle import (
        partial_acceptances_for,
        synthesis_request,
    )
    from harness.re_v2.protocol_27.recovery import load_protocol_27_run_context

    run_dir = tmp_path / "runs" / run_id
    seed = _input_set(run_dir.name)
    budget = synthesis_budget_policy_v1(
        token_limit=10_000_000, active_ms_limit=10_000_000
    )
    request = synthesis_request(
        seed.parent,
        budget,
        expected_v2_index_hash=expected_v2,
        expected_compatibility_generation=expected_compatibility,
    )
    inputs = replace(
        seed,
        request=request,
        partial_acceptances=partial_acceptances_for(seed.parent, request),
        budget_policy=budget,
    )
    create_protocol_27_run_store(run_dir, inputs)
    validated = load_protocol_27_inputs(run_dir)
    class Ready(RuntimeError):
        pass

    with pytest.raises(Ready):
        Protocol27Controller(
            validated,
            provider_factory=lambda: _ScriptedProvider(),  # type: ignore[arg-type]
            fault_hook=lambda point: (
                (_ for _ in ()).throw(Ready(point))
                if point == "synthesis_materialization_event"
                else None
            ),
        ).run_to_closure()
    return load_protocol_27_run_context(run_dir)


@pytest.mark.unit
def test_partial_descriptor_publishes_existing_paths_and_labels(tmp_path: Path) -> None:
    from harness.re_registry import canonical_re_artifacts, load_published_index
    from harness.re_v2.protocol_27.publication import publish_protocol_27_generation

    context = _completed_context(tmp_path)

    result = publish_protocol_27_generation(context)

    assert result.status == "published_partial"
    assert (tmp_path / "re/sources/api/overview.md").is_file()
    published = load_published_index(tmp_path)
    assert published is not None
    assert published.publication_status == "partial"
    assert published.synthesis_quality is not None
    assert published.synthesis_quality.input_quality == "partial"
    downstream = canonical_re_artifacts(tmp_path, published)
    assert downstream["re_overview"] == str(
        tmp_path / "re/workspace/overview.md"
    )
    assert set(downstream["source_manifests"]) == {"api", "web"}
    v2 = load_published_v2_index(tmp_path)
    assert v2 is not None
    assert v2.run_id == context.inputs.manifest.run_id


@pytest.mark.unit
def test_descriptor_binds_staged_compatibility_index_without_cycle(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.materialization import (
        validate_or_repair_synthesis_materialization,
    )
    from harness.re_v2.protocol_27.publication import (
        build_compatibility_candidate,
        build_publication_descriptor,
    )

    context = _completed_context(tmp_path)
    materialization = validate_or_repair_synthesis_materialization(context)
    candidate = build_compatibility_candidate(context, materialization, 1)
    descriptor = build_publication_descriptor(context, materialization, candidate)

    assert descriptor.compatibility_generation == 1
    assert descriptor.compatibility_index_hash == content_digest(candidate.index_bytes)
    assert descriptor.descriptor_id.encode() not in candidate.index_bytes


@pytest.mark.unit
def test_v2_cas_conflict_rolls_back_compatibility_projection(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.publication import publish_protocol_27_generation

    context = _completed_context(tmp_path)
    competed = False

    def race(point: str) -> None:
        nonlocal competed
        if point != "after_compatibility_index" or competed:
            return
        competed = True
        publish_generation(
            tmp_path,
            "competing-run",
            (content_digest(b"competing-root"),),
            content_digest(b"competing-policy"),
            expected_index_hash=EMPTY_INDEX_HASH,
        )

    result = publish_protocol_27_generation(context, fault_hook=race)

    assert competed
    assert result.status == "conflict"
    assert not (tmp_path / "re/index.json").exists()
    assert not (tmp_path / "re/sources/api").exists()


class _PublicationCrash(BaseException):
    pass


@pytest.mark.unit
def test_crash_between_indexes_recovers_without_invalid_projection(tmp_path: Path) -> None:
    from harness.re_registry import load_published_index
    from harness.re_v2.protocol_27.publication import (
        publish_protocol_27_generation,
        recover_protocol_27_publication,
    )

    context = _completed_context(tmp_path)

    with pytest.raises(_PublicationCrash):
        publish_protocol_27_generation(
            context,
            fault_hook=lambda point: (
                (_ for _ in ()).throw(_PublicationCrash(point))
                if point == "after_compatibility_index"
                else None
            ),
        )

    result = recover_protocol_27_publication(context)

    assert result.status == "published_partial"
    assert load_published_index(tmp_path) is not None
    assert load_published_v2_index(tmp_path) is not None


@pytest.mark.unit
@pytest.mark.parametrize(
    "boundary",
    (
        "publication_marker_staged",
        "after_install_intent:sources/api",
        "after_install_rename:sources/api",
        "after_replace:sources/api",
        "after_install_intent:workspace",
        "after_install_rename:workspace",
        "after_replace:workspace",
        "after_install_intent:index.json",
        "after_compatibility_index",
        "compatibility_journal_retained",
        "generation_temporary_written",
        "generation_promoted",
        "index_temporary_written",
        "index_replaced",
        "publication_receipt",
        "publication_event",
        "publication_journal_finalized",
        "publication_staging_cleaned",
    ),
)
def test_publication_crash_boundaries_recover_to_exact_dual_publication(
    tmp_path: Path, boundary: str
) -> None:
    from harness.re_registry import load_published_index
    from harness.re_v2.protocol_27.publication import (
        publish_protocol_27_generation,
        recover_protocol_27_publication,
    )

    context = _completed_context(tmp_path)

    with pytest.raises(_PublicationCrash):
        publish_protocol_27_generation(
            context,
            fault_hook=lambda point: (
                (_ for _ in ()).throw(_PublicationCrash(point))
                if point == boundary
                else None
            ),
        )

    result = recover_protocol_27_publication(context)

    assert result.status == "published_partial"
    compatibility = load_published_index(tmp_path)
    assert compatibility is not None
    assert compatibility.generation == 1
    assert load_published_v2_index(tmp_path) == result.v2_index


@pytest.mark.unit
@pytest.mark.parametrize(
    "boundary",
    (
        "after_backup_intent:sources/api",
        "after_backup_rename:sources/api",
        "after_backup:sources/api",
        "after_backup_intent:workspace",
        "after_backup_rename:workspace",
        "after_backup:workspace",
        "after_backup_intent:index.json",
        "after_backup_rename:index.json",
        "after_backup:index.json",
    ),
)
def test_replacement_backup_crashes_restore_then_complete(
    tmp_path: Path, boundary: str
) -> None:
    from harness.re_registry import load_published_index
    from harness.re_v2.publication import current_index_hash
    from harness.re_v2.protocol_27.publication import (
        publish_protocol_27_generation,
        recover_protocol_27_publication,
    )

    first = _completed_context(tmp_path, run_id="re-synthesis-first")
    assert publish_protocol_27_generation(first).status == "published_partial"
    second = _completed_context(
        tmp_path,
        expected_v2=current_index_hash(tmp_path),
        expected_compatibility=1,
        run_id="re-synthesis-second",
    )

    with pytest.raises(_PublicationCrash):
        publish_protocol_27_generation(
            second,
            fault_hook=lambda point: (
                (_ for _ in ()).throw(_PublicationCrash(point))
                if point == boundary
                else None
            ),
        )

    result = recover_protocol_27_publication(second)

    assert result.status == "published_partial"
    published = load_published_index(tmp_path)
    assert published is not None
    assert published.generation == 2
    assert published.published_from_run == "re-synthesis-second"


@pytest.mark.unit
def test_existing_publication_recovery_entrypoint_dispatches_marked_protocol_27(
    tmp_path: Path,
) -> None:
    import json

    from harness.re_publication import recover_interrupted_publication
    from harness.re_registry import load_published_index
    from harness.re_v2.protocol_27.publication import publish_protocol_27_generation

    context = _completed_context(tmp_path)
    with pytest.raises(_PublicationCrash):
        publish_protocol_27_generation(
            context,
            fault_hook=lambda point: (
                (_ for _ in ()).throw(_PublicationCrash(point))
                if point == "after_compatibility_index"
                else None
            ),
        )
    owner_path = tmp_path / "re/.locks/publish.lock/owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["pid"] = 999_999_999
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    assert recover_interrupted_publication(tmp_path, stale_after_seconds=0)

    published = load_published_index(tmp_path)
    assert published is not None
    assert published.published_from_run == context.inputs.manifest.run_id
    assert load_published_v2_index(tmp_path) is not None
    assert not (tmp_path / "re/.locks/publish.lock").exists()


@pytest.mark.unit
def test_ordinary_publication_error_rolls_back_and_allows_retry(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.publication import publish_protocol_27_generation

    context = _completed_context(tmp_path)
    with pytest.raises(RuntimeError, match="injected-error"):
        publish_protocol_27_generation(
            context,
            fault_hook=lambda point: (
                (_ for _ in ()).throw(RuntimeError("injected-error"))
                if point == "after_replace:sources/api"
                else None
            ),
        )

    assert not (tmp_path / "re/.staging/re-synthesis-child").exists()
    assert not (tmp_path / "re/sources/api").exists()
    assert publish_protocol_27_generation(context).status == "published_partial"
