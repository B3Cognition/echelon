from __future__ import annotations

import json
from pathlib import Path
import re
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
    read_deferred_evidence,
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
        "provider_limit_message": "Provider session limit resets at 17:00.",
        "verification_summary": "200 focused tests passed",
        "outcomes": ["Implemented provider-owned model selection."],
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
    assert decoded["provider_limit_message"] == "Provider session limit resets at 17:00."
    assert decoded["verification"] == "200 focused tests passed"
    assert decoded["outcomes"] == ["Implemented provider-owned model selection."]
    assert decoded["next_command"] == "echelon spec continue"


def test_rich_evidence_round_trips_through_deferred_storage(tmp_path: Path) -> None:
    path = tmp_path / "worked-on.json"
    evidence = WorkedOnEvidence(
        command="delivery run",
        status="blocked",
        duration="3h 27m",
        outcomes=("Implemented provider-owned model selection.",),
        commits=("abcdef123456 — feat: resolve provider models",),
        provider_limit_message="Session limit resets at 17:00.",
        next_note="Retry after the provider reset.",
    )
    path.write_text(evidence.to_json(), encoding="utf-8")

    assert read_deferred_evidence(path) == evidence


def test_evidence_byte_bound_retains_priority_multibyte_facts() -> None:
    huge = "🙂" * 5_000
    evidence = WorkedOnEvidence(
        command=huge,
        status=huge,
        run_id=huge,
        spec_id=huge,
        goal=huge,
        current_phase=huge,
        duration=huge,
        outcomes=(huge,) * 16,
        commits=(huge,) * 16,
        verification=huge,
        verification_failures=(huge,) * 16,
        blocker=huge,
        provider_limit_message=huge,
        next_command=huge,
        next_note=huge,
    )

    payload = evidence.to_json()
    decoded = json.loads(payload)

    assert len(payload.encode("utf-8")) <= MAX_EVIDENCE_BYTES
    for key in (
        "verification",
        "blocker",
        "provider_limit_message",
        "next_command",
        "next_note",
    ):
        assert decoded[key]


def test_phase_a_evidence_uses_only_recorded_rich_handoff_facts() -> None:
    evidence = phase_a_evidence(
        command="spec continue",
        state={
            "status": "blocked",
            "created_at": "2026-08-12T10:00:00+00:00",
            "updated_at": "2026-08-12T13:27:00+00:00",
            "outcomes": ["Defined deterministic mapping precedence."],
            "verification_summary": "200 focused tests passed",
            "lifecycle_commits": [
                {
                    "commit": "abcdef1234567890abcdef1234567890abcdef12",
                    "subject": "feat: resolve provider models",
                }
            ],
            "provider_limit_message": "Usage limit resets at 17:00.",
        },
        result=SimpleNamespace(status="blocked", phase="phase3-plan"),
        next_command="echelon spec continue",
        next_note="Retry the blocked phase after the provider reset.",
    )

    assert evidence.duration == "3h 27m"
    assert evidence.outcomes == ("Defined deterministic mapping precedence.",)
    assert evidence.verification == "200 focused tests passed"
    assert evidence.commits == (
        "abcdef123456 — feat: resolve provider models",
    )
    assert evidence.provider_limit_message == "Usage limit resets at 17:00."
    assert evidence.next_note == "Retry the blocked phase after the provider reset."


def test_phase_a_evidence_extracts_persisted_delivery_checkpoint_commit() -> None:
    evidence = phase_a_evidence(
        command="spec continue",
        state={
            "status": "blocked",
            "checkpoint_commits": [
                {
                    "commit": "abcdef1234567890abcdef1234567890abcdef12",
                    "subject": "harness-checkpoint: 014/default iter-0 build T-001",
                    "outer_iter": 0,
                    "inner_iter": 1,
                    "phase": "build",
                    "task_ids": ["T-001"],
                    "phase_group": "phase-2-foundation",
                    "completed_tasks_before": 0,
                    "completed_tasks_after": 1,
                    "created_at": "2026-08-12T10:03:05+00:00",
                }
            ],
        },
        result=SimpleNamespace(status="blocked", phase="build"),
        next_command="echelon spec continue",
    )

    assert evidence.commits == (
        "abcdef123456 — harness-checkpoint: 014/default iter-0 build T-001",
    )


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


def test_delivery_evidence_uses_selected_canonical_strategy_facts() -> None:
    result = SimpleNamespace(
        status="blocked",
        termination_reason="provider_session_limit",
        final_verify=SimpleNamespace(passed=True, failures=[], duration_s=12.5),
    )
    comparison = {
        "strategies": {
            "default": {
                "converged": False,
                "started_at": "2026-08-12T10:00:00+00:00",
                "updated_at": "2026-08-12T10:03:05+00:00",
                "outcomes": ["Implemented the resolver."],
                "checkpoint_commits": [
                    {
                        "commit": "1234567890abcdef1234567890abcdef12345678",
                        "subject": "harness-checkpoint: 014/default iter-0 build T-001",
                        "outer_iter": 0,
                        "inner_iter": 1,
                        "phase": "build",
                        "task_ids": ["T-001"],
                        "phase_group": "phase-2-foundation",
                        "completed_tasks_before": 0,
                        "completed_tasks_after": 1,
                        "created_at": "2026-08-12T10:03:05+00:00",
                    }
                ],
                "provider_limit_message": "Rate limit resets in 20 minutes.",
                "next_note": "Retry verification after the provider reset.",
            }
        }
    }

    evidence = delivery_evidence(
        command="delivery continue",
        intent=SimpleNamespace(spec_id="014", strategies=("default",)),
        result_map={"default": result},
        comparison=comparison,
        next_command="echelon delivery continue 014",
    )

    assert evidence.duration == "3m 5s"
    assert evidence.outcomes == ("Implemented the resolver.",)
    assert evidence.verification == "passed in 12.5s"
    assert evidence.commits == (
        "1234567890ab — harness-checkpoint: 014/default iter-0 build T-001",
    )
    assert evidence.provider_limit_message == "Rate limit resets in 20 minutes."
    assert evidence.next_note == "Retry verification after the provider reset."


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


def test_fallback_is_rich_narrative_and_keeps_recovery_action() -> None:
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        goal="Add secure sessions",
        completed_phases=("phase1-what", "phase3-plan"),
        blocker="container runtime unavailable",
        next_command="echelon spec continue",
    )

    lines = fallback_summary(evidence)

    assert 4 <= len(lines) <= 8
    assert lines[0] == "Worked through 2 phases toward Add secure sessions."
    assert any("container runtime unavailable" in line for line in lines)
    assert lines[-1] == "Next, run `echelon spec continue`."
    assert not any("files" in line.lower() for line in lines)


def test_generate_summary_uses_fast_low_metadata_once_and_removes_temp_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        json.dumps(
            {
                "lines": [
                    "Implemented provider-owned model selection.",
                    "Added deterministic mapping precedence.",
                    "Verification passed.",
                    "The feature is ready for integration.",
                ]
            }
        )
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        goal="Add sessions",
        outcomes=(
            "Implemented provider-owned model selection.",
            "Added deterministic mapping precedence.",
        ),
        verification="passed",
    )

    lines = generate_summary(tmp_path, evidence, provider=provider)

    assert lines == (
        "Implemented provider-owned model selection.",
        "Added deterministic mapping precedence.",
        "Verification passed.",
        "The feature is ready for integration.",
    )
    assert "•" not in format_worked_on(lines)
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["timeout_ms"] == 30_000
    assert call["request_metadata"]["quiet"] is True
    assert call["request_metadata"]["allow_non_git_cwd"] is True
    metadata = call["request_metadata"]["prompt_metadata"]
    assert metadata["model_tier"] == "fast"
    assert metadata["effort"] == "low"
    assert "tools" not in metadata
    cwd = Path(str(call["cwd"]))
    assert cwd.parent != tmp_path
    assert not cwd.exists()
    assert '"goal":"Add sessions"' in str(call["prompt"])


@pytest.mark.parametrize(
    "invented_verification",
    (
        "Verification passed across 999 focused tests.",
        "Verification passed with `pytest tests/unit -q`.",
        "Verification passed with pytest tests/unit -q.",
    ),
)
def test_generate_summary_rejects_unrecorded_verification_details(
    invented_verification: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        json.dumps(
            {
                "lines": [
                    "Implemented provider-owned model selection.",
                    "Added deterministic mapping precedence.",
                    invented_verification,
                    "The feature is ready for integration.",
                ]
            }
        )
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        outcomes=(
            "Implemented provider-owned model selection.",
            "Added deterministic mapping precedence.",
        ),
        verification="passed",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_generate_summary_rejects_count_that_only_prefix_matches_recorded_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"lines":["Implemented provider-owned model selection.",'
        '"Recorded verification: passed in 12.5s.",'
        '"Verification covered 12 focused tests.",'
        '"The feature is ready for integration."]}'
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        outcomes=("Implemented provider-owned model selection.",),
        verification="passed in 12.5s",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_generate_summary_rejects_mismatched_recorded_command_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"lines":["Implemented provider-owned model selection.",'
        '"Recorded verification: pytest tests/unit/test_a.py passed.",'
        '"Verification passed with pytest tests/unit/test_b.py.",'
        '"The feature is ready for integration."]}'
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        outcomes=("Implemented provider-owned model selection.",),
        verification="pytest tests/unit/test_a.py passed",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


@pytest.mark.parametrize(
    ("verification", "claim"),
    (
        ("ruff check src passed", "Verification passed with ruff check src."),
        (
            "python -m unittest discover tests passed",
            "Verification passed with python -m unittest discover tests.",
        ),
    ),
)
def test_generate_summary_accepts_exact_arbitrary_recorded_command(
    verification: str,
    claim: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    expected = (
        "Implemented provider-owned model selection.",
        f"Recorded verification: {verification}.",
        claim,
        "The feature is ready for integration.",
    )
    provider = FakeProvider(json.dumps({"lines": list(expected)}))
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        outcomes=("Implemented provider-owned model selection.",),
        verification=verification,
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == expected


def test_generate_summary_suppresses_provider_console_noise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)

    class NoisyProvider(FakeProvider):
        def run_agent_result(self, *args, **kwargs):
            print('raw {"lines":["Done.","Built.","Verified.","Ready."]}')
            print("provider diagnostic", file=sys.stderr)
            return super().run_agent_result(*args, **kwargs)

    provider = NoisyProvider(
        '{"lines":["Implemented the requested work.","Recorded the completed change.",'
        '"Verification passed.","The work is ready for integration."]}'
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        outcomes=(
            "Implemented the requested work.",
            "Recorded the completed change.",
        ),
        verification="passed",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == (
        "Implemented the requested work.",
        "Recorded the completed change.",
        "Verification passed.",
        "The work is ready for integration.",
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        '{"lines":["Only one.","Only two."]}',
        '{"lines":["One.","Two.","Three.","Four.","Five.","Six.","Seven.","Eight.","Nine."]}',
        '{"lines":["Safe sentence.","Unsafe \\u001b[31mred sentence.","Third.","Fourth."]}',
        '{"lines":["# Heading.","Second.","Third.","Fourth."]}',
        '{"lines":["- Bullet.","Second.","Third.","Fourth."]}',
        '{"lines":["Run failed verification.","Second.","Third.","Fourth."]}',
        '{"lines":["The work completed successfully.","All checks succeeded.","Third.","Fourth."]}',
        '{"lines":["The implementation completed successfully.","Next action remains.","Third.","Fourth."]}',
        '{"lines":["Everything was successfully implemented.","Next action remains.","Third.","Fourth."]}',
        '{"lines":["The release succeeded.","Next action remains.","Third.","Fourth."]}',
        '{"lines":["The feature shipped successfully.","Next action remains.","Third.","Fourth."]}',
        '{"lines":["Validation succeeded.","Next action remains.","Third.","Fourth."]}',
        '{"lines":["Implemented one change. Verified another.","Second.","Third.","Fourth."]}',
        'commentary\n{"lines":["One.","Two.","Three.","Four."]}',
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


def test_generate_summary_rejects_blocked_output_that_omits_provider_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"lines":["Implemented the resolver.","Recorded partial progress.",'
        '"The run remains blocked.","Retry the current phase later."]}'
    )
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        blocker="controller_state_contract_validation_failed",
        provider_limit_message="You've hit your session limit.",
        next_command="echelon spec continue",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_generate_summary_rejects_blocked_provider_output_without_limit_or_with_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"lines":["The provider handled the request.","The run remains blocked.",'
        '"The feature is ready for integration.","Next retry remains available."]}'
    )
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        blocker="provider_session_limit",
        provider_limit_message="Session limit resets at 17:00.",
        next_command="echelon spec continue",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_generate_summary_rejects_bounded_evidence_and_code_review_readiness_evasion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"lines":["Bounded evidence explains the stop.","The run remains blocked.",'
        '"The next step is ready for code review.","Retry remains available."]}'
    )
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        blocker="provider_session_limit",
        provider_limit_message="Session limit resets at 17:00.",
        next_command="echelon spec continue",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_generate_summary_rejects_provider_limit_semantic_not_in_recorded_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"lines":["The rate limit explains the stop.","The run remains blocked.",'
        '"Retry remains available.","Next work remains pending."]}'
    )
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        blocker="provider_session_limit",
        provider_limit_message="Session limit resets at 17:00.",
        next_command="echelon spec continue",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_generate_summary_accepts_recorded_provider_limit_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    expected = (
        "The session limit resets at 17:00.",
        "The run remains blocked.",
        "Retry remains available.",
        "Next work remains pending.",
    )
    provider = FakeProvider(json.dumps({"lines": list(expected)}))
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        blocker="provider_session_limit",
        provider_limit_message="Session limit resets at 17:00.",
        next_command="echelon spec continue",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == expected


@pytest.mark.parametrize(
    "readiness",
    (
        "The next step is ready for code review.",
        "The next step is ready for review.",
        "The next step is ready for integration.",
        "The next step is ready to merge.",
        "The next step is ready to deploy.",
    ),
)
def test_generate_summary_rejects_blocked_readiness_variants(
    readiness: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        json.dumps(
            {
                "lines": [
                    "The session limit explains the stop.",
                    "The run remains blocked.",
                    readiness,
                    "Retry remains available.",
                ]
            }
        )
    )
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        blocker="provider_session_limit",
        provider_limit_message="Session limit resets at 17:00.",
        next_command="echelon spec continue",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_generate_summary_rejects_contradiction_of_exact_verification_fact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"lines":["Implemented the resolver.","Recorded the completed change.",'
        '"Verification failed for the work.","The feature is ready for integration."]}'
    )
    evidence = WorkedOnEvidence(
        command="delivery run",
        status="done",
        verification="passed in 12.5s",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


@pytest.mark.parametrize(
    "missing_fact",
    ["verification", "commit", "outcome"],
)
def test_generate_summary_requires_supplied_exact_grounding_facts(
    missing_fact: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    facts = {
        "verification": "Recorded verification: 200 focused tests passed.",
        "commit": "Recorded abcdef123456 — feat: resolve models.",
        "outcome": "Implemented provider-owned model selection.",
    }
    lines = [
        value for key, value in facts.items() if key != missing_fact
    ]
    lines.extend(("Recorded deterministic progress.", "The work is ready for review."))
    provider = FakeProvider(json.dumps({"lines": lines[:4]}))
    evidence = WorkedOnEvidence(
        command="delivery run",
        status="done",
        outcomes=("Implemented provider-owned model selection.",),
        commits=("abcdef123456 — feat: resolve models",),
        verification="200 focused tests passed",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_generate_summary_accepts_all_exact_grounding_facts_with_colons(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    expected = (
        "Implemented provider-owned model selection.",
        "Recorded verification: 200 focused tests passed.",
        "Recorded abcdef123456 — feat: resolve models.",
        "The work is ready for review.",
    )
    provider = FakeProvider(json.dumps({"lines": list(expected)}))
    evidence = WorkedOnEvidence(
        command="delivery run",
        status="done",
        outcomes=("Implemented provider-owned model selection.",),
        commits=("abcdef123456 — feat: resolve models",),
        verification="200 focused tests passed",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == expected


def test_generate_summary_rejects_claim_piggybacking_on_exact_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"lines":["Refactored OAuth while implemented provider-owned model selection.",'
        '"The recorded run status is done.","The work is ready for review.",'
        '"No further recovery command was recorded."]}'
    )
    evidence = WorkedOnEvidence(
        command="delivery run",
        status="done",
        outcomes=("Implemented provider-owned model selection.",),
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


@pytest.mark.parametrize(
    "invented",
    [
        "Implemented an OAuth gateway.",
        "Refactored authentication into a new gateway.",
        "Deployed the service integration.",
        "Worked through one phase and refactored authentication into a new OAuth gateway.",
        "Worked through one phase; refactored authentication into a new OAuth gateway.",
        "Worked through one phase, then refactored authentication into a new OAuth gateway.",
    ],
)
def test_generate_summary_rejects_unrecorded_engineering_outcome(
    invented: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        json.dumps(
            {
                "lines": [
                    invented,
                    "Worked through one phase.",
                    "The recorded run status is done.",
                    "The work is ready for review.",
                ]
            }
        )
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        completed_phases=("phase1-what",),
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(evidence)


def test_fallback_lines_remain_within_external_contract_bounds() -> None:
    huge = "🙂" * 1_000
    evidence = WorkedOnEvidence(
        command=huge,
        status="blocked",
        goal=huge,
        duration=huge,
        blocker=huge,
        provider_limit_message=huge,
        next_command=huge,
        next_note=huge,
    )

    lines = fallback_summary(evidence)

    assert 4 <= len(lines) <= 8
    assert all(len(line) <= 280 for line in lines)
    assert sum(len(line) for line in lines) <= 1_600
    assert all(len(re.findall(r"[.!?](?:\s|$)", line)) == 1 for line in lines)


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


def test_format_worked_on_joins_plain_lines_without_glyphs() -> None:
    assert format_worked_on(("Implemented the resolver.", "Verification passed.")) == (
        "Implemented the resolver.\nVerification passed."
    )
    assert "•" not in format_worked_on(("Implemented the resolver.",))
