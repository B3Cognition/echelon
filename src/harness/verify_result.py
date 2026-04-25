"""VerifyResult and FailureEntry dataclasses with validation.

VerifyResult represents the outcome of a verification pass (test suite,
typechecker, security scan). FailureEntry represents a single failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from harness.errors import SchemaViolationError


class FailureCategory(str, Enum):
    """Categories of verification failures."""
    TEST = "test"
    TYPECHECK = "typecheck"
    LINT = "lint"
    SECURITY = "security"
    BUILD = "build"
    PLAYWRIGHT_TEST = "playwright_test"
    OTHER = "other"


@dataclass
class FailureEntry:
    """A single failure from a verification pass."""
    category: FailureCategory
    id: str
    error: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FailureEntry:
        """Create FailureEntry from a dictionary."""
        if not isinstance(data, dict):
            raise SchemaViolationError(
                "FailureEntry data must be a dictionary",
                field="failures[]",
            )
        raw_category = str(data.get("category", "other"))
        try:
            category = FailureCategory(raw_category)
        except ValueError:
            raise SchemaViolationError(
                f"Invalid failure category '{raw_category}'. "
                f"Must be one of: {[c.value for c in FailureCategory]}",
                field="failures[].category",
            )
        return cls(
            category=category,
            id=str(data.get("id", "")),
            error=str(data.get("error", "")),
        )


@dataclass
class VerifyResult:
    """Result of a verification pass (test suite, typecheck, etc.)."""
    passed: bool
    failures: List[FailureEntry] = field(default_factory=list)
    duration_s: float = 0.0
    token_usage: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VerifyResult:
        """Create VerifyResult from a dictionary, validating schema."""
        if not isinstance(data, dict):
            raise SchemaViolationError(
                "VerifyResult data must be a dictionary",
                field="<root>",
            )

        if "passed" not in data:
            raise SchemaViolationError(
                "Missing required field 'passed'",
                field="passed",
            )

        failures_raw = data.get("failures", [])
        if not isinstance(failures_raw, list):
            raise SchemaViolationError(
                "Field 'failures' must be a list",
                field="failures",
            )

        failures = [FailureEntry.from_dict(f) for f in failures_raw]

        return cls(
            passed=bool(data["passed"]),
            failures=failures,
            duration_s=float(data.get("duration_s", 0.0)),
            token_usage=int(data.get("token_usage", 0)),
        )
