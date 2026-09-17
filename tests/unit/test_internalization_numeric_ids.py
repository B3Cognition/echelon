"""Subprocess regressions for wide numeric IDs in internalization metrics."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "internalization"


def _run_metric(tmp_path: Path, script: str, spec: str, output: str) -> dict[str, object]:
    spec_path = tmp_path / "spec.md"
    output_path = tmp_path / "output.md"
    spec_path.write_text(spec, encoding="utf-8")
    output_path.write_text(output, encoding="utf-8")
    completed = subprocess.run(
        ["bash", str(SCRIPTS / script), str(spec_path), str(output_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_i01_distinguishes_wide_ids_and_ignores_malformed_prefixes(tmp_path: Path) -> None:
    """Truncating at three digits must not merge two wide requirements."""
    result = _run_metric(
        tmp_path,
        "i01-requirement-coverage.sh",
        "FR-001: Legacy.\nFR-1000000: First.\nFR-1000001: Second.\n",
        "Delivered FR-001 and FR-1000000, not FR-1000001-extra.\n",
    )

    assert result == {
        "metric": "I-01",
        "name": "requirement_coverage_rate",
        "score": 0.6667,
        "reason": None,
        "spec_ids": 3,
        "output_ids": 2,
        "intersection": 2,
    }


def test_i06_requires_a_complete_legacy_or_wide_citation(tmp_path: Path) -> None:
    """A malformed wide token must not turn an uncited decision into a cited one."""
    result = _run_metric(
        tmp_path,
        "i06-uncited-decision.sh",
        "FR-001: Legacy.\nFR-1000000: Wide.\n",
        "Decision: selected FR-1000000.\n"
        "Decision: selected FR-1000000-extra.\n"
        "Decision: implemented FR-001.\n",
    )

    assert result["decisions"] == 3
    assert result["cited"] == 2
    assert result["uncited"] == 1
    assert result["score"] == 0.6667


def test_i07_keeps_distinct_wide_and_legacy_suffix_citations(tmp_path: Path) -> None:
    """Cross-reference sets must retain full IDs and supported legacy suffixes."""
    result = _run_metric(
        tmp_path,
        "i07-cross-reference-accuracy.sh",
        "FR-1000000: First.\nFR-1000001: Second.\nFR-123a: Legacy suffix.\n",
        "Cites FR-1000000, FR-1000002, FR-123a, FR-1000001-extra, "
        "and FR-1000003a.\n",
    )

    assert result["citations"] == 3
    assert result["valid"] == 2
    assert result["invalid"] == 1
    assert result["invalid_ids"] == "FR-1000002"
    assert result["score"] == 0.6667


def test_i08_scope_matching_rejects_a_wide_id_prefix(tmp_path: Path) -> None:
    """Substring scope matching must not accept a malformed extension of a valid ID."""
    result = _run_metric(
        tmp_path,
        "i08-keyword-scope.sh",
        "FR-001: Legacy.\nFR-1000000: First.\nFR-1000001: Second.\n",
        "Decision: selected FR-1000001.\n"
        "Decision: selected FR-1000000-extra.\n"
        "Decision: implemented FR-001.\n",
    )

    assert result["decisions"] == 3
    assert result["scoped"] == 2
    assert result["score"] == 0.6667


def test_i15_traces_complete_wide_and_legacy_suffix_ids(tmp_path: Path) -> None:
    """A malformed token must not inherit traceability from its numeric prefix."""
    result = _run_metric(
        tmp_path,
        "i15-decision-traceability.sh",
        "FR-1000000: First.\nFR-1000001: Second.\nFR-123a: Legacy suffix.\n"
        "FR-1000003a: Malformed wide suffix.\n",
        "Decision: selected FR-1000000.\n"
        "Decision: selected FR-1000001-extra.\n"
        "Decision: implemented FR-123a.\n"
        "Decision: selected FR-1000003a.\n",
    )

    assert result["decisions"] == 4
    assert result["traced"] == 2
    assert result["untraced"] == 2
    assert result["valid_ids_in_spec"] == 3
    assert result["score"] == 0.5


def test_i16_counts_only_complete_wide_and_legacy_id_references(tmp_path: Path) -> None:
    """Priority attention must not count malformed extensions as legacy citations."""
    output_lines = (
        ["Decision: selected FR-1000000."] * 4
        + ["Decision: selected FR-1000001."] * 3
        + ["Decision: selected FR-1000002."] * 2
        + ["Decision: selected FR-001."]
        + ["Decision: selected FR-001-extra."] * 5
    )
    result = _run_metric(
        tmp_path,
        "i16-priority-alignment.sh",
        "FR-1000000 | P0\n"
        "FR-1000001 | P1\n"
        "FR-1000002 | P2\n"
        "FR-001 | P3\n",
        "\n".join(output_lines) + "\n",
    )

    assert result["requirements"] == 4
    assert result["score"] == 1.0
