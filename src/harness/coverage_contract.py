"""Typed planning obligations derived from a coverage-map row."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


class CoverageContractError(ValueError):
    """Raised when a planning coverage row is syntactically ambiguous."""


_RANGE_RE = re.compile(
    r"^(?P<prefix>[A-Z][A-Z0-9_]*)-(?P<start>\d+)\s*[–—]\s*"
    r"(?:(?P=prefix)-)?(?P<end>\d+)$"
)
_TEST_TYPE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DELIMITER_RE = re.compile(r"\s*(?:,|/|;)\s*")
_REQUIREMENT_DELIMITER_RE = re.compile(r"\s*(?:,|/)\s*")


@dataclass(frozen=True)
class CoverageObligation:
    """One canonical requirement's planned logical test obligation."""

    requirement_id: str
    test_case_id: str
    test_type: str
    automation_status: str
    coverage_status: str
    evidence: str
    gap_action: str


def parse_coverage_obligations(
    requirement_cell: str,
    test_case_cell: str,
    test_type_cell: str,
    automation_status: str,
    coverage_status: str,
    evidence: str,
    gap_action: str,
    canonical_ids: Iterable[str],
) -> tuple[CoverageObligation, ...]:
    """Parse one coverage-map row into canonical typed test obligations."""
    canonical = {
        str(item).strip() for item in canonical_ids if str(item).strip()
    }
    requirement_ids = _canonical_requirement_ids(requirement_cell, canonical)
    if not requirement_ids:
        return ()

    test_case_ids = _split_non_empty(test_case_cell, field_name="test case")
    test_types = _split_non_empty(test_type_cell, field_name="test type")
    for test_type in test_types:
        if not _TEST_TYPE.fullmatch(test_type):
            raise CoverageContractError(f"invalid coverage test type: {test_type}")
    if len(test_types) == 1:
        assigned_types = tuple(test_types[0] for _ in test_case_ids)
    elif len(test_types) == len(test_case_ids):
        assigned_types = test_types
    else:
        raise CoverageContractError(
            "coverage test type/case cardinality must be one or match case count"
        )

    case_types: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    for test_case_id, test_type in zip(test_case_ids, assigned_types, strict=True):
        prior = case_types.get(test_case_id)
        if prior is not None and prior != test_type:
            raise CoverageContractError(
                f"incompatible coverage test types for {test_case_id}: "
                f"{prior} and {test_type}"
            )
        if prior is None:
            case_types[test_case_id] = test_type
            pairs.append((test_case_id, test_type))

    normalized_automation = str(automation_status).strip().lower()
    normalized_coverage = str(coverage_status).strip().lower()
    normalized_evidence = str(evidence).strip()
    normalized_gap_action = str(gap_action).strip()
    return tuple(
        CoverageObligation(
            requirement_id=requirement_id,
            test_case_id=test_case_id,
            test_type=test_type,
            automation_status=normalized_automation,
            coverage_status=normalized_coverage,
            evidence=normalized_evidence,
            gap_action=normalized_gap_action,
        )
        for requirement_id in requirement_ids
        for test_case_id, test_type in pairs
    )


def _canonical_requirement_ids(value: str, canonical_ids: set[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for raw in _REQUIREMENT_DELIMITER_RE.split(str(value).strip()):
        token = raw.strip()
        range_match = _RANGE_RE.fullmatch(token)
        if range_match is None:
            if token in canonical_ids and token not in selected:
                selected.append(token)
            continue
        prefix = range_match.group("prefix")
        start_text = range_match.group("start")
        end_text = range_match.group("end")
        start = int(start_text)
        end = int(end_text)
        if end < start or end - start > 10_000:
            continue
        width = max(len(start_text), len(end_text))
        for number in range(start, end + 1):
            requirement_id = f"{prefix}-{number:0{width}d}"
            if requirement_id in canonical_ids and requirement_id not in selected:
                selected.append(requirement_id)
    return tuple(selected)


def _split_non_empty(value: str, *, field_name: str) -> tuple[str, ...]:
    tokens = tuple(token.strip() for token in _DELIMITER_RE.split(str(value).strip()))
    if not tokens or any(not token for token in tokens):
        raise CoverageContractError(
            f"coverage row must declare at least one {field_name}"
        )
    return tokens
