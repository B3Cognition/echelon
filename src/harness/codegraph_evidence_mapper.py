"""Deterministic requirement-to-CodeGraph evidence mapper for verify-spec."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any


REQUIREMENT_ID_RE = re.compile(r"^(?:US|AC|FR|NFR|EDGE|SC|WF|PLAN)[A-Za-z0-9_.:-]*$")
TASK_ROW_RE = re.compile(
    r"^- \[[ xX]\]\s+(?P<task_id>T-[A-Za-z0-9_.-]+|T[A-Za-z0-9_.-]+)"
    r"(?:\s+\[P\])?.*?\breq=(?P<req>[A-Za-z0-9_,.-]+)\b"
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
STOPWORDS = {
    "a",
    "after",
    "all",
    "along",
    "and",
    "are",
    "as",
    "at",
    "background",
    "be",
    "by",
    "can",
    "card",
    "cards",
    "changes",
    "current",
    "each",
    "exactly",
    "for",
    "from",
    "gameplay",
    "has",
    "in",
    "into",
    "is",
    "item",
    "items",
    "mission",
    "n",
    "navigational",
    "of",
    "one",
    "order",
    "per",
    "pipeline",
    "player",
    "portal",
    "produces",
    "state",
    "the",
    "to",
    "test",
    "tests",
    "visible",
    "view",
    "with",
}
KNOWN_ACRONYMS = {"ar", "ui", "api", "gps", "nfc"}
CONFIDENCE_ORDER = ("high", "medium", "low", "none", "ambiguous")


@dataclass(frozen=True)
class EvidenceMapResult:
    out_json_path: Path
    out_md_path: Path
    total_requirements: int
    counts: dict[str, int]


@dataclass(frozen=True)
class RequirementRow:
    id: str
    category: str
    source: str
    requirement: str
    acceptance_signal: str


@dataclass(frozen=True)
class SymbolRecord:
    symbol: str
    name: str
    kind: str
    file_path: str
    line_start: int | None
    line_end: int | None
    tokens: frozenset[str]
    searchable: str
    is_test: bool


def write_codegraph_evidence_map(
    requirement_audit_path: Path,
    codegraph_analysis_path: Path,
    tasks_path: Path,
    out_json_path: Path,
    out_md_path: Path,
    coverage_map_path: Path | None = None,
) -> EvidenceMapResult:
    """Write deterministic CodeGraph evidence map artifacts."""
    requirements = _parse_requirement_audit(
        requirement_audit_path.read_text(encoding="utf-8", errors="replace")
    )
    analysis = json.loads(codegraph_analysis_path.read_text(encoding="utf-8"))
    symbols = _parse_symbols(analysis)
    task_index = _parse_task_requirements(
        tasks_path.read_text(encoding="utf-8", errors="replace")
    )
    coverage_text = ""
    if coverage_map_path is not None and coverage_map_path.is_file():
        coverage_text = coverage_map_path.read_text(encoding="utf-8", errors="replace")

    entries = [
        _map_requirement(row, symbols, task_index.get(row.id, []), coverage_text)
        for row in requirements
    ]
    counts = Counter(str(entry["confidence"]) for entry in entries)
    for confidence in CONFIDENCE_ORDER:
        counts.setdefault(confidence, 0)

    payload = {
        "schema_version": 1,
        "source_files": {
            "requirement_audit": str(requirement_audit_path),
            "codegraph_analysis": str(codegraph_analysis_path),
            "tasks": str(tasks_path),
            "coverage_map": str(coverage_map_path) if coverage_map_path else None,
        },
        "summary": {
            "total_requirements": len(entries),
            "counts": {key: counts[key] for key in CONFIDENCE_ORDER},
        },
        "requirements": entries,
    }

    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    out_md_path.write_text(_render_markdown(payload), encoding="utf-8")
    return EvidenceMapResult(
        out_json_path=out_json_path,
        out_md_path=out_md_path,
        total_requirements=len(entries),
        counts={key: counts[key] for key in CONFIDENCE_ORDER},
    )


def _parse_requirement_audit(markdown: str) -> list[RequirementRow]:
    rows: list[RequirementRow] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 5 or cells[0] == "ID" or not REQUIREMENT_ID_RE.match(cells[0]):
            continue
        rows.append(
            RequirementRow(
                id=cells[0],
                category=cells[1],
                source=cells[2],
                requirement=cells[3],
                acceptance_signal=cells[4],
            )
        )
    return rows


def _parse_task_requirements(markdown: str) -> dict[str, list[str]]:
    by_req: dict[str, list[str]] = defaultdict(list)
    for line in markdown.splitlines():
        match = TASK_ROW_RE.match(line)
        if match is None:
            continue
        task_id = match.group("task_id")
        for req_id in match.group("req").split(","):
            normalized = req_id.strip()
            if normalized and normalized != "UNMAPPED":
                by_req[normalized].append(task_id)
    return {req: sorted(set(task_ids)) for req, task_ids in by_req.items()}


def _parse_symbols(analysis: dict[str, Any]) -> list[SymbolRecord]:
    raw_symbols = analysis.get("symbols")
    if not isinstance(raw_symbols, list):
        raw_symbols = []
    symbols: list[SymbolRecord] = []
    for raw in raw_symbols:
        if not isinstance(raw, dict):
            continue
        file_path = str(raw.get("file_path") or raw.get("qualified_name") or "")
        name = str(raw.get("name") or "")
        qualified = str(raw.get("qualified_name") or name or file_path)
        searchable = " ".join([qualified, name, file_path])
        tokens = frozenset(_tokens(searchable, keep_acronyms=True))
        symbols.append(
            SymbolRecord(
                symbol=qualified,
                name=name,
                kind=str(raw.get("kind") or "unknown"),
                file_path=file_path,
                line_start=_optional_int(raw.get("line_start")),
                line_end=_optional_int(raw.get("line_end")),
                tokens=tokens,
                searchable=_collapse(searchable),
                is_test=_is_test_symbol(qualified, name, file_path),
            )
        )
    return symbols


def _map_requirement(
    row: RequirementRow,
    symbols: list[SymbolRecord],
    task_ids: list[str],
    coverage_text: str,
) -> dict[str, Any]:
    id_variants = _requirement_id_variants(row.id)
    query_text = " ".join([row.id, row.requirement, row.acceptance_signal])
    query_tokens = _tokens(query_text, keep_acronyms=True)

    implementation: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for symbol in symbols:
        direct_id = any(variant in symbol.searchable for variant in id_variants)
        overlap = sorted(set(query_tokens).intersection(symbol.tokens))
        token_match = _strong_token_match(query_tokens, overlap)
        coverage_match = bool(coverage_text and row.id in coverage_text and symbol.file_path in coverage_text)
        if not direct_id and not token_match and not coverage_match:
            continue
        evidence = _symbol_evidence(
            symbol,
            reasons=_match_reasons(direct_id, token_match, coverage_match, overlap),
        )
        if symbol.is_test:
            tests.append(evidence)
        else:
            implementation.append(evidence)

    implementation = _dedupe_evidence(implementation)[:8]
    tests = _dedupe_evidence(tests)[:8]
    confidence, notes = _confidence(implementation, tests)
    negative_evidence = []
    if confidence == "none":
        negative_evidence.append(
            "No CodeGraph source or test symbols matched requirement id "
            f"{row.id} or tokens: {', '.join(query_tokens[:12])}"
        )

    return {
        "id": row.id,
        "category": row.category,
        "source": row.source,
        "requirement": row.requirement,
        "acceptance_signal": row.acceptance_signal,
        "task_ids": task_ids,
        "implementation_evidence": implementation,
        "test_evidence": tests,
        "negative_evidence": negative_evidence,
        "confidence": confidence,
        "notes": notes,
    }


def _confidence(
    implementation: list[dict[str, Any]], tests: list[dict[str, Any]]
) -> tuple[str, str]:
    if implementation and tests:
        return "high", "CodeGraph found both source and executable test symbols."
    if tests:
        return "medium", "CodeGraph found test symbols but no implementation symbol."
    if implementation:
        return "low", "CodeGraph found source candidates but no executable test symbol."
    return "none", "No deterministic CodeGraph evidence found; LLM fallback should inspect."


def _symbol_evidence(symbol: SymbolRecord, reasons: list[str]) -> dict[str, Any]:
    return {
        "symbol": symbol.symbol,
        "kind": symbol.kind,
        "file": symbol.file_path,
        "line_start": symbol.line_start,
        "line_end": symbol.line_end,
        "reasons": reasons,
    }


def _match_reasons(
    direct_id: bool,
    token_match: bool,
    coverage_match: bool,
    overlap: list[str],
) -> list[str]:
    reasons = []
    if direct_id:
        reasons.append("direct_requirement_id_match")
    if token_match:
        reasons.append("term_match:" + ",".join(overlap[:8]))
    if coverage_match:
        reasons.append("coverage_map_path_match")
    return reasons


def _strong_token_match(query_tokens: list[str], overlap: list[str]) -> bool:
    meaningful = [token for token in overlap if token not in STOPWORDS]
    if len(meaningful) >= 2:
        return True
    if len(meaningful) == 1:
        token = meaningful[0]
        return token not in KNOWN_ACRONYMS and query_tokens.count(token) >= 1
    return False


def _tokens(text: str, keep_acronyms: bool = False) -> list[str]:
    expanded = _split_camel(text)
    tokens = []
    for match in WORD_RE.finditer(expanded):
        token = match.group(0).lower()
        if token in STOPWORDS:
            continue
        if len(token) < 3 and not (keep_acronyms and token in KNOWN_ACRONYMS):
            continue
        tokens.append(token)
    return sorted(set(tokens))


def _split_camel(text: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return text


def _collapse(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _requirement_id_variants(req_id: str) -> set[str]:
    collapsed = _collapse(req_id)
    return {collapsed, req_id.lower().replace("-", ""), req_id.lower().replace("-", "_")}


def _is_test_symbol(qualified: str, name: str, file_path: str) -> bool:
    combined = " ".join([qualified, name, file_path]).lower()
    return (
        "/tests/" in combined
        or "tests.swift" in combined
        or "test" in name.lower()
        or "tests::" in qualified.lower()
        or "/uitests/" in combined
    )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int | None]] = set()
    deduped = []
    for item in sorted(items, key=_evidence_sort_key):
        key = (str(item["symbol"]), str(item["file"]), item.get("line_start"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _evidence_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    kind = str(item.get("kind") or "")
    kind_rank = {
        "method": 0,
        "function": 0,
        "class": 1,
        "struct": 1,
        "interface": 1,
        "enum": 1,
        "file": 3,
    }.get(kind, 2)
    return kind_rank, str(item.get("symbol") or "")


def _render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# CodeGraph Evidence Map",
        "",
        f"Requirements: {summary['total_requirements']}",
        "",
        "| ID | Confidence | Task IDs | Implementation Evidence | Test Evidence | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in payload["requirements"]:
        impl = _evidence_cell(entry["implementation_evidence"])
        tests = _evidence_cell(entry["test_evidence"])
        task_ids = ", ".join(entry["task_ids"]) if entry["task_ids"] else ""
        lines.append(
            "| {id} | {confidence} | {task_ids} | {impl} | {tests} | {notes} |".format(
                id=_md(entry["id"]),
                confidence=_md(entry["confidence"]),
                task_ids=_md(task_ids),
                impl=_md(impl),
                tests=_md(tests),
                notes=_md(entry["notes"]),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _evidence_cell(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    return "; ".join(
        f"{item['file']}::{item['symbol']}" for item in items[:3]
    )


def _md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
