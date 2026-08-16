from __future__ import annotations

import pytest

from harness.run_summary_facts import (
    SummaryFact,
    SummaryFactCategory,
    SummaryFactImportance,
    build_summary_catalog,
    resolve_fact_ids,
    select_fallback_fact_ids,
)


def _fact(category, importance, text, order):
    return SummaryFact(category, importance, text, order)


def test_catalog_assigns_ids_after_priority_admission() -> None:
    catalog = build_summary_catalog(
        command="echelon spec run",
        task="Create a greeting.",
        status="done",
        facts=(
            _fact(
                SummaryFactCategory.WORK,
                SummaryFactImportance.NORMAL,
                "Prepared the greeting specification.",
                0,
            ),
            _fact(
                SummaryFactCategory.VERIFICATION,
                SummaryFactImportance.CRITICAL,
                "The specification checks passed.",
                1,
            ),
        ),
    )
    assert [(item.id, item.text) for item in catalog.entries] == [
        ("f0001", "The specification checks passed."),
        ("f0002", "Prepared the greeting specification."),
        ("f0003", "Echelon completed the requested specification work."),
    ]
    assert catalog.by_id["f0001"] is catalog.entries[0]


def test_catalog_adds_bounded_outcome_when_all_producer_facts_are_invalid() -> None:
    catalog = build_summary_catalog(
        command="echelon delivery continue",
        task="Deliver the greeting.",
        status="blocked",
        facts=(
            _fact(
                SummaryFactCategory.WORK,
                SummaryFactImportance.HIGH,
                "unsafe\x1b]0;title\x07.",
                0,
            ),
        ),
    )
    assert [item.category for item in catalog.entries] == [
        SummaryFactCategory.OUTCOME
    ]
    assert catalog.entries[0].text == (
        "Echelon worked on the requested delivery, but it is not complete."
    )


def test_catalog_is_bounded_and_retains_late_critical_fact() -> None:
    facts = tuple(
        _fact(
            SummaryFactCategory.WORK,
            SummaryFactImportance.NORMAL,
            f"Recorded material work item {index} with {'detail ' * 35}complete.",
            index,
        )
        for index in range(100)
    ) + (
        _fact(
            SummaryFactCategory.VERIFICATION,
            SummaryFactImportance.CRITICAL,
            "The authoritative verification passed.",
            100,
        ),
    )
    catalog = build_summary_catalog(
        command="echelon delivery run 014",
        task="Deliver the greeting.",
        status="done",
        facts=facts,
    )
    assert len(catalog.packet_json.encode("utf-8")) <= 12_288
    assert any(
        item.text == "The authoritative verification passed."
        for item in catalog.entries
    )
    assert [item.id for item in catalog.entries] == [
        f"f{index:04d}" for index in range(1, len(catalog.entries) + 1)
    ]


def test_fallback_prefers_importance_then_category_diversity() -> None:
    catalog = build_summary_catalog(
        command="echelon delivery run 014",
        task="Deliver the greeting.",
        status="blocked",
        facts=(
            _fact(
                SummaryFactCategory.WORK,
                SummaryFactImportance.CRITICAL,
                "Implemented the greeting utility.",
                0,
            ),
            _fact(
                SummaryFactCategory.WORK,
                SummaryFactImportance.HIGH,
                "Added its command entry point.",
                1,
            ),
            _fact(
                SummaryFactCategory.VERIFICATION,
                SummaryFactImportance.HIGH,
                "The focused tests passed.",
                2,
            ),
            _fact(
                SummaryFactCategory.BLOCKER,
                SummaryFactImportance.HIGH,
                "Delivery stopped at the review checkpoint.",
                3,
            ),
        ),
    )
    selected = select_fallback_fact_ids(catalog)
    assert resolve_fact_ids(catalog, selected) == (
        "Implemented the greeting utility.",
        "The focused tests passed.",
        "Delivery stopped at the review checkpoint.",
    )


def test_fallback_returns_the_only_fact_and_honors_mandatory_budget() -> None:
    catalog = build_summary_catalog(
        command="echelon spec run",
        task="Create a greeting.",
        status="done",
        facts=(),
    )
    assert resolve_fact_ids(catalog, select_fallback_fact_ids(catalog)) == (
        "Echelon completed the requested specification work.",
    )
    assert select_fallback_fact_ids(
        catalog,
        mandatory_lines=("x" * 1_190,),
    ) == ()


@pytest.mark.parametrize("selected", [("missing",), ("f0001", "f0001")])
def test_resolve_fact_ids_rejects_unknown_or_duplicate_ids(selected) -> None:
    catalog = build_summary_catalog(
        command="echelon spec run",
        task="Create a greeting.",
        status="done",
        facts=(),
    )
    with pytest.raises(ValueError):
        resolve_fact_ids(catalog, selected)
