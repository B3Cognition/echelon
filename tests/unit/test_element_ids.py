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


def test_format_handles_giant_ordinals_without_changing_global_guard() -> None:
    """Python's decimal conversion guard must not impose an ID ceiling."""
    import sys

    guard = sys.get_int_max_str_digits()
    assert format_element_id("AC", 10 ** 5000) == "AC-1" + "0" * 5000
    assert sys.get_int_max_str_digits() == guard


def test_giant_numeric_sorting_retains_padding_and_does_not_change_guard() -> None:
    """Large legacy labels must sort numerically without normalization."""
    import sys

    guard = sys.get_int_max_str_digits()
    lower = "FR-" + "9" * 5000
    padded_lower = "FR-0" + "9" * 5000
    higher = "FR-1" + "0" * 5000
    assert sorted([higher, lower, padded_lower], key=element_id_sort_key) == [padded_lower, lower, higher]
    assert sys.get_int_max_str_digits() == guard


def test_decimal_counter_helpers_allow_zero_and_preserve_legacy_digit_parsing() -> None:
    """Counters need zero, while existing numeric sorting accepts padded Unicode digits."""
    from kernel.element_ids import decimal_to_int, int_to_decimal

    assert int_to_decimal(0) == "0"
    assert decimal_to_int("0") == 0
    assert decimal_to_int("00042") == 42
    assert decimal_to_int("٠٠٤٢") == 42
    assert element_id_sort_key("FR-٠٠٤٢") == ("FR", 0, 42, "FR-٠٠٤٢")


@pytest.mark.parametrize("value", [True, -1, 1.5, "1", None])
def test_decimal_counter_format_rejects_invalid_values(value) -> None:
    """Counter formatting must never coerce bool, negative, or noninteger values."""
    from kernel.element_ids import int_to_decimal

    with pytest.raises(ValueError):
        int_to_decimal(value)


@pytest.mark.parametrize("value", ["", "-1", "+1", "1.0", " 1", "one", None, 1])
def test_decimal_counter_parse_rejects_nondecimal_values(value) -> None:
    """Malformed decimal counter input must not be silently coerced."""
    from kernel.element_ids import decimal_to_int

    with pytest.raises(ValueError):
        decimal_to_int(value)
