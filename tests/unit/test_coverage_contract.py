"""Tests for typed planned coverage obligations."""

from __future__ import annotations

import pytest

from harness.coverage_contract import (
    CoverageContractError,
    parse_coverage_obligations,
)


def test_invalid_coverage_map_identifies_row_and_requirement(tmp_path):
    from harness.coverage_evidence import parse_coverage_map_obligations

    path = tmp_path / "coverage-map.md"
    path.write_text(
        "# Coverage\n"
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| AC-003 | UT-VIS-001, E2E-VIS-001, E2E-VIS-002 | unit/e2e | planned | planned | tests | implement |\n"
    )
    with pytest.raises(CoverageContractError, match=r"line 4.*AC-003.*cardinality"):
        parse_coverage_map_obligations(path, {"AC-003"})

@pytest.mark.parametrize("case_id", [
    "C-HTTP-001..N", "E-VIS-001..004", "UT-001–004", "UT-001...",
    "TBD", "test one", "ut-001", "UT_001", "UT--001", "`UT-001`",
])
def test_planning_rejects_case_ids_that_cannot_be_bound(case_id: str) -> None:
    with pytest.raises(CoverageContractError, match="explicit.*case ID"):
        parse_coverage_obligations(
            "FR-001", case_id, "unit", "automated", "automated",
            "assert actual outcome", "implement", {"FR-001"},
        )


@pytest.mark.unit
def test_parse_coverage_obligations_expands_coupled_requirements_and_types() -> None:
    obligations = parse_coverage_obligations(
        "AC-001 / FR-001",
        "UT-001; E2E-001",
        "unit/e2e",
        "deferred-automation",
        "deferred-automation",
        "oracle",
        "repair",
        {"AC-001", "FR-001"},
    )

    assert {
        (item.requirement_id, item.test_case_id, item.test_type)
        for item in obligations
    } == {
        ("AC-001", "UT-001", "unit"),
        ("AC-001", "E2E-001", "e2e"),
        ("FR-001", "UT-001", "unit"),
        ("FR-001", "E2E-001", "e2e"),
    }


@pytest.mark.unit
def test_parse_coverage_obligations_applies_one_type_to_each_case() -> None:
    obligations = parse_coverage_obligations(
        "FR-001",
        "UT-001, UT-002",
        "unit",
        "automated",
        "automated",
        "tests/unit/inventory.test.ts",
        "",
        {"FR-001"},
    )

    assert [item.test_type for item in obligations] == ["unit", "unit"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("test_cases", "test_types", "message"),
    [
        ("UT-001 / E2E-001", "unit/e2e/contract", "type/case cardinality"),
        ("UT-001", "UNIT", "invalid coverage test type"),
        ("UT-001 / UT-001", "unit/e2e", "incompatible coverage test types"),
    ],
)
def test_parse_coverage_obligations_rejects_ambiguous_test_type_contracts(
    test_cases: str,
    test_types: str,
    message: str,
) -> None:
    with pytest.raises(CoverageContractError, match=message):
        parse_coverage_obligations(
            "FR-001",
            test_cases,
            test_types,
            "automated",
            "automated",
            "oracle",
            "repair",
            {"FR-001"},
        )


@pytest.mark.unit
def test_parse_coverage_obligations_ignores_noncanonical_requirements() -> None:
    assert (
        parse_coverage_obligations(
            "FR-999",
            "UT-001",
            "unit",
            "automated",
            "automated",
            "oracle",
            "repair",
            {"FR-001"},
        )
        == ()
    )
