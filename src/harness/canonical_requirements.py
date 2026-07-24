"""Deterministic canonical requirement inventory for verify-spec."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

REQ_ID_RE = re.compile(
    r"\b(?:FR|NFR|EDGE|REQ|AC|US|SC)(?:-[A-Z0-9_.:]+)+\b(?!-[A-Za-z0-9])"
)
TASK_REQ_RE = re.compile(r"\breq=(?P<reqs>[A-Za-z0-9_,.:-]+)")
INVENTORY_JSON = "canonical-requirements.json"
INVENTORY_MD = "canonical-requirements.md"
REQUIREMENT_AUDIT_MD = "requirement-audit.md"


@dataclass(frozen=True)
class CanonicalRequirement:
    id: str
    source_kind: str
    source_file: str
    source_line: int
    source_text: str


@dataclass(frozen=True)
class CanonicalRequirementInventoryResult:
    json_path: Path
    markdown_path: Path
    count: int
    inventory_hash: str


@dataclass(frozen=True)
class RequirementAuditResult:
    audit_path: Path
    count: int


def extract_canonical_requirements(spec_dir: Path) -> list[CanonicalRequirement]:
    rows: dict[str, CanonicalRequirement] = {}
    for filename, source_kind in (
        ("spec.md", "spec"),
        ("plan.md", "plan"),
        ("coverage-map.md", "coverage"),
    ):
        _collect_markdown_ids(spec_dir / filename, source_kind, rows)
    _collect_task_metadata_ids(spec_dir / "tasks.md", rows)
    return [rows[item_id] for item_id in sorted(rows)]


def write_canonical_requirements(
    *, spec_dir: Path, verify_run_dir: Path
) -> CanonicalRequirementInventoryResult:
    requirements = extract_canonical_requirements(spec_dir)
    verify_run_dir.mkdir(parents=True, exist_ok=True)
    inventory_hash = _inventory_hash(requirements)
    json_path = verify_run_dir / INVENTORY_JSON
    markdown_path = verify_run_dir / INVENTORY_MD
    payload = {
        "kind": "echelon.canonical_requirements",
        "version": 1,
        "spec_dir": str(spec_dir),
        "inventory_hash": inventory_hash,
        "requirements": [
            {
                "id": row.id,
                "source_kind": row.source_kind,
                "source_file": row.source_file,
                "source_line": row.source_line,
                "source_text": row.source_text,
            }
            for row in requirements
        ],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(_render_markdown(requirements), encoding="utf-8")
    return CanonicalRequirementInventoryResult(
        json_path=json_path,
        markdown_path=markdown_path,
        count=len(requirements),
        inventory_hash=inventory_hash,
    )


def canonical_requirement_ids(inventory_path: Path) -> set[str]:
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    return {
        str(row.get("id", "")).strip()
        for row in data.get("requirements", [])
        if str(row.get("id", "")).strip()
    }


def write_requirement_audit(*, verify_run_dir: Path) -> RequirementAuditResult:
    requirements = _load_inventory_requirements(verify_run_dir / INVENTORY_JSON)
    audit_path = verify_run_dir / REQUIREMENT_AUDIT_MD
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(_render_requirement_audit(requirements), encoding="utf-8")
    return RequirementAuditResult(audit_path=audit_path, count=len(requirements))


def _collect_markdown_ids(
    path: Path, source_kind: str, rows: dict[str, CanonicalRequirement]
) -> None:
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for lineno, line in enumerate(lines, start=1):
        for item_id in REQ_ID_RE.findall(line):
            rows.setdefault(
                item_id,
                CanonicalRequirement(
                    item_id, source_kind, path.name, lineno, line.strip()
                ),
            )


def _collect_task_metadata_ids(
    path: Path, rows: dict[str, CanonicalRequirement]
) -> None:
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for lineno, line in enumerate(lines, start=1):
        match = TASK_REQ_RE.search(line)
        if match is None:
            continue
        for item_id in _split_reqs(match.group("reqs")):
            if item_id == "UNMAPPED" or not REQ_ID_RE.fullmatch(item_id):
                continue
            rows.setdefault(
                item_id,
                CanonicalRequirement(
                    item_id, "task_metadata", path.name, lineno, line.strip()
                ),
            )


def _split_reqs(value: str) -> Iterable[str]:
    for item in value.split(","):
        item = item.strip()
        if item:
            yield item


def _inventory_hash(requirements: list[CanonicalRequirement]) -> str:
    digest = hashlib.sha256()
    for row in requirements:
        digest.update(row.id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(row.source_kind.encode("utf-8"))
        digest.update(b"\0")
        digest.update(row.source_file.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row.source_line).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _render_markdown(requirements: list[CanonicalRequirement]) -> str:
    lines = [
        "# Canonical Requirements",
        "",
        "| ID | Source Kind | Source File | Line | Source Text |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for row in requirements:
        lines.append(
            f"| {row.id} | {row.source_kind} | {row.source_file} | "
            f"{row.source_line} | {_escape_cell(row.source_text)} |"
        )
    return "\n".join(lines) + "\n"


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _load_inventory_requirements(inventory_path: Path) -> list[CanonicalRequirement]:
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    rows: list[CanonicalRequirement] = []
    for raw in data.get("requirements", []):
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "").strip()
        if not item_id:
            continue
        rows.append(
            CanonicalRequirement(
                id=item_id,
                source_kind=str(raw.get("source_kind") or ""),
                source_file=str(raw.get("source_file") or ""),
                source_line=int(raw.get("source_line") or 0),
                source_text=str(raw.get("source_text") or ""),
            )
        )
    return sorted(rows, key=lambda row: row.id)


def _render_requirement_audit(requirements: list[CanonicalRequirement]) -> str:
    lines = [
        "# Requirement Audit",
        "",
        "| ID | Category | Source | Requirement | Acceptance Signal |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in requirements:
        lines.append(
            f"| {row.id} | {_category_for(row.id)} | "
            f"{_escape_cell(_source_ref(row))} | "
            f"{_escape_cell(_requirement_text(row))} | "
            f"Source-defined observable behavior for {row.id}. |"
        )
    return "\n".join(lines) + "\n"


def _category_for(item_id: str) -> str:
    prefix = item_id.split("-", 1)[0].upper()
    if prefix == "FR":
        return "functional"
    if prefix == "NFR":
        return "non_functional"
    if prefix == "EDGE":
        return "edge_case"
    if prefix == "US":
        return "user_story"
    if prefix == "AC":
        return "acceptance"
    if prefix in {"SC", "REQ"}:
        return "requirement"
    return "requirement"


def _source_ref(row: CanonicalRequirement) -> str:
    if row.source_file and row.source_line:
        return f"{row.source_file}:{row.source_line}"
    return row.source_file or row.source_kind or "unknown"


def _requirement_text(row: CanonicalRequirement) -> str:
    text = row.source_text.strip()
    text = _strip_markdown_prefix(text)
    text = re.sub(rf"^\*\*{re.escape(row.id)}\*\*\s*:\s*", "", text)
    text = re.sub(rf"^{re.escape(row.id)}\s*:\s*", "", text)
    text = _strip_markdown_prefix(text)
    return text.strip() or row.id


def _strip_markdown_prefix(text: str) -> str:
    return re.sub(r"^[\s>#.\-]*", "", text)
