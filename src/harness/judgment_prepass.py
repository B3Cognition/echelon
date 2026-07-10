"""Deterministic judgment pre-pass for verify-spec stage 5."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


FULFILLMENT_STATUSES = {
    "IMPLEMENTED",
    "PARTIAL",
    "UNVERIFIED",
    "MISSING",
    "DEVIATED",
    "OBSOLETE_SPEC",
}


@dataclass(frozen=True)
class JudgmentRow:
    id: str
    mechanical: bool
    proposed_status: str | None
    reason_code: str | None
    fallback_reason: str | None
    report_row: str | None

    @classmethod
    def mechanical_row(
        cls, item_id: str, proposed_status: str, reason_code: str
    ) -> "JudgmentRow":
        return cls(
            id=item_id,
            mechanical=True,
            proposed_status=proposed_status,
            reason_code=reason_code,
            fallback_reason=None,
            report_row=_mechanical_report_row(item_id, proposed_status, reason_code),
        )

    @classmethod
    def fallback_row(cls, item_id: str, fallback_reason: str) -> "JudgmentRow":
        return cls(
            id=item_id,
            mechanical=False,
            proposed_status=None,
            reason_code=None,
            fallback_reason=fallback_reason,
            report_row=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mechanical": self.mechanical,
            "proposed_status": self.proposed_status,
            "reason_code": self.reason_code,
            "fallback_reason": self.fallback_reason,
            "report_row": self.report_row,
        }


@dataclass(frozen=True)
class JudgmentPrepassResult:
    json_path: Path
    markdown_path: Path
    mechanical_count: int
    fallback_count: int


@dataclass(frozen=True)
class _ImplementationRow:
    id: str
    implementation_evidence: str
    test_evidence: str
    codegraph_evidence: str
    evidence_kind: str
    evidence_strength: str
    runtime_threshold: bool
    confidence: str
    notes: str


def build_judgment_prepass(
    *, spec_dir: Path, verify_run_dir: Path
) -> list[JudgmentRow]:
    del spec_dir
    inventory_ids = _inventory_ids(verify_run_dir / "canonical-requirements.json")
    implementation_rows = _implementation_rows(verify_run_dir / "implementation-map.md")
    by_id = {row.id: row for row in implementation_rows}

    results: list[JudgmentRow] = []
    for item_id in inventory_ids:
        row = by_id.get(item_id)
        if row is None:
            results.append(JudgmentRow.fallback_row(item_id, "missing_implementation_map_row"))
            continue
        results.append(_classify_row(row))
    return results


def write_judgment_prepass(
    *, spec_dir: Path, verify_run_dir: Path
) -> JudgmentPrepassResult:
    rows = build_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)
    payload = {
        "rows": [row.to_dict() for row in rows],
        "summary": {
            "mechanical_count": sum(1 for row in rows if row.mechanical),
            "fallback_count": sum(1 for row in rows if not row.mechanical),
            "fallback_ids": [row.id for row in rows if not row.mechanical],
        },
    }
    json_path = verify_run_dir / "judgment-prepass.json"
    markdown_path = verify_run_dir / "judgment-prepass.md"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(
        render_judgment_prepass_markdown(rows), encoding="utf-8"
    )
    return JudgmentPrepassResult(
        json_path=json_path,
        markdown_path=markdown_path,
        mechanical_count=payload["summary"]["mechanical_count"],
        fallback_count=payload["summary"]["fallback_count"],
    )


def render_judgment_prepass_markdown(rows: list[JudgmentRow]) -> str:
    lines = [
        "# Judgment Pre-Pass",
        "",
        "| ID | Mechanical | Proposed Status | Reason | Fallback Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.id} | {str(row.mechanical).lower()} | "
            f"{row.proposed_status or ''} | {row.reason_code or ''} | "
            f"{row.fallback_reason or ''} |"
        )
    return "\n".join(lines) + "\n"


def assemble_full_report(
    *,
    canonical_ids: list[str],
    mechanical_rows: dict[str, str],
    fallback_rows: dict[str, str],
    task_progress_row: str | None = None,
) -> str:
    lines = [
        "# Fulfillment Report",
        "",
        "| ID | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for item_id in canonical_ids:
        row = mechanical_rows.get(item_id) or fallback_rows.get(item_id)
        if row is None:
            raise ValueError(f"missing fulfillment row for {item_id}")
        lines.append(row)
    if task_progress_row:
        lines.append(task_progress_row)
    return "\n".join(lines) + "\n"


def assemble_fulfillment_report(
    *,
    canonical_inventory_path: Path,
    judgment_prepass_path: Path,
    fallback_report_path: Path,
    output_report_path: Path,
    state_path: Path | None = None,
) -> None:
    canonical_ids = _inventory_ids(canonical_inventory_path)
    scoped_ids = _scoped_ids(state_path) if state_path is not None else None
    if scoped_ids is not None:
        canonical_ids = [item_id for item_id in canonical_ids if item_id in scoped_ids]

    prepass_rows = _judgment_rows(judgment_prepass_path)
    mechanical_rows = {
        row.id: str(row.report_row)
        for row in prepass_rows
        if row.mechanical and row.report_row and row.id in canonical_ids
    }
    expected_fallback_ids = {
        row.id for row in prepass_rows if not row.mechanical and row.id in canonical_ids
    }
    fallback_rows = (
        _fallback_report_rows(
            fallback_report_path, expected_ids=expected_fallback_ids
        )
        if expected_fallback_ids
        else {}
    )
    task_progress_row = None if scoped_ids is not None else _task_progress_row(fallback_report_path)
    report = assemble_full_report(
        canonical_ids=canonical_ids,
        mechanical_rows=mechanical_rows,
        fallback_rows=fallback_rows,
        task_progress_row=task_progress_row,
    )
    output_report_path.write_text(report, encoding="utf-8")


def write_fallback_fulfillment_template(
    *,
    judgment_prepass_path: Path,
    output_path: Path,
    state_path: Path | None = None,
) -> list[str]:
    """Write a bounded fallback report template for SPEC-GUARD judgment."""
    scoped_ids = _scoped_ids(state_path) if state_path is not None else None
    fallback_ids = [
        row.id
        for row in _judgment_rows(judgment_prepass_path)
        if not row.mechanical and (scoped_ids is None or row.id in scoped_ids)
    ]
    lines = [
        "# Fallback Fulfillment Judgment",
        "",
        "Fill only `TODO_STATUS` and `TODO_EVIDENCE` cells for the listed IDs.",
        "Allowed status values: "
        + ", ".join(sorted(FULFILLMENT_STATUSES, key=_status_sort_key))
        + ".",
        "Do not add, remove, or reorder rows.",
        "",
        "| ID | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for item_id in fallback_ids:
        lines.append(f"| {item_id} | TODO_STATUS | TODO_EVIDENCE |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fallback_ids


def _classify_row(row: _ImplementationRow) -> JudgmentRow:
    if row.runtime_threshold and row.evidence_kind == "assertion_only":
        return JudgmentRow.mechanical_row(
            row.id, "UNVERIFIED", "threshold_assertion_only"
        )
    if (
        not row.implementation_evidence.strip()
        and not row.test_evidence.strip()
        and row.confidence == "none"
    ):
        return JudgmentRow.mechanical_row(row.id, "MISSING", "no_evidence")
    if _notes_require_judgment(row.notes):
        return JudgmentRow.fallback_row(row.id, "notes_require_judgment")
    if (
        not row.runtime_threshold
        and row.confidence == "high"
        and row.evidence_strength == "strong"
        and row.implementation_evidence.strip()
        and row.test_evidence.strip()
    ):
        return JudgmentRow.mechanical_row(
            row.id, "IMPLEMENTED", "source_and_test_strong"
        )
    return JudgmentRow.fallback_row(
        row.id, "confidence_or_semantics_require_judgment"
    )


def _notes_require_judgment(notes: str) -> bool:
    lowered = notes.lower()
    return any(
        token in lowered
        for token in ("partial", "ambiguous", "deviat", "obsolete", "missing acceptance")
    )


def _inventory_ids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("requirements", [])
    if not isinstance(rows, list):
        return []
    ids = [
        str(row.get("id", "")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    ]
    return ids


def _judgment_rows(path: Path) -> list[JudgmentRow]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        return []
    result: list[JudgmentRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("id", "")).strip()
        if not item_id:
            continue
        result.append(
            JudgmentRow(
                id=item_id,
                mechanical=bool(row.get("mechanical")),
                proposed_status=(
                    str(row.get("proposed_status")).strip()
                    if row.get("proposed_status") is not None
                    else None
                ),
                reason_code=(
                    str(row.get("reason_code")).strip()
                    if row.get("reason_code") is not None
                    else None
                ),
                fallback_reason=(
                    str(row.get("fallback_reason")).strip()
                    if row.get("fallback_reason") is not None
                    else None
                ),
                report_row=(
                    str(row.get("report_row"))
                    if row.get("report_row") is not None
                    else None
                ),
            )
        )
    return result


def _implementation_rows(path: Path) -> list[_ImplementationRow]:
    rows: list[_ImplementationRow] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 9 or cells[0] in {"ID", "---"}:
            continue
        rows.append(
            _ImplementationRow(
                id=cells[0],
                implementation_evidence=cells[1],
                test_evidence=cells[2],
                codegraph_evidence=cells[3],
                evidence_kind=cells[4],
                evidence_strength=cells[5],
                runtime_threshold=cells[6].lower() == "true",
                confidence=cells[7].lower(),
                notes=cells[8],
            )
        )
    return rows


def _fallback_report_rows(path: Path, *, expected_ids: set[str]) -> dict[str, str]:
    if not path.exists():
        return {}
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] in {"ID", "---", "Status"}:
            continue
        item_id = cells[0]
        if item_id == "TASK-PROGRESS":
            continue
        if item_id not in expected_ids:
            raise ValueError(f"unexpected fallback fulfillment row for {item_id}")
        if len(cells) >= 3 and (
            cells[1] == "TODO_STATUS" or cells[2] == "TODO_EVIDENCE"
        ):
            raise ValueError(f"unfilled fallback fulfillment row for {item_id}")
        if len(cells) < 3 or cells[1] not in FULFILLMENT_STATUSES:
            status = cells[1] if len(cells) > 1 else ""
            raise ValueError(
                f"invalid fallback fulfillment status for {item_id}: {status}"
            )
        if item_id in rows:
            raise ValueError(f"duplicate fallback fulfillment row for {item_id}")
        rows[item_id] = line
    return rows


def _task_progress_row(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and cells[0] == "TASK-PROGRESS":
            return line
    return None


def _scoped_ids(path: Path | None) -> set[str] | None:
    if path is None or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("verify_scope") != "scoped":
        return None
    raw_ids = data.get("scoped_ids", [])
    if not isinstance(raw_ids, list):
        return None
    return {str(item).strip() for item in raw_ids if str(item).strip()}


def _mechanical_report_row(item_id: str, status: str, reason_code: str) -> str:
    return f"| {item_id} | {status} | prepass:{reason_code} |"


def _status_sort_key(status: str) -> tuple[int, str]:
    order = {
        "IMPLEMENTED": 0,
        "PARTIAL": 1,
        "UNVERIFIED": 2,
        "MISSING": 3,
        "DEVIATED": 4,
        "OBSOLETE_SPEC": 5,
    }
    return (order.get(status, 99), status)
