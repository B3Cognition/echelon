"""Fulfillment verification helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import yaml

NON_STRICT_BLOCKING = {"MISSING", "PARTIAL", "DEVIATED"}
STRICT_BLOCKING = NON_STRICT_BLOCKING | {"UNVERIFIED"}
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)


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
    summary_count = re.compile(
        r"\b(?P<status>MISSING|PARTIAL|DEVIATED|UNVERIFIED)\s*:?\s*(?P<count>\d+)\b"
    )

    for line in text.splitlines():
        if "|" not in line:
            for match in summary_count.finditer(line):
                if int(match.group("count")) > 0:
                    statuses.add(match.group("status"))
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


def read_fulfillment_metadata(report_path: Path) -> dict[str, Any]:
    """Return YAML frontmatter metadata from a fulfillment report."""
    if not report_path.exists():
        return {}
    text = report_path.read_text(encoding="utf-8", errors="replace")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
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
    if run_id:
        metadata["verify_run_id"] = run_id
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
