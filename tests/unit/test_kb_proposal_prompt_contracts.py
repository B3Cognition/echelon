"""Static prompt contracts for Phase A KB proposal pipeline."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_sage_records_decisions_as_kb_proposals() -> None:
    text = _read("extension/agents/exploration/sage.md")
    assert "sage-decision-proposal-template.yaml" in text
    assert "${SQUAD_DIR}/kb-proposals/" in text
    assert "Do not edit `knowledge-base/sage-decisions.yaml` directly" in text
    assert "append an entry to `${PROJECT_ROOT}/knowledge-base/sage-decisions.yaml`" not in text


def test_mirror_records_patterns_and_pitfalls_as_kb_proposals() -> None:
    text = _read("extension/agents/learning/mirror.md")
    assert "pattern-proposal-template.yaml" in text
    assert "pitfall-proposal-template.yaml" in text
    assert "${SQUAD_DIR}/kb-proposals/" in text
    assert (
        "Do not edit `knowledge-base/patterns.yaml` or `knowledge-base/pitfalls.yaml` directly"
        in text
    )
    assert "Append to `knowledge-base/patterns.yaml`" not in text
    assert "Append to `knowledge-base/pitfalls.yaml`" not in text


def test_finalize_runs_kb_apply_non_blocking() -> None:
    text = _read("extension/workflow/phases/phase4-document.md")
    assert "echelon kb validate --run-id" in text
    assert "echelon kb apply --run-id" in text
    assert "does not stop finalization" in text
    assert "kb_validation_status: degraded" in text
    assert "kb_apply_status: degraded" in text
    assert "kb_usage_status: degraded" in text
    assert "kb-apply-report.yaml" in text
    assert "Update `knowledge-base/patterns.yaml` and `knowledge-base/pitfalls.yaml`" not in text
    assert "KB_VALIDATE_EXIT=$?" in text
    assert "KB_APPLY_EXIT=$?" in text
    assert "echelon kb validate --run-id \"${RUN_ID}\" || true" not in text
    assert "echelon kb apply --run-id \"${RUN_ID}\" || true" not in text


def test_finalize_has_no_direct_canonical_kb_writes() -> None:
    text = _read("extension/workflow/phases/phase4-document.md")
    direct_write = re.compile(
        r"\b(?:update|append|write|modify)\s+(?:to\s+)?`?knowledge-base/",
        re.IGNORECASE,
    )

    assert not direct_write.search(text)


def test_auditor_records_calibration_as_kb_proposals() -> None:
    text = _read("extension/agents/learning/auditor.md")
    assert "calibration-observation-proposal-template.yaml" in text
    assert "${SQUAD_DIR}/kb-proposals/" in text
    assert "Do not edit `knowledge-base/calibration-profile.yaml` directly" in text
    direct_write = re.compile(
        r"\b(?:update|append|write|modify)\s+(?:to\s+)?`?knowledge-base/calibration-profile\.yaml",
        re.IGNORECASE,
    )

    assert not direct_write.search(text)


def test_scorekeeper_records_internalization_as_kb_proposals() -> None:
    text = _read("extension/agents/control/scorekeeper.md")
    assert "internalization-observation-proposal-template.yaml" in text
    assert "${SQUAD_DIR}/kb-proposals/" in text
    assert "Do not edit `knowledge-base/agent-scores.yaml` directly" in text
    direct_write = re.compile(
        r"\b(?:update|append|write|modify)\s+(?:to\s+)?`?knowledge-base/agent-scores\.yaml",
        re.IGNORECASE,
    )

    assert not direct_write.search(text)


def test_finalize_applies_kb_proposals_after_scorekeeper() -> None:
    text = _read("extension/workflow/phases/phase4-document.md")

    assert text.index("echelon kb apply --run-id") > text.index(
        "Run speckit-echelon-scorekeeper"
    )
    assert text.index("echelon kb apply --run-id") < text.index(
        "12.7b Collect Final Artifacts"
    )


def test_workflow_allows_kb_status_state_updates() -> None:
    text = _read("extension/workflow/definition.yaml")
    for key in [
        "kb_usage_status",
        "kb_validation_status",
        "kb_apply_status",
        "kb_contract_violations",
        "kb_apply_report",
    ]:
        assert key in text
