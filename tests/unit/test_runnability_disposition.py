from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.runnability_evidence import RunnabilityStage, write_runnability_report
from harness.runnability_disposition import (
    RunnabilityDispositionError,
    defer_runnability,
    plan_runnability,
    read_runnability_disposition,
    read_runnability_history,
)


def _report(
    root: Path,
    *,
    status: str = "not_runnable",
    failure_class: str = "primary_journey_failed",
) -> Path:
    ref = write_runnability_report(
        evidence_dir=root / "evidence" / "user-runnability",
        spec_id="003-browser-game",
        target_id="sources/game",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        candidate_fingerprint="product-1",
        contract_hash="contract-1",
        stack_hash="stack-1",
        status=status,
        failure_class=failure_class if status != "runnable" else "",
        summary="The checkpoint journey did not persist." if status != "runnable" else "Passed.",
        stages=(
            RunnabilityStage(name="install", status="passed", exit_code=0),
            RunnabilityStage(name="primary_journey", status="failed", exit_code=1),
            RunnabilityStage(name="persistence", status="not_run"),
        )
        if status != "runnable"
        else (
            RunnabilityStage(name="install", status="passed", exit_code=0),
            RunnabilityStage(name="primary_journey", status="passed", exit_code=0),
            RunnabilityStage(name="persistence", status="passed", exit_code=0),
        ),
        required_stages=("install", "primary_journey", "persistence"),
        attempt_sequence=1,
        sensitive_environment={},
        user_commands={"start": ("pnpm start:local",)},
    )
    return ref.path.parent / "report.json"


@pytest.mark.unit
def test_defer_records_owner_reason_and_follow_up_without_erasing_history(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)

    deferred = defer_runnability(
        spec_dir=tmp_path,
        target="sources/game",
        reason="Local deployment is explicitly scheduled as a separate deliverable.",
        evidence_report=report,
        approved_at="2026-09-01T12:00:00+00:00",
    )
    planned = plan_runnability(
        tmp_path,
        planned_at="2026-09-01T13:00:00+00:00",
    )

    assert deferred.status == "deferred"
    assert deferred.target == "sources/game"
    assert planned.status == "planned"
    assert [event.status for event in read_runnability_history(tmp_path)] == [
        "deferred",
        "planned",
    ]
    assert read_runnability_disposition(tmp_path) == planned
    assert (tmp_path / "runnability-follow-up.md").is_file()


@pytest.mark.unit
def test_defer_requires_failed_current_evidence(tmp_path: Path) -> None:
    report = _report(tmp_path, status="runnable")

    with pytest.raises(RunnabilityDispositionError, match="failed.*report"):
        defer_runnability(
            spec_dir=tmp_path,
            target="sources/game",
            reason="Separate work approved.",
            evidence_report=report,
            approved_at="2026-09-01T12:00:00+00:00",
        )

    assert not (tmp_path / "runnability-disposition.json").exists()


@pytest.mark.unit
def test_defer_requires_non_empty_owner_reason_and_existing_report(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "report.json"

    with pytest.raises(RunnabilityDispositionError, match="non-empty reason"):
        defer_runnability(
            spec_dir=tmp_path,
            target="sources/game",
            reason="  ",
            evidence_report=missing,
        )
    with pytest.raises(RunnabilityDispositionError, match="report does not exist"):
        defer_runnability(
            spec_dir=tmp_path,
            target="sources/game",
            reason="Separate work approved.",
            evidence_report=missing,
        )


@pytest.mark.unit
def test_plan_requires_active_deferral_and_appends_instead_of_rewriting(
    tmp_path: Path,
) -> None:
    with pytest.raises(RunnabilityDispositionError, match="no active runnability deferral"):
        plan_runnability(tmp_path, planned_at="2026-09-01T13:00:00+00:00")

    report = _report(tmp_path)
    defer_runnability(
        spec_dir=tmp_path,
        target="sources/game",
        reason="Separate work approved.",
        evidence_report=report,
        approved_at="2026-09-01T12:00:00+00:00",
    )
    original = json.loads(
        (tmp_path / "runnability-disposition.json").read_text(encoding="utf-8")
    )

    plan_runnability(tmp_path, planned_at="2026-09-01T13:00:00+00:00")

    updated = json.loads(
        (tmp_path / "runnability-disposition.json").read_text(encoding="utf-8")
    )
    assert updated["events"][0] == original["events"][0]
    assert len(updated["events"]) == 2
    assert read_runnability_history(tmp_path)[0].reason == "Separate work approved."


@pytest.mark.unit
def test_follow_up_proposal_is_deterministic_and_advisory(tmp_path: Path) -> None:
    report = _report(tmp_path)

    disposition = defer_runnability(
        spec_dir=tmp_path,
        target="sources/game",
        reason="Separate work approved.",
        evidence_report=report,
        approved_at="2026-09-01T12:00:00+00:00",
    )
    proposal = (tmp_path / "runnability-follow-up.md").read_text(encoding="utf-8")

    assert disposition.follow_up_proposal == "runnability-follow-up.md"
    assert "# Make sources/game locally runnable" in proposal
    assert "primary_journey" in proposal
    assert "persistence" in proposal
    assert "primary_journey_failed" in proposal
    assert "stack-1" in proposal
    assert str(report.resolve()) in proposal
    assert (
        'echelon spec run "Make sources/game locally runnable" --target sources/game'
        in proposal
    )
    assert "advisory" in proposal.lower()
    assert not (tmp_path / "specs").exists()
