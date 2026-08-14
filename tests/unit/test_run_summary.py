from __future__ import annotations

from pathlib import Path
import sys

import pytest

from harness.ai_cli_backend import CliRunResult
from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.run_summary import (
    RunSummaryContext,
    SummaryAgent,
    summarize_run,
    summarize_run_for_cli,
)


class _RecordingProvider:
    def __init__(self, result: CliRunResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def run_agent_result(
        self,
        cwd: str,
        prompt: str,
        **kwargs: object,
    ) -> CliRunResult:
        self.calls.append((cwd, prompt, kwargs))
        return self.result


def _context(project_root: Path) -> RunSummaryContext:
    return RunSummaryContext(
        project_root=project_root,
        command="echelon spec continue",
        task="Add a human-readable run handoff.",
        status="done",
        facts=(
            "Published specs/123-run-handoff/spec.md.",
            "Verification passed: 42 tests.",
        ),
        next_step="echelon delivery run 123-run-handoff",
        inspect_paths=(project_root / "runs" / "spec-123",),
    )


def test_summarize_run_uses_fast_low_agent_in_isolated_directory(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout=(
                "Published the run-handoff specification.\n"
                "Verified the result with 42 passing tests.\n"
                "The specification is ready for delivery."
            ),
            stderr="",
        )
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low", "tools": "write"},
    )

    summary = summarize_run(_context(project_root), provider=provider, agent=agent)

    assert summary == (
        "Published the run-handoff specification.\n"
        "Verified the result with 42 passing tests.\n"
        "The specification is ready for delivery."
    )
    assert len(provider.calls) == 1
    cwd, prompt, kwargs = provider.calls[0]
    assert Path(cwd) != project_root
    assert project_root not in Path(cwd).parents
    assert not Path(cwd).exists()
    assert '"command": "echelon spec continue"' in prompt
    assert '"status": "done"' in prompt
    assert "Published specs/123-run-handoff/spec.md." in prompt
    assert kwargs["timeout_ms"] == 30_000
    assert kwargs["request_metadata"] == {
        "allow_non_git_cwd": True,
        "prompt_metadata": {
            "model_tier": "fast",
            "effort": "low",
            "tools": "write",
            "quiet": True,
        }
    }


def test_summarize_run_falls_back_when_agent_fails(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(exit_code=1, stdout="", stderr="provider unavailable")
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low"},
    )

    summary = summarize_run(_context(project_root), provider=provider, agent=agent)

    assert summary == (
        "Echelon completed the requested specification work.\n"
        "Published specs/123-run-handoff/spec.md.\n"
        "Verification passed: 42 tests.\n"
        "Next: echelon delivery run 123-run-handoff"
    )


def test_quality_debt_and_provider_limit_are_bounded_independent_summary_truths(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec continue",
        task="Prepare a proportional specification.",
        status="done",
        facts=("Result: done.",),
        next_step="echelon delivery run 001-demo",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80", "atomicity 0.72 < 0.85"),
        quality_debt_resolved_by="COMMANDER",
        provider_limit_message="Provider limit reached; resets at 21:10.",
    )
    provider = _RecordingProvider(
        CliRunResult(exit_code=1, stdout="", stderr="provider unavailable")
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "accepted with quality debt" in summary.lower()
    assert "overall 0.70 < 0.80" in summary
    assert "atomicity 0.72 < 0.85" in summary
    assert "COMMANDER" in summary
    assert "quality-debt.json" in summary
    assert "Provider limit reached" in summary
    assert "quality passed" not in summary.lower()


def test_qualitative_only_quality_debt_names_residual_sage_findings(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec continue",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=(),
        quality_debt_qualitative_issues=(
            "ISS-QUALITY-0: Residual quality debt",
        ),
        quality_debt_resolved_by="user",
    )
    provider = _RecordingProvider(
        CliRunResult(exit_code=1, stdout="", stderr="provider unavailable")
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "accepted with quality debt" in summary.lower()
    assert "ISS-QUALITY-0: Residual quality debt" in summary
    assert "quality passed" not in summary.lower()


def test_summary_agent_receives_bounded_quality_debt_fields(tmp_path: Path) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=tuple(f"gate-{index}" for index in range(12)),
        quality_debt_resolved_by="user",
    )
    provider = _RecordingProvider(
        CliRunResult(exit_code=0, stdout="Accepted with quality debt.", stderr="")
    )

    summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    prompt = provider.calls[0][1]
    assert '"quality_debt_status": "accepted_with_debt"' in prompt
    assert '"quality_debt_artifact": "specs/001-demo/quality-debt.json"' in prompt
    assert '"quality_debt_resolved_by": "user"' in prompt
    assert "gate-0" in prompt
    assert "gate-7" in prompt
    assert "gate-8" not in prompt


def test_summary_agent_cannot_collapse_authorized_debt_into_quality_pass(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="user",
    )
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout="Specification quality passed and is fully certified.",
            stderr="",
        )
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "accepted with quality debt" in summary.lower()
    assert "quality passed" not in summary.lower()
    assert "fully certified" not in summary.lower()


def test_model_summary_cannot_omit_required_debt_and_provider_facts(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80", "atomicity 0.72 < 0.85"),
        quality_debt_resolved_by="COMMANDER",
        provider_limit_message="Provider limit reached; resets at 21:10.",
    )
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout="Implemented the requested specification and prepared delivery.",
            stderr="",
        )
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "accepted with quality debt" in summary.lower()
    assert "COMMANDER" in summary
    assert "overall 0.70 < 0.80" in summary
    assert "atomicity 0.72 < 0.85" in summary
    assert "specs/001-demo/quality-debt.json" in summary
    assert "Provider limit reached; resets at 21:10" in summary


def test_model_summary_rejects_success_wording_that_contradicts_accepted_debt(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="user",
    )
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout="All specification quality checks succeeded; the work is ready.",
            stderr="",
        )
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "all specification quality checks succeeded" not in summary.lower()
    assert "accepted with quality debt" in summary.lower()


@pytest.mark.parametrize(
    "claim",
    (
        "The specification cleared every quality bar.",
        "Quality review found no remaining issues.",
        "The spec meets all required standards.",
        "Every acceptance criterion has been satisfied.",
        "The requirements are validated and ready for unconditional approval.",
        "No defects remain in the specification assessment.",
        "The quality gates exceeded every benchmark.",
        "The specification earned a clean bill of health.",
        "All requirement concerns have been resolved.",
        "The specification is fully compliant.",
        "No outstanding concerns remain in the specification.",
        "The specification is free of deficiencies.",
        "The specification looks good overall.",
        "Specification deficiencies are absent.",
        "The specification lacks unresolved concerns.",
        "There are zero quality failures.",
        "Specification quality reports an absence of deficiencies.",
        "The specification is concern-free.",
        "Successfully fixed all specification quality issues.",
        "Resolved every specification quality concern.",
    ),
)
def test_debt_mode_rejects_paraphrased_specification_quality_success_claims(
    tmp_path: Path,
    claim: str,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="COMMANDER",
    )
    provider = _RecordingProvider(
        CliRunResult(exit_code=0, stdout=claim, stderr="")
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert claim not in summary
    assert "accepted with quality debt by COMMANDER" in summary
    assert "overall 0.70 < 0.80" in summary


def test_debt_mode_removes_only_contradictory_specification_clause(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="COMMANDER",
    )
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout=(
                "Successfully implemented downstream planning. "
                "The specification continued with accepted quality debt."
            ),
            stderr="",
        )
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "Successfully implemented downstream planning." in summary
    assert summary.lower().count("accepted with quality debt") == 1
    assert "overall 0.70 < 0.80" in summary


@pytest.mark.parametrize(
    "narration",
    (
        "Successfully implemented downstream planning.",
        "Implemented specification debt propagation across planning.",
        "The specification remains below the overall quality threshold.",
        "Recorded unresolved concerns in specification evidence.",
        "No outstanding concerns remain in downstream planning.",
        "Successfully implemented quality-debt propagation through planning.",
        (
            "Successfully implemented downstream planning, while specification "
            "quality remains below threshold."
        ),
    ),
)
def test_debt_mode_preserves_non_verdict_work_and_debt_narration(
    tmp_path: Path,
    narration: str,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="COMMANDER",
    )
    provider = _RecordingProvider(
        CliRunResult(exit_code=0, stdout=narration, stderr="")
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert narration in summary


@pytest.mark.parametrize(
    "narration",
    (
        "Implemented residual gates display in the CLI.",
        "Implemented handling when the specification is accepted with quality debt.",
        "Implemented provider session limit handling and reset messaging.",
        "Documented residual gates in the CLI.",
        "Displayed specs/001/quality-debt.json in status.",
        "Handled provider session limit reset messaging.",
    ),
)
def test_authoritative_truth_dedup_preserves_genuine_action_narration(
    tmp_path: Path,
    narration: str,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="COMMANDER",
        provider_limit_message="You've hit your session limit · resets 4am",
    )
    provider = _RecordingProvider(
        CliRunResult(exit_code=0, stdout=narration, stderr="")
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert narration in summary
    assert "accepted with quality debt" in summary.lower()
    assert summary.count("You've hit your session limit · resets 4am") == 1


@pytest.mark.parametrize(
    ("model_line", "safe_action", "forbidden_verdict"),
    (
        (
            "Implemented downstream planning and the specification passed every quality gate.",
            "Implemented downstream planning",
            "passed every quality gate",
        ),
        (
            "Added CLI status, but the specification is free of deficiencies.",
            "Added CLI status",
            "free of deficiencies",
        ),
        (
            "Wired planning, although specification quality reports an absence of failures.",
            "Wired planning",
            "absence of failures",
        ),
        (
            "Implemented downstream planning and it passed all checks.",
            "Implemented downstream planning",
            "passed all checks",
        ),
        (
            "Added CLI status and certified the specification.",
            "Added CLI status",
            "certified the specification",
        ),
        (
            "Implemented planning and met every quality standard.",
            "Implemented planning",
            "met every quality standard",
        ),
        (
            "Updated CLI status and fixed all specification quality issues.",
            "Updated CLI status",
            "fixed all specification quality issues",
        ),
    ),
)
def test_debt_mode_splits_action_narration_from_embedded_quality_verdict(
    tmp_path: Path,
    model_line: str,
    safe_action: str,
    forbidden_verdict: str,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="COMMANDER",
    )
    provider = _RecordingProvider(
        CliRunResult(exit_code=0, stdout=model_line, stderr="")
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert safe_action in summary
    assert forbidden_verdict not in summary.lower()
    assert "accepted with quality debt" in summary.lower()


@pytest.mark.parametrize(
    "narration",
    (
        "Implemented downstream planning and updated verification wiring.",
        "Documented residual gates and provider reset behavior.",
        "Added CLI status and surfaced debt evidence.",
        "Tested planning and fixed CLI rendering.",
    ),
)
def test_debt_mode_preserves_ordinary_coordinated_work_actions(
    tmp_path: Path,
    narration: str,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="COMMANDER",
    )
    provider = _RecordingProvider(
        CliRunResult(exit_code=0, stdout=narration, stderr="")
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert narration in summary


def test_session_limit_and_quality_debt_implementation_narration_are_deduplicated(
    tmp_path: Path,
) -> None:
    provider_message = "You've hit your session limit · resets 4am"
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="COMMANDER",
        provider_limit_message=provider_message,
    )
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout=(
                "Implemented quality-debt propagation through planning and verification.\n"
                f"{provider_message}"
            ),
            stderr="",
        )
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert (
        "Implemented quality-debt propagation through planning and verification."
        in summary
    )
    assert summary.count(provider_message) == 1
    assert len(summary.splitlines()) <= 7
    assert len(summary) <= 1_200
    assert "accepted with quality debt" in summary.lower()


def test_pure_debt_and_session_limit_truth_echoes_are_deduplicated(
    tmp_path: Path,
) -> None:
    provider_message = "You've hit your session limit · resets 4am"
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=("overall 0.70 < 0.80",),
        quality_debt_resolved_by="COMMANDER",
        provider_limit_message=provider_message,
    )
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout=f"Accepted with quality debt.\n{provider_message}",
            stderr="",
        )
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert summary.lower().count("accepted with quality debt") == 1
    assert summary.count(provider_message) == 1


def test_long_obedient_model_summary_is_bounded_and_truths_are_deduplicated(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon spec run",
        task="Prepare a proportional specification.",
        status="done",
        quality_debt_status="accepted_with_debt",
        quality_debt_artifact="specs/001-demo/quality-debt.json",
        quality_debt_failed_gates=(
            "overall 0.70 < 0.80",
            "atomicity 0.72 < 0.85",
        ),
        quality_debt_resolved_by="COMMANDER",
        provider_limit_message="Provider limit reached; resets at 21:10.",
    )
    narrative = "Implemented proportional authoring behavior " + ("carefully " * 30)
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout="\n".join(
                (
                    narrative,
                    (
                        "Specification quality was accepted with quality debt by "
                        "COMMANDER; residual gate overall remains below threshold."
                    ),
                    "Provider limit reached; resets at 21:10.",
                    narrative,
                    narrative,
                    narrative,
                    narrative,
                )
            ),
            stderr="",
        )
    )

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert len(summary.splitlines()) <= 7
    assert len(summary) <= 1_200
    assert summary.lower().count("accepted with quality debt") == 1
    assert summary.lower().count("provider limit") == 1
    assert "COMMANDER" in summary
    assert "overall 0.70 < 0.80" in summary
    assert "atomicity 0.72 < 0.85" in summary
    assert "quality-debt.json" in summary


def test_delivery_fallback_prioritizes_outcome_and_verification_over_branch_noise(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon delivery continue",
        task="Deliver spec 123.",
        status="blocked",
        facts=(
            "default: branch: harness/123/default/iter-2",
            "default: PR: not created",
            "default: iterations: 2 outer, 3 inner retries",
            "default: verify: ✗ failed (1 check)",
            "default: stopped: checkpoint recovery needed",
            "Delivery result: 0 converged, 0 failed, 1 checkpointed.",
        ),
        next_step="echelon delivery continue 123",
    )
    provider = _RecordingProvider(CliRunResult(exit_code=1, stdout="", stderr=""))

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "Delivery result: 0 converged, 0 failed, 1 checkpointed." in summary
    assert "Verification: ✗ failed (1 check)." in summary
    assert "checkpoint recovery needed" in summary
    assert "branch:" not in summary
    assert "iterations:" not in summary


def test_delivery_fallback_does_not_report_one_strategy_as_aggregate_verification(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon delivery run",
        task="Deliver spec 123.",
        status="blocked",
        facts=(
            "default: verify: ✓ passed",
            "backup: verify: ✗ failed (2 checks)",
            "Delivery result: 1 converged, 1 failed.",
        ),
        next_step="echelon delivery run 123",
    )
    provider = _RecordingProvider(CliRunResult(exit_code=1, stdout="", stderr=""))

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "Verification differed across strategies" in summary
    assert "Verification: ✓ passed" not in summary


def test_delivery_fallback_normalizes_matching_verdicts_with_different_timings(
    tmp_path: Path,
) -> None:
    context = RunSummaryContext(
        project_root=tmp_path,
        command="echelon delivery run",
        task="Deliver spec 123.",
        status="done",
        facts=(
            "default: verify: ✓ passed (1.0s)",
            "backup: verify: ✓ passed (2.0s)",
            "Delivery result: 2 converged, 0 failed.",
        ),
    )
    provider = _RecordingProvider(CliRunResult(exit_code=1, stdout="", stderr=""))

    summary = summarize_run(
        context,
        provider=provider,
        agent=SummaryAgent(prompt="Summarize.", metadata={}),
    )

    assert "Verification: passed across strategies." in summary
    assert "Verification differed" not in summary


def test_summarize_run_keeps_provider_progress_out_of_the_terminal(
    tmp_path: Path,
    capsys,
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()

    class NoisyProvider(_RecordingProvider):
        def run_agent_result(self, cwd: str, prompt: str, **kwargs: object):
            print("provider progress")
            print("provider warning", file=sys.stderr)
            return super().run_agent_result(cwd, prompt, **kwargs)

    provider = NoisyProvider(
        CliRunResult(exit_code=0, stdout="Useful human summary.", stderr="")
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low"},
    )

    assert summarize_run(_context(project_root), provider=provider, agent=agent)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_summarize_run_rejects_empty_model_output(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(exit_code=0, stdout="```text\n\n```", stderr="")
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low"},
    )

    summary = summarize_run(_context(project_root), provider=provider, agent=agent)

    assert summary.startswith("Echelon completed the requested specification work")


def test_summarize_run_never_prints_raw_model_json(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout='{"summary":"Published the specification."}',
            stderr="",
        )
    )
    agent = SummaryAgent(
        prompt="Summarize the completed Echelon run.",
        metadata={"model_tier": "fast", "effort": "low"},
    )

    summary = summarize_run(_context(project_root), provider=provider, agent=agent)

    assert summary.startswith("Echelon completed the requested specification work")
    assert "{" not in summary


def test_summarize_run_for_cli_loads_the_dedicated_workspace_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    provider = _RecordingProvider(
        CliRunResult(
            exit_code=0,
            stdout="Finished the requested specification.\nIt is ready for delivery.",
            stderr="",
        )
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "harness.prosaic_prompt_loader.ProsaicPromptLoader.load_subagent",
        lambda _loader, agent_id: (
            captured.setdefault("agent_id", agent_id)
            and ProsaicCommandArtifact(
                frontmatter={"model_tier": "fast", "effort": "low"},
                body="Summarize this run.",
            )
        ),
    )
    monkeypatch.setattr(
        "harness.config.load_config",
        lambda root, squad_only=False: captured.update(
            {"config_root": root, "squad_only": squad_only}
        )
        or object(),
    )
    monkeypatch.setattr(
        "harness.llm_provider.AICodingCliProvider",
        lambda _config: provider,
    )

    summary = summarize_run_for_cli(_context(project_root))

    assert summary == (
        "Finished the requested specification.\nIt is ready for delivery."
    )
    assert captured == {
        "agent_id": "echelon.summarizer",
        "config_root": project_root,
        "squad_only": True,
    }
