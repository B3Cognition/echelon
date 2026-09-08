"""Shared harness-owned acquisition of candidate verification evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Callable, Mapping

from harness.config import HarnessConfig
from harness.browser_runtime import is_transient_browser_runtime_failure
from harness.canonical_requirements import extract_canonical_requirements
from harness.coverage_evidence import (
    active_unmapped_coverage_requirement_ids,
    parse_coverage_map_obligations,
)
from harness.coverage_observation import (
    CoverageObservationError,
    CoverageObservationResult,
    write_coverage_observation,
)
from harness.coverage_observer_runner import run_coverage_observers
from harness.deferred_scope import active_entries
from harness.errors import NotSupportedError, SandboxError
from harness.product_inventory import product_evidence_fingerprint
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.runnability_contract import (
    CONTRACT_PATH as RUNNABILITY_CONTRACT_PATH,
    RunnabilityContractError,
    load_runnability_contract,
)
from harness.runnability_disposition import (
    RunnabilityDispositionError,
    read_runnability_disposition,
)
from harness.runnability_runner import RunnabilityRunResult, RunnabilityRunner
from harness.stacks.preflight import (
    coverage_observer_preflight_findings,
    required_coverage_observers_for_types,
)
from harness.stacks.resolver import (
    resolved_coverage_observer_plan_sha256,
    resolved_stack_contract_sha256,
)
from harness.verify_detection import detect_verify_command
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult
from harness.verification_evidence import (
    VerificationEvidenceRef,
    VerificationStage,
    write_verification_receipt,
)
from harness.verification_plan import build_verification_plan, materialize_services


@dataclass(frozen=True)
class RunnabilityGateResult:
    verify_result: VerifyResult
    state_summary: dict[str, object] | None = None


@dataclass(frozen=True)
class CoverageGateResult:
    verify_result: VerifyResult
    observation: CoverageObservationResult | None = None
    observer_required: bool = False
    state_summary: dict[str, object] | None = None


class CandidateEvidenceRunner:
    """Acquire immutable candidate evidence without using an LLM or user host."""

    def __init__(
        self,
        *,
        provider: SandboxProvider,
        config: HarnessConfig | Callable[[], HarnessConfig],
        sandbox_spec_factory: Callable[[Path], SandboxSpec],
        evidence_root: Path,
        spec_id: str,
        target_id: str,
        strategy_id: str,
        build_id: str,
        runtime_root: Path | None = None,
        sensitive_environment: Mapping[str, str] | None = None,
    ) -> None:
        self._provider = provider
        self._config_source = config
        self._sandbox_spec_factory = sandbox_spec_factory
        self._evidence_root = Path(evidence_root)
        self._spec_id = spec_id
        self._target_id = target_id
        self._strategy_id = strategy_id
        self._build_id = build_id
        self._runtime_root = Path(runtime_root).resolve() if runtime_root else None
        self._sensitive_environment = sensitive_environment or os.environ

    def run_standard(
        self,
        *,
        handle: SandboxHandle | None,
        worktree: Path,
        allow_legacy_structured: bool = False,
    ) -> VerifyResult:
        """Run ordinary verification in a managed sandbox and retain a receipt."""
        candidate = Path(worktree)
        config = self._config()
        owned_handle = False
        try:
            if handle is None:
                handle = self._provider.create(self._sandbox_spec_factory(candidate))
                owned_handle = True
            plan = build_verification_plan(
                candidate,
                config,
                services=tuple(config.verification_services),
            )
            service_env: dict[str, str] = {}
            stages: list[VerificationStage] = []
            if plan.services:
                materialized = materialize_services(
                    plan.services, session_id=handle.session_id
                )
                self._provider.start_services(handle, materialized.services)
                service_env = dict(materialized.verifier_environment)

            fingerprint_before = _candidate_fingerprint(candidate)
            candidate_commit = _current_git_commit(candidate)
            execution_context = {
                "mode": "sandbox",
                "image": plan.image,
                "network": "internal",
                "services": [service.service_name for service in plan.services],
            }
            for command in plan.bootstrap_commands:
                started_at = _now()
                result = self._provider.exec(
                    handle, command, env=service_env, timeout_ms=600_000
                )
                stages.append(_stage("bootstrap", command, result, started_at))
                if result.exit_code != 0:
                    failures = [
                        FailureEntry(
                            category=FailureCategory.BUILD,
                            id="sandbox-bootstrap",
                            error=(result.stdout + result.stderr)[-2000:],
                        )
                    ]
                    return self._attach_receipt(
                        candidate=candidate,
                        candidate_commit=candidate_commit,
                        fingerprint_before=fingerprint_before,
                        stages=tuple(stages),
                        failures=failures,
                        duration_s=result.duration_ms / 1000.0,
                        detection_evidence=("sandbox bootstrap",),
                        execution_context=execution_context,
                    )

            command = config.verify_command
            detection_evidence: tuple[str, ...] = ("harness verify_command",)
            legacy_structured = False
            if not command:
                if allow_legacy_structured:
                    command = "echelon verify"
                    legacy_structured = True
                else:
                    detection = detect_verify_command(candidate)
                    if detection.command is None:
                        return VerifyResult(
                            passed=False,
                            failures=[
                                FailureEntry(
                                    category=FailureCategory.BUILD,
                                    id="local-verify-skipped",
                                    error=(
                                        "no high-confidence verifier was detected; "
                                        "set harness.verify_command"
                                    ),
                                )
                            ],
                        )
                    command = detection.command
                    detection_evidence = tuple(detection.evidence)

            started_at = _now()
            result = self._provider.exec(
                handle, command, env=service_env, timeout_ms=600_000
            )
            if legacy_structured:
                try:
                    return VerifyResult.from_dict(json.loads(result.stdout))
                except (json.JSONDecodeError, TypeError, ValueError):
                    return VerifyResult(
                        passed=result.exit_code == 0,
                        failures=[]
                        if result.exit_code == 0
                        else [
                            FailureEntry(
                                category=FailureCategory.TEST,
                                id="verify-command",
                                error=(result.stdout + result.stderr)[-2000:],
                            )
                        ],
                        duration_s=result.duration_ms / 1000.0,
                        token_usage=_estimate_tokens(result.stdout, result.stderr),
                    )

            if result.exit_code != 0 and is_transient_browser_runtime_failure(
                result.stdout, result.stderr
            ):
                transient_failure = FailureEntry(
                    category=FailureCategory.OTHER,
                    id="transient-browser-runtime",
                    error=(result.stdout + result.stderr)[-2000:],
                )
                recorded = self._attach_receipt(
                    candidate=candidate,
                    candidate_commit=candidate_commit,
                    fingerprint_before=fingerprint_before,
                    stages=(*stages, _stage("verify", command, result, started_at)),
                    failures=[transient_failure],
                    duration_s=result.duration_ms / 1000.0,
                    detection_evidence=(
                        "sandbox provider",
                        *detection_evidence,
                        "transient browser runtime failure",
                    ),
                    execution_context=execution_context,
                )
                if any(
                    failure.id == "verification-evidence-invalid"
                    for failure in recorded.failures
                ):
                    return recorded
                retry_stages: list[VerificationStage] = []
                if owned_handle:
                    self._provider.destroy(handle)
                    handle = self._provider.create(self._sandbox_spec_factory(candidate))
                    service_env = {}
                    if plan.services:
                        materialized = materialize_services(
                            plan.services, session_id=handle.session_id
                        )
                        self._provider.start_services(handle, materialized.services)
                        service_env = dict(materialized.verifier_environment)
                    for bootstrap_command in plan.bootstrap_commands:
                        bootstrap_started_at = _now()
                        bootstrap_result = self._provider.exec(
                            handle,
                            bootstrap_command,
                            env=service_env,
                            timeout_ms=600_000,
                        )
                        retry_stages.append(
                            _stage(
                                "bootstrap",
                                bootstrap_command,
                                bootstrap_result,
                                bootstrap_started_at,
                            )
                        )
                        if bootstrap_result.exit_code != 0:
                            return self._attach_receipt(
                                candidate=candidate,
                                candidate_commit=candidate_commit,
                                fingerprint_before=fingerprint_before,
                                stages=tuple(retry_stages),
                                failures=[
                                    FailureEntry(
                                        category=FailureCategory.BUILD,
                                        id="sandbox-bootstrap",
                                        error=(
                                            bootstrap_result.stdout
                                            + bootstrap_result.stderr
                                        )[-2000:],
                                    )
                                ],
                                duration_s=bootstrap_result.duration_ms / 1000.0,
                                detection_evidence=(
                                    "fresh sandbox after transient browser runtime failure",
                                ),
                                execution_context=execution_context,
                            )
                started_at = _now()
                result = self._provider.exec(
                    handle, command, env=service_env, timeout_ms=600_000
                )
                stages = retry_stages
                detection_evidence = (
                    *detection_evidence,
                    "one automatic fresh-sandbox browser runtime retry",
                )

            failures = []
            if result.exit_code != 0:
                transient_after_retry = (
                    "one automatic fresh-sandbox browser runtime retry"
                    in detection_evidence
                    and is_transient_browser_runtime_failure(
                        result.stdout, result.stderr
                    )
                )
                failures.append(
                    FailureEntry(
                        category=(
                            FailureCategory.OTHER
                            if transient_after_retry
                            else FailureCategory.TEST
                        ),
                        id=(
                            "sandbox-browser-runtime-unavailable"
                            if transient_after_retry
                            else "verify-command"
                        ),
                        error=(result.stdout + result.stderr)[-2000:],
                    )
                )
            return self._attach_receipt(
                candidate=candidate,
                candidate_commit=candidate_commit,
                fingerprint_before=fingerprint_before,
                stages=(*stages, _stage("verify", command, result, started_at)),
                failures=failures,
                duration_s=result.duration_ms / 1000.0,
                detection_evidence=("sandbox provider", *detection_evidence),
                execution_context=execution_context,
            )
        except (NotSupportedError, SandboxError) as exc:
            return VerifyResult(
                passed=False,
                failures=[
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="sandbox-verification-unavailable",
                        error=str(exc),
                    )
                ],
            )
        finally:
            if owned_handle and handle is not None:
                self._provider.destroy(handle)

    def apply_runnability(
        self,
        *,
        verify_result: VerifyResult,
        worktree: Path,
        spec_dir: Path | None,
        candidate_commit: str,
        evidence_dir: Path,
    ) -> RunnabilityGateResult:
        """Apply the owner/stack-controlled composed journey gate."""
        if not verify_result.passed:
            return RunnabilityGateResult(verify_result)
        config = self._config()
        policy = str(
            getattr(
                getattr(config, "resolved_runnability", None),
                "policy",
                "not_applicable",
            )
        )
        required = policy == "required"
        if spec_dir is not None:
            try:
                disposition = read_runnability_disposition(spec_dir)
            except RunnabilityDispositionError as exc:
                return RunnabilityGateResult(
                    _gate_failure(
                        verify_result,
                        "user-runnability-disposition-invalid",
                        f"Owner runnability disposition is invalid: {exc}",
                        {"disposition": str(spec_dir / "runnability-disposition.json")},
                    )
                )
            if disposition is not None and disposition.status == "deferred":
                return RunnabilityGateResult(
                    verify_result,
                    {
                        "status": "deferred",
                        "failed_stage": None,
                        "failure_class": "owner_deferred",
                        "summary": disposition.reason,
                        "report": disposition.evidence_report,
                        "candidate_fingerprint": "",
                        "contract_hash": "",
                        "stack_hash": "",
                        "user_commands": {},
                    },
                )

        contract_path = worktree / RUNNABILITY_CONTRACT_PATH
        if not contract_path.exists():
            if not required:
                return RunnabilityGateResult(verify_result)
            return RunnabilityGateResult(
                _gate_failure(
                    verify_result,
                    "user-runnability-contract-missing",
                    "Selected stacks require a composed user-runnability journey, "
                    f"but {RUNNABILITY_CONTRACT_PATH} is missing from the candidate.",
                    {
                        "contract": str(RUNNABILITY_CONTRACT_PATH),
                        "required_repair": (
                            "Add the project-owned runnability contract and real journey."
                        ),
                    },
                )
            )
        try:
            contract = load_runnability_contract(worktree)
        except (OSError, RunnabilityContractError) as exc:
            return RunnabilityGateResult(
                _gate_failure(
                    verify_result,
                    "user-runnability-contract-invalid",
                    f"Candidate runnability contract is invalid: {exc}",
                    {
                        "contract": str(RUNNABILITY_CONTRACT_PATH),
                        "required_repair": "Repair the candidate-owned runnability contract.",
                    },
                )
            )
        if contract is None:
            return RunnabilityGateResult(
                _gate_failure(
                    verify_result,
                    "user-runnability-contract-missing",
                    "Selected stacks require a composed user-runnability journey, "
                    f"but {RUNNABILITY_CONTRACT_PATH} is missing from the candidate.",
                    {
                        "contract": str(RUNNABILITY_CONTRACT_PATH),
                        "required_repair": (
                            "Add the project-owned runnability contract and real journey."
                        ),
                    },
                )
            )
        if not contract.enabled:
            if not required:
                return RunnabilityGateResult(verify_result)
            return RunnabilityGateResult(
                _gate_failure(
                    verify_result,
                    "user-runnability-contract-disabled",
                    "A candidate contract cannot disable a stack-required runnability gate.",
                    {
                        "contract": str(RUNNABILITY_CONTRACT_PATH),
                        "required_repair": (
                            "Enable and complete the candidate runnability contract."
                        ),
                    },
                )
            )
        resolved = getattr(config, "resolved_stacks", None)
        if resolved is None:
            return RunnabilityGateResult(
                _gate_failure(
                    verify_result,
                    "user-runnability-stack-resolution-missing",
                    "Resolved stack evidence is unavailable for the runnability gate.",
                    {"required_repair": "Rerun with resolved stack runtime data."},
                )
            )
        result = RunnabilityRunner(
            provider=self._provider,
            sandbox_spec_factory=self._sandbox_spec_factory,
            spec_id=self._spec_id,
            target_id=self._target_id,
            strategy_id=self._strategy_id,
            build_id=self._build_id,
            browser_helper=self._browser_helper(worktree),
        ).run(
            worktree=worktree,
            contract=contract,
            resolved=resolved,
            candidate_commit=candidate_commit,
            evidence_dir=evidence_dir,
            attempt_sequence=_next_runnability_attempt(evidence_dir),
        )
        summary = _runnability_summary(result)
        if result.status == "runnable":
            evidence = dict(verify_result.verification_evidence)
            evidence["runnability_evidence"] = result.evidence.as_mapping()
            return RunnabilityGateResult(
                VerifyResult(
                    passed=True,
                    failures=list(verify_result.failures),
                    duration_s=verify_result.duration_s,
                    token_usage=verify_result.token_usage,
                    verification_evidence=evidence,
                ),
                summary,
            )
        report = str(result.evidence.markdown_path)
        failure_id = (
            "user-runnability-sandbox-prerequisite"
            if result.failure_class == "sandbox_prerequisite_missing"
            else f"user-runnability-{result.failure_class.replace('_', '-')}"
        )
        repair = (
            "Repair the sandbox/provider prerequisite and retry."
            if result.failure_class == "sandbox_prerequisite_missing"
            else "Repair the candidate product or .echelon/runnability.yml, then retry."
        )
        return RunnabilityGateResult(
            _gate_failure(
                verify_result,
                failure_id,
                f"User runnability {result.failure_class} failed at "
                f"{result.failed_stage or 'unknown'}: {result.summary}. Evidence: {report}",
                {
                    "failed_stage": result.failed_stage,
                    "failure_class": result.failure_class,
                    "summary": result.summary,
                    "report": report,
                    "required_repair": repair,
                },
            ),
            summary,
        )

    def apply_coverage(
        self,
        *,
        verify_result: VerifyResult,
        worktree: Path,
        spec_dir: Path | None,
        evidence_dir: Path,
        required_case_ids: set[str] | None = None,
    ) -> CoverageGateResult:
        """Apply required per-requirement coverage observation.

        ``required_case_ids`` scopes an intermediate delivery slice to test
        obligations owned by tasks already completed.  ``None`` remains the
        full-map, fail-closed contract used by standalone verification and by
        a fully completed delivery.
        """
        if not verify_result.passed:
            return CoverageGateResult(verify_result)
        config = self._config()
        resolved = getattr(config, "resolved_stacks", None)
        required = tuple(
            item
            for item in getattr(resolved, "coverage_observers", ())
            if item.observer.required
        )
        if not required:
            return CoverageGateResult(verify_result)
        if spec_dir is None:
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observer-spec-missing",
                    "Required coverage observers could not find the active spec.",
                ),
                observer_required=True,
            )
        coverage_map = spec_dir / "coverage-map.md"
        if not coverage_map.is_file():
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observer-map-missing",
                    "Required coverage observers need the spec coverage-map.md.",
                ),
                observer_required=True,
            )
        try:
            canonical_ids = {
                item.id for item in extract_canonical_requirements(spec_dir)
            }
            obligations = tuple(
                obligation
                for row in parse_coverage_map_obligations(
                    coverage_map, canonical_ids
                )
                for obligation in row
            )
            deferred_ids = {
                item_id
                for entry in active_entries(spec_dir)
                for item_id in entry.selected_ids
                if not item_id.startswith("T-")
            }
            unmapped = active_unmapped_coverage_requirement_ids(
                canonical_ids=canonical_ids,
                obligations=obligations,
                deferred_ids=deferred_ids,
            )
            if unmapped:
                return CoverageGateResult(
                    _coverage_failure(
                        verify_result,
                        "coverage-observer-map-incomplete",
                        "Required coverage observation has no planned test obligation "
                        "for active requirement(s): " + ", ".join(unmapped[:20]),
                    ),
                    observer_required=True,
                )
            obligations = tuple(
                item for item in obligations if item.requirement_id not in deferred_ids
            )
            if required_case_ids is not None:
                available_case_ids = {item.test_case_id for item in obligations}
                missing_case_ids = sorted(required_case_ids - available_case_ids)
                if missing_case_ids:
                    return CoverageGateResult(
                        _coverage_failure(
                            verify_result,
                            "coverage-observer-scope-invalid",
                            "Completed task coverage ownership is absent from "
                            "coverage-map.md: " + ", ".join(missing_case_ids[:20]),
                        ),
                        observer_required=True,
                    )
                obligations = tuple(
                    item
                    for item in obligations
                    if item.test_case_id in required_case_ids
                )
            coverage_map_hash = hashlib.sha256(coverage_map.read_bytes()).hexdigest()
            contract_hash = _runnability_contract_hash(verify_result)
            if (
                str(getattr(resolved.runnability, "policy", "not_applicable"))
                == "required"
                and contract_hash is None
            ):
                raise CoverageObservationError(
                    "required runnability contract evidence is missing"
                )
        except (CoverageObservationError, OSError, ValueError) as exc:
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observer-contract-invalid",
                    f"Coverage observation inputs are invalid: {exc}",
                ),
                observer_required=True,
            )
        if not obligations:
            return CoverageGateResult(
                verify_result,
                observer_required=False,
                state_summary={
                    "status": "not_required",
                    "reason": (
                        "completed tasks own no coverage obligations"
                        if required_case_ids is not None
                        else "all planned coverage requirements are owner-deferred"
                    ),
                },
            )
        test_types = {item.test_type for item in obligations}
        unavailable = coverage_observer_preflight_findings(
            resolved, coverage_test_types=test_types
        )
        if unavailable:
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observer-unavailable",
                    "; ".join(item.message for item in unavailable),
                ),
                observer_required=True,
            )
        observers = required_coverage_observers_for_types(
            resolved, coverage_test_types=test_types
        )
        if not observers:
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observer-unavailable",
                    "Required coverage observers could not select an observer for "
                    "the planned coverage test types.",
                ),
                observer_required=True,
            )
        candidate_commit = _current_git_commit(worktree)
        candidate_fingerprint = _candidate_fingerprint(worktree)
        if not candidate_commit or not candidate_fingerprint:
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observer-candidate-invalid",
                    "Required coverage observers could not bind execution to the "
                    "candidate commit and product fingerprint.",
                ),
                observer_required=True,
            )
        standard_receipt = _verification_receipt(verify_result)
        if standard_receipt is None:
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observer-standard-evidence-missing",
                    "Required coverage observers need the passed sandbox verification "
                    "receipt, but none was attached.",
                ),
                observer_required=True,
            )
        bundle = run_coverage_observers(
            provider=self._provider,
            sandbox_spec_factory=self._sandbox_spec_factory,
            worktree=worktree,
            config=config,
            observers=observers,
            standard_receipt=standard_receipt,
            candidate_commit=candidate_commit,
            candidate_fingerprint=candidate_fingerprint,
            evidence_dir=evidence_dir,
            spec_id=self._spec_id,
            target_id=self._target_id,
            strategy_id=self._strategy_id,
            build_id=self._build_id,
            sensitive_environment=self._sensitive_environment,
        )
        observer_evidence = {
            run.observer_id: {
                "status": run.status,
                "reason": run.reason,
                "failure_kind": run.failure_kind,
                "receipt": run.receipt.as_mapping() if run.receipt else None,
                "execution_count": len(run.executions),
            }
            for run in bundle.observer_runs
        }
        failed = [run for run in bundle.observer_runs if run.status != "passed"]
        if failed:
            browser_runtime_unavailable = any(
                run.failure_kind == "browser_runtime_unavailable" for run in failed
            )
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    (
                        "sandbox-browser-runtime-unavailable"
                        if browser_runtime_unavailable
                        else "coverage-observer-failed"
                    ),
                    "; ".join(
                        f"{run.observer_id}: {run.reason or 'observer did not pass'}"
                        for run in failed
                    ),
                    observer_evidence,
                ),
                observer_required=True,
                state_summary={"status": "failed", "observers": observer_evidence},
            )
        receipts = {
            run.observer_id: run.receipt
            for run in bundle.observer_runs
            if run.receipt is not None
        }
        if len(receipts) != len(observers):
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observer-receipt-missing",
                    "A required coverage observer did not retain a receipt.",
                    observer_evidence,
                ),
                observer_required=True,
            )
        try:
            observation = write_coverage_observation(
                evidence_dir=evidence_dir,
                candidate_commit=candidate_commit,
                candidate_fingerprint=candidate_fingerprint,
                coverage_map_hash=coverage_map_hash,
                resolved_stack_hash=resolved_stack_contract_sha256(resolved),
                observer_plan_hash=resolved_coverage_observer_plan_sha256(resolved),
                runnability_contract_hash=contract_hash,
                verification_receipt=bundle.standard_receipt,
                observer_receipts=receipts,
                observer_test_types={
                    item.observer.id: item.observer.test_types for item in observers
                },
                obligations=obligations,
                executions=tuple(
                    execution
                    for run in bundle.observer_runs
                    for execution in run.executions
                ),
                candidate_worktree=worktree,
                attempt_sequence=_next_coverage_attempt(evidence_dir),
                sensitive_environment=self._sensitive_environment,
            )
        except (CoverageObservationError, OSError, ValueError) as exc:
            return CoverageGateResult(
                _coverage_failure(
                    verify_result,
                    "coverage-observation-invalid",
                    f"Coverage observation could not be recorded: {exc}",
                    observer_evidence,
                ),
                observer_required=True,
            )
        evidence = dict(verify_result.verification_evidence)
        evidence["coverage_observation"] = observation.ref.as_mapping()
        evidence["coverage_observers"] = observer_evidence
        summary = _coverage_summary(observation, observer_evidence)
        if observation.ref.passed:
            return CoverageGateResult(
                VerifyResult(
                    passed=True,
                    failures=list(verify_result.failures),
                    duration_s=verify_result.duration_s,
                    token_usage=verify_result.token_usage,
                    verification_evidence=evidence,
                ),
                observation=observation,
                observer_required=True,
                state_summary=summary,
            )
        unresolved = [
            f"{requirement_id}: {item.reason}"
            for requirement_id, item in sorted(observation.requirements.items())
            if item.status != "observed"
        ]
        return CoverageGateResult(
            VerifyResult(
                passed=False,
                failures=[
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="coverage-observation-gaps",
                        error="Required coverage observations did not pass: "
                        + "; ".join(unresolved[:20]),
                        details={
                            "observation": observation.ref.as_mapping(),
                            "requirements": {
                                key: value.status
                                for key, value in observation.requirements.items()
                                if value.status != "observed"
                            },
                            "test_cases": {
                                key: {
                                    "test_type": value.test_type,
                                    "status": value.status,
                                    "reason": value.reason,
                                }
                                for key, value in observation.test_cases.items()
                                if value.status != "passed"
                            },
                        },
                    )
                ],
                duration_s=verify_result.duration_s,
                token_usage=verify_result.token_usage,
                verification_evidence=evidence,
            ),
            observation=observation,
            observer_required=True,
            state_summary=summary,
        )

    def _browser_helper(self, worktree: Path) -> bytes | None:
        candidates = []
        if self._runtime_root is not None:
            candidates.append(
                self._runtime_root / "scripts" / "user-runnability-browser.mjs"
            )
        candidates.append(
            Path(worktree)
            / ".echelon"
            / "runtime"
            / "scripts"
            / "user-runnability-browser.mjs"
        )
        for candidate in candidates:
            try:
                return candidate.read_bytes()
            except OSError:
                continue
        return None

    def _config(self) -> HarnessConfig:
        return (
            self._config_source()
            if callable(self._config_source)
            else self._config_source
        )

    def _attach_receipt(
        self,
        *,
        candidate: Path,
        candidate_commit: str | None,
        fingerprint_before: str | None,
        stages: tuple[VerificationStage, ...],
        failures: list[FailureEntry],
        duration_s: float,
        detection_evidence: tuple[str, ...],
        execution_context: Mapping[str, object],
    ) -> VerifyResult:
        fingerprint_after = _candidate_fingerprint(candidate)
        missing = [
            name
            for name, value in (
                ("candidate commit", candidate_commit),
                ("pre-verification fingerprint", fingerprint_before),
                ("post-verification fingerprint", fingerprint_after),
            )
            if not value
        ]
        if missing:
            return VerifyResult(
                passed=False,
                failures=[
                    *failures,
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="verification-evidence-invalid",
                        error=(
                            "could not bind verification to the candidate commit and "
                            "content fingerprint; missing " + ", ".join(missing)
                        ),
                    ),
                ],
                duration_s=duration_s,
            )
        if fingerprint_before != fingerprint_after:
            failures.append(
                FailureEntry(
                    category=FailureCategory.OTHER,
                    id="candidate-mutated-during-verification",
                    error="sandbox verification changed bounded candidate content",
                )
            )
        evidence_dir = self._evidence_root / self._strategy_id / "verification"
        try:
            ref = write_verification_receipt(
                evidence_dir=evidence_dir,
                spec_id=self._spec_id,
                target_id=self._target_id,
                strategy_id=self._strategy_id,
                build_id=self._build_id,
                candidate_commit=candidate_commit,
                fingerprint_before=fingerprint_before,
                fingerprint_after=fingerprint_after,
                verifier_source="sandbox",
                detection_evidence=detection_evidence,
                execution_context=execution_context,
                stages=stages,
                attempt_sequence=_next_attempt(evidence_dir),
                sensitive_environment=self._sensitive_environment,
                started_at=stages[0].started_at if stages else None,
            )
        except (OSError, ValueError) as exc:
            return VerifyResult(
                passed=False,
                failures=[
                    *failures,
                    FailureEntry(
                        category=FailureCategory.OTHER,
                        id="verification-evidence-invalid",
                        error=f"could not persist verification evidence: {exc}",
                    ),
                ],
                duration_s=duration_s,
            )
        return VerifyResult(
            passed=ref.passed and not failures,
            failures=failures,
            duration_s=duration_s,
            token_usage=sum(
                _estimate_tokens(
                    stage.stdout.decode(errors="replace"),
                    stage.stderr.decode(errors="replace"),
                )
                for stage in stages
            ),
            verification_evidence=ref.as_mapping(),
        )


def _stage(name: str, command: str, result: object, started_at: str) -> VerificationStage:
    return VerificationStage(
        name=name,
        command=tuple(shlex.split(command)),
        exit_code=int(getattr(result, "exit_code")),
        duration_ms=int(getattr(result, "duration_ms")),
        stdout=str(getattr(result, "stdout")).encode(),
        stderr=str(getattr(result, "stderr")).encode(),
        started_at=started_at,
        completed_at=_now(),
    )


def _candidate_fingerprint(candidate: Path) -> str | None:
    try:
        return product_evidence_fingerprint(candidate)
    except (OSError, ValueError):
        return None


def _current_git_commit(candidate: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=candidate,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _next_attempt(evidence_dir: Path) -> int:
    highest = 0
    for path in evidence_dir.glob("attempt-*.json") if evidence_dir.exists() else ():
        match = re.match(r"attempt-(\d+)-", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _next_runnability_attempt(evidence_dir: Path) -> int:
    highest = 0
    for path in evidence_dir.glob("attempt-*.json") if evidence_dir.exists() else ():
        match = re.match(r"attempt-(\d+)-", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _next_coverage_attempt(evidence_dir: Path) -> int:
    root = evidence_dir / "coverage-observation"
    highest = 0
    for path in root.glob("attempt-*.json") if root.exists() else ():
        match = re.match(r"attempt-(\d+)-", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _verification_receipt(result: VerifyResult) -> VerificationEvidenceRef | None:
    try:
        return VerificationEvidenceRef.from_mapping(result.verification_evidence)
    except (TypeError, ValueError):
        return None


def _runnability_contract_hash(result: VerifyResult) -> str | None:
    raw = result.verification_evidence.get("runnability_evidence")
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("contract_hash")
    return str(value) if isinstance(value, str) and value else None


def _coverage_summary(
    observation: CoverageObservationResult,
    observer_evidence: Mapping[str, object],
) -> dict[str, object]:
    fingerprints = {
        key: str(observation.fingerprints.get(key) or "")
        for key in (
            "coverage_map_hash",
            "resolved_stack_hash",
            "observer_plan_hash",
            "runnability_contract_hash",
        )
        if observation.fingerprints.get(key)
    }
    fingerprints["candidate_fingerprint"] = observation.ref.candidate_fingerprint
    return {
        "status": "passed" if observation.ref.passed else "failed",
        "path": str(observation.ref.path),
        "ref": observation.ref.as_mapping(),
        "requirements_observed": sum(
            item.status == "observed" for item in observation.requirements.values()
        ),
        "requirements_total": len(observation.requirements),
        "observers": dict(observer_evidence),
        "fingerprints": fingerprints,
    }


def _coverage_failure(
    source: VerifyResult,
    failure_id: str,
    error: str,
    observer_evidence: Mapping[str, object] | None = None,
) -> VerifyResult:
    evidence = dict(source.verification_evidence)
    if observer_evidence is not None:
        evidence["coverage_observers"] = dict(observer_evidence)
    return VerifyResult(
        passed=False,
        failures=[
            FailureEntry(
                category=FailureCategory.OTHER,
                id=failure_id,
                error=error,
            )
        ],
        duration_s=source.duration_s,
        token_usage=source.token_usage,
        verification_evidence=evidence,
    )


def _runnability_summary(result: RunnabilityRunResult) -> dict[str, object]:
    summary: dict[str, object] = {
        "status": result.status,
        "failed_stage": result.failed_stage,
        "failure_class": result.failure_class,
        "summary": result.summary,
        "report": str(result.evidence.markdown_path),
        "candidate_fingerprint": result.candidate_fingerprint,
        "contract_hash": result.contract_hash,
        "stack_hash": result.stack_hash,
        "user_commands": {
            key: list(commands) for key, commands in result.user_commands.items()
        },
    }
    if result.local_journey_status != "not_required" or result.local_user_commands:
        local: dict[str, object] = {
            "status": result.local_journey_status,
            "reason": result.local_journey_reason,
            "commands": {
                key: list(commands)
                for key, commands in result.local_user_commands.items()
            },
        }
        if result.local_boundary_probes:
            local["boundary_probes"] = [
                {
                    "id": probe.id,
                    "service": probe.service,
                    "command": probe.command,
                }
                for probe in result.local_boundary_probes
            ]
        summary["local_journey"] = local
    return summary


def _gate_failure(
    source: VerifyResult,
    failure_id: str,
    error: str,
    details: dict[str, object],
) -> VerifyResult:
    return VerifyResult(
        passed=False,
        failures=[
            FailureEntry(
                category=FailureCategory.OTHER,
                id=failure_id,
                error=error,
                details=details,
            )
        ],
        duration_s=source.duration_s,
        token_usage=source.token_usage,
        verification_evidence=dict(source.verification_evidence),
    )


def _estimate_tokens(stdout: str, stderr: str) -> int:
    return (len(stdout) + len(stderr)) // 4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
