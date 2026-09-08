"""Authoritative standalone spec verification orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any

from harness.candidate_evidence import CandidateEvidenceRunner
from harness.config import HarnessConfig
from harness.durable_json import write_json_atomic
from harness.fulfillment_runner import FulfillmentRefreshResult, FulfillmentRunner
from harness.provider import SandboxProvider
from harness.verify_result import VerifyResult
from harness.verify_spec_run import block_verify_spec_run, init_verify_spec_run
from harness.verification_stack_runtime import build_verification_sandbox_spec


@dataclass(frozen=True)
class AuthoritativeSpecVerificationResult:
    status: str
    exit_code: int
    verify_run_dir: Path
    failure_class: str = ""
    reason: str = ""
    report_path: str | None = None
    verified_ledger: dict[str, int] | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.status in {"cached", "refreshed"}


class AuthoritativeSpecVerifier:
    """Acquire stack evidence, then invoke semantic fulfillment judgment."""

    def __init__(
        self,
        *,
        target: Path,
        spec_dir: Path,
        config: HarnessConfig,
        evidence_runner: Any | None = None,
        fulfillment_runner: FulfillmentRunner | Any,
        provider: SandboxProvider | None = None,
    ) -> None:
        self._target = Path(target).resolve()
        self._spec_dir = Path(spec_dir).resolve()
        self._config = config
        self._evidence_runner = evidence_runner
        self._fulfillment_runner = fulfillment_runner
        self._provider = provider

    def run(
        self,
        *,
        reconcile: bool,
        dry_run: bool,
    ) -> AuthoritativeSpecVerificationResult:
        initialized = init_verify_spec_run(
            project_root=self._target,
            spec_id=self._spec_dir.name,
            spec_dir=self._spec_dir,
            reconcile=reconcile,
            dry_run=dry_run,
        )
        runner = self._evidence_runner or self._build_evidence_runner(
            initialized.verify_run_dir
        )
        standard = runner.run_standard(
            handle=None,
            worktree=self._target,
            allow_legacy_structured=False,
        )
        self._update_state(
            initialized,
            standard_verification="passed" if standard.passed else "failed",
            standard_verification_evidence=dict(standard.verification_evidence),
        )
        if not standard.passed:
            return self._blocked(initialized.verify_run_dir, standard)

        runnability = runner.apply_runnability(
            verify_result=standard,
            worktree=self._target,
            spec_dir=self._spec_dir,
            candidate_commit=_current_git_commit(self._target),
            evidence_dir=initialized.verify_run_dir / "evidence" / "user-runnability",
        )
        self._update_state(
            initialized,
            user_runnability=(
                runnability.state_summary or {"status": "not_required"}
            ),
        )
        if not runnability.verify_result.passed:
            return self._blocked(initialized.verify_run_dir, runnability.verify_result)

        coverage = runner.apply_coverage(
            verify_result=runnability.verify_result,
            worktree=self._target,
            spec_dir=self._spec_dir,
            evidence_dir=initialized.verify_run_dir / "evidence" / "standalone",
        )
        self._update_state(
            initialized,
            coverage_observation=(
                coverage.state_summary or {"status": "not_required"}
            ),
        )
        if not coverage.verify_result.passed:
            return self._blocked(initialized.verify_run_dir, coverage.verify_result)

        fulfillment = self._fulfillment_runner.refresh(
            str(self._target),
            self._spec_dir.name,
            spec_dir=self._spec_dir,
            orchestration_root=initialized.orchestration_root,
            reconcile=reconcile,
            dry_run=dry_run,
            verification_evidence=dict(
                coverage.verify_result.verification_evidence
            ),
            coverage_observation=coverage.observation,
            observer_required=coverage.observer_required,
            verify_run_dir=initialized.verify_run_dir,
        )
        if not fulfillment.ok:
            state = json.loads(initialized.state_path.read_text(encoding="utf-8"))
            if state.get("status") in {"in_progress", "blocked"}:
                block_verify_spec_run(
                    initialized.verify_run_dir,
                    reason=fulfillment.reason or "fulfillment verification failed",
                )
        return _from_fulfillment(fulfillment, initialized.verify_run_dir)

    def _build_evidence_runner(self, verify_run_dir: Path) -> CandidateEvidenceRunner:
        if self._provider is None:
            raise RuntimeError("authoritative verification requires a sandbox provider")
        return CandidateEvidenceRunner(
            provider=self._provider,
            config=self._config,
            sandbox_spec_factory=lambda worktree: build_verification_sandbox_spec(
                self._config,
                worktree=worktree,
                spec_id=self._spec_dir.name,
                strategy_id="standalone",
                run_id=verify_run_dir.name,
            ),
            evidence_root=verify_run_dir / "evidence",
            spec_id=self._spec_dir.name,
            target_id=self._target.name,
            strategy_id="standalone",
            build_id=verify_run_dir.name,
            runtime_root=self._spec_dir.parent.parent / ".echelon" / "runtime",
        )

    @staticmethod
    def _update_state(initialized: Any, **updates: object) -> None:
        state = json.loads(initialized.state_path.read_text(encoding="utf-8"))
        state.update(updates)
        write_json_atomic(
            initialized.state_path,
            state,
            trusted_root=initialized.orchestration_root,
        )

    @staticmethod
    def _blocked(
        verify_run_dir: Path,
        result: VerifyResult,
    ) -> AuthoritativeSpecVerificationResult:
        reason = result.failures[0].id if result.failures else "evidence-acquisition-failed"
        block_verify_spec_run(verify_run_dir, reason=reason)
        return AuthoritativeSpecVerificationResult(
            status="evidence_failed",
            exit_code=1,
            verify_run_dir=verify_run_dir,
            failure_class=_failure_class(result),
            reason=reason,
        )


def _from_fulfillment(
    result: FulfillmentRefreshResult,
    verify_run_dir: Path,
) -> AuthoritativeSpecVerificationResult:
    return AuthoritativeSpecVerificationResult(
        status=result.status,
        exit_code=result.exit_code,
        verify_run_dir=verify_run_dir,
        reason=result.reason,
        report_path=result.report_path,
        verified_ledger=result.verified_ledger,
    )


def _failure_class(result: VerifyResult) -> str:
    identifiers = {failure.id for failure in result.failures}
    if any(
        identifier == "sandbox-verification-unavailable"
        or identifier == "user-runnability-sandbox-prerequisite"
        or identifier == "coverage-observer-unavailable"
        for identifier in identifiers
    ):
        return "environment_unavailable"
    if any(
        identifier.endswith("evidence-invalid")
        or identifier in {
            "coverage-observation-invalid",
            "coverage-observer-receipt-missing",
        }
        for identifier in identifiers
    ):
        return "harness_error"
    return "candidate_failure"


def _current_git_commit(target: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""
