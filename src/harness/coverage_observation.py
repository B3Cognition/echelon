"""Immutable, source-bound observation of planned coverage test cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from harness.coverage_contract import CoverageObligation
from harness.durable_json import write_json_atomic
from harness.test_execution_evidence import (
    ObservedTestExecution,
    PhysicalTestIdentity,
    TestExecutionEvidenceError,
    parse_echelon_case_tags,
)
from harness.verification_evidence import (
    VerificationEvidenceRef,
    redact_verification_text,
    validate_equivalent_product_receipt,
    validate_verification_receipt,
)


AUTHORITY = "ralph-coverage-observation"
SCHEMA_VERSION = 1
_MAX_DIAGNOSTIC_CHARS = 1000


class CoverageObservationError(ValueError):
    """Raised when an observation cannot be trusted enough to persist."""


@dataclass(frozen=True)
class CoverageObservationRef:
    """Digest-bound reference to an immutable coverage observation attempt."""

    path: Path
    receipt_sha256: str
    observation_sha256: str
    candidate_fingerprint: str
    passed: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "receipt_sha256": self.receipt_sha256,
            "observation_sha256": self.observation_sha256,
            "candidate_fingerprint": self.candidate_fingerprint,
            "passed": self.passed,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CoverageObservationRef":
        return cls(
            path=Path(str(value.get("path") or "")),
            receipt_sha256=str(value.get("receipt_sha256") or ""),
            observation_sha256=str(value.get("observation_sha256") or ""),
            candidate_fingerprint=str(value.get("candidate_fingerprint") or ""),
            passed=value.get("passed") is True,
        )


@dataclass(frozen=True)
class CoverageObservationValidation:
    """Fail-closed outcome for one persisted coverage observation."""

    valid: bool
    reason: str = ""


@dataclass(frozen=True)
class CoverageProjectResult:
    name: str
    status: str
    retry_count: int
    error: str = ""


@dataclass(frozen=True)
class CoverageTestMatch:
    observer: str
    file: str
    title: str
    source_sha256: str
    projects: tuple[CoverageProjectResult, ...]


@dataclass(frozen=True)
class CoverageTestCaseObservation:
    test_case_id: str
    test_type: str
    status: str
    reason: str
    matches: tuple[CoverageTestMatch, ...] = ()


@dataclass(frozen=True)
class CoverageRequirementObservation:
    requirement_id: str
    status: str
    test_case_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class CoverageObservationResult:
    ref: CoverageObservationRef
    test_cases: dict[str, CoverageTestCaseObservation]
    requirements: dict[str, CoverageRequirementObservation]
    fingerprints: Mapping[str, str | None] = field(default_factory=dict)


def write_coverage_observation(
    *,
    evidence_dir: Path,
    candidate_commit: str,
    candidate_fingerprint: str,
    coverage_map_hash: str,
    resolved_stack_hash: str,
    observer_plan_hash: str,
    runnability_contract_hash: str | None,
    verification_receipt: VerificationEvidenceRef,
    observer_receipts: Mapping[str, VerificationEvidenceRef],
    obligations: Sequence[CoverageObligation],
    executions: Sequence[ObservedTestExecution],
    candidate_worktree: Path,
    attempt_sequence: int,
    sensitive_environment: Mapping[str, str],
    observer_test_types: Mapping[str, Sequence[str]] | None = None,
) -> CoverageObservationResult:
    """Persist the deterministic result of matching planned cases to executions."""
    if attempt_sequence < 1:
        raise ValueError("attempt_sequence must be positive")
    standard_validation = validate_verification_receipt(
        verification_receipt,
        candidate_commit=candidate_commit,
        candidate_fingerprint=candidate_fingerprint,
    )
    if not standard_validation.valid:
        raise CoverageObservationError(
            "standard verification receipt is invalid: " + standard_validation.reason
        )
    for observer_id, receipt in sorted(observer_receipts.items()):
        validation = validate_verification_receipt(
            receipt,
            candidate_commit=candidate_commit,
            candidate_fingerprint=candidate_fingerprint,
        )
        if not validation.valid:
            raise CoverageObservationError(
                f"observer receipt {observer_id} is invalid: {validation.reason}"
            )

    case_types, requirement_cases = _planned_cases(obligations)
    grouped = _group_executions(executions)
    identity_details, unknown_tags = _identity_details(
        grouped,
        candidate_worktree=Path(candidate_worktree),
        case_types=case_types,
        observer_test_types=observer_test_types,
        sensitive_environment=sensitive_environment,
    )
    test_cases = _observe_test_cases(
        case_types,
        grouped,
        identity_details,
        observer_receipts=set(observer_receipts),
        sensitive_environment=sensitive_environment,
    )
    requirements = _observe_requirements(requirement_cases, test_cases)
    empty_observers = {
        observer_id
        for observer_id in observer_receipts
        if not any(item.observer_id == observer_id for item in executions)
    }
    failure_reasons = [
        f"unknown planned-case tag: {tag}" for tag in sorted(unknown_tags)
    ] + [
        f"observer {observer_id} reported zero tests"
        for observer_id in sorted(empty_observers)
    ]
    passed = (
        bool(test_cases)
        and all(item.status == "passed" for item in test_cases.values())
        and all(item.status == "observed" for item in requirements.values())
        and not failure_reasons
    )

    root = _prepare_observation_root(Path(evidence_dir))
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "candidate_commit": candidate_commit,
        "candidate_fingerprint": candidate_fingerprint,
        "fingerprints": {
            "coverage_map_hash": coverage_map_hash,
            "resolved_stack_hash": resolved_stack_hash,
            "observer_plan_hash": observer_plan_hash,
            "runnability_contract_hash": runnability_contract_hash,
        },
        "verification_receipt": verification_receipt.as_mapping(),
        "observer_receipts": {
            observer_id: receipt.as_mapping()
            for observer_id, receipt in sorted(observer_receipts.items())
        },
        "test_cases": {
            case_id: _test_case_payload(item)
            for case_id, item in sorted(test_cases.items())
        },
        "requirements": {
            requirement_id: asdict(item)
            for requirement_id, item in sorted(requirements.items())
        },
        "failure_reasons": failure_reasons,
        "status": "passed" if passed else "failed",
    }
    observation_sha256 = _observation_sha256(payload)
    payload["observation_sha256"] = observation_sha256
    receipt_sha256 = _sha256_json(payload)
    payload["receipt_sha256"] = receipt_sha256

    candidate_prefix = candidate_commit[:12] or "uncommitted"
    attempt_stem = f"attempt-{attempt_sequence:04d}-{candidate_prefix}"
    json_path = root / f"{attempt_stem}.json"
    markdown_path = root / f"{attempt_stem}.md"
    _write_json_exclusive(json_path, payload)
    _write_text_exclusive(
        markdown_path,
        _render_markdown(test_cases, requirements, failure_reasons),
    )
    write_json_atomic(
        root / "latest.json",
        {"path": json_path.name, "receipt_sha256": receipt_sha256},
        trusted_root=root,
    )
    ref = CoverageObservationRef(
        path=json_path,
        receipt_sha256=receipt_sha256,
        observation_sha256=observation_sha256,
        candidate_fingerprint=candidate_fingerprint,
        passed=passed,
    )
    return CoverageObservationResult(
        ref=ref,
        test_cases=test_cases,
        requirements=requirements,
        fingerprints={
            "coverage_map_hash": coverage_map_hash,
            "resolved_stack_hash": resolved_stack_hash,
            "observer_plan_hash": observer_plan_hash,
            "runnability_contract_hash": runnability_contract_hash,
        },
    )


def load_coverage_observation(path: Path) -> CoverageObservationResult:
    """Load a self-consistent, passing immutable observation for CLI consumers."""
    observation_path = Path(path)
    if not observation_path.is_absolute() or observation_path.is_symlink():
        raise CoverageObservationError("coverage observation path is unsafe")
    try:
        payload = json.loads(observation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageObservationError("coverage observation is unavailable") from exc
    if not isinstance(payload, dict):
        raise CoverageObservationError("coverage observation is malformed")
    fingerprints = payload.get("fingerprints")
    if not isinstance(fingerprints, dict):
        raise CoverageObservationError("coverage observation fingerprints are malformed")
    normalized_fingerprints: dict[str, str | None] = {}
    for key in (
        "coverage_map_hash",
        "resolved_stack_hash",
        "observer_plan_hash",
        "runnability_contract_hash",
    ):
        value = fingerprints.get(key)
        if value is not None and not isinstance(value, str):
            raise CoverageObservationError("coverage observation fingerprints are malformed")
        normalized_fingerprints[key] = value
    ref = CoverageObservationRef(
        path=observation_path,
        receipt_sha256=str(payload.get("receipt_sha256") or ""),
        observation_sha256=str(payload.get("observation_sha256") or ""),
        candidate_fingerprint=str(payload.get("candidate_fingerprint") or ""),
        passed=payload.get("status") == "passed",
    )
    validation = validate_coverage_observation(
        ref,
        candidate_commit=str(payload.get("candidate_commit") or ""),
        candidate_fingerprint=ref.candidate_fingerprint,
        coverage_map_hash=normalized_fingerprints["coverage_map_hash"] or "",
        resolved_stack_hash=normalized_fingerprints["resolved_stack_hash"] or "",
        observer_plan_hash=normalized_fingerprints["observer_plan_hash"] or "",
        runnability_contract_hash=normalized_fingerprints["runnability_contract_hash"],
    )
    if not validation.valid:
        raise CoverageObservationError(
            "coverage observation is invalid: " + validation.reason
        )
    return CoverageObservationResult(
        ref=ref,
        test_cases=_load_test_cases(payload.get("test_cases")),
        requirements=_load_requirements(payload.get("requirements")),
        fingerprints=normalized_fingerprints,
    )


def validate_coverage_observation(
    ref: CoverageObservationRef,
    *,
    candidate_commit: str | None = None,
    candidate_fingerprint: str,
    coverage_map_hash: str,
    resolved_stack_hash: str,
    observer_plan_hash: str,
    runnability_contract_hash: str | None,
    allow_equivalent_product: bool = False,
) -> CoverageObservationValidation:
    """Validate an observation and its receipt bundle.

    Exact commit validation is the default. Landing alone may opt into
    equivalent-product carry-forward for merge-only commits, after it has
    independently checked every product-affecting fingerprint.
    """
    try:
        path = ref.path
        if not path.is_absolute() or path.is_symlink():
            return _invalid("coverage observation path is not absolute and regular")
        root = path.parent.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if resolved.parent != root or not resolved.is_file():
            return _invalid("coverage observation path escapes its evidence directory")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _invalid("coverage observation is not a JSON object")
        if payload.get("authority") != AUTHORITY:
            return _invalid("coverage observation authority mismatch")
        embedded_receipt_sha = str(payload.get("receipt_sha256") or "")
        receipt_payload = dict(payload)
        receipt_payload.pop("receipt_sha256", None)
        observed_receipt_sha = _sha256_json(receipt_payload)
        if not (
            hmac.compare_digest(observed_receipt_sha, ref.receipt_sha256)
            and hmac.compare_digest(observed_receipt_sha, embedded_receipt_sha)
        ):
            return _invalid("coverage observation receipt digest mismatch")
        embedded_observation_sha = str(payload.get("observation_sha256") or "")
        observed_observation_sha = _observation_sha256(payload)
        if not (
            hmac.compare_digest(observed_observation_sha, ref.observation_sha256)
            and hmac.compare_digest(
                observed_observation_sha, embedded_observation_sha
            )
        ):
            return _invalid("coverage observation digest mismatch")
        latest_path = root / "latest.json"
        if latest_path.is_symlink():
            return _invalid("coverage observation latest pointer is symlinked")
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if not isinstance(latest, dict):
            return _invalid("coverage observation latest pointer is malformed")
        selected = str(latest.get("path") or "")
        if Path(selected).name != selected or selected in {"", ".", ".."}:
            return _invalid("coverage observation latest pointer path is unsafe")
        if selected != resolved.name or not hmac.compare_digest(
            str(latest.get("receipt_sha256") or ""), ref.receipt_sha256
        ):
            return _invalid("coverage observation is not the selected latest attempt")
        if payload.get("status") != "passed" or ref.passed is not True:
            return _invalid("coverage observation is not passing")
        if (
            str(payload.get("candidate_fingerprint") or "") != candidate_fingerprint
            or ref.candidate_fingerprint != candidate_fingerprint
        ):
            return _invalid("coverage observation candidate fingerprint mismatch")
        fingerprints = payload.get("fingerprints")
        if not isinstance(fingerprints, dict):
            return _invalid("coverage observation fingerprints are malformed")
        expected_fingerprints = {
            "coverage_map_hash": coverage_map_hash,
            "resolved_stack_hash": resolved_stack_hash,
            "observer_plan_hash": observer_plan_hash,
            "runnability_contract_hash": runnability_contract_hash,
        }
        labels = {
            "coverage_map_hash": "coverage map",
            "resolved_stack_hash": "resolved stack",
            "observer_plan_hash": "observer plan",
            "runnability_contract_hash": "runnability contract",
        }
        for key, expected in expected_fingerprints.items():
            if fingerprints.get(key) != expected:
                return _invalid(f"{labels[key]} fingerprint mismatch")
        verification = _verification_ref(payload.get("verification_receipt"))
        if verification is None:
            return _invalid("coverage observation verification receipt is malformed")
        expected_commit = candidate_commit or str(payload.get("candidate_commit") or "")
        if not expected_commit:
            return _invalid("coverage observation candidate commit is missing")
        validation = (
            validate_equivalent_product_receipt(
                verification,
                candidate_fingerprint=candidate_fingerprint,
            )
            if allow_equivalent_product
            else validate_verification_receipt(
                verification,
                candidate_commit=expected_commit,
                candidate_fingerprint=candidate_fingerprint,
            )
        )
        if not validation.valid:
            return _invalid("coverage observation verifier receipt is invalid")
        observer_refs = payload.get("observer_receipts")
        if not isinstance(observer_refs, dict):
            return _invalid("coverage observation observer receipts are malformed")
        for raw_ref in observer_refs.values():
            observer_ref = _verification_ref(raw_ref)
            if observer_ref is None:
                return _invalid("coverage observation observer receipt is malformed")
            validation = (
                validate_equivalent_product_receipt(
                    observer_ref,
                    candidate_fingerprint=candidate_fingerprint,
                )
                if allow_equivalent_product
                else validate_verification_receipt(
                    observer_ref,
                    candidate_commit=expected_commit,
                    candidate_fingerprint=candidate_fingerprint,
                )
            )
            if not validation.valid:
                return _invalid("coverage observation observer receipt is invalid")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError):
        return _invalid("coverage observation is unavailable or malformed")
    return CoverageObservationValidation(valid=True)


def _planned_cases(
    obligations: Sequence[CoverageObligation],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    case_types: dict[str, str] = {}
    requirement_cases: dict[str, list[str]] = {}
    for obligation in obligations:
        prior_type = case_types.get(obligation.test_case_id)
        if prior_type is not None and prior_type != obligation.test_type:
            raise CoverageObservationError(
                f"incompatible planned test types for {obligation.test_case_id}"
            )
        case_types[obligation.test_case_id] = obligation.test_type
        requirement_cases.setdefault(obligation.requirement_id, [])
        if obligation.test_case_id not in requirement_cases[obligation.requirement_id]:
            requirement_cases[obligation.requirement_id].append(
                obligation.test_case_id
            )
    return case_types, {
        requirement_id: tuple(case_ids)
        for requirement_id, case_ids in requirement_cases.items()
    }


def _load_test_cases(value: object) -> dict[str, CoverageTestCaseObservation]:
    if not isinstance(value, dict):
        raise CoverageObservationError("coverage observation test cases are malformed")
    result: dict[str, CoverageTestCaseObservation] = {}
    for case_id, raw in value.items():
        if not isinstance(case_id, str) or not isinstance(raw, dict):
            raise CoverageObservationError("coverage observation test cases are malformed")
        test_type = str(raw.get("test_type") or "").strip()
        status = str(raw.get("status") or "").strip()
        if not test_type or not status:
            raise CoverageObservationError("coverage observation test cases are malformed")
        result[case_id] = CoverageTestCaseObservation(
            test_case_id=str(raw.get("test_case_id") or case_id).strip(),
            test_type=test_type,
            status=status,
            reason=str(raw.get("reason") or status).strip(),
        )
    return result


def _load_requirements(value: object) -> dict[str, CoverageRequirementObservation]:
    if not isinstance(value, dict):
        raise CoverageObservationError("coverage observation requirements are malformed")
    result: dict[str, CoverageRequirementObservation] = {}
    for requirement_id, raw in value.items():
        if not isinstance(requirement_id, str) or not isinstance(raw, dict):
            raise CoverageObservationError("coverage observation requirements are malformed")
        raw_case_ids = raw.get("test_case_ids")
        if not isinstance(raw_case_ids, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_case_ids
        ):
            raise CoverageObservationError("coverage observation requirements are malformed")
        status = str(raw.get("status") or "").strip()
        if not status:
            raise CoverageObservationError("coverage observation requirements are malformed")
        result[requirement_id] = CoverageRequirementObservation(
            requirement_id=str(raw.get("requirement_id") or requirement_id).strip(),
            status=status,
            test_case_ids=tuple(raw_case_ids),
            reason=str(raw.get("reason") or status).strip(),
        )
    return result


def _group_executions(
    executions: Sequence[ObservedTestExecution],
) -> dict[PhysicalTestIdentity, list[ObservedTestExecution]]:
    grouped: dict[PhysicalTestIdentity, list[ObservedTestExecution]] = {}
    for execution in executions:
        identity = PhysicalTestIdentity.from_execution(execution)
        grouped.setdefault(identity, []).append(execution)
    return grouped


@dataclass(frozen=True)
class _IdentityDetail:
    tags: tuple[str, ...]
    source_sha256: str = ""
    reason: str = ""


def _identity_details(
    grouped: Mapping[PhysicalTestIdentity, Sequence[ObservedTestExecution]],
    *,
    candidate_worktree: Path,
    case_types: Mapping[str, str],
    observer_test_types: Mapping[str, Sequence[str]] | None,
    sensitive_environment: Mapping[str, str],
) -> tuple[dict[PhysicalTestIdentity, _IdentityDetail], set[str]]:
    details: dict[PhysicalTestIdentity, _IdentityDetail] = {}
    unknown_tags: set[str] = set()
    for identity, executions in grouped.items():
        try:
            tags = parse_echelon_case_tags(identity.title)
        except TestExecutionEvidenceError as exc:
            details[identity] = _IdentityDetail(
                tags=(), reason=_safe_diagnostic(str(exc), sensitive_environment)
            )
            continue
        if not tags:
            details[identity] = _IdentityDetail(tags=())
            continue
        for tag in tags:
            if tag not in case_types:
                unknown_tags.add(tag)
        reason, source_sha256 = _source_binding(
            candidate_worktree,
            identity,
            sensitive_environment=sensitive_environment,
        )
        if not reason:
            declared_types = (
                {
                    str(value).strip()
                    for value in observer_test_types.get(identity.observer_id, ())
                    if str(value).strip()
                }
                if observer_test_types is not None
                else {execution.test_type for execution in executions}
            )
            type_mismatches = {
                case_types[tag]
                for tag in tags
                if tag in case_types and case_types[tag] not in declared_types
            }
            if type_mismatches:
                reason = "observer does not own the planned coverage test type"
        details[identity] = _IdentityDetail(
            tags=tags,
            source_sha256=source_sha256,
            reason=reason,
        )
    return details, unknown_tags


def _source_binding(
    worktree: Path,
    identity: PhysicalTestIdentity,
    *,
    sensitive_environment: Mapping[str, str],
) -> tuple[str, str]:
    try:
        root = worktree.resolve(strict=True)
        if not root.is_dir():
            return "candidate worktree is not a directory", ""
        relative = Path(identity.file)
        if (
            relative.is_absolute()
            or not relative.parts
            or "." in relative.parts
            or ".." in relative.parts
            or "\\" in identity.file
        ):
            return "test file must be target-relative", ""
        if len(relative.parts) == 1:
            matches = _bare_report_source_matches(root, relative.name, identity.title)
            if not matches:
                return (
                    "test reporter basename did not identify a tagged source file "
                    "in the candidate worktree",
                    "",
                )
            if len(matches) != 1:
                return (
                    "test reporter basename maps to multiple tagged source files "
                    "in the candidate worktree",
                    "",
                )
            _, content = matches[0]
            return "", hashlib.sha256(content).hexdigest()
        candidate = root
        for part in relative.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                return "test file path must not traverse a symlink", ""
        resolved = candidate.resolve(strict=True)
        if resolved.parent != root and root not in resolved.parents:
            return "test file escapes candidate worktree", ""
        if not resolved.is_file():
            return "test file is not regular", ""
        content = resolved.read_bytes()
        text = content.decode("utf-8")
        if identity.title not in text:
            return "test source does not contain the reported tagged title", ""
        return "", hashlib.sha256(content).hexdigest()
    except (OSError, UnicodeDecodeError, RuntimeError) as exc:
        return _safe_diagnostic(str(exc), sensitive_environment), ""


def _bare_report_source_matches(
    root: Path,
    filename: str,
    title: str,
) -> list[tuple[Path, bytes]]:
    """Find exact tagged sources for an observer that reports only a basename.

    Playwright's JSON reporter can omit a test file's directory.  Resolve that
    incomplete identity only inside the candidate worktree and only when its
    tagged title identifies one regular, non-symlinked source file.  This
    preserves source-bound evidence without trusting a reporter path to reach
    outside the candidate.
    """
    matches: list[tuple[Path, bytes]] = []
    excluded_directories = {
        ".git",
        "node_modules",
        ".pnpm-store",
        "coverage",
        "dist",
        "test-results",
    }
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if name not in excluded_directories and not (current_path / name).is_symlink()
        ]
        if filename not in files:
            continue
        candidate = current_path / filename
        if candidate.is_symlink():
            continue
        resolved = candidate.resolve(strict=True)
        if resolved.parent != root and root not in resolved.parents:
            continue
        if not resolved.is_file():
            continue
        content = resolved.read_bytes()
        if title in content.decode("utf-8"):
            matches.append((resolved, content))
    return matches


def _observe_test_cases(
    case_types: Mapping[str, str],
    grouped: Mapping[PhysicalTestIdentity, Sequence[ObservedTestExecution]],
    details: Mapping[PhysicalTestIdentity, _IdentityDetail],
    *,
    observer_receipts: set[str],
    sensitive_environment: Mapping[str, str],
) -> dict[str, CoverageTestCaseObservation]:
    identities_by_case: dict[str, list[PhysicalTestIdentity]] = {
        case_id: [] for case_id in case_types
    }
    for identity, detail in details.items():
        for tag in detail.tags:
            if tag in identities_by_case:
                identities_by_case[tag].append(identity)

    results: dict[str, CoverageTestCaseObservation] = {}
    for case_id, test_type in sorted(case_types.items()):
        identities = identities_by_case[case_id]
        if not identities:
            results[case_id] = CoverageTestCaseObservation(
                test_case_id=case_id,
                test_type=test_type,
                status="unbound",
                reason="no executed tagged test matches the planned case",
            )
            continue
        if len(identities) != 1:
            results[case_id] = CoverageTestCaseObservation(
                test_case_id=case_id,
                test_type=test_type,
                status="duplicate_binding",
                reason="case tag maps to more than one physical test identity",
            )
            continue
        identity = identities[0]
        detail = details[identity]
        matches = (_test_match(identity, grouped[identity], detail, sensitive_environment),)
        if identity.observer_id not in observer_receipts:
            status = "observer_missing"
            reason = "the test execution has no matching observer receipt"
        elif detail.reason:
            status = "invalid_report"
            reason = detail.reason
        else:
            statuses = {execution.status for execution in grouped[identity]}
            if "failed" in statuses:
                status = "failed"
                reason = "at least one project terminal result failed"
            elif statuses != {"passed"}:
                status = "skipped" if "skipped" in statuses else "invalid_report"
                reason = (
                    "at least one project terminal result was skipped"
                    if status == "skipped"
                    else "test reporter has an invalid terminal status"
                )
            else:
                status = "passed"
                reason = "all observed project terminal results passed"
        results[case_id] = CoverageTestCaseObservation(
            test_case_id=case_id,
            test_type=test_type,
            status=status,
            reason=reason,
            matches=matches,
        )
    return results


def _test_match(
    identity: PhysicalTestIdentity,
    executions: Sequence[ObservedTestExecution],
    detail: _IdentityDetail,
    sensitive_environment: Mapping[str, str],
) -> CoverageTestMatch:
    projects = tuple(
        CoverageProjectResult(
            name=execution.project,
            status=execution.status,
            retry_count=execution.retry_count,
            error=_safe_diagnostic(execution.error, sensitive_environment),
        )
        for execution in sorted(
            executions,
            key=lambda item: (item.project, item.retry_count, item.status),
        )
    )
    return CoverageTestMatch(
        observer=identity.observer_id,
        file=identity.file,
        title=identity.title,
        source_sha256=detail.source_sha256,
        projects=projects,
    )


def _observe_requirements(
    requirement_cases: Mapping[str, Sequence[str]],
    test_cases: Mapping[str, CoverageTestCaseObservation],
) -> dict[str, CoverageRequirementObservation]:
    results: dict[str, CoverageRequirementObservation] = {}
    for requirement_id, case_ids in sorted(requirement_cases.items()):
        unresolved = [
            test_cases[case_id]
            for case_id in case_ids
            if test_cases[case_id].status != "passed"
        ]
        if unresolved:
            status = unresolved[0].status
            reason = "; ".join(
                f"{item.test_case_id}={item.status}" for item in unresolved
            )
        else:
            status = "observed"
            reason = "all planned cases were observed as passed"
        results[requirement_id] = CoverageRequirementObservation(
            requirement_id=requirement_id,
            status=status,
            test_case_ids=tuple(case_ids),
            reason=reason,
        )
    return results


def _prepare_observation_root(evidence_dir: Path) -> Path:
    root = Path(os.path.abspath(os.fspath(evidence_dir))) / "coverage-observation"
    if root.is_symlink():
        raise OSError("coverage observation directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve(strict=True)


def _test_case_payload(item: CoverageTestCaseObservation) -> dict[str, object]:
    return {
        "test_case_id": item.test_case_id,
        "test_type": item.test_type,
        "status": item.status,
        "reason": item.reason,
        "matches": [
            {
                "observer": match.observer,
                "file": match.file,
                "title": match.title,
                "source_sha256": match.source_sha256,
                "projects": [asdict(project) for project in match.projects],
            }
            for match in item.matches
        ],
    }


def _render_markdown(
    test_cases: Mapping[str, CoverageTestCaseObservation],
    requirements: Mapping[str, CoverageRequirementObservation],
    failure_reasons: Sequence[str],
) -> str:
    lines = [
        "# Coverage Observation",
        "",
        "## Requirements",
        "",
        "| Requirement | Status | Planned cases | Reason |",
        "|---|---|---|---|",
    ]
    for requirement_id, item in sorted(requirements.items()):
        lines.append(
            f"| {requirement_id} | {item.status} | "
            f"{', '.join(item.test_case_ids)} | {item.reason} |"
        )
    lines.extend(
        [
            "",
            "## Test Cases",
            "",
            "| Case | Type | Status | Reason |",
            "|---|---|---|---|",
        ]
    )
    for case_id, item in sorted(test_cases.items()):
        lines.append(
            f"| {case_id} | {item.test_type} | {item.status} | {item.reason} |"
        )
    if failure_reasons:
        lines.extend(["", "## Observation Failures", ""])
        lines.extend(f"- {reason}" for reason in failure_reasons)
    return "\n".join(lines) + "\n"


def _safe_diagnostic(
    value: str,
    sensitive_environment: Mapping[str, str],
) -> str:
    return redact_verification_text(str(value), sensitive_environment)[
        -_MAX_DIAGNOSTIC_CHARS:
    ]


def _verification_ref(value: object) -> VerificationEvidenceRef | None:
    if not isinstance(value, Mapping):
        return None
    return VerificationEvidenceRef.from_mapping(value)


def _observation_sha256(payload: Mapping[str, object]) -> str:
    stable = dict(payload)
    stable.pop("observation_sha256", None)
    stable.pop("receipt_sha256", None)
    return _sha256_json(stable)


def _sha256_json(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _write_json_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    _write_bytes_exclusive(
        path,
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        ),
    )


def _write_text_exclusive(path: Path, text: str) -> None:
    _write_bytes_exclusive(path, text.encode("utf-8"))


def _write_bytes_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        remaining = memoryview(content)
        while remaining:
            written = os.write(descriptor, remaining)
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def _invalid(reason: str) -> CoverageObservationValidation:
    return CoverageObservationValidation(valid=False, reason=reason)
