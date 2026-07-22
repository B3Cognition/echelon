from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_semantic_preflight import check_semantic_preflight


pytestmark = pytest.mark.unit


def _coverage() -> str:
    return """## Behavior Coverage

| Category | Status | Observed Scope | Source Evidence |
|---|---|---|---|
| public operations | observed | load and validate | `src/io.ts:1` |
| configuration keys | not-observed | none found | — |
| errors and recovery | observed | read failures | `src/io.ts:4-12` |
| boundaries and edge cases | not-observed | none found | — |
| operator-visible behavior | not-observed | none found | — |
| tests | not-observed | none found | — |
| evidence scope | observed | read branches | `src/io.ts:4-12` |
"""


def test_preflight_rejects_unscoped_universal_requirement(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "## Requirements (Non-Functional)\n\n"
        "### NFR-001: Safety\nEvery read failure is recovered. `src/io.ts:4`\n",
        encoding="utf-8",
    )

    findings = check_semantic_preflight(spec, None)

    assert [item.code for item in findings] == [
        "behavior_coverage_missing",
        "unscoped_universal_claim",
    ]


def test_preflight_accepts_exhaustively_scoped_claim(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "## Requirements (Non-Functional)\n\n"
        "### NFR-001: Safety\nEvery read failure is recovered. "
        "Evidence Scope: exhaustive. `src/io.ts:4-12`\n\n"
        + _coverage(),
        encoding="utf-8",
    )

    assert check_semantic_preflight(spec, None) == ()


def test_host_port_literal_does_not_satisfy_source_evidence(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "## Requirements (Non-Functional)\n\n"
        "### NFR-001: Availability\nEvery request uses `localhost:2746`. "
        "Evidence Scope: exhaustive.\n\n"
        + _coverage(),
        encoding="utf-8",
    )

    findings = check_semantic_preflight(spec, None)

    assert [item.code for item in findings] == ["unscoped_universal_claim"]


def test_preflight_reports_unmentioned_known_public_symbol(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(_coverage(), encoding="utf-8")
    analysis = tmp_path / "analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "public_symbols": [
                    {"name": "load"},
                    {"name": "validate"},
                    {"name": "remove"},
                ],
            }
        ),
        encoding="utf-8",
    )

    findings = check_semantic_preflight(spec, analysis)

    assert len(findings) == 1
    assert findings[0].code == "public_surface_coverage_missing"
    assert "remove" in findings[0].message


def test_unknown_analysis_shape_does_not_invent_public_symbols(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(_coverage(), encoding="utf-8")
    analysis = tmp_path / "analysis.json"
    analysis.write_text('{"schema_version":1,"files":[]}', encoding="utf-8")

    assert check_semantic_preflight(spec, analysis) == ()
