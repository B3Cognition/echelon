from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.test_re_v2_protocol_27_controller import _ScriptedProvider
from tests.unit.test_re_v2_protocol_27_publication import _completed_context


@pytest.mark.integration
def test_partial_publication_keeps_existing_paths_and_explicit_quality(
    tmp_path: Path,
) -> None:
    from harness.published_re_context import (
        attach_published_re_context,
        write_canonical_re_context,
    )
    from harness.re_registry import canonical_re_artifacts, load_published_index
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    context = _completed_context(tmp_path)
    run_protocol_27_synthesis(
        context.paths.root.parent,
        lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    )

    index = load_published_index(tmp_path)
    assert index is not None
    assert index.publication_status == "partial"
    assert index.synthesis_quality is not None
    assert index.synthesis_quality.input_quality == "partial"
    assert index.synthesis_quality.debt_manifest_hashes
    canonical = canonical_re_artifacts(tmp_path, index)
    assert Path(canonical["re_overview"]).is_file()
    assert set(canonical["source_manifests"]) == {"api", "web"}

    spec_run = tmp_path / "runs/spec-test"
    spec_run.mkdir()
    attached = attach_published_re_context(
        tmp_path,
        spec_run,
        ignore=False,
        re_sources=["api", "web"],
    )
    assert attached["status"] == "attached"
    assert attached["publication_status"] == "partial"
    assert attached["synthesis_quality"] == {
        "input_quality": "partial",
        "debt_manifest_hashes": list(index.synthesis_quality.debt_manifest_hashes),
        "partial_acceptance_receipt_ids": list(
            index.synthesis_quality.partial_acceptance_receipt_ids
        ),
        "synthesis_root_id": index.synthesis_quality.synthesis_root_id,
        "full_quality_claim": "unavailable",
    }
    spec_dir = spec_run / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    canonical_context = write_canonical_re_context(tmp_path, spec_dir, attached)
    durable = json.loads(canonical_context.read_text(encoding="utf-8"))
    assert durable["synthesis_quality"]["full_quality_claim"] == "unavailable"


@pytest.mark.integration
def test_complete_publication_exposes_full_quality_without_new_paths(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from harness.re_registry import load_published_index
    from harness.re_v2.publication import EMPTY_INDEX_HASH
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.inputs import create_protocol_27_run_store
    from harness.re_v2.protocol_27.lifecycle import (
        partial_acceptances_for,
        synthesis_request,
    )
    from tests.re_v2_protocol_27_fixtures import synthesis_budget_policy_v1
    from tests.unit.test_re_v2_protocol_27_inputs import _input_set

    run_dir = tmp_path / "runs/re-complete"
    seed = _input_set(run_dir.name, partial_sources=frozenset())
    parent = seed.parent
    budget = synthesis_budget_policy_v1(
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )
    request = synthesis_request(
        parent,
        budget,
        expected_v2_index_hash=EMPTY_INDEX_HASH,
        expected_compatibility_generation=0,
    )
    inputs = replace(
        seed,
        parent=parent,
        request=request,
        partial_acceptances=partial_acceptances_for(parent, request),
        budget_policy=budget,
    )
    create_protocol_27_run_store(run_dir, inputs)
    from harness.re_v2.protocol_27.inputs import load_protocol_27_inputs

    result = Protocol27Controller(
        inputs=load_protocol_27_inputs(run_dir),
        provider_factory=lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    ).run_to_closure()

    assert result.synthesis_closure_complete
    index = load_published_index(tmp_path)
    assert index is not None
    assert index.publication_status == "complete"
    assert index.synthesis_quality is not None
    assert index.synthesis_quality.input_quality == "complete"
