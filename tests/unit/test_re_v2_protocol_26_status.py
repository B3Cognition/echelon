from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.protocol_26.adoption import initialize_protocol_26_run_store
from harness.re_v2.protocol_26.inputs import create_protocol_26_run_store
from harness.re_v2.protocol_26.status import protocol_26_status_document
from tests.unit.test_re_v2_protocol_26_inputs import _protocol26_input_fixture


@pytest.mark.unit
def test_status_reports_frozen_checkpoint_adoption_and_avoided_reservations(
    tmp_path: Path,
) -> None:
    supplied = _protocol26_input_fixture("L1")
    run_dir = tmp_path / "runs" / supplied.manifest.run_id
    create_protocol_26_run_store(run_dir, supplied.manifest, supplied)
    initialize_protocol_26_run_store(run_dir)

    status = protocol_26_status_document(run_dir)
    checkpoints = status["checkpoints"]

    assert status["engine_protocol_version"] == "2.6"
    assert checkpoints["selected_count"] == 1
    assert checkpoints["adopted_count"] == 1
    assert checkpoints["avoided_dispatch_count"] == 1
    assert checkpoints["avoided_active_ms_reservation"] > 0
    assert "observed_tokens" not in checkpoints
    assert "adopted 1 checkpoints" in status["banner"]


@pytest.mark.unit
def test_status_survives_deleted_cache_and_has_no_completion_overclaim(
    tmp_path: Path,
) -> None:
    supplied = _protocol26_input_fixture("L1")
    run_dir = tmp_path / "runs" / supplied.manifest.run_id
    create_protocol_26_run_store(run_dir, supplied.manifest, supplied)
    initialize_protocol_26_run_store(run_dir)

    status = protocol_26_status_document(run_dir)

    assert status["checkpoints"]["reconstruction_state"] == "frozen_self_contained"
    assert "workspace synthesis complete" not in status["banner"].lower()
    assert "published" not in status["banner"].lower()
    assert "repair complete" not in status["banner"].lower()
    assert "synthesis_status" not in status
    assert "publication_status" not in status
    assert "full_quality_claim" not in status
