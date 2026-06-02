"""Fulfillment verification helpers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

NON_STRICT_BLOCKING = {"MISSING", "PARTIAL", "DEVIATED"}
STRICT_BLOCKING = NON_STRICT_BLOCKING | {"UNVERIFIED"}


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
    known = STRICT_BLOCKING | {"IMPLEMENTED", "OBSOLETE_SPEC"}
    requirement_id = re.compile(r"^(?:FR|AC|US|NFR|REQ|EDGE)-[A-Za-z0-9_.:-]+$")

    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and requirement_id.match(cells[0]) and cells[1] in known:
            statuses.add(cells[1])

    return statuses


def fulfillment_has_blocking_gaps(report_path: Path, strict: bool = False) -> bool:
    """Return True when a fulfillment report contains unresolved gap statuses."""
    if not report_path.exists():
        return False
    return bool(_statuses_in_report(report_path) & blocking_statuses(strict))
