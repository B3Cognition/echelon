from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def _run_harness(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_validate_fulfillment_artifacts_cli_stamps_valid_state(tmp_path: Path) -> None:
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "# Requirement Audit\n\n"
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | functional | spec.md | Do thing | Signal |\n",
        encoding="utf-8",
    )
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "# Fulfillment Report\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | source_and_test |\n",
        encoding="utf-8",
    )
    canonical = tmp_path / "canonical-requirements.json"
    canonical.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")

    completed = _run_harness(
        [
            "validate-fulfillment-artifacts",
            str(audit),
            str(report),
            str(canonical),
            str(state),
        ]
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["fulfillment_artifacts"] == "valid"
    assert payload["fulfillment_artifacts_audit_count"] == 1
    assert payload["fulfillment_artifacts_report_count"] == 1


def test_validate_fulfillment_artifacts_cli_stamps_invalid_state(tmp_path: Path) -> None:
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "# Requirement Audit\n\n"
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | functional | spec.md | Do thing | Signal |\n",
        encoding="utf-8",
    )
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "# Fulfillment Report\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-999 | IMPLEMENTED | source_and_test |\n",
        encoding="utf-8",
    )
    canonical = tmp_path / "canonical-requirements.json"
    canonical.write_text(
        json.dumps({"requirements": [{"id": "FR-001"}]}),
        encoding="utf-8",
    )
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")

    completed = _run_harness(
        [
            "validate-fulfillment-artifacts",
            str(audit),
            str(report),
            str(canonical),
            str(state),
        ]
    )

    assert completed.returncode == 1
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["fulfillment_artifacts"] == "invalid"
    assert payload["fulfillment_artifacts_missing_in_report"] == ["FR-001"]
    assert payload["fulfillment_artifacts_extra_in_report"] == ["FR-999"]


def test_validate_fulfillment_artifacts_cli_requires_state_before_validation(
    tmp_path: Path,
) -> None:
    audit = tmp_path / "requirement-audit.md"
    report = tmp_path / "fulfillment-report.md"
    canonical = tmp_path / "canonical-requirements.json"
    state = tmp_path / "state.json"

    completed = _run_harness(
        [
            "validate-fulfillment-artifacts",
            str(audit),
            str(report),
            str(canonical),
            str(state),
        ]
    )

    assert completed.returncode == 1
    assert "state.json missing for verify-spec run:" in completed.stderr
    assert "Traceback" not in completed.stderr
