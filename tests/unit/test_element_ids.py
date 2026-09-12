"""Tests for shared numeric element ID formatting and ordering."""

from __future__ import annotations

import pytest

from codegen.decompose.task_queue import generate_task_ids
from kernel.element_ids import element_id_sort_key, format_element_id


@pytest.mark.parametrize(
    ("ordinal", "want"),
    [
        (1, "AC-000001"),
        (999999, "AC-999999"),
        (1000000, "AC-1000000"),
        (10000000, "AC-10000000"),
    ],
)
def test_format_grows_without_wrapping(ordinal: int, want: str) -> None:
    """A fixed output width must not wrap or reject growing ordinals."""
    assert format_element_id("AC", ordinal) == want


def test_task_id_generator_uses_six_digit_minimum() -> None:
    """A public producer must use the same minimum width as the formatter."""
    assert generate_task_ids(3) == ["T-000001", "T-000002", "T-000003"]


@pytest.mark.parametrize("prefix", ["FR", "NFR", "ISS", "U", "A", "T"])
def test_format_accepts_uppercase_alphabetic_prefixes(prefix: str) -> None:
    """Hard-coding only short prefixes would reject valid element families."""
    assert format_element_id(prefix, 42) == f"{prefix}-000042"


@pytest.mark.parametrize("prefix", ["", "fr", "FR1", "FR-", None, 7])
def test_format_rejects_invalid_prefixes(prefix: object) -> None:
    """Accepting non-uppercase alphabetic prefixes would create malformed labels."""
    with pytest.raises(ValueError, match="prefix"):
        format_element_id(prefix, 1)  # type: ignore[arg-type]


@pytest.mark.parametrize("ordinal", [True, False, 0, -1, 1.0, "1", None])
def test_format_rejects_non_positive_integer_ordinals(ordinal: object) -> None:
    """Boolean coercion and nonpositive values must not allocate numeric aliases."""
    with pytest.raises(ValueError, match="positive integer"):
        format_element_id("FR", ordinal)  # type: ignore[arg-type]


def test_numeric_order_retains_original_labels() -> None:
    """Lexicographic ordering must not place a million before 999999."""
    labels = ["FR-1000000", "FR-999999", "FR-001"]
    assert sorted(labels, key=element_id_sort_key) == [
        "FR-001",
        "FR-999999",
        "FR-1000000",
    ]


def test_numeric_order_keeps_padding_aliases_distinct() -> None:
    """Numeric comparison must not normalize distinct published text labels."""
    labels = ["FR-001", "FR-000001"]
    assert sorted(labels, key=element_id_sort_key) == ["FR-000001", "FR-001"]


def test_sort_key_has_deterministic_opaque_fallback() -> None:
    """Unsupported legacy labels must remain sortable without reinterpretation."""
    labels = ["legacy-z", "FR-composite-001", "legacy-a"]
    assert sorted(labels, key=element_id_sort_key) == [
        "FR-composite-001",
        "legacy-a",
        "legacy-z",
    ]
