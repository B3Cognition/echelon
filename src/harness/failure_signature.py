"""Failure signature normalization and same-failure detection.

Per data-model FailureSignature:
  fingerprint = normalize(category + ":" + id + ":" + strip_stack_frames(lowercase(error)))

strip_stack_frames removes file paths and line numbers but retains
assertion messages and test identifiers.

Structured coverage gaps instead fingerprint complete case debt because their
human-readable error summary is truncated.

Per FR-LOOP-003a/b: detect when the same fingerprint appears N consecutive
times (default threshold=3).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import List, Set

from harness.coverage_contract import is_coverage_case_id


# Patterns for stripping stack frame details
_FILE_PATH_PATTERN = re.compile(
    r'(?:File\s+")?\b(?:/[\w./-]+|[A-Za-z]:\\[\w.\\-]+)'
    r'(?:\.py|\.js|\.ts|\.rs|\.go)'
    r'(?:", line \d+)?'
)
# Match line:col references like ":42", ":42:10" but only when preceded by
# a file-path-like context or at start of a word boundary (not mid-sentence numbers)
_LINE_NUMBER_PATTERN = re.compile(r'(?<=\.py|\.js|\.ts|\.rs|\.go):\d+(?::\d+)?')
_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_stack_frames(error: str) -> str:
    """Remove file paths and line numbers, retain assertion messages."""
    # Remove ANSI escape codes
    cleaned = _ANSI_ESCAPE.sub("", error)
    # Remove file paths (absolute and Windows-style)
    cleaned = _FILE_PATH_PATTERN.sub("", cleaned)
    # Remove standalone line numbers (e.g., ":42", ":42:10")
    cleaned = _LINE_NUMBER_PATTERN.sub("", cleaned)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize(category: str, test_id: str, error: str, *, details: object = None) -> str:
    """Compute a normalized failure fingerprint.

    Coverage uses complete case debt, not the truncated display summary.
    Other failures (and incomplete coverage details) retain legacy normalization.
    """
    if test_id == "coverage-observation-gaps" and isinstance(details, Mapping):
        cases = details.get("test_cases")
        if isinstance(cases, Mapping) and cases:
            debt = []
            for case_id, observation in cases.items():
                if (not isinstance(case_id, str) or not is_coverage_case_id(case_id)
                        or not isinstance(observation, Mapping)):
                    break
                test_type = observation.get("test_type")
                status = observation.get("status")
                if (not isinstance(test_type, str) or not test_type.strip()
                        or not isinstance(status, str) or not status.strip()):
                    break
                debt.append((case_id, test_type, status))
            else:
                # Reasons and receipt paths are diagnostic, not progress identity.
                payload = json.dumps(sorted(debt), separators=(",", ":"))
                digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                return f"{category}:{test_id}:case-debt:{digest}"
    error_normalized = _strip_stack_frames(error.lower())
    raw = f"{category}:{test_id}:{error_normalized}"
    return raw


def detect_same_failure(
    failure_lists: List[List[str]],
    threshold: int = 3,
) -> Set[str]:
    """Detect failure fingerprints that appear in N consecutive iterations.

    Args:
        failure_lists: List of fingerprint lists, one per iteration (ordered).
        threshold: Number of consecutive appearances to trigger detection.

    Returns:
        Set of fingerprints that appeared in `threshold` or more consecutive iterations.
    """
    if threshold < 1 or not failure_lists:
        return set()

    # Track consecutive appearance count per fingerprint
    # We need fingerprints that appear in `threshold` consecutive lists
    detected: Set[str] = set()

    # Get all unique fingerprints
    all_fps: Set[str] = set()
    for fp_list in failure_lists:
        all_fps.update(fp_list)

    for fp in all_fps:
        consecutive = 0
        for fp_list in failure_lists:
            if fp in fp_list:
                consecutive += 1
                if consecutive >= threshold:
                    detected.add(fp)
                    break
            else:
                consecutive = 0

    return detected
