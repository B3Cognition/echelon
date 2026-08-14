"""Controller-owned proportional Phase 1 quality repair accounting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness.proportional_quality import (
    AUTOMATIC_REPAIR_LIMIT,
    EXTENSION_REPAIR_LIMIT,
    initialize_repair_state,
    record_what_outcome,
    validate_repair_state,
)


def _repair_state(**overrides: object) -> dict[str, object]:
    state = initialize_repair_state({"spec_authoring_mode": "proportional"})
    assert state is not None
    return {**state, **overrides}


def test_new_proportional_run_starts_with_controller_owned_limits() -> None:
    repair = initialize_repair_state({"spec_authoring_mode": "proportional"})

    assert repair == {
        "schema_version": 1,
        "authoring_mode": "proportional",
        "automatic_limit": AUTOMATIC_REPAIR_LIMIT,
        "automatic_consumed": 0,
        "extension_limit": EXTENSION_REPAIR_LIMIT,
        "extension_authorized": 0,
        "extension_consumed": 0,
        "migration_basis": "fresh",
    }


def test_perfectionist_run_never_creates_proportional_repair_state() -> None:
    state = {"spec_authoring_mode": "perfectionist", "iteration": 4}

    assert initialize_repair_state(state) is None
    assert "phase1_quality_repair" not in state


def test_existing_valid_state_round_trips_detached_on_resume() -> None:
    existing = _repair_state(automatic_consumed=2, extension_authorized=1)

    restored = initialize_repair_state(
        {
            "spec_authoring_mode": "proportional",
            "phase1_quality_repair": existing,
        }
    )

    assert restored == existing
    assert restored is not existing
    restored["automatic_consumed"] = 1
    assert existing["automatic_consumed"] == 2


def _certified_why2_score(
    tmp_path: Path,
    *,
    iteration: int,
    passed: bool,
) -> dict[str, object]:
    report_path = tmp_path / f"phase1-why2-iter-{iteration}.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "completed",
                "phase": "phase1-why2",
                "iteration": iteration,
                "spec": {"path": "specs/001/spec.md", "sha256": "a" * 64},
                "pass": passed,
            }
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    return {
        "pass": passed,
        "pass_id": f"WHY2-iter-{iteration}",
        "source": "harness:understanding",
        "evidence": str(report_path),
        "evidence_digest": digest,
        "overall": 0.9,
        "structure": 0.9,
        "readability": 0.9,
        "cognitive": 0.9,
        "semantic": 0.9,
        "testability": 0.9,
        "behavioral": 0.9,
        "depth": 0.9,
    }


def test_legacy_history_counts_completed_certified_why2_assessments(
    tmp_path: Path,
) -> None:
    repair = initialize_repair_state(
        {
            "quality_scores": [
                _certified_why2_score(tmp_path, iteration=0, passed=False),
                _certified_why2_score(tmp_path, iteration=1, passed=True),
                _certified_why2_score(tmp_path, iteration=2, passed=False),
                _certified_why2_score(tmp_path, iteration=3, passed=True),
                {"source": "agent", "pass_id": "WHY2-iter-99", "pass": True},
            ],
            "iteration": 0,
        }
    )

    assert repair is not None
    assert repair["automatic_consumed"] == 3
    assert repair["migration_basis"] == "why2_history"


@pytest.mark.parametrize(
    "mutate_score",
    [
        lambda score: score.pop("evidence_digest"),
        lambda score: score.update(evidence_digest="f" * 64),
        lambda score: score.update(pass_id="WHY2-iter-9"),
        lambda score: score.update(source="harness:forged"),
    ],
)
def test_partial_or_forged_why2_history_falls_back_to_global_iteration(
    tmp_path: Path,
    mutate_score,
) -> None:
    score = _certified_why2_score(tmp_path, iteration=0, passed=False)
    mutate_score(score)

    repair = initialize_repair_state(
        {"quality_scores": [score], "iteration": 2}
    )

    assert repair is not None
    assert repair["automatic_consumed"] == 2
    assert repair["migration_basis"] == "iteration_fallback"


def test_history_free_legacy_run_uses_capped_global_iteration() -> None:
    repair = initialize_repair_state({"iteration": 9})

    assert repair is not None
    assert repair["automatic_consumed"] == 3
    assert repair["migration_basis"] == "iteration_fallback"


def test_changed_valid_automatic_what_consumes_only_automatic_budget() -> None:
    original = _repair_state()

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="b" * 64,
        valid_completion=True,
        extension_active=False,
    )

    assert outcome.outcome == "consumed"
    assert outcome.repair_state["automatic_consumed"] == 1
    assert outcome.repair_state["extension_consumed"] == 0
    assert original["automatic_consumed"] == 0


def test_changed_valid_extension_what_consumes_only_extension_budget() -> None:
    original = _repair_state(extension_authorized=1)

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="b" * 64,
        valid_completion=True,
        extension_active=True,
    )

    assert outcome.outcome == "consumed"
    assert outcome.repair_state["automatic_consumed"] == 0
    assert outcome.repair_state["extension_consumed"] == 1


def test_unchanged_valid_automatic_what_reports_no_progress_without_consuming() -> None:
    original = _repair_state()

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="a" * 64,
        valid_completion=True,
        extension_active=False,
    )

    assert outcome.outcome == "no_artifact_progress"
    assert outcome.repair_state["automatic_consumed"] == 0
    assert outcome.repair_state["extension_consumed"] == 0


def test_unchanged_valid_authorized_extension_consumes_extension_once() -> None:
    original = _repair_state(extension_authorized=1)

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="a" * 64,
        valid_completion=True,
        extension_active=True,
    )

    assert outcome.outcome == "no_artifact_progress"
    assert outcome.repair_state["extension_consumed"] == 1


@pytest.mark.parametrize("valid_completion,extension_active", [(False, False), (False, True)])
def test_operational_what_outcome_never_consumes_budget(
    valid_completion: bool,
    extension_active: bool,
) -> None:
    original = _repair_state(extension_authorized=1)

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="b" * 64,
        valid_completion=valid_completion,
        extension_active=extension_active,
    )

    assert outcome.outcome == "not_consumed"
    assert outcome.repair_state == original


@pytest.mark.parametrize(
    "override",
    [
        {"automatic_limit": 2},
        {"extension_limit": 2},
        {"automatic_consumed": -1},
        {"automatic_consumed": 4},
        {"extension_consumed": 2},
        {"authoring_mode": "perfectionist"},
        {"agent_override": True},
    ],
)
def test_invalid_or_agent_authored_repair_state_fails_closed(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        validate_repair_state(_repair_state(**override))


@pytest.mark.parametrize(
    ("field", "malformed"),
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("automatic_limit", True),
        ("automatic_limit", 3.0),
        ("extension_limit", True),
        ("extension_limit", 1.0),
        ("automatic_consumed", True),
        ("automatic_consumed", 0.0),
        ("extension_authorized", True),
        ("extension_authorized", 0.0),
        ("extension_consumed", True),
        ("extension_consumed", 0.0),
    ],
)
def test_repair_state_rejects_boolean_and_equal_valued_float_numbers(
    field: str,
    malformed: object,
) -> None:
    with pytest.raises(ValueError):
        validate_repair_state(_repair_state(**{field: malformed}))


def test_persisted_repair_key_cannot_be_replaced_with_agent_authored_null() -> None:
    with pytest.raises(ValueError):
        initialize_repair_state(
            {
                "spec_authoring_mode": "proportional",
                "phase1_quality_repair": None,
            }
        )
