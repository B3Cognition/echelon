from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from harness.governance_structural_gate import run_governance_structural_gate


EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "extension"


def _governance(
    *,
    enabled: bool = True,
    tier: str = "structural",
    on_exhausted: str = "block",
    max_repair_attempts: int = 3,
) -> dict[str, object]:
    return {
        "governance": {
            "enabled": enabled,
            "max_repair_attempts": max_repair_attempts,
            "on_exhausted": on_exhausted,
            "artifacts": {
                "feasibility": {
                    "tier": tier,
                    "template": "feasibility-template.md",
                    "verdict": {
                        "section": "Kill / Defer / Pass Decision",
                        "enum": ["PASS", "KILL", "DEFER"],
                    },
                },
                "intent-alignment-check": {
                    "tier": tier,
                    "template": "intent-alignment-check-template.md",
                    "verdict": {
                        "section": "Alignment Verdict",
                        "enum": ["ALIGNED", "DRIFT"],
                    },
                    "cross_refs": [{"ids": "REQ|FR|NFR", "against": "spec.md"}],
                },
            },
        }
    }


def _write_governance_artifacts(
    root: Path,
    *,
    feasibility: str = "valid",
    intent: str = "valid",
    write_spec: bool = True,
) -> Path:
    spec_dir = root / "specs"
    spec_dir.mkdir()
    if feasibility == "valid":
        (spec_dir / "feasibility.md").write_text(
            "# Feasibility\n\n"
            "## Metadata\nSpec: demo\n\n"
            "## Feasibility Verdict\nFeasible.\n\n"
            "## Key Risks\nNo blocking risks.\n\n"
            "## Kill / Defer / Pass Decision\nDecision: PASS\n",
            encoding="utf-8",
        )
    elif feasibility == "invalid":
        (spec_dir / "feasibility.md").write_text("# Incomplete\n", encoding="utf-8")
    if intent == "valid":
        (spec_dir / "intent-alignment-check.md").write_text(
            "# Intent Alignment Check\n\n"
            "## Metadata\nSpec: demo\n\n"
            "## Alignment Verdict\nVerdict: ALIGNED\n\n"
            "| User Intent | Gatekeeper Scope / Decision | Aligned? | Divergence |\n"
            "|---|---|---|---|\n"
            "| Intent | Scope | yes | none |\n\n"
            "## Divergence Points\nNo divergence found.\n\n"
            "## Required Action\nNo corrective action required.\n",
            encoding="utf-8",
        )
    elif intent == "invalid":
        (spec_dir / "intent-alignment-check.md").write_text(
            "# Incomplete\n", encoding="utf-8"
        )
    if write_spec:
        (spec_dir / "spec.md").write_text("# Spec\n\n## REQ-1\nRequired.\n", encoding="utf-8")
    return spec_dir


def _run(
    spec_dir: Path | None,
    *,
    artifact_key: str = "feasibility",
    config: dict[str, object] | None = None,
    previous_attempts: object = 0,
    iteration: object = 0,
    max_iterations: object = 5,
):
    return run_governance_structural_gate(
        artifact_key=artifact_key,
        spec_dir=spec_dir,
        extension_root=EXTENSION_ROOT,
        governance_config=config or _governance(),
        previous_attempts=previous_attempts,
        iteration=iteration,
        max_iterations=max_iterations,
    )


@pytest.mark.parametrize(
    ("artifact_key", "report_name"),
    [
        ("feasibility", "feasibility-structural-report.json"),
        (
            "intent-alignment-check",
            "intent-alignment-check-structural-report.json",
        ),
    ],
)
def test_valid_artifact_proceeds_with_versioned_report(
    tmp_path: Path, artifact_key: str, report_name: str
) -> None:
    result = _run(
        _write_governance_artifacts(tmp_path),
        artifact_key=artifact_key,
        previous_attempts=2,
    )

    assert result.action == "proceed"
    assert result.passed is True
    assert result.attempts == 0
    assert result.findings == 0
    assert result.report_path is not None
    assert result.report_path.name == report_name
    assert json.loads(result.report_path.read_text(encoding="utf-8")) == {
        "artifact": artifact_key,
        "findings": [],
        "ok": True,
        "path": str(
            result.report_path.parent
            / (
                "feasibility.md"
                if artifact_key == "feasibility"
                else "intent-alignment-check.md"
            )
        ),
        "schema_version": 1,
    }


def test_invalid_feasibility_requests_repair(tmp_path: Path) -> None:
    spec_dir = _write_governance_artifacts(tmp_path, feasibility="invalid")
    result = _run(spec_dir, previous_attempts=1)

    assert result.action == "repair"
    assert result.passed is False
    assert result.attempts == 2
    assert result.findings >= 1
    assert result.report_path is not None
    assert result.report_path.name == "feasibility-structural-report.json"


@pytest.mark.parametrize(
    ("artifact_key", "expected_code"),
    [
        ("feasibility", "missing-structural-artifact"),
        ("intent-alignment-check", "missing-cross-reference"),
    ],
)
def test_missing_inputs_are_reported_as_repairable(
    tmp_path: Path, artifact_key: str, expected_code: str
) -> None:
    spec_dir = _write_governance_artifacts(
        tmp_path,
        feasibility="missing" if artifact_key == "feasibility" else "valid",
        write_spec=artifact_key != "intent-alignment-check",
    )
    result = _run(spec_dir, artifact_key=artifact_key)

    assert result.action == "repair"
    assert result.attempts == 1
    assert result.report_path is not None
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert expected_code in {finding["code"] for finding in report["findings"]}


@pytest.mark.parametrize(
    ("enabled", "tier"),
    [(False, "structural"), (True, "semantic")],
)
def test_disabled_or_non_structural_gate_bypasses_without_report(
    tmp_path: Path, enabled: bool, tier: str
) -> None:
    result = _run(
        _write_governance_artifacts(tmp_path, feasibility="invalid"),
        config=_governance(enabled=enabled, tier=tier),
        previous_attempts=2,
    )

    assert result.action == "proceed"
    assert result.passed is True
    assert result.attempts == 0
    assert result.findings == 0
    assert result.report_path is None


@pytest.mark.parametrize(
    ("on_exhausted", "expected_action", "expected_reason"),
    [
        ("warn", "proceed_with_warning", None),
        ("block", "block", "governance_structural_exhausted"),
    ],
)
def test_repair_budget_exhaustion_uses_configured_policy(
    tmp_path: Path,
    on_exhausted: str,
    expected_action: str,
    expected_reason: str | None,
) -> None:
    result = _run(
        _write_governance_artifacts(tmp_path, feasibility="invalid"),
        config=_governance(on_exhausted=on_exhausted, max_repair_attempts=2),
        previous_attempts=1,
    )

    assert result.action == expected_action
    assert result.exhausted_artifact == "feasibility"
    assert result.blocked_reason == expected_reason


def test_workflow_iteration_exhaustion_warns(tmp_path: Path) -> None:
    result = _run(
        _write_governance_artifacts(tmp_path, feasibility="invalid"),
        config=_governance(on_exhausted="warn", max_repair_attempts=99),
        iteration=5,
        max_iterations=5,
    )

    assert result.action == "proceed_with_warning"
    assert result.exhausted_artifact == "feasibility"


def test_invalid_prior_attempts_are_normalized(tmp_path: Path) -> None:
    result = _run(
        _write_governance_artifacts(tmp_path, feasibility="invalid"),
        previous_attempts="invalid",
    )

    assert result.attempts == 1


def test_evidence_failure_blocks_without_spending_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_dir = _write_governance_artifacts(tmp_path)
    monkeypatch.setattr(
        "harness.governance_structural_gate._write_json_atomic",
        Mock(side_effect=OSError("disk full")),
    )
    result = _run(spec_dir, previous_attempts=2)

    assert result.action == "block"
    assert result.attempts == 2
    assert result.report_path is None
    assert result.blocked_reason == "governance_structural_evidence_write_failed"


@pytest.mark.parametrize("spec_dir", [None])
def test_missing_controller_context_blocks_without_report(spec_dir: None) -> None:
    result = _run(spec_dir, previous_attempts=2)

    assert result.action == "block"
    assert result.attempts == 2
    assert result.report_path is None
    assert result.blocked_reason == "governance_structural_spec_dir_invalid"


def test_state_updates_use_existing_persisted_field_names(tmp_path: Path) -> None:
    result = _run(
        _write_governance_artifacts(tmp_path, intent="invalid"),
        artifact_key="intent-alignment-check",
    )

    assert result.state_updates() == {
        "structural_action": "repair",
        "intent_alignment_check_structural_pass": False,
        "intent_alignment_check_structural_attempts": 1,
        "intent_alignment_check_structural_findings": result.findings,
        "intent_alignment_check_structural_report": str(result.report_path),
    }
