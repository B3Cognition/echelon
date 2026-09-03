"""Deterministic coverage-map evidence for fulfillment decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Iterable

from kernel.task_contract import parse_task_rows


_REQUIRED_HEADERS = (
    "Requirement ID",
    "Test Case ID",
    "Test Type",
    "Automation Status",
    "Coverage Type",
    "Evidence",
    "Gap / Action",
)
_DECLARED_STATUSES = frozenset(
    {"automated", "deferred-automation", "escalate"}
)
_RANGE_RE = re.compile(
    r"^(?P<prefix>[A-Z][A-Z0-9_]*)-(?P<start>\d+)\s*[–—]\s*"
    r"(?:(?P=prefix)-)?(?P<end>\d+)$"
)


@dataclass(frozen=True)
class CoverageEvidenceRow:
    requirement_ids: tuple[str, ...]
    test_case_ids: tuple[str, ...]
    test_type: str
    automation_status: str
    coverage_type: str
    evidence: str
    gap_action: str


@dataclass(frozen=True)
class RequirementCoverageEvidence:
    requirement_id: str
    status: str
    test_case_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class CoverageEvidenceResult:
    by_requirement: dict[str, RequirementCoverageEvidence]
    rows: tuple[CoverageEvidenceRow, ...]
    task_integrity_gaps: tuple["CoverageTaskIntegrityGap", ...] = ()
    json_path: Path | None = None
    markdown_path: Path | None = None


@dataclass(frozen=True)
class CoverageTaskIntegrityGap:
    task_id: str
    requirement_ids: tuple[str, ...]
    statuses: tuple[str, ...]
    test_case_ids: tuple[str, ...]


def build_coverage_evidence(
    *,
    spec_dir: Path,
    canonical_ids: Iterable[str],
    deferred_ids: set[str],
) -> CoverageEvidenceResult:
    """Parse and classify the existing coverage map for canonical IDs."""
    canonical = tuple(dict.fromkeys(str(item).strip() for item in canonical_ids))
    canonical_set = {item for item in canonical if item}
    path = Path(spec_dir) / "coverage-map.md"
    rows = _parse_rows(path, canonical_set) if path.is_file() else ()
    by_id: dict[str, list[CoverageEvidenceRow]] = {
        item: [] for item in canonical if item
    }
    for row in rows:
        for requirement_id in row.requirement_ids:
            if requirement_id in by_id:
                by_id[requirement_id].append(row)

    classified = {
        requirement_id: _classify_requirement(
            requirement_id,
            by_id[requirement_id],
            owner_deferred=requirement_id in deferred_ids,
        )
        for requirement_id in by_id
    }
    task_gaps = _task_integrity_gaps(Path(spec_dir), classified)
    return CoverageEvidenceResult(
        by_requirement=classified,
        rows=rows,
        task_integrity_gaps=task_gaps,
    )


def write_coverage_evidence(
    *,
    spec_dir: Path,
    verify_run_dir: Path,
    canonical_ids: Iterable[str],
    deferred_ids: set[str],
) -> CoverageEvidenceResult:
    result = build_coverage_evidence(
        spec_dir=spec_dir,
        canonical_ids=canonical_ids,
        deferred_ids=deferred_ids,
    )
    root = Path(verify_run_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "coverage-evidence.json"
    markdown_path = root / "coverage-evidence.md"
    payload = {
        "schema_version": 1,
        "requirements": {
            item_id: asdict(row)
            for item_id, row in sorted(result.by_requirement.items())
        },
        "task_integrity_gaps": [
            asdict(gap) for gap in result.task_integrity_gaps
        ],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    return CoverageEvidenceResult(
        by_requirement=result.by_requirement,
        rows=result.rows,
        task_integrity_gaps=result.task_integrity_gaps,
        json_path=json_path,
        markdown_path=markdown_path,
    )


def _parse_rows(
    path: Path,
    canonical_ids: set[str],
) -> tuple[CoverageEvidenceRow, ...]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[CoverageEvidenceRow] = []
    active = False
    for line in lines:
        cells = _table_cells(line)
        if cells == list(_REQUIRED_HEADERS):
            active = True
            continue
        if not active:
            continue
        if not cells:
            active = False
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if len(cells) != len(_REQUIRED_HEADERS):
            active = False
            continue
        requirement_ids = _requirement_ids(cells[0], canonical_ids)
        if not requirement_ids:
            continue
        rows.append(
            CoverageEvidenceRow(
                requirement_ids=requirement_ids,
                test_case_ids=_test_case_ids(cells[1]),
                test_type=cells[2].strip().lower(),
                automation_status=cells[3].strip().lower(),
                coverage_type=cells[4].strip().lower(),
                evidence=cells[5].strip(),
                gap_action=cells[6].strip(),
            )
        )
    return tuple(rows)


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _requirement_ids(value: str, canonical_ids: set[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for raw in re.split(r"\s*,\s*", value.strip()):
        token = raw.strip()
        match = _RANGE_RE.fullmatch(token)
        if match is None:
            if token in canonical_ids:
                selected.append(token)
            continue
        prefix = match.group("prefix")
        start_text = match.group("start")
        end_text = match.group("end")
        start = int(start_text)
        end = int(end_text)
        width = max(len(start_text), len(end_text))
        if end < start or end - start > 10_000:
            continue
        selected.extend(
            item
            for number in range(start, end + 1)
            if (item := f"{prefix}-{number:0{width}d}") in canonical_ids
        )
    return tuple(dict.fromkeys(selected))


def _test_case_ids(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            token.strip()
            for token in re.split(r"\s*(?:/|,)\s*", value)
            if token.strip()
        )
    )


def _classify_requirement(
    requirement_id: str,
    rows: list[CoverageEvidenceRow],
    *,
    owner_deferred: bool,
) -> RequirementCoverageEvidence:
    test_ids = tuple(
        dict.fromkeys(test_id for row in rows for test_id in row.test_case_ids)
    )
    if owner_deferred:
        return RequirementCoverageEvidence(
            requirement_id=requirement_id,
            status="owner_deferred",
            test_case_ids=test_ids,
            reason="active owner-controlled deferred scope",
        )
    if not rows:
        return RequirementCoverageEvidence(
            requirement_id=requirement_id,
            status="missing",
            test_case_ids=(),
            reason="no coverage-map row",
        )
    if any(
        row.automation_status not in _DECLARED_STATUSES
        or row.coverage_type not in _DECLARED_STATUSES
        or row.automation_status != row.coverage_type
        for row in rows
    ):
        status = "contradictory"
        reason = "automation and coverage statuses are invalid or disagree"
    elif any(row.automation_status == "escalate" for row in rows):
        status = "escalated"
        reason = "coverage map requires escalation"
    elif any(row.automation_status == "deferred-automation" for row in rows):
        status = "deferred"
        reason = "required automation remains deferred"
    elif any(not row.evidence for row in rows):
        status = "contradictory"
        reason = "automated coverage has no evidence"
    else:
        status = "automated"
        reason = "all declared coverage is automated and evidence-linked"
    return RequirementCoverageEvidence(
        requirement_id=requirement_id,
        status=status,
        test_case_ids=test_ids,
        reason=reason,
    )


def _task_integrity_gaps(
    spec_dir: Path,
    by_requirement: dict[str, RequirementCoverageEvidence],
) -> tuple[CoverageTaskIntegrityGap, ...]:
    tasks_path = spec_dir / "tasks.md"
    if not tasks_path.is_file():
        return ()
    gaps: list[CoverageTaskIntegrityGap] = []
    tasks = parse_task_rows(
        tasks_path.read_text(encoding="utf-8", errors="replace")
    )
    for task in tasks:
        if task.status.strip().lower() != "x":
            continue
        requirement_ids = tuple(
            requirement_id
            for requirement_id in task.requirements
            if requirement_id in by_requirement
            and by_requirement[requirement_id].status
            not in {"automated", "owner_deferred"}
        )
        if not requirement_ids:
            continue
        gaps.append(
            CoverageTaskIntegrityGap(
                task_id=task.task_id,
                requirement_ids=requirement_ids,
                statuses=tuple(
                    f"{requirement_id}={by_requirement[requirement_id].status}"
                    for requirement_id in requirement_ids
                ),
                test_case_ids=tuple(
                    dict.fromkeys(
                        test_case_id
                        for requirement_id in requirement_ids
                        for test_case_id in by_requirement[
                            requirement_id
                        ].test_case_ids
                    )
                ),
            )
        )
    return tuple(gaps)


def _render_markdown(result: CoverageEvidenceResult) -> str:
    lines = [
        "# Coverage Evidence",
        "",
        "| Requirement ID | Status | Test Case IDs | Reason |",
        "|---|---|---|---|",
    ]
    for requirement_id, row in sorted(result.by_requirement.items()):
        lines.append(
            f"| {requirement_id} | {row.status} | "
            f"{', '.join(row.test_case_ids)} | {row.reason} |"
        )
    lines.extend(["", "## Completed Task Integrity Gaps", ""])
    if not result.task_integrity_gaps:
        lines.append("None.")
    else:
        for gap in result.task_integrity_gaps:
            lines.append(
                f"- {gap.task_id}: {', '.join(gap.statuses)}; tests: "
                f"{', '.join(gap.test_case_ids) or 'none declared'}"
            )
    return "\n".join(lines) + "\n"
