"""Common normalized evidence for harness-owned test observers."""

from __future__ import annotations

from dataclasses import dataclass
import re


class TestExecutionEvidenceError(ValueError):
    """Raised when structured execution evidence is unsafe or ambiguous."""

    __test__ = False


_ECHELON_CASE_TAG_MARKER = re.compile(r"\[echelon:", re.IGNORECASE)
_TERMINAL_ECHELON_CASE_TAG = re.compile(
    r"\[echelon:(?P<case_ids>[^\]]*)\]\s*$", re.IGNORECASE
)
_CASE_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")


@dataclass(frozen=True)
class ObservedTestExecution:
    """One normalized terminal result from a structured test reporter."""

    observer_id: str
    test_type: str
    file: str
    title: str
    project: str
    status: str
    retry_count: int
    error: str = ""


@dataclass(frozen=True)
class PhysicalTestIdentity:
    """The source test identity, excluding retry, shard, and browser project."""

    observer_id: str
    file: str
    title: str

    @classmethod
    def from_execution(cls, execution: ObservedTestExecution) -> "PhysicalTestIdentity":
        return cls(
            observer_id=execution.observer_id,
            file=execution.file,
            title=execution.title,
        )


def parse_echelon_case_tags(title: str) -> tuple[str, ...]:
    """Return ordered unique case IDs from one terminal Echelon title tag.

    The tag is deliberately required at the end so a runner cannot match a
    partial title whose description changes the exercised behavior.
    """
    if not isinstance(title, str):
        raise TestExecutionEvidenceError("test title must be a string")
    if _ECHELON_CASE_TAG_MARKER.search(title) is None:
        return ()

    match = _TERMINAL_ECHELON_CASE_TAG.search(title)
    if match is None:
        raise TestExecutionEvidenceError("Echelon case tag must end the test title")

    raw_case_ids = match.group("case_ids").strip()
    if not raw_case_ids:
        raise TestExecutionEvidenceError(
            "Echelon case tag must contain at least one case id"
        )

    case_ids: list[str] = []
    for raw_case_id in raw_case_ids.split(","):
        case_id = raw_case_id.strip()
        if not case_id:
            raise TestExecutionEvidenceError(
                "Echelon case tag has malformed comma-separated case ids"
            )
        if not _CASE_ID.fullmatch(case_id):
            raise TestExecutionEvidenceError(
                f"invalid Echelon case id: {case_id}"
            )
        if case_id not in case_ids:
            case_ids.append(case_id)
    return tuple(case_ids)
