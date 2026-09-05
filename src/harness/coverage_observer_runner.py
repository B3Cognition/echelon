"""Sandbox-owned execution of stack-declared structured coverage observers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import shlex
from typing import Callable, Mapping, Sequence

from harness.config import HarnessConfig
from harness.coverage_observation import CoverageObservationResult
from harness.errors import NotSupportedError, SandboxError
from harness.playwright_evidence import (
    PlaywrightEvidenceError,
    parse_playwright_json_executions,
)
from harness.product_inventory import product_evidence_fingerprint
from harness.provider import SandboxHandle, SandboxProvider, SandboxSpec
from harness.stacks.resolver import ResolvedCoverageObserver
from harness.test_execution_evidence import ObservedTestExecution
from harness.verification_evidence import (
    VerificationEvidenceRef,
    VerificationStage,
    validate_verification_receipt,
    write_verification_receipt,
)
from harness.verification_plan import build_verification_plan, materialize_services
from harness.vitest_evidence import VitestEvidenceError, parse_vitest_json


_MAX_REPORT_BYTES = 8 * 1024 * 1024
_ATTEMPT_RE = re.compile(r"attempt-(\d+)-")


@dataclass(frozen=True)
class CoverageObserverRun:
    """One required observer's sandbox receipt and normalized executions."""

    observer_id: str
    receipt: VerificationEvidenceRef | None
    executions: tuple[ObservedTestExecution, ...]
    status: str
    reason: str = ""


@dataclass(frozen=True)
class CoverageVerificationBundle:
    """The ordinary verifier plus all required structured observer runs."""

    standard_receipt: VerificationEvidenceRef
    observer_runs: tuple[CoverageObserverRun, ...]
    observation: CoverageObservationResult | None = None


def run_coverage_observers(
    *,
    provider: SandboxProvider,
    sandbox_spec_factory: Callable[[Path], SandboxSpec],
    worktree: Path,
    config: HarnessConfig,
    observers: Sequence[ResolvedCoverageObserver],
    standard_receipt: VerificationEvidenceRef,
    candidate_commit: str,
    candidate_fingerprint: str,
    evidence_dir: Path,
    spec_id: str,
    target_id: str,
    strategy_id: str,
    build_id: str,
    sensitive_environment: Mapping[str, str],
) -> CoverageVerificationBundle:
    """Run required coverage observers without ever using the user host.

    Captured observers parse a stack-owned report produced by the ordinary
    successful verifier.  Isolated observers receive a fresh provider session,
    independently materialized sidecars, and the same deterministic bootstrap
    plan as the ordinary verifier.  A failed observer is retained as a named
    result rather than raised, so Ralph can make it a repairable product failure.
    """
    required = tuple(item for item in observers if item.observer.required)
    standard_validation = validate_verification_receipt(
        standard_receipt,
        candidate_commit=candidate_commit,
        candidate_fingerprint=candidate_fingerprint,
    )
    if not standard_validation.valid:
        return CoverageVerificationBundle(
            standard_receipt=standard_receipt,
            observer_runs=tuple(
                CoverageObserverRun(
                    observer_id=item.observer.id,
                    receipt=None,
                    executions=(),
                    status="failed",
                    reason=(
                        "standard verification receipt is invalid: "
                        + standard_validation.reason
                    ),
                )
                for item in required
            ),
        )

    current_fingerprint = _candidate_fingerprint(worktree)
    if current_fingerprint != candidate_fingerprint:
        return CoverageVerificationBundle(
            standard_receipt=standard_receipt,
            observer_runs=tuple(
                CoverageObserverRun(
                    observer_id=item.observer.id,
                    receipt=None,
                    executions=(),
                    status="failed",
                    reason="candidate fingerprint changed before coverage observation",
                )
                for item in required
            ),
        )

    return CoverageVerificationBundle(
        standard_receipt=standard_receipt,
        observer_runs=tuple(
            _run_observer(
                provider=provider,
                sandbox_spec_factory=sandbox_spec_factory,
                worktree=Path(worktree),
                config=config,
                resolved=item,
                standard_receipt=standard_receipt,
                candidate_commit=candidate_commit,
                candidate_fingerprint=candidate_fingerprint,
                evidence_dir=Path(evidence_dir),
                spec_id=spec_id,
                target_id=target_id,
                strategy_id=strategy_id,
                build_id=build_id,
                sensitive_environment=sensitive_environment,
            )
            for item in required
        ),
    )


def _run_observer(
    *,
    provider: SandboxProvider,
    sandbox_spec_factory: Callable[[Path], SandboxSpec],
    worktree: Path,
    config: HarnessConfig,
    resolved: ResolvedCoverageObserver,
    standard_receipt: VerificationEvidenceRef,
    candidate_commit: str,
    candidate_fingerprint: str,
    evidence_dir: Path,
    spec_id: str,
    target_id: str,
    strategy_id: str,
    build_id: str,
    sensitive_environment: Mapping[str, str],
) -> CoverageObserverRun:
    observer = resolved.observer
    if observer.mode == "captured":
        return _run_captured_observer(
            resolved=resolved,
            worktree=worktree,
            standard_receipt=standard_receipt,
            candidate_fingerprint=candidate_fingerprint,
            sensitive_environment=sensitive_environment,
        )
    return _run_isolated_observer(
        provider=provider,
        sandbox_spec_factory=sandbox_spec_factory,
        worktree=worktree,
        config=config,
        resolved=resolved,
        candidate_commit=candidate_commit,
        candidate_fingerprint=candidate_fingerprint,
        evidence_dir=evidence_dir,
        spec_id=spec_id,
        target_id=target_id,
        strategy_id=strategy_id,
        build_id=build_id,
        sensitive_environment=sensitive_environment,
    )


def _run_captured_observer(
    *,
    resolved: ResolvedCoverageObserver,
    worktree: Path,
    standard_receipt: VerificationEvidenceRef,
    candidate_fingerprint: str,
    sensitive_environment: Mapping[str, str],
) -> CoverageObserverRun:
    observer = resolved.observer
    if _candidate_fingerprint(worktree) != candidate_fingerprint:
        return CoverageObserverRun(
            observer_id=observer.id,
            receipt=standard_receipt,
            executions=(),
            status="failed",
            reason="candidate fingerprint changed before captured report collection",
        )
    try:
        executions = _parse_report(
            worktree=worktree,
            report_path=observer.report_path,
            observer_id=observer.id,
            test_type=observer.test_types[0],
            adapter=observer.adapter,
        )
    except CoverageObserverError as exc:
        return CoverageObserverRun(
            observer_id=observer.id,
            receipt=standard_receipt,
            executions=(),
            status="failed",
            reason=_redact_reason(str(exc), sensitive_environment),
        )
    return CoverageObserverRun(
        observer_id=observer.id,
        receipt=standard_receipt,
        executions=executions,
        status="passed",
    )


def _run_isolated_observer(
    *,
    provider: SandboxProvider,
    sandbox_spec_factory: Callable[[Path], SandboxSpec],
    worktree: Path,
    config: HarnessConfig,
    resolved: ResolvedCoverageObserver,
    candidate_commit: str,
    candidate_fingerprint: str,
    evidence_dir: Path,
    spec_id: str,
    target_id: str,
    strategy_id: str,
    build_id: str,
    sensitive_environment: Mapping[str, str],
) -> CoverageObserverRun:
    observer = resolved.observer
    handle: SandboxHandle | None = None
    stages: list[VerificationStage] = []
    environment: dict[str, str] = {}
    started_at = datetime.now(timezone.utc).isoformat()
    failure_reason = ""
    fingerprint_after = candidate_fingerprint
    try:
        if _candidate_fingerprint(worktree) != candidate_fingerprint:
            failure_reason = "candidate fingerprint changed before coverage observation"
            raise CoverageObserverError(failure_reason)
        handle = provider.create(sandbox_spec_factory(worktree))
        plan = build_verification_plan(
            worktree,
            config,
            services=tuple(config.verification_services),
        )
        if plan.services:
            materialized = materialize_services(plan.services, session_id=handle.session_id)
            provider.start_services(handle, materialized.services)
            environment.update(materialized.verifier_environment)
        for command in plan.bootstrap_commands:
            result = provider.exec(
                handle,
                command,
                cwd="/workspace",
                env=environment,
                timeout_ms=600_000,
            )
            stages.append(_stage("bootstrap", command, result))
            if result.exit_code != 0:
                failure_reason = "sandbox bootstrap failed"
                break
        if not failure_reason:
            result = provider.exec(
                handle,
                observer.command,
                cwd="/workspace",
                env=environment,
                timeout_ms=600_000,
            )
            stages.append(_stage("coverage-observer", observer.command, result))
            if result.exit_code != 0:
                failure_reason = "coverage observer command failed"
        fingerprint_after = _candidate_fingerprint(worktree) or ""
        if not failure_reason and fingerprint_after != candidate_fingerprint:
            failure_reason = "candidate fingerprint changed during coverage observation"
    except (
        CoverageObserverError,
        NotSupportedError,
        SandboxError,
        OSError,
        RuntimeError,
    ) as exc:
        failure_reason = _redact_reason(str(exc), sensitive_environment)
    finally:
        if handle is not None:
            try:
                provider.destroy(handle)
            except (SandboxError, RuntimeError, OSError) as exc:
                failure_reason = failure_reason or _redact_reason(
                    f"sandbox cleanup failed: {exc}", sensitive_environment
                )

    receipt = _write_observer_receipt(
        evidence_dir=evidence_dir,
        observer_id=observer.id,
        spec_id=spec_id,
        target_id=target_id,
        strategy_id=strategy_id,
        build_id=build_id,
        candidate_commit=candidate_commit,
        candidate_fingerprint=candidate_fingerprint,
        fingerprint_after=fingerprint_after,
        stages=stages,
        sensitive_environment={**dict(sensitive_environment), **environment},
        started_at=started_at,
    )
    if receipt is None:
        return CoverageObserverRun(
            observer_id=observer.id,
            receipt=None,
            executions=(),
            status="failed",
            reason=failure_reason or "could not persist coverage observer receipt",
        )
    if failure_reason or not receipt.passed:
        return CoverageObserverRun(
            observer_id=observer.id,
            receipt=receipt,
            executions=(),
            status="failed",
            reason=failure_reason or "coverage observer receipt did not pass",
        )
    try:
        executions = _parse_report(
            worktree=worktree,
            report_path=observer.report_path,
            observer_id=observer.id,
            test_type=observer.test_types[0],
            adapter=observer.adapter,
        )
    except CoverageObserverError as exc:
        return CoverageObserverRun(
            observer_id=observer.id,
            receipt=receipt,
            executions=(),
            status="failed",
            reason=_redact_reason(str(exc), {**dict(sensitive_environment), **environment}),
        )
    return CoverageObserverRun(
        observer_id=observer.id,
        receipt=receipt,
        executions=executions,
        status="passed",
    )


def _stage(name: str, command: str, result: object) -> VerificationStage:
    exit_code = int(getattr(result, "exit_code"))
    duration_ms = int(getattr(result, "duration_ms"))
    return VerificationStage(
        name=name,
        command=tuple(shlex.split(command)),
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout=str(getattr(result, "stdout")).encode(),
        stderr=str(getattr(result, "stderr")).encode(),
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


def _write_observer_receipt(
    *,
    evidence_dir: Path,
    observer_id: str,
    spec_id: str,
    target_id: str,
    strategy_id: str,
    build_id: str,
    candidate_commit: str,
    candidate_fingerprint: str,
    fingerprint_after: str,
    stages: Sequence[VerificationStage],
    sensitive_environment: Mapping[str, str],
    started_at: str,
) -> VerificationEvidenceRef | None:
    root = Path(evidence_dir) / "coverage-observers" / observer_id
    try:
        return write_verification_receipt(
            evidence_dir=root,
            spec_id=spec_id,
            target_id=target_id,
            strategy_id=strategy_id,
            build_id=build_id,
            candidate_commit=candidate_commit,
            fingerprint_before=candidate_fingerprint,
            fingerprint_after=fingerprint_after,
            verifier_source="sandbox-coverage-observer",
            detection_evidence=(f"stack coverage observer: {observer_id}",),
            execution_context={"mode": "sandbox", "observer": observer_id},
            stages=stages,
            attempt_sequence=_next_attempt(root),
            sensitive_environment=sensitive_environment,
            started_at=started_at,
        )
    except (OSError, ValueError):
        return None


def _next_attempt(root: Path) -> int:
    highest = 0
    try:
        paths = root.glob("attempt-*.json")
    except OSError:
        return 1
    for path in paths:
        match = _ATTEMPT_RE.match(path.name)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _parse_report(
    *,
    worktree: Path,
    report_path: str,
    observer_id: str,
    test_type: str,
    adapter: str,
) -> tuple[ObservedTestExecution, ...]:
    try:
        report = _safe_report_path(worktree, report_path)
        raw = report.read_bytes()
    except OSError as exc:
        raise CoverageObserverError("structured observer report is unavailable") from exc
    if len(raw) > _MAX_REPORT_BYTES:
        raise CoverageObserverError("structured observer report exceeds size limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CoverageObserverError("structured observer report is not UTF-8") from exc
    try:
        if adapter == "vitest-json":
            return parse_vitest_json(
                text, observer_id=observer_id, test_type=test_type
            )
        if adapter == "playwright-json":
            return parse_playwright_json_executions(
                text, observer_id=observer_id, test_type=test_type
            )
    except (VitestEvidenceError, PlaywrightEvidenceError) as exc:
        raise CoverageObserverError(str(exc)) from exc
    raise CoverageObserverError(f"unsupported coverage observer adapter: {adapter}")


def _safe_report_path(worktree: Path, report_path: str) -> Path:
    root = Path(worktree).resolve(strict=True)
    relative = Path(report_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or "." in relative.parts
        or ".." in relative.parts
        or "\\" in report_path
    ):
        raise CoverageObserverError("structured observer report path is unsafe")
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise CoverageObserverError("structured observer report path traverses a symlink")
    resolved = candidate.resolve(strict=True)
    if (resolved.parent != root and root not in resolved.parents) or not resolved.is_file():
        raise CoverageObserverError("structured observer report escapes candidate worktree")
    return resolved


def _candidate_fingerprint(worktree: Path) -> str | None:
    try:
        return product_evidence_fingerprint(Path(worktree))
    except (OSError, RuntimeError, ValueError):
        return None


def _redact_reason(value: str, sensitive_environment: Mapping[str, str]) -> str:
    from harness.verification_evidence import redact_verification_text

    return redact_verification_text(value, sensitive_environment)[-1000:]


class CoverageObserverError(RuntimeError):
    """An observer could not produce trustworthy structured output."""
