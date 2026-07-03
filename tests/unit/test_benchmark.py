from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.benchmark import (
    BenchmarkRunRecord,
    list_fixtures,
    list_variants,
    plan_variant_commands,
    summarize_records,
    write_summary,
)


def test_lists_tiny_notes_fixture() -> None:
    fixtures = {fixture.id: fixture for fixture in list_fixtures()}

    fixture = fixtures["tiny-notes"]

    assert "notes" in fixture.prompt.lower()
    assert "local persistence" in fixture.prompt.lower()
    assert "automated test" in fixture.prompt.lower()


def test_lists_expected_variants() -> None:
    variants = {variant.id: variant for variant in list_variants()}

    assert list(variants) == [
        "baseline",
        "constitution",
        "constitution-tasks",
        "constitution-tasks-adrs",
    ]
    assert variants["constitution-tasks"].phases == (
        "phase-exp-constitution-quality",
        "phase-exp-tasks-quality",
    )


def test_plans_baseline_without_cleanse_phases() -> None:
    plan = plan_variant_commands("tiny-notes", "baseline")

    assert plan.fixture_id == "tiny-notes"
    assert plan.variant_id == "baseline"
    assert plan.phase_ids == ()
    assert plan.commands[0][:2] == ("echelon", "run")
    assert plan.commands[-1][:3] == ("echelon", "harness", "run")


def test_plans_constitution_tasks_adrs_with_ordered_phases() -> None:
    plan = plan_variant_commands("tiny-notes", "constitution-tasks-adrs")

    assert plan.phase_ids == (
        "phase-exp-constitution-quality",
        "phase-exp-tasks-quality",
        "phase-exp-adr-quality",
    )
    assert ("echelon", "phase", "run", "phase-exp-constitution-quality") in plan.commands
    assert ("echelon", "phase", "run", "phase-exp-tasks-quality") in plan.commands
    assert ("echelon", "phase", "run", "phase-exp-adr-quality") in plan.commands


def test_unknown_fixture_and_variant_fail_clearly() -> None:
    with pytest.raises(ValueError, match="Unknown benchmark fixture"):
        plan_variant_commands("missing", "baseline")

    with pytest.raises(ValueError, match="Unknown benchmark variant"):
        plan_variant_commands("tiny-notes", "missing")


def test_summarize_records_prefers_build_outcomes() -> None:
    records = [
        BenchmarkRunRecord(
            variant_id="baseline",
            status="complete",
            build_dispatches=8,
            retries=2,
            blocked_states=1,
            verification_failures=2,
            fulfillment_gaps=3,
            elapsed_seconds=600.0,
        ),
        BenchmarkRunRecord(
            variant_id="constitution-tasks",
            status="complete",
            build_dispatches=5,
            retries=0,
            blocked_states=0,
            verification_failures=0,
            fulfillment_gaps=1,
            elapsed_seconds=420.0,
        ),
    ]

    summary = summarize_records(records)

    assert summary["best_variant"] == "constitution-tasks"
    assert summary["variants"]["baseline"]["build_dispatches"] == 8
    assert summary["variants"]["constitution-tasks"]["fulfillment_gaps"] == 1


def test_write_summary_outputs_json_and_markdown(tmp_path: Path) -> None:
    records = [
        BenchmarkRunRecord(
            variant_id="baseline",
            status="complete",
            build_dispatches=8,
            retries=2,
            blocked_states=1,
            verification_failures=2,
            fulfillment_gaps=3,
            elapsed_seconds=600.0,
        )
    ]

    json_path, md_path = write_summary(tmp_path, records)

    assert json.loads(json_path.read_text(encoding="utf-8"))["best_variant"] == "baseline"
    assert "| baseline | complete | 8 | 2 | 1 | 2 | 3 | 600.0 |" in md_path.read_text(encoding="utf-8")
