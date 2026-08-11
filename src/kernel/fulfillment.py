"""Fulfillment verification helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from harness.deferred_scope import active_entries

NON_STRICT_BLOCKING = {"MISSING", "PARTIAL", "DEVIATED"}
STRICT_BLOCKING = NON_STRICT_BLOCKING | {"UNVERIFIED"}
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)
_TABLE_ITEM_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9_.:]+)*$")
DEFERRED_SCOPE = "DEFERRED_SCOPE"
_KNOWN_STATUSES = STRICT_BLOCKING | {"IMPLEMENTED", "OBSOLETE_SPEC", DEFERRED_SCOPE}


@dataclass(frozen=True)
class FulfillmentArtifactValidation:
    """Result of comparing verify-spec requirement and judgment row IDs."""

    ok: bool
    audit_count: int
    report_count: int
    missing_in_report: tuple[str, ...]
    extra_in_report: tuple[str, ...]
    summary_count_mismatches: tuple[str, ...] = ()


@dataclass(frozen=True)
class FulfillmentGap:
    """One normalized blocking requirement judgment."""

    requirement_id: str
    status: str
    summary: str
    recommended_action: str


def blocking_statuses(strict: bool = False) -> set[str]:
    """Return statuses that should block fulfillment completion."""
    return set(STRICT_BLOCKING if strict else NON_STRICT_BLOCKING)


def make_verify_spec_run_dir(
    project_root: Path,
    spec_id: str,
    timestamp: str | None = None,
) -> Path:
    """Return the runtime directory for a spec fulfillment verification run."""
    runs = project_root / "runs"
    current = runs / ".current"
    if current.exists():
        run_id = current.read_text().strip()
        active = runs / run_id
        if run_id and active.exists():
            return active / "verify-spec" / spec_id

    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    return runs / f"verify-spec-{spec_id}-{stamp}"


def latest_fulfillment_report(spec_dir: Path) -> Path | None:
    """Return the newest fulfillment-report*.md in a spec directory."""
    reports = sorted(
        spec_dir.glob("fulfillment-report*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


def _statuses_in_report(report_path: Path) -> set[str]:
    text = report_path.read_text()
    statuses: set[str] = set()
    requirement_id = re.compile(
        r"^(?:FR|AC|US|NFR|REQ|EDGE|SC|CONSTRAINT)[A-Za-z0-9_.:-]*$"
    )
    summary_count = re.compile(
        r"\b(?P<status>MISSING|PARTIAL|DEVIATED|UNVERIFIED|DEFERRED_SCOPE)\s*(?::|=)?\s*(?P<count>\d+)\b"
    )

    for line in text.splitlines():
        if "|" not in line:
            for match in summary_count.finditer(line):
                if int(match.group("count")) > 0:
                    statuses.add(match.group("status"))
            continue

        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] in STRICT_BLOCKING:
            count_match = re.search(r"\d+", cells[1])
            if count_match and int(count_match.group(0)) > 0:
                statuses.add(cells[0])
        if len(cells) >= 2 and requirement_id.match(cells[0]):
            for cell in cells[1:3]:
                if cell in _KNOWN_STATUSES:
                    statuses.add(cell)

    return statuses


def fulfillment_has_blocking_gaps(report_path: Path, strict: bool = False) -> bool:
    """Return True when a fulfillment report contains unresolved gap statuses."""
    if not report_path.exists():
        return False
    return bool(_statuses_in_report(report_path) & blocking_statuses(strict))


def blocking_fulfillment_gaps(
    report_path: Path,
    *,
    strict: bool = False,
    gaps_path: Path | None = None,
) -> tuple[FulfillmentGap, ...]:
    """Return deterministic per-requirement blocking judgments from a report."""
    if not report_path.exists():
        return ()

    allowed = blocking_statuses(strict)
    recommendation = _fulfillment_gap_recommendation(gaps_path)
    rows: list[FulfillmentGap] = []
    for line in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = _table_cells(line)
        if cells is None or len(cells) < 2:
            continue
        requirement_id = cells[0]
        status = cells[1].upper()
        if not _TABLE_ITEM_ID_RE.match(requirement_id) or status not in allowed:
            continue
        summary = cells[2].strip() if len(cells) >= 3 else ""
        rows.append(
            FulfillmentGap(
                requirement_id=requirement_id,
                status=status,
                summary=summary or "No fulfillment evidence was recorded.",
                recommended_action=recommendation,
            )
        )
    return tuple(sorted(rows, key=lambda row: row.requirement_id))


def _fulfillment_gap_recommendation(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"(?ims)^recommended action\s*:\s*(.+?)(?=^\s*$|^##\s|\Z)",
        text,
    )
    if match is None:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def apply_deferred_scope_to_report(report_path: Path, spec_dir: Path) -> tuple[str, ...]:
    """Overlay active, explicitly deferred requirement IDs onto a report."""
    entries_by_id = {
        item_id: entry
        for entry in active_entries(spec_dir)
        for item_id in entry.selected_ids
        if not item_id.startswith("T-")
    }
    if not entries_by_id:
        return ()
    changed: list[str] = []
    lines: list[str] = []
    for line in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = _table_cells(line)
        if cells is None or len(cells) < 3:
            lines.append(line)
            continue
        entry = entries_by_id.get(cells[0])
        if entry is None:
            lines.append(line)
            continue
        cells[1] = DEFERRED_SCOPE
        cells[2] = f"defer:{entry.entry_id}: {_escape_table_cell(entry.reason)}"
        lines.append("| " + " | ".join(cells) + " |")
        changed.append(cells[0])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tuple(changed)


def validate_deferred_scope_rows(report_path: Path, spec_dir: Path) -> list[str]:
    """Return deferred rows that lack an active, correctly cited ledger entry."""
    entries_by_id = {
        item_id: entry
        for entry in active_entries(spec_dir)
        for item_id in entry.selected_ids
        if not item_id.startswith("T-")
    }
    issues: list[str] = []
    for line in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = _table_cells(line)
        if cells is None or len(cells) < 2 or cells[1] != DEFERRED_SCOPE:
            continue
        entry = entries_by_id.get(cells[0])
        if entry is None:
            issues.append(f"{cells[0]} has no active defer entry")
            continue
        evidence = cells[2] if len(cells) >= 3 else ""
        expected = f"defer:{entry.entry_id}: {_escape_table_cell(entry.reason)}"
        if evidence != expected:
            issues.append(
                f"{cells[0]} does not cite active defer entry {entry.entry_id}"
            )
    return issues


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped.strip("|"))]
    if not cells or cells[0] in {"ID", "Requirement", "Status"}:
        return None
    if set(cells[0]) <= {"-", ":"}:
        return None
    return cells


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|")


def read_fulfillment_metadata(report_path: Path) -> dict[str, Any]:
    """Return YAML frontmatter metadata from a fulfillment report."""
    if not report_path.exists():
        return {}
    text = report_path.read_text(encoding="utf-8", errors="replace")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def stamp_fulfillment_report(
    report_path: Path,
    *,
    spec_id: str,
    commit: str,
    run_id: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Record deterministic verification provenance in a fulfillment report."""
    text = report_path.read_text(encoding="utf-8", errors="replace")
    match = _FRONTMATTER_RE.match(text)
    body = text[match.end():] if match else text
    metadata = read_fulfillment_metadata(report_path)
    metadata.update(
        {
            "spec_id": spec_id,
            "verified_commit": commit,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if extra_metadata:
        metadata.update(extra_metadata)
    if run_id:
        metadata["verify_run_id"] = run_id
    import yaml

    frontmatter = yaml.dump(
        metadata,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()
    report_path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")


def fulfillment_report_is_current(report_path: Path, *, current_commit: str) -> bool:
    """Return True when a report was generated for the current code commit."""
    metadata = read_fulfillment_metadata(report_path)
    verified_commit = metadata.get("verified_commit")
    return isinstance(verified_commit, str) and verified_commit == current_commit


def fulfillment_table_ids(markdown: str) -> set[str]:
    """Extract first-column item IDs from markdown fulfillment-style tables."""
    ids: set[str] = set()
    table_contains_item_ids = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            table_contains_item_ids = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if set(cells[0]) <= {"-", ":"}:
            continue
        if cells[0] in {"ID", "Requirement"}:
            table_contains_item_ids = True
            continue
        if cells[0] in {"Status", "Category", "Metric"}:
            table_contains_item_ids = False
            continue
        if not table_contains_item_ids:
            continue
        item_id = cells[0]
        if _TABLE_ITEM_ID_RE.match(item_id):
            ids.add(item_id)
    return ids


def _summary_status_counts(markdown: str) -> dict[str, set[int]]:
    counts: dict[str, set[int]] = {status: set() for status in _KNOWN_STATUSES}
    inline_count = re.compile(
        r"\b(?P<status>IMPLEMENTED|PARTIAL|UNVERIFIED|MISSING|DEVIATED|OBSOLETE_SPEC|DEFERRED_SCOPE)"
        r"\s*(?::|=)?\s*(?P<count>\d+)\b"
    )

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] in _KNOWN_STATUSES:
                count_match = re.search(r"\d+", cells[1])
                if count_match:
                    counts[cells[0]].add(int(count_match.group(0)))
            continue
        for match in inline_count.finditer(stripped):
            counts[match.group("status")].add(int(match.group("count")))

    return {status: values for status, values in counts.items() if values}


def _requirement_status_counts(markdown: str) -> dict[str, int]:
    counts = {status: 0 for status in _KNOWN_STATUSES}
    table_contains_item_ids = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            table_contains_item_ids = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if set(cells[0]) <= {"-", ":"}:
            continue
        if cells[0] in {"ID", "Requirement"}:
            table_contains_item_ids = True
            continue
        if cells[0] in {"Status", "Category", "Metric"}:
            table_contains_item_ids = False
            continue
        if not table_contains_item_ids:
            continue
        item_id = cells[0]
        if item_id == "TASK-PROGRESS" or not _TABLE_ITEM_ID_RE.match(item_id):
            continue
        for cell in cells[1:4]:
            if cell in _KNOWN_STATUSES:
                counts[cell] += 1
                break
    return counts


def _summary_count_mismatches(markdown: str) -> tuple[str, ...]:
    reported = _summary_status_counts(markdown)
    observed = _requirement_status_counts(markdown)
    mismatches: list[str] = []
    for status in sorted(reported):
        row_count = observed.get(status, 0)
        for count in sorted(reported[status]):
            if count != row_count:
                mismatches.append(
                    f"{status} reported {count} but requirement rows contain {row_count}"
                )
    return tuple(mismatches)


def validate_fulfillment_artifacts(
    *,
    requirement_audit_path: Path,
    fulfillment_report_path: Path,
    canonical_inventory_path: Path | None = None,
) -> FulfillmentArtifactValidation:
    """Validate that SPEC-GUARD judged exactly the audited requirement IDs."""
    audit_ids = (
        _canonical_inventory_ids(canonical_inventory_path)
        if canonical_inventory_path is not None and canonical_inventory_path.is_file()
        else fulfillment_table_ids(
            requirement_audit_path.read_text(encoding="utf-8", errors="replace")
        )
    )
    report_ids = fulfillment_table_ids(
        fulfillment_report_path.read_text(encoding="utf-8", errors="replace")
    )
    report_text = fulfillment_report_path.read_text(encoding="utf-8", errors="replace")
    summary_mismatches = _summary_count_mismatches(report_text)
    comparable_report_ids = set(report_ids)
    comparable_report_ids.discard("TASK-PROGRESS")
    missing = tuple(sorted(audit_ids - comparable_report_ids))
    extra = tuple(sorted(comparable_report_ids - audit_ids))
    return FulfillmentArtifactValidation(
        ok=not missing and not extra and not summary_mismatches,
        audit_count=len(audit_ids),
        report_count=len(comparable_report_ids),
        missing_in_report=missing,
        extra_in_report=extra,
        summary_count_mismatches=summary_mismatches,
    )


def _canonical_inventory_ids(inventory_path: Path) -> set[str]:
    try:
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    rows = data.get("requirements", [])
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("id", "")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }
