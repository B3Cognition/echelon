import json
from pathlib import Path
from types import SimpleNamespace

from harness.verify_result import FailureCategory, FailureEntry, VerifyResult


def _ambiguous_result(worktree: Path) -> VerifyResult:
    return VerifyResult(
        passed=False,
        failures=[
            FailureEntry(
                category=FailureCategory.TEST,
                id="browser-verification-diagnosis-required",
                error=(
                    "Test timeout of 60000ms exceeded.\n"
                    "Error: Object with guid response@abc was not bound in the connection"
                ),
            )
        ],
        verification_evidence={
            "path": str(worktree / "evidence" / "attempt-0002.json"),
        },
    )


def test_debugger_diagnosis_is_read_only_durable_and_routes_timeout_to_repair(
    tmp_path: Path,
) -> None:
    from harness.verification_diagnostic import run_verification_diagnostic

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "package.json").write_text("{}\n", encoding="utf-8")
    before = (worktree / "package.json").read_bytes()
    calls: list[tuple[str, str, dict]] = []

    def execute(cwd: str, prompt: str, **kwargs: object) -> SimpleNamespace:
        calls.append((cwd, prompt, kwargs))
        return SimpleNamespace(
            exit_code=0,
            timed_out=False,
            stderr="",
            stdout=json.dumps(
                {
                    "primary_failure": "test_timeout",
                    "secondary_failure": "cleanup_connection_error",
                    "owner": "product_verification",
                    "disposition": "repair_delivery",
                    "reason": "The second browser navigation exceeded the test budget.",
                    "recommended_action": "Use the project-supported production browser test server.",
                }
            ),
        )

    executor = SimpleNamespace(supports_read_only_review=True, run_agent_result=execute)
    diagnosis = run_verification_diagnostic(
        worktree=worktree,
        evidence_root=tmp_path / "evidence",
        result=_ambiguous_result(worktree),
        executor=executor,
        agent_body="DEBUGGER",
    )

    assert diagnosis.status == "diagnosed"
    assert diagnosis.disposition == "repair_delivery"
    assert diagnosis.owner == "product_verification"
    assert diagnosis.report_path is not None and diagnosis.report_path.is_file()
    assert (worktree / "package.json").read_bytes() == before
    assert len(calls) == 1
    metadata = calls[0][2]["request_metadata"]["prompt_metadata"]
    assert metadata["tool_write_scope_exclusive"] is True
    assert metadata["tool_write_paths"] == []


def test_non_ambiguous_failure_does_not_invoke_debugger(tmp_path: Path) -> None:
    from harness.verification_diagnostic import run_verification_diagnostic

    executor = SimpleNamespace(
        supports_read_only_review=True,
        run_agent_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not invoke DEBUGGER")
        ),
    )
    result = VerifyResult(
        passed=False,
        failures=[FailureEntry(FailureCategory.TEST, "verify-command", "expected 2, received 1")],
    )

    diagnosis = run_verification_diagnostic(
        worktree=tmp_path,
        evidence_root=tmp_path / "evidence",
        result=result,
        executor=executor,
        agent_body="DEBUGGER",
    )

    assert diagnosis.status == "not_applicable"
