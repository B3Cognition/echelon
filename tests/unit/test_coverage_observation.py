"""Tests for immutable, source-bound coverage observations."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.coverage_contract import parse_coverage_obligations
from harness.coverage_observation import (
    validate_coverage_observation,
    write_coverage_observation,
)
from harness.test_execution_evidence import ObservedTestExecution
from harness.verification_evidence import VerificationStage, write_verification_receipt


_COMMIT = "a" * 40
_FINGERPRINT = "b" * 64
_MAP_HASH = "c" * 64
_STACK_HASH = "d" * 64
_OBSERVER_PLAN_HASH = "e" * 64
_CONTRACT_HASH = "f" * 64
_TITLE = "persistent journey [echelon:E2E-001]"
_FILE = "tests/journey.spec.ts"


def _receipt(root: Path, *, sequence: int = 1):
    return write_verification_receipt(
        evidence_dir=root,
        spec_id="003-demo",
        strategy_id="default",
        build_id="build-1",
        candidate_commit=_COMMIT,
        fingerprint_before=_FINGERPRINT,
        fingerprint_after=_FINGERPRINT,
        verifier_source="configured",
        stages=[
            VerificationStage(
                name="verify",
                command=("pnpm", "verify"),
                exit_code=0,
                duration_ms=1,
                stdout=b"passed\n",
                stderr=b"",
            )
        ],
        attempt_sequence=sequence,
        sensitive_environment={},
    )


def _obligations(case_id: str = "E2E-001"):
    return parse_coverage_obligations(
        "FR-001",
        case_id,
        "e2e",
        "deferred-automation",
        "deferred-automation",
        "oracle",
        "repair",
        {"FR-001"},
    )


def _execution(
    *,
    file: str = _FILE,
    title: str = _TITLE,
    project: str = "chromium",
    status: str = "passed",
) -> ObservedTestExecution:
    return ObservedTestExecution(
        observer_id="playwright",
        test_type="e2e",
        file=file,
        title=title,
        project=project,
        status=status,
        retry_count=0,
        error="test failed" if status == "failed" else "",
    )


def _source(worktree: Path, file: str = _FILE, title: str = _TITLE) -> None:
    path = worktree / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"test({title!r}, () => {{}});\n", encoding="utf-8")


def _write_observation(
    tmp_path: Path,
    *,
    obligations=None,
    executions=None,
    worktree: Path | None = None,
    extra_observer_receipt: bool = False,
):
    candidate_worktree = worktree or tmp_path / "candidate"
    if worktree is None:
        _source(candidate_worktree)
    standard = _receipt(tmp_path / "standard")
    observer = _receipt(tmp_path / "playwright")
    observer_receipts = {"playwright": observer}
    if extra_observer_receipt:
        observer_receipts["vitest"] = _receipt(tmp_path / "vitest")
    return write_coverage_observation(
        evidence_dir=tmp_path / "verify",
        candidate_commit=_COMMIT,
        candidate_fingerprint=_FINGERPRINT,
        coverage_map_hash=_MAP_HASH,
        resolved_stack_hash=_STACK_HASH,
        observer_plan_hash=_OBSERVER_PLAN_HASH,
        runnability_contract_hash=_CONTRACT_HASH,
        verification_receipt=standard,
        observer_receipts=observer_receipts,
        obligations=_obligations() if obligations is None else obligations,
        executions=(_execution(),) if executions is None else executions,
        candidate_worktree=candidate_worktree,
        attempt_sequence=1,
        sensitive_environment={},
    )


@pytest.mark.unit
def test_write_coverage_observation_records_a_passed_source_bound_requirement(
    tmp_path: Path,
) -> None:
    result = _write_observation(tmp_path)

    assert result.ref.passed is True
    assert result.test_cases["E2E-001"].status == "passed"
    assert result.requirements["FR-001"].status == "observed"
    assert validate_coverage_observation(
        result.ref,
        candidate_fingerprint=_FINGERPRINT,
        coverage_map_hash=_MAP_HASH,
        resolved_stack_hash=_STACK_HASH,
        observer_plan_hash=_OBSERVER_PLAN_HASH,
        runnability_contract_hash=_CONTRACT_HASH,
    ).valid


@pytest.mark.unit
def test_coverage_observation_marks_an_untagged_planned_case_unbound(
    tmp_path: Path,
) -> None:
    result = _write_observation(tmp_path, obligations=_obligations("E2E-002"))

    assert result.ref.passed is False
    assert result.test_cases["E2E-002"].status == "unbound"
    assert result.requirements["FR-001"].status == "unbound"


@pytest.mark.unit
def test_coverage_observation_accepts_each_type_owned_by_one_multi_type_observer(
    tmp_path: Path,
) -> None:
    title = "core behavior [echelon:UT-001, INT-001]"
    worktree = tmp_path / "candidate"
    _source(worktree, title=title)
    obligations = parse_coverage_obligations(
        "FR-001",
        "UT-001; INT-001",
        "unit/integration",
        "deferred-automation",
        "deferred-automation",
        "oracle",
        "repair",
        {"FR-001"},
    )
    standard = _receipt(tmp_path / "standard")
    observer = _receipt(tmp_path / "vitest")
    result = write_coverage_observation(
        evidence_dir=tmp_path / "verify",
        candidate_commit=_COMMIT,
        candidate_fingerprint=_FINGERPRINT,
        coverage_map_hash=_MAP_HASH,
        resolved_stack_hash=_STACK_HASH,
        observer_plan_hash=_OBSERVER_PLAN_HASH,
        runnability_contract_hash=_CONTRACT_HASH,
        verification_receipt=standard,
        observer_receipts={"vitest": observer},
        observer_test_types={"vitest": ("unit", "integration")},
        obligations=obligations,
        executions=(
            ObservedTestExecution(
                observer_id="vitest",
                test_type="unit",
                file=_FILE,
                title=title,
                project="default",
                status="passed",
                retry_count=0,
            ),
        ),
        candidate_worktree=worktree,
        attempt_sequence=1,
        sensitive_environment={},
    )

    assert result.ref.passed is True
    assert result.test_cases["UT-001"].status == "passed"
    assert result.test_cases["INT-001"].status == "passed"


@pytest.mark.unit
def test_coverage_observation_rejects_duplicate_physical_case_bindings(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "candidate"
    _source(worktree, "tests/first.spec.ts")
    _source(worktree, "tests/second.spec.ts")
    result = _write_observation(
        tmp_path,
        worktree=worktree,
        executions=(
            _execution(file="tests/first.spec.ts"),
            _execution(file="tests/second.spec.ts"),
        ),
    )

    assert result.ref.passed is False
    assert result.test_cases["E2E-001"].status == "duplicate_binding"


@pytest.mark.unit
@pytest.mark.parametrize("status", ["skipped", "failed"])
def test_coverage_observation_rejects_nonpassing_tagged_terminal_result(
    tmp_path: Path, status: str
) -> None:
    result = _write_observation(tmp_path, executions=(_execution(status=status),))

    assert result.ref.passed is False
    assert result.test_cases["E2E-001"].status == status


@pytest.mark.unit
def test_coverage_observation_rejects_a_source_without_the_reported_tag(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "candidate"
    _source(worktree, title="different journey")
    result = _write_observation(tmp_path, worktree=worktree)

    assert result.ref.passed is False
    assert result.test_cases["E2E-001"].status == "invalid_report"


@pytest.mark.unit
def test_coverage_observation_rejects_an_observer_receipt_without_executions(
    tmp_path: Path,
) -> None:
    result = _write_observation(tmp_path, extra_observer_receipt=True)

    assert result.ref.passed is False
    assert result.requirements["FR-001"].status == "observed"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("coverage_map_hash", "0" * 64, "coverage map fingerprint mismatch"),
        ("observer_plan_hash", "1" * 64, "observer plan fingerprint mismatch"),
    ],
)
def test_coverage_observation_validation_rejects_input_fingerprint_drift(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    result = _write_observation(tmp_path)
    expected = {
        "candidate_fingerprint": _FINGERPRINT,
        "coverage_map_hash": _MAP_HASH,
        "resolved_stack_hash": _STACK_HASH,
        "observer_plan_hash": _OBSERVER_PLAN_HASH,
        "runnability_contract_hash": _CONTRACT_HASH,
    }
    expected[field] = value

    validation = validate_coverage_observation(result.ref, **expected)

    assert validation.valid is False
    assert message in validation.reason


@pytest.mark.unit
def test_coverage_observation_validation_rejects_a_symlinked_latest_pointer(
    tmp_path: Path,
) -> None:
    result = _write_observation(tmp_path)
    latest = result.ref.path.parent / "latest.json"
    latest.unlink()
    latest.symlink_to(result.ref.path.name)

    validation = validate_coverage_observation(
        result.ref,
        candidate_fingerprint=_FINGERPRINT,
        coverage_map_hash=_MAP_HASH,
        resolved_stack_hash=_STACK_HASH,
        observer_plan_hash=_OBSERVER_PLAN_HASH,
        runnability_contract_hash=_CONTRACT_HASH,
    )

    assert validation.valid is False
    assert "latest pointer is symlinked" in validation.reason
