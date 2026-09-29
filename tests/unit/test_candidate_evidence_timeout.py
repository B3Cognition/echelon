"""The workspace's explicit verify deadline reaches only authoritative commands."""

from pathlib import Path

import pytest

import harness.candidate_evidence as candidate_evidence
from harness.candidate_evidence import CandidateEvidenceRunner
from harness.config import HarnessConfig
from harness.exec_result import ExecResult
from harness.provider import SandboxHandle
from harness.verification_plan import VerificationPlan
from harness.verify_result import VerifyResult


class RecordingProvider:
    def __init__(self, results: list[ExecResult]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[str, int]] = []

    def exec(self, _handle: SandboxHandle, command: str, **kwargs: object) -> ExecResult:
        self.calls.append((command, kwargs["timeout_ms"]))
        return next(self.results)


def _result(exit_code: int = 0, stdout: str = "") -> ExecResult:
    return ExecResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr="",
        duration_ms=1,
        resource_stats=None,
    )


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    results: list[ExecResult],
    bootstrap_commands: tuple[str, ...] = (),
) -> list[tuple[str, int]]:
    config = HarnessConfig(verify_command="npm run verify")
    # Config parsing is covered separately; isolate sandbox dispatch here.
    config.verification.command_timeout_ms = 1_800_000
    provider = RecordingProvider(results)
    monkeypatch.setattr(
        candidate_evidence,
        "build_verification_plan",
        lambda *_args, **_kwargs: VerificationPlan(
            execution="sandbox",
            image="example:latest",
            bootstrap_commands=bootstrap_commands,
            browser_requirement=None,
        ),
    )
    monkeypatch.setattr(candidate_evidence, "_candidate_fingerprint", lambda _path: "a" * 64)
    monkeypatch.setattr(candidate_evidence, "_current_git_commit", lambda _path: "b" * 40)
    runner = CandidateEvidenceRunner(
        provider=provider,
        config=config,
        sandbox_spec_factory=lambda _path: None,
        evidence_root=tmp_path / "evidence",
        spec_id="001-demo",
        target_id="demo",
        build_id="build-1",
    )
    monkeypatch.setattr(
        runner,
        "_attach_receipt",
        lambda **_kwargs: VerifyResult(passed=True, failures=[], duration_s=0),
    )

    result = runner.run_standard(handle=SandboxHandle(id="sandbox", session_id="session"), worktree=tmp_path)

    assert result.passed is True
    return provider.calls


def test_authoritative_verify_uses_configured_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _run(tmp_path, monkeypatch, results=[_result()])

    assert calls == [("npm run verify", 1_800_000)]


def test_browser_retry_uses_same_configured_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _run(
        tmp_path,
        monkeypatch,
        results=[
            _result(1, "browserContext.newPage: Target crashed; session closed"),
            _result(),
        ],
    )

    assert calls == [
        ("npm run verify", 1_800_000),
        ("npm run verify", 1_800_000),
    ]


def test_bootstrap_retains_ten_minute_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _run(
        tmp_path,
        monkeypatch,
        results=[_result(), _result()],
        bootstrap_commands=("npm ci",),
    )

    assert calls == [("npm ci", 600_000), ("npm run verify", 1_800_000)]
