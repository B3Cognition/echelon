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
        verification="passed: `bash  -lc 'pytest -q'`",
        provider_limit_message="Session limit resets at 17:00.",
        next_command="bash  -lc 'echelon delivery continue 014'",
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


def test_delivery_evidence_keeps_canonical_provider_limit_for_generic_stop() -> None:
    result = SimpleNamespace(
        status="blocked",
        termination_reason="build_incomplete",
        final_verify=None,
    )
    evidence = delivery_evidence(
        command="delivery continue",
        intent=SimpleNamespace(spec_id="014", strategies=("default",)),
        result_map={"default": result},
        comparison={
            "strategies": {
                "default": {
                    "converged": False,
                    "provider_limit_message": "Usage limit resets at 17:00.",
                }
            }
        },
        next_command="echelon delivery continue 014",
    )

    assert evidence.provider_limit_message == "Usage limit resets at 17:00."


def test_delivery_scope_recovers_rich_persisted_strategy_evidence(
    tmp_path: Path,
) -> None:
    from harness.worked_on_summary import _SummaryScope, _delivery_scope_evidence

    state_dir = tmp_path / "runs" / "build-1" / "state"
    state_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current-build-014").write_text(
        "build-1",
        encoding="utf-8",
    )
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "termination_reason": "build_incomplete",
                "duration": "3m 5s",
                "outcomes": ["Implemented the resolver."],
                "checkpoint_commits": [
                    {"commit": "abcdef1234567", "subject": "checkpoint resolver"}
                ],
                "verification_summary": "pytest tests/unit -q passed",
                "provider_limit_message": "Usage limit resets at 17:00.",
                "next_note": "Retry after the provider reset.",
            }
        ),
        encoding="utf-8",
    )

    evidence = _delivery_scope_evidence(
        _SummaryScope("delivery continue", tmp_path, spec_id="014")
    )

    assert evidence is not None
    assert evidence.duration == "3m 5s"
    assert evidence.outcomes == ("Implemented the resolver.",)
    assert evidence.commits == ("abcdef123456 — checkpoint resolver",)
    assert evidence.verification == "pytest tests/unit -q passed"
    assert evidence.provider_limit_message == "Usage limit resets at 17:00."
    assert evidence.next_note == "Retry after the provider reset."


def test_delivery_scope_normalizes_converged_state_to_ready_candidate(
    tmp_path: Path,
) -> None:
    from harness.worked_on_summary import (
        _SummaryScope,
        _delivery_scope_evidence,
        narrative_candidates,
    )

    state_dir = tmp_path / "runs" / "build-1" / "state"
    state_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current-build-014").write_text(
        "build-1",
        encoding="utf-8",
    )
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "status": "converged",
                "termination_reason": "converged",
                "outcomes": ["Implemented the resolver."],
                "verification_summary": "passed in 12.5s",
            }
        ),
        encoding="utf-8",
    )

    evidence = _delivery_scope_evidence(
        _SummaryScope("delivery continue", tmp_path, spec_id="014")
    )

    assert evidence is not None
    assert evidence.status == "done"
    assert evidence.blocker == ""
    assert evidence.next_command == ""
    candidate_ids = {candidate.id for candidate in narrative_candidates(evidence)}
    assert "readiness" in candidate_ids
    assert "blocker" not in candidate_ids


def test_candidate_selection_packet_is_bounded_and_retains_required_facts() -> None:
    from harness.worked_on_summary import (
        _candidate_selection_packet,
        narrative_candidates,
    )

    huge = "🙂" * 600
    evidence = WorkedOnEvidence(
        command="delivery continue",
        status="blocked",
        outcomes=tuple(f"Outcome {index} {huge}" for index in range(64)),
        decisions=tuple(f"Decision {index} {huge}" for index in range(64)),
        commits=tuple(
            f"abcdef12345{index % 10} — checkpoint {index} {huge}"
            for index in range(64)
        ),
        blocker="verification failed",
        provider_limit_message="Usage limit resets at 17:00.",
        next_command="echelon delivery continue 014",
    )

    packet, retained = _candidate_selection_packet(narrative_candidates(evidence))
    payload = json.loads(packet)
    by_id = {candidate.id: candidate for candidate in retained}

    assert len(packet.encode("utf-8")) <= MAX_EVIDENCE_BYTES
    assert {"blocker", "provider-limit", "next-action"} <= set(by_id)
    assert by_id["blocker"].text == "The run stopped because verification failed."
    assert by_id["provider-limit"].text == (
        "The provider reported a limit: Usage limit resets at 17:00."
    )
    assert by_id["next-action"].text == (
        "Next, run `echelon delivery continue 014`."
    )
    assert {item["id"] for item in payload["candidates"]} == set(by_id)


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

def test_narrative_candidates_are_controller_authored_and_stably_identified() -> None:
    from harness.worked_on_summary import narrative_candidates

    evidence = WorkedOnEvidence(
        command="delivery run",
        status="done",
        goal="Add sessions",
        completed_tasks=("T-001", "T-002"),
        outcomes=(
            "Implemented the resolver.",
            "Added deterministic mapping precedence.",
        ),
        decisions=("Use provider-owned mapping.",),
        verification="pytest tests/unit/test_resolver.py -q passed",
        commits=("abcdef123456 — feat: implement resolver",),
    )

    candidates = narrative_candidates(evidence)
    by_id = {candidate.id: candidate for candidate in candidates}

    assert tuple(by_id) == (
        "outcome",
        "progress",
        "outcome-2",
        "decision-1",
        "verification",
        "commit-1",
        "readiness",
    )
    assert by_id["outcome"].text == "Implemented the resolver."
    assert by_id["progress"].text == "Worked through 2 tasks toward Add sessions."
    assert by_id["outcome-2"].text == "Added deterministic mapping precedence."
    assert by_id["decision-1"].text == "Recorded decision: Use provider-owned mapping."
    assert by_id["verification"].text == (
        "Recorded verification: pytest tests/unit/test_resolver.py -q passed."
    )
    assert by_id["commit-1"].text == (
        "Recorded lifecycle commit abcdef123456 — feat: implement resolver."
    )
    assert by_id["readiness"].text == "The completed work is ready for review."
    assert all(not candidate.required for candidate in candidates)


def test_unfinished_candidate_facts_are_required() -> None:
    from harness.worked_on_summary import narrative_candidates

    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        blocker="controller state validation failed",
        provider_limit_message="Session limit resets at 17:00.",
        next_command="echelon spec continue",
    )

    by_id = {
        candidate.id: candidate
        for candidate in narrative_candidates(evidence)
    }

    assert by_id["blocker"].text == (
        "The run stopped because controller state validation failed."
    )
    assert by_id["provider-limit"].text == (
        "The provider reported a limit: Session limit resets at 17:00."
    )
    assert by_id["next-action"].text == "Next, run `echelon spec continue`."
    assert {
        candidate_id
        for candidate_id, candidate in by_id.items()
        if candidate.required
    } == {"blocker", "provider-limit", "next-action"}


def test_sparse_unfinished_evidence_still_builds_four_factual_candidates() -> None:
    from harness.worked_on_summary import narrative_candidates

    candidates = narrative_candidates(
        WorkedOnEvidence(
            command="delivery run",
            status="failed",
            next_command="echelon delivery continue 014",
        )
    )

    assert len(candidates) >= 4
    assert candidates[0].text == (
        "Attempted delivery run for the requested work."
    )
    assert any(
        candidate.text == "No completed tasks or phases were recorded."
        for candidate in candidates
    )
    assert any(
        candidate.text == "The recorded run status is failed."
        for candidate in candidates
    )
    assert any(
        candidate.text == "Next, run `echelon delivery continue 014`."
        for candidate in candidates
    )


def test_candidate_commands_remain_controller_owned_opaque_text() -> None:
    from harness.worked_on_summary import narrative_candidates

    verification = (
        "passed: `bash  -lc 'pytest tests/unit/test_a.py -q && "
        "printf \"%s\" \"$TOKEN\"'`"
    )
    next_command = (
        "bash  -lc 'echelon delivery continue 014 && "
        "printf \"%s\" \"$TOKEN\"'"
    )
    candidates = narrative_candidates(
        WorkedOnEvidence(
            command="delivery continue",
            status="blocked",
            verification=verification,
            blocker="provider_session_limit",
            next_command=next_command,
        )
    )
    by_id = {candidate.id: candidate.text for candidate in candidates}

    assert verification in by_id["verification"]
    assert next_command in by_id["next-action"]


def test_opaque_candidate_facts_cannot_inject_terminal_lines() -> None:
    from harness.worked_on_summary import narrative_candidates

    candidates = narrative_candidates(
        WorkedOnEvidence(
            command="delivery continue",
            status="blocked",
            verification="passed\rFORGED STATUS\r\nMORE",
            blocker="provider_session_limit",
            next_command="echo ok\rFORGED ACTION",
        )
    )
    rendered = format_worked_on(candidate.text for candidate in candidates)

    assert "\r" not in rendered
    assert "\nFORGED" not in rendered


def test_progress_candidate_surfaces_recorded_duration() -> None:
    from harness.worked_on_summary import narrative_candidates

    candidates = narrative_candidates(
        WorkedOnEvidence(
            command="delivery run",
            status="done",
            duration="3m 5s",
        )
    )

    assert {candidate.id: candidate.text for candidate in candidates}["progress"] == (
        "The recorded run duration was 3m 5s."
    )


def _candidate_fixture() -> tuple[object, ...]:
    from harness.worked_on_summary import NarrativeCandidate

    return (
        NarrativeCandidate("outcome", "Implemented the resolver.", 10),
        NarrativeCandidate("changes", "Added deterministic mapping.", 20),
        NarrativeCandidate("verification", "Verification passed.", 30),
        NarrativeCandidate("blocker", "The run remains blocked.", 40, required=True),
        NarrativeCandidate(
            "provider-limit",
            "The provider reported a session limit.",
            50,
            required=True,
        ),
        NarrativeCandidate(
            "next-action",
            "Next, run `echelon spec continue`.",
            60,
            required=True,
        ),
        NarrativeCandidate("readiness", "The work is ready for review.", 70),
        NarrativeCandidate("commit-1", "Recorded commit abcdef123456.", 80),
        NarrativeCandidate("decision-1", "Recorded decision: use A.", 90),
    )


def test_selected_candidate_ids_accepts_exact_closed_contract() -> None:
    from harness.worked_on_summary import _selected_candidate_ids

    candidates = _candidate_fixture()
    assert _selected_candidate_ids(
        '{"line_ids":["outcome","changes","verification","blocker",'
        '"provider-limit","next-action"]}',
        candidates,
    ) == (
        "outcome",
        "changes",
        "verification",
        "blocker",
        "provider-limit",
        "next-action",
    )


@pytest.mark.parametrize(
    "raw",
    (
        '{"line_ids":["outcome","changes"]}',
        '{"line_ids":["outcome","changes","verification","blocker",'
        '"provider-limit","next-action","readiness","commit-1","decision-1"]}',
        '{"line_ids":["outcome","changes","verification","unknown",'
        '"blocker","provider-limit","next-action"]}',
        '{"line_ids":["outcome","changes","verification","verification",'
        '"blocker","provider-limit","next-action"]}',
        'commentary\n{"line_ids":["outcome","changes","verification","blocker",'
        '"provider-limit","next-action"]}',
        '{"line_ids":["outcome","changes","verification","blocker",'
        '"provider-limit","next-action"],"text":"MODEL INJECTION"}',
        '{"line_ids":["outcome","changes","verification","blocker",'
        '"provider-limit","next-action"],"lines":["MODEL INJECTION"]}',
    ),
)
def test_selected_candidate_ids_rejects_malformed_or_open_contract(raw: str) -> None:
    from harness.worked_on_summary import _selected_candidate_ids

    assert _selected_candidate_ids(raw, _candidate_fixture()) is None


@pytest.mark.parametrize("omitted", ("blocker", "provider-limit", "next-action"))
def test_selected_candidate_ids_rejects_omitted_required_id(omitted: str) -> None:
    from harness.worked_on_summary import _selected_candidate_ids

    ids = [
        candidate.id
        for candidate in _candidate_fixture()
        if candidate.id != omitted
    ][:8]
    assert len(ids) >= 4

    assert _selected_candidate_ids(
        json.dumps({"line_ids": ids}),
        _candidate_fixture(),
    ) is None


def test_generate_summary_renders_only_selected_controller_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    from harness.worked_on_summary import NarrativeCandidate

    candidates = (
        NarrativeCandidate("outcome", "Implemented the resolver.", 10),
        NarrativeCandidate("changes", "Added deterministic mapping.", 20),
        NarrativeCandidate("verification", "Verification passed.", 30),
        NarrativeCandidate("readiness", "The work is ready for review.", 40),
    )
    monkeypatch.setattr(
        "harness.worked_on_summary.narrative_candidates",
        lambda _evidence: candidates,
    )
    provider = FakeProvider(
        '{"line_ids":["outcome","changes","verification","readiness"]}'
    )

    lines = generate_summary(
        tmp_path,
        WorkedOnEvidence(command="delivery run", status="done"),
        provider=provider,
    )

    assert lines == tuple(candidate.text for candidate in candidates)
    assert format_worked_on(lines) == (
        "Implemented the resolver.\n"
        "Added deterministic mapping.\n"
        "Verification passed.\n"
        "The work is ready for review."
    )
    assert "•" not in format_worked_on(lines)


@pytest.mark.parametrize(
    "raw",
    (
        '{"line_ids":["outcome","progress","verification","readiness"],'
        '"text":"MODEL-AUTHORED SENTENCE"}',
        '{"line_ids":["outcome","progress","verification","readiness"],'
        '"lines":["MODEL-AUTHORED SENTENCE"]}',
        '{"line_ids":["outcome","progress","verification","unknown"]}',
        '{"line_ids":["outcome","outcome","verification","readiness"]}',
    ),
)
def test_model_text_and_invalid_ids_never_render(
    raw: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    evidence = WorkedOnEvidence(
        command="delivery run",
        status="done",
        goal="Add sessions",
        outcomes=("Implemented the resolver.",),
        verification="passed",
    )
    fallback = fallback_summary(evidence)

    rendered = generate_summary(
        tmp_path,
        evidence,
        provider=FakeProvider(raw),
    )

    assert rendered == fallback
    assert "MODEL-AUTHORED SENTENCE" not in format_worked_on(rendered)
    assert "unknown" not in format_worked_on(rendered)


def test_generate_summary_requires_all_unfinished_required_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    evidence = WorkedOnEvidence(
        command="spec continue",
        status="blocked",
        blocker="controller state validation failed",
        provider_limit_message="Session limit resets at 17:00.",
        next_command="echelon spec continue",
    )
    provider = FakeProvider(
        '{"line_ids":["outcome","progress","verification","blocker",'
        '"next-action"]}'
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(
        evidence
    )


def test_generate_summary_uses_fast_low_metadata_once_and_removes_temp_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)
    provider = FakeProvider(
        '{"line_ids":["outcome","progress","verification","readiness"]}'
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        goal="Add sessions",
        outcomes=("Implemented provider-owned model selection.",),
        verification="passed",
    )

    lines = generate_summary(tmp_path, evidence, provider=provider)

    assert lines == (
        "Implemented provider-owned model selection.",
        "No completed tasks or phases were recorded.",
        "Verification passed for the completed work.",
        "The completed work is ready for review.",
    )
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
    prompt = str(call["prompt"])
    assert '"candidates":' in prompt
    assert '"id":"outcome"' in prompt
    assert '"required":false' in prompt


def test_generate_summary_suppresses_provider_console_noise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    summarizer_artifact: ProsaicCommandArtifact,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_prompt(monkeypatch, summarizer_artifact)

    class NoisyProvider(FakeProvider):
        def run_agent_result(self, *args, **kwargs):
            print('raw {"line_ids":["outcome","progress","verification","readiness"]}')
            print("provider diagnostic", file=sys.stderr)
            return super().run_agent_result(*args, **kwargs)

    provider = NoisyProvider(
        '{"line_ids":["outcome","progress","verification","readiness"]}'
    )
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        outcomes=("Implemented the requested work.",),
        verification="passed",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == (
        "Implemented the requested work.",
        "No completed tasks or phases were recorded.",
        "Verification passed for the completed work.",
        "The completed work is ready for review.",
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_fallback_orders_candidates_and_retains_required_facts() -> None:
    evidence = WorkedOnEvidence(
        command="delivery continue",
        status="blocked",
        outcomes=tuple(f"Recorded outcome {index}." for index in range(8)),
        decisions=tuple(f"Decision {index}." for index in range(8)),
        commits=tuple(
            f"abcdef12345{index} — checkpoint {index}"
            for index in range(8)
        ),
        verification="failed",
        blocker="verification failed",
        provider_limit_message="Usage limit resets at 17:00.",
        next_command="echelon delivery continue 014",
    )

    lines = fallback_summary(evidence)

    assert 4 <= len(lines) <= 8
    assert any("verification failed" in line for line in lines)
    assert any("Usage limit resets at 17:00." in line for line in lines)
    assert lines[-1] == "Next, run `echelon delivery continue 014`."


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
    evidence = WorkedOnEvidence(
        command="spec run",
        status="blocked",
        blocker="provider unavailable",
    )

    assert generate_summary(tmp_path, evidence, provider=provider) == fallback_summary(
        evidence
    )
    assert len(provider.calls) == 1


def test_format_worked_on_joins_plain_lines_without_glyphs() -> None:
    assert format_worked_on(("Implemented the resolver.", "Verification passed.")) == (
        "Implemented the resolver.\nVerification passed."
    )
    assert "•" not in format_worked_on(("Implemented the resolver.",))
