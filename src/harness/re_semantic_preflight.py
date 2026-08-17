"""Cheap structural checks that precede LLM semantic validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from harness.re_source_evidence import contains_source_reference, source_references


BEHAVIOR_COVERAGE_CATEGORIES = (
    "public operations",
    "configuration keys",
    "errors and recovery",
    "boundaries and edge cases",
    "operator-visible behavior",
    "tests",
    "evidence scope",
)

_UNIVERSAL = re.compile(r"\b(all|always|every|never)\b", re.I)
_BOUNDED_EXCLUSION = re.compile(
    r"\b(?:not exhaustive|not verified against|does not cover|doesn't cover|"
    r"excludes|outside (?:the )?scope)\b",
    re.I,
)
_SENTENCE_BOUNDARY = re.compile(r"[.!?][\"')\]]*\s+(?=[A-Z`*])")
_REQUIREMENT = re.compile(
    r"^###\s+(?P<title>(?:FR|NFR)-\d+[^\n]*)\n(?P<body>.*?)(?=^###\s+|^##\s+|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True)
class SemanticPreflightFinding:
    code: str
    message: str
    references: tuple[str, ...] = ()


def check_semantic_preflight(
    spec_path: Path,
    analysis_path: Path | None,
) -> tuple[SemanticPreflightFinding, ...]:
    text = spec_path.read_text(encoding="utf-8")
    findings: list[SemanticPreflightFinding] = []
    coverage, malformed_coverage, invalid_coverage_statuses = _behavior_coverage_rows(text)
    if coverage is None:
        findings.append(
            SemanticPreflightFinding(
                "behavior_coverage_missing",
                "source-domain spec must contain a Behavior Coverage table",
            )
        )
    else:
        if malformed_coverage:
            findings.append(
                SemanticPreflightFinding(
                    "behavior_coverage_row_malformed",
                    "Behavior Coverage rows require Category, Status, Observed Scope, "
                    "and Source Evidence columns: " + ", ".join(malformed_coverage),
                )
            )
        if invalid_coverage_statuses:
            findings.append(
                SemanticPreflightFinding(
                    "behavior_coverage_status_invalid",
                    "Behavior Coverage status must be observed, not-observed, or "
                    "not-applicable: "
                    + ", ".join(
                        f"{category}={status}"
                        for category, status in invalid_coverage_statuses
                    ),
                )
            )
        invalid_status_categories = {
            category for category, _status in invalid_coverage_statuses
        }
        missing = tuple(
            category
            for category in BEHAVIOR_COVERAGE_CATEGORIES
            if category not in coverage
            and category not in malformed_coverage
            and category not in invalid_status_categories
        )
        if missing:
            findings.append(
                SemanticPreflightFinding(
                    "behavior_coverage_category_missing",
                    "Behavior Coverage is missing: " + ", ".join(missing),
                )
            )
        invalid = tuple(
            category
            for category, (status, evidence) in coverage.items()
            if status == "observed" and not contains_source_reference(evidence)
        )
        if invalid:
            findings.append(
                SemanticPreflightFinding(
                    "behavior_coverage_evidence_invalid",
                    "Observed coverage rows need source evidence: "
                    + ", ".join(sorted(invalid)),
                )
            )

    without_fences = _FENCE.sub("", text)
    requirement_ids: set[str] = set()
    reported_duplicate_ids: set[str] = set()
    for match in _REQUIREMENT.finditer(without_fences):
        title = match.group("title").strip()
        requirement_id_match = re.match(r"(?:FR|NFR)-\d+", title, re.IGNORECASE)
        if requirement_id_match is not None:
            requirement_id = requirement_id_match.group(0).upper()
            if (
                requirement_id in requirement_ids
                and requirement_id not in reported_duplicate_ids
            ):
                findings.append(
                    SemanticPreflightFinding(
                        "duplicate_requirement_id",
                        f"duplicate requirement heading: {requirement_id}",
                    )
                )
                reported_duplicate_ids.add(requirement_id)
            requirement_ids.add(requirement_id)
        body = match.group("body")
        universal_terms = _unscoped_universal_terms(body)
        exhaustive_scope = re.search(
            r"(?:\*\*)?Evidence Scope:(?:\*\*)?\s*exhaustive\b",
            body,
            re.IGNORECASE,
        )
        if universal_terms and not (
            exhaustive_scope and contains_source_reference(body)
        ):
            findings.append(
                SemanticPreflightFinding(
                    "unscoped_universal_claim",
                    f"{title} uses a universal claim without "
                    "exhaustive evidence scope; unscoped universal term(s): "
                    + ", ".join(universal_terms),
                    source_references(body),
                )
            )

    missing_symbols = _missing_public_symbols(text, analysis_path)
    if missing_symbols:
        findings.append(
            SemanticPreflightFinding(
                "public_surface_coverage_missing",
                "Known public symbols are absent from the spec: "
                + ", ".join(missing_symbols),
            )
        )
    return tuple(findings)


def _unscoped_universal_terms(body: str) -> tuple[str, ...]:
    """Return distinct universal terms outside bounded exclusion clauses."""
    # Identifiers and literal values can legitimately contain words such as
    # ``all`` (for example ``ALL_KPI`` or ``/settings/all-kpi``).  Preserve
    # offsets while excluding inline code from the prose-quantifier scan.
    prose = _INLINE_CODE.sub(lambda match: " " * len(match.group(0)), body)
    terms: list[str] = []
    for match in _UNIVERSAL.finditer(prose):
        sentence_start = 0
        for boundary in _SENTENCE_BOUNDARY.finditer(prose, 0, match.start()):
            sentence_start = boundary.end()
        if not _BOUNDED_EXCLUSION.search(prose[sentence_start:match.start()]):
            term = match.group(0).casefold()
            if term not in terms:
                terms.append(term)
    return tuple(terms)


def _behavior_coverage_rows(
    text: str,
) -> tuple[
    dict[str, tuple[str, str]] | None,
    tuple[str, ...],
    tuple[tuple[str, str], ...],
]:
    section = re.search(
        r"^##\s+Behavior Coverage\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        text,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if section is None:
        return None, (), ()
    rows: dict[str, tuple[str, str]] = {}
    malformed: list[str] = []
    invalid_statuses: list[tuple[str, str]] = []
    for line in section.group("body").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        category_key = cells[0].strip("*_` ").casefold() if cells else ""
        if len(cells) != 4:
            if category_key in BEHAVIOR_COVERAGE_CATEGORIES:
                malformed.append(category_key)
            continue
        category, status, _scope, evidence = cells
        category_key = category.strip("*_` ").casefold()
        status_key = status.strip("*_` ").casefold()
        if category_key not in BEHAVIOR_COVERAGE_CATEGORIES:
            continue
        if status_key in {"observed", "not-observed", "not-applicable"}:
            rows[category_key] = (status_key, evidence)
        else:
            invalid_statuses.append((category_key, status_key))
    return (
        rows,
        tuple(dict.fromkeys(malformed)),
        tuple(dict.fromkeys(invalid_statuses)),
    )


def _missing_public_symbols(text: str, analysis_path: Path | None) -> tuple[str, ...]:
    if analysis_path is None or not analysis_path.is_file():
        return ()
    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    raw = payload.get("public_symbols") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return ()
    symbols = tuple(
        item["name"].strip()
        for item in raw
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item["name"].strip()
    )
    return tuple(
        symbol
        for symbol in symbols
        if re.search(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])", text) is None
    )
