from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.worked_on_summary import (
    MAX_EVIDENCE_BYTES,
    WorkedOnEvidence,
    delivery_evidence,
    fallback_summary,
    format_worked_on,
    generate_summary,
    phase_a_evidence,
)


class FakeProvider:
    def __init__(
        self,
        stdout: str,
        *,
        exit_code: int = 0,
        timed_out: bool = False,
    ) -> None:
        self.stdout = stdout
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.calls: list[dict[str, object]] = []

    def run_agent_result(self, cwd: str, prompt: str, **kwargs: object) -> object:
        self.calls.append({"cwd": cwd, "prompt": prompt, **kwargs})
        return SimpleNamespace(
            stdout=self.stdout,
            stderr="",
            exit_code=self.exit_code,
            timed_out=self.timed_out,
        )


@pytest.fixture
def summarizer_artifact() -> ProsaicCommandArtifact:
    return ProsaicCommandArtifact(
        frontmatter={
            "name": "echelon.summarizer",
            "model_tier": "fast",
            "effort": "low",
        },
        body="Return the strict summary JSON.",
    )


def _install_fake_prompt(
    monkeypatch: pytest.MonkeyPatch,
    artifact: ProsaicCommandArtifact,
) -> None:
    monkeypatch.setattr(
        "harness.worked_on_summary.ProsaicPromptLoader.load_agent",
        lambda _self, _agent_id: artifact,
    )


def test_phase_a_evidence_preserves_terminal_fields_within_byte_bound() -> None:
    state = {
        "run_id": "spec-20260812-120000-000001",
        "spec_id": "014-session-security",
        "status": "blocked",
        "phase": "terminal-blocked",
        "blocked_reason": "container runtime unavailable",
        "completed_phases": [f"phase-{index}-" + ("x" * 300) for index in range(200)],
        "decisions": ["y" * 1000 for _ in range(100)],
        "artifacts": ["z" * 1000 for _ in range(100)],
    }

    evidence = phase_a_evidence(
        command="spec continue",
        state=state,
        result=SimpleNamespace(status="blocked", phase="terminal-blocked"),
        next_command="echelon spec continue",
    )
    payload = evidence.to_json()

    assert len(payload.encode("utf-8")) <= MAX_EVIDENCE_BYTES
    decoded = json.loads(payload)
    assert decoded["status"] == "blocked"
    assert decoded["blocker"] == "container runtime unavailable"
    assert decoded["next_command"] == "echelon spec continue"


def test_delivery_evidence_reports_progress_verification_and_recovery() -> None:
    result = SimpleNamespace(
        status="blocked",
        termination_reason="build_incomplete",
        final_verify=SimpleNamespace(passed=False, failures=[]),
    )
    comparison = {
        "strategies": {
            "default": {
                "converged": False,
                "outer_iterations": 2,
                "inner_iterations": 1,
                "completed_task_ids": ["T-001", "T-002"],
            }
        },
        "summary": {"converged": 0, "failed": 1},
    }

    evidence = delivery_evidence(
        command="delivery continue",
        intent=SimpleNamespace(spec_id="014-session-security", mode="semi", strategies=("default",)),
        result_map={"default": result},
        comparison=comparison,
        next_command="echelon delivery continue 014-session-security",
    )

    assert evidence.status == "blocked"
    assert evidence.verification == "failed"
    assert evidence.completed_tasks == ("T-001", "T-002")
    assert evidence.next_command == "echelon delivery continue 014-session-security"


def test_delivery_evidence_uses_converged_strategy_verification_regardless_of_order() -> None:
    passed = SimpleNamespace(
        status="done",
        termination_reason="converged",
        final_verify=SimpleNamespace(passed=True, failures=[]),
    )
    failed = SimpleNamespace(
        status="failed",
        termination_reason="outer_cap",
        final_verify=SimpleNamespace(
            passed=False,
            failures=[SimpleNamespace(error="losing strategy failed")],
        ),
    )
    comparison = {
        "strategies": {
            "winner": {"converged": True},
            "loser": {"converged": False},
        },
        "summary": {"converged": 1, "failed": 1},
    }

    for result_map in (
        {"winner": passed, "loser": failed},
        {"loser": failed, "winner": passed},
    ):
        evidence = delivery_evidence(
            command="delivery run",
            intent=SimpleNamespace(spec_id="014", strategies=("winner", "loser")),
            result_map=result_map,
            comparison=comparison,
            next_command="",
        )
        assert evidence.status == "done"
        assert evidence.verification == "passed"
        assert evidence.verification_failures == ()


def test_fallback_is_narrative_and_keeps_recovery_action() -> None:
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        goal="Add secure sessions",
        completed_phases=("phase1-what", "phase3-plan"),
        blocker="container runtime unavailable",
        next_command="echelon spec continue",
    )

    bullets = fallback_summary(evidence)

    assert 2 <= len(bullets) <= 4
    assert bullets[0] == "Worked through 2 phases toward Add secure sessions."
    assert "container runtime unavailable" in bullets[1]
    assert bullets[-1] == "Next, run `echelon spec continue`."
    assert not any("files" in bullet.lower() for bullet in bullets)


def test_generate_summary_uses_fast_low_metadata_once_and_removes_temp_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        json.dumps(
            {
                "bullets": [
                    "Defined the session boundary.",
                    "Verified the new behavior.",
                ]
            }
        )
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        goal="Add sessions",
        verification="passed",
    )

    bullets = generate_summary(tmp_path, evidence, provider=provider)

    assert bullets == (
        "Defined the session boundary.",
        "Verified the new behavior.",
    )
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["timeout_ms"] == 30_000
    assert call["request_metadata"]["quiet"] is True
    metadata = call["request_metadata"]["prompt_metadata"]
    assert metadata["model_tier"] == "fast"
    assert metadata["effort"] == "low"
    assert "tools" not in metadata
    cwd = Path(str(call["cwd"]))
    assert cwd.parent != tmp_path
    assert not cwd.exists()
    assert '"goal":"Add sessions"' in str(call["prompt"])


def test_generate_summary_suppresses_provider_console_noise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)

    class NoisyProvider(FakeProvider):
        def run_agent_result(self, *args, **kwargs):
            print('raw {"bullets":["Done.","Verified."]}')
            print("provider diagnostic", file=sys.stderr)
            return super().run_agent_result(*args, **kwargs)

    provider = NoisyProvider(
        '{"bullets":["Completed the requested work.","Verification passed."]}'
    )
    evidence = WorkedOnEvidence(
        command="spec run", status="done", verification="passed"
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == (
        "Completed the requested work.",
        "Verification passed.",
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        '{"bullets":[]}',
        '{"bullets":["Only one sentence."]}',
        '{"bullets":["One.","Two.","Three.","Four.","Five."]}',
        '{"bullets":["Safe sentence.","Unsafe \\u001b[31mred sentence."]}',
        '{"bullets":["# Heading.","Second sentence."]}',
        '{"bullets":["Run failed verification.","Second sentence."]}',
        '{"bullets":["The work completed successfully.","All checks succeeded."]}',
        '{"bullets":["The implementation completed successfully.","Next action remains."]}',
        '{"bullets":["Everything was successfully implemented.","Next action remains."]}',
        '{"bullets":["The release succeeded.","Next action remains."]}',
        '{"bullets":["The feature shipped successfully.","Next action remains."]}',
        '{"bullets":["Validation succeeded.","Next action remains."]}',
        '{"bullets":["Implemented one change. Verified another.","All done."]}',
    ],
)
def test_generate_summary_falls_back_on_invalid_or_contradictory_output(
    stdout: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(stdout)
    evidence = WorkedOnEvidence(
        command="delivery run",
        status=(
            "blocked"
            if any(
                phrase in stdout
                for phrase in (
                    "completed successfully",
                    "successfully implemented",
                    "release succeeded",
                    "shipped successfully",
                )
            )
            else "done"
        ),
        goal="Add sessions",
        verification=(
            "failed"
            if "All checks succeeded" in stdout or "Validation succeeded" in stdout
            else "passed"
        ),
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("exit_code,timed_out", [(1, False), (0, True)])
def test_generate_summary_falls_back_without_retry_on_provider_failure(
    exit_code: int,
    timed_out: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider("", exit_code=exit_code, timed_out=timed_out)
    evidence = WorkedOnEvidence(command="spec run", status="blocked", blocker="provider unavailable")

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)
    assert len(provider.calls) == 1


def test_format_worked_on_owns_bullet_rendering() -> None:
    assert format_worked_on(("Defined the boundary.", "Verified the behavior.")) == (
        "• Defined the boundary.\n• Verified the behavior."
    )
