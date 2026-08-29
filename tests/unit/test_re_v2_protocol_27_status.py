from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.test_re_v2_protocol_27_publication import _completed_context


@pytest.mark.unit
def test_partial_input_complete_synthesis_is_not_blocked(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.publication import publish_protocol_27_generation
    from harness.re_v2.protocol_27.status import protocol_27_status_document

    context = _completed_context(tmp_path)
    assert publish_protocol_27_generation(context).status == "published_partial"

    document = protocol_27_status_document(tmp_path / "runs/re-synthesis-child")

    assert document["synthesis_status"] == "complete"
    assert document["input_quality"] == "partial"
    assert document["publication_status"] == "published_partial"
    assert document["full_quality_claim"] == "unavailable"
    assert document["next_action"] == "none; synthesis and publication are complete"


@pytest.mark.unit
def test_status_json_reports_authenticated_resources_and_artifacts(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.publication import publish_protocol_27_generation
    from harness.re_v2.protocol_27.status import render_protocol_27_status

    context = _completed_context(tmp_path)
    publish_protocol_27_generation(context)

    document = json.loads(
        render_protocol_27_status(
            tmp_path / "runs/re-synthesis-child",
            as_json=True,
        )
    )

    assert document["artifact_counts"]["required"] > 0
    assert document["artifact_counts"]["unresolved"] == 0
    assert document["resources"]["provider_attempts"] > 0
    assert document["sources"]["partial"] == ["web"]
    assert document["partial_acceptance_receipt_ids"]


@pytest.mark.unit
def test_conflict_banner_names_current_run_as_successor_parent(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.status import render_protocol_27_status
    from harness.re_v2.publication import EMPTY_INDEX_HASH, publish_generation
    from harness.re_v2.canonical import content_digest

    _completed_context(tmp_path)
    publish_generation(
        tmp_path,
        "competing-run",
        (content_digest(b"competing-root"),),
        content_digest(b"competing-policy"),
        expected_index_hash=EMPTY_INDEX_HASH,
    )

    rendered = render_protocol_27_status(tmp_path / "runs/re-synthesis-child")

    assert "RE WORKSPACE SYNTHESIS — COMPLETE, PUBLICATION CONFLICT" in rendered
    assert "--from-run re-synthesis-child" in rendered
    assert "--accept-partial web" in rendered


@pytest.mark.unit
def test_incomplete_banner_names_exact_unresolved_artifacts(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.inputs import create_protocol_27_run_store
    from harness.re_v2.protocol_27.recovery import (
        load_protocol_27_run_context,
        recover_protocol_27_run,
    )
    from harness.re_v2.protocol_27.status import render_protocol_27_status
    from tests.unit.test_re_v2_protocol_27_inputs import _input_set

    run_dir = tmp_path / "runs/re-incomplete"
    create_protocol_27_run_store(run_dir, _input_set(run_dir.name))
    recover_protocol_27_run(load_protocol_27_run_context(run_dir))

    rendered = render_protocol_27_status(run_dir)

    assert "RE WORKSPACE SYNTHESIS — INCOMPLETE" in rendered
    assert "unresolved:" in rendered
    assert "echelon re continue re-incomplete" in rendered
