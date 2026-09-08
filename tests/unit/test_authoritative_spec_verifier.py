import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.candidate_evidence import CoverageGateResult, RunnabilityGateResult
from harness.config import HarnessConfig
from harness.fulfillment_runner import FulfillmentRefreshResult
from harness.verify_result import VerifyResult


@pytest.mark.unit
def test_authoritative_verifier_acquires_all_evidence_before_fulfillment(
    tmp_path: Path,
) -> None:
    from harness.authoritative_spec_verifier import AuthoritativeSpecVerifier

    target = tmp_path / "target"
    spec_dir = tmp_path / "specs" / "001-demo"
    target.mkdir()
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    standard = VerifyResult(
        passed=True,
        verification_evidence={"path": "/tmp/receipt.json", "passed": True},
    )
    runnable = VerifyResult(
        passed=True,
        verification_evidence={
            **standard.verification_evidence,
            "runnability_evidence": {"contract_hash": "contract"},
        },
    )
    complete = VerifyResult(
        passed=True,
        verification_evidence={
            **runnable.verification_evidence,
            "coverage_observation": {"path": "/tmp/coverage.json"},
        },
    )
    evidence_runner = MagicMock()
    evidence_runner.run_standard.return_value = standard
    evidence_runner.apply_runnability.return_value = RunnabilityGateResult(
        runnable, {"status": "runnable"}
    )
    observation = MagicMock()
    evidence_runner.apply_coverage.return_value = CoverageGateResult(
        complete,
        observation=observation,
        observer_required=True,
        state_summary={"status": "passed"},
    )
    fulfillment = MagicMock()
    fulfillment.refresh.return_value = FulfillmentRefreshResult(
        status="refreshed", exit_code=0
    )
    verifier = AuthoritativeSpecVerifier(
        target=target,
        spec_dir=spec_dir,
        config=HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
        ),
        evidence_runner=evidence_runner,
        fulfillment_runner=fulfillment,
    )

    result = verifier.run(reconcile=True, dry_run=False)

    assert result.status == "refreshed"
    evidence_runner.run_standard.assert_called_once()
    evidence_runner.apply_runnability.assert_called_once()
    evidence_runner.apply_coverage.assert_called_once()
    kwargs = fulfillment.refresh.call_args.kwargs
    assert kwargs["verification_evidence"] == complete.verification_evidence
    assert kwargs["coverage_observation"] is observation
    assert kwargs["observer_required"] is True
    assert Path(kwargs["verify_run_dir"]).is_dir()
    state = json.loads((Path(kwargs["verify_run_dir"]) / "state.json").read_text())
    assert state["standard_verification"] == "passed"
    assert state["user_runnability"]["status"] == "runnable"
    assert state["coverage_observation"]["status"] == "passed"


@pytest.mark.unit
def test_authoritative_verifier_blocks_evidence_failure_without_fulfillment(
    tmp_path: Path,
) -> None:
    from harness.authoritative_spec_verifier import AuthoritativeSpecVerifier
    from harness.verify_result import FailureCategory, FailureEntry

    target = tmp_path / "target"
    spec_dir = tmp_path / "specs" / "001-demo"
    target.mkdir()
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    failed = VerifyResult(
        passed=False,
        failures=[
            FailureEntry(
                category=FailureCategory.OTHER,
                id="sandbox-verification-unavailable",
                error="docker unavailable",
            )
        ],
    )
    evidence_runner = MagicMock()
    evidence_runner.run_standard.return_value = failed
    fulfillment = MagicMock()
    verifier = AuthoritativeSpecVerifier(
        target=target,
        spec_dir=spec_dir,
        config=HarnessConfig(
            target_repo=str(target),
            target_default_branch="main",
            provider="docker",
        ),
        evidence_runner=evidence_runner,
        fulfillment_runner=fulfillment,
    )

    result = verifier.run(reconcile=False, dry_run=False)

    assert result.status == "evidence_failed"
    assert result.failure_class == "environment_unavailable"
    fulfillment.refresh.assert_not_called()
    state = json.loads((result.verify_run_dir / "state.json").read_text())
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "sandbox-verification-unavailable"


@pytest.mark.unit
def test_authoritative_verifier_terminalizes_failed_fulfillment(
    tmp_path: Path,
) -> None:
    from harness.authoritative_spec_verifier import AuthoritativeSpecVerifier

    target = tmp_path / "target"
    spec_dir = tmp_path / "specs" / "001-demo"
    target.mkdir()
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    passed = VerifyResult(
        passed=True,
        verification_evidence={"path": "/tmp/receipt.json", "passed": True},
    )
    evidence_runner = MagicMock()
    evidence_runner.run_standard.return_value = passed
    evidence_runner.apply_runnability.return_value = RunnabilityGateResult(passed)
    evidence_runner.apply_coverage.return_value = CoverageGateResult(passed)
    fulfillment = MagicMock()
    fulfillment.refresh.return_value = FulfillmentRefreshResult(
        status="failed", exit_code=1, reason="semantic fulfillment failed"
    )
    verifier = AuthoritativeSpecVerifier(
        target=target,
        spec_dir=spec_dir,
        config=HarnessConfig(
            target_repo=str(target), target_default_branch="main", provider="docker"
        ),
        evidence_runner=evidence_runner,
        fulfillment_runner=fulfillment,
    )

    result = verifier.run(reconcile=False, dry_run=False)

    state = json.loads((result.verify_run_dir / "state.json").read_text())
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "semantic fulfillment failed"
