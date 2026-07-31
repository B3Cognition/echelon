"""Tests for blocked squad next-step guidance."""

from __future__ import annotations

import json
from pathlib import Path

from echelon.cli import (
    _next_continue_phase,
    _print_next_steps,
    _print_open_issues,
    _print_staging_artifacts,
)


def _valid_plan_conformance_json() -> str:
    return json.dumps(
        {
            "status": "pass",
            "findings": [],
            "sources": [
                "spec.md",
                "requirements-overview.md",
                "plan.md",
                "tasks.md",
            ],
        },
        indent=2,
    ) + "\n"


def _issues_doc(title: str) -> str:
    return "\n".join(
        [
            "# Issues",
            "",
            "**CRITICAL:** 1",
            "**HIGH:** 0",
            "**MEDIUM:** 0",
            "**LOW:** 0",
            "",
            f"### ISS-001: {title}",
            "**Severity:** CRITICAL",
            "**Responsible agent:** CARTOGRAPHER",
        ]
    )


def test_prior_artifact_manifest_prefers_active_spec_dir_over_staging(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260717-100000-000001"
    staging_dir = run_dir / "staging"
    spec_dir = run_dir / "specs" / "001-demo"
    staging_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (staging_dir / "stale-map.md").write_text("stale", encoding="utf-8")
    (spec_dir / "domain-map.md").write_text("active", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps({"spec_dir": str(spec_dir.relative_to(tmp_path))}),
        encoding="utf-8",
    )

    _print_staging_artifacts(tmp_path)

    captured = capsys.readouterr()
    assert "domain-map" in captured.out
    assert "stale-map" not in captured.out


def test_open_issues_prefers_active_spec_dir_over_staging(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260717-100000-000001"
    staging_dir = run_dir / "staging"
    spec_dir = run_dir / "specs" / "001-demo"
    staging_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)
    (staging_dir / "issues.md").write_text(
        _issues_doc("STALE staging issue"), encoding="utf-8"
    )
    (spec_dir / "issues.md").write_text(
        _issues_doc("ACTIVE spec issue"), encoding="utf-8"
    )
    (run_dir / "state.json").write_text(
        json.dumps({"spec_dir": str(spec_dir.relative_to(tmp_path))}),
        encoding="utf-8",
    )

    _print_open_issues(tmp_path)

    captured = capsys.readouterr()
    assert "ACTIVE spec issue" in captured.out
    assert "STALE staging issue" not in captured.out
    assert str(spec_dir / "issues.md") in captured.out


def test_blocked_squad_escalation_prioritizes_resume(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "\n".join(
            [
                "# Quality Gates",
                "",
                "## Verdict: FAIL",
                "",
                "| Gate | Score | Threshold | Result | Note |",
                "| --- | --- | --- | --- | --- |",
                "| Overall | 0.68 | 0.75 | FAIL | hard fail |",
            ]
        ),
        encoding="utf-8",
    )

    run_dir = tmp_path / "runs" / "spec-20260607-215902-820491"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "phase1-why2",
                "staging_dir": str(run_dir / "staging"),
                "blocked_reason": "WHY2 user-gated issue",
                "escalation_question": "Q1: confirm widget team intent?",
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "RUN BLOCKED — answer required" in captured.out
    assert 'echelon spec resume "<your answer>"' in captured.out
    assert "Q1: confirm widget team intent?" in captured.out
    assert "echelon spec continue" not in captured.out


def test_blocked_squad_escalation_displays_executable_options(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260724-070600-019100"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "checkpoint-assess",
                "blocked_reason": "checkpoint-assess human gate",
                "escalation_question": (
                    "Approve proceeding to DECIDE, or return to WHAT to fix "
                    "the priority-tag inconsistency?"
                ),
                "escalation_options": [
                    {
                        "id": "proceed_to_decide",
                        "label": "Proceed to DECIDE",
                        "next_phase": "phase2-decide",
                    },
                    {
                        "id": "route_back_to_what",
                        "label": "Return to WHAT",
                        "next_phase": "phase1-what",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "A: Proceed to DECIDE" in captured.out
    assert "B: Return to WHAT" in captured.out
    assert "Answer with A/B, the option id, or the option label." in captured.out


def test_checkpoint_next_step_includes_recent_gate_context(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260731-130948-336574"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "reasoning-journal.jsonl").write_text(
        json.dumps(
            {
                "phase": "phase1-lexicon-derive",
                "type": "insight",
                "data": {
                    "artifact": "requirements.lexicon.md",
                    "reasoning": (
                        "Repair finding source-hash-mismatch was caused solely "
                        "by a stale SOURCE_SHA256 header value."
                    ),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "checkpoint-assess",
                "autonomy_mode": "semi",
                "blocked_reason": "checkpoint_assess_decision_required",
                "escalation_question": "Review Phase 1 Checkpoint artifacts.",
                "escalation_options": [
                    {
                        "id": "approve",
                        "label": "Approve",
                        "next_phase": "phase2-decide",
                    },
                    {
                        "id": "reject",
                        "label": "Reject",
                        "next_phase": "terminal-blocked",
                    },
                ],
                "quality_scores": [
                    {
                        "pass": True,
                        "pass_id": "WHY2-iter-4",
                        "overall": 0.8092,
                        "structure": 0.95,
                        "testability": 0.9271,
                        "cognitive": 0.6732,
                    }
                ],
                "lexicon_evaluation": "passed",
                "lexicon_findings": 0,
                "lexicon_report": "runs/spec/spec-lexicon-report.json",
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "Why approval is needed: semi mode pauses at Phase 1 Checkpoint" in captured.out
    assert "WHY2 passed (WHY2-iter-4: overall 0.8092" in captured.out
    assert "Spec Lexicon passed with 0 finding(s)" in captured.out
    assert "source-hash-mismatch" in captured.out


def test_controller_contract_failure_without_recovery_does_not_suggest_continue(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260726-075512-129608"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "phase1-why2",
                "blocked_reason": "controller_state_contract_validation_failed",
                "last_dispatch": {"phase_id": "phase1-understanding"},
                "controller_contract_error": {
                    "phase_id": "phase1-why2",
                    "contract": "preparation",
                    "validator": "ownership",
                },
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "echelon spec continue" not in captured.out
    assert "no runtime-sync recovery instruction was recorded" in captured.out
    assert 'echelon spec resume "<your answer>"' not in captured.out
    assert "echelon spec rewind" not in captured.out


def test_stale_contract_metadata_renders_current_missing_output_recovery(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-test"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "missing_phase_outputs",
                "recovery_instruction": {
                    "schema_version": 1,
                    "kind": "sync_runtime_then_retry",
                    "reason_code": "controller_state_contract_validation_failed",
                    "phase": "phase1-what",
                    "requires_human_input": False,
                },
                "phase_output_recovery": {
                    "phase": "phase1-what",
                    "missing_outputs": ["requirements-overview.md"],
                    "prior_state_updates": {},
                },
                "issue_resolution_recovery": {
                    "issue_id": "ISS-003",
                    "from_phase": "phase1-why2",
                    "to_phase": "phase1-what",
                    "reason": "issue_resolution",
                },
                "last_dispatch": {
                    "phase_id": "phase1-what",
                    "verdict": "BLOCKED",
                },
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    output = capsys.readouterr().out
    assert "missing_phase_outputs" in output
    assert "phase1-what" in output
    assert "echelon spec continue" in output
    assert "controller_state_contract_validation_failed" not in output
    assert "runtime contracts" not in output


def test_ready_next_step_has_clear_subtitle_and_next_command(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "00-overview.md", "requirements-overview.md",
        "plan-conformance.md", "plan-conformance.json",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else f"# {name}\n"
        )
        (spec_dir / name).write_text(content, encoding="utf-8")
    (spec_dir / "constitution.md").write_text(
        "# Constitution\n\nReady.\n",
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "READY TO BUILD" in captured.out
    assert "ready" in captured.out
    assert "constitution.md" in captured.out
    assert "HOW artifacts" in captured.out
    assert "tasks.md" in captured.out
    assert "next" in captured.out
    assert "echelon delivery run 001-demo" in captured.out
    assert "\n  build\n" not in captured.out


def test_done_run_without_spec_md_is_not_ready_to_build(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )
    for name in ("plan.md", "research.md", "data-model.md", "tasks.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    run_dir = tmp_path / "runs" / "spec-20260623-100000-000001"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "done",
                "phase": "DONE",
                "spec_id": "001-demo",
                "spec_dir": "specs/001-demo",
                "completed_phases": ["phase1-constitution"],
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "READY TO BUILD" not in captured.out
    assert "PHASE A INCOMPLETE" in captured.out
    assert "BUILD BLOCKED" not in captured.out
    assert "spec.md absent" in captured.out


def test_partial_constitution_placeholders_are_reported_precisely(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text(
        "# Constitution\n\n[PRINCIPLE_1_NAME] -> I. Real Principle\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "spec-20260609-152410-385227"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "completed_phases": ["phase1-constitution"],
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "unresolved constitution template marker" in captured.out
    assert "[PRINCIPLE_1_NAME]" in captured.out
    assert "blank template" not in captured.out


def test_blocked_non_escalation_run_does_not_claim_ready_to_build(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "00-overview.md", "requirements-overview.md",
        "plan-conformance.md", "plan-conformance.json",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else f"# {name}\n"
        )
        (spec_dir / name).write_text(content, encoding="utf-8")
    (spec_dir / "constitution.md").write_text(
        "# Constitution\n\nReady.\n",
        encoding="utf-8",
    )
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: FAIL\n",
        encoding="utf-8",
    )

    run_dir = tmp_path / "runs" / "spec-20260618-073106-635192"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "missing_echelon_result",
                "last_dispatch": {"phase_id": "phase3-sentinel"},
                "completed_phases": ["phase1-constitution", "phase3-how"],
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "READY TO BUILD" not in captured.out
    assert "RUN BLOCKED" in captured.out
    assert "missing_echelon_result" in captured.out
    assert "echelon spec continue" in captured.out
    assert "will retry the blocked phase; it was not marked complete" in captured.out


def test_blocked_incomplete_discover_prioritizes_retry_over_constitution(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260625-140321-450919"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "missing_echelon_result",
                "last_dispatch": {"phase_id": "phase1-discover"},
                "completed_phases": ["init"],
            }
        ),
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) == "phase1-discover"

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "RUN BLOCKED" in captured.out
    assert "missing_echelon_result" in captured.out
    assert "phase1-discover" in captured.out
    assert "phase1-constitution has not completed" not in captured.out


def test_blocked_missing_result_retries_redispatched_completed_phase(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260627-201457-781907"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "missing_echelon_result",
                "last_dispatch": {"phase_id": "phase1-why2"},
                "completed_phases": [
                    "init",
                    "phase1-constitution",
                    "phase1-discover",
                    "phase1-what",
                    "phase1-why2",
                    "checkpoint-assess",
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) == "phase1-why2"

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "RUN BLOCKED" in captured.out
    assert "missing_echelon_result" in captured.out
    assert "phase1-why2" in captured.out
    assert "echelon spec continue" in captured.out
    assert "manual recovery required" not in captured.out


def test_blocked_timeout_next_step_uses_continue_not_resume(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260625-140321-450919"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "agent_timeout",
                "last_dispatch": {"phase_id": "phase1-discover"},
                "completed_phases": ["init"],
            }
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "blocked")

    captured = capsys.readouterr()
    assert "RUN BLOCKED" in captured.out
    assert "agent_timeout" in captured.out
    assert "echelon spec continue" in captured.out
    assert 'echelon spec resume "<your answer>"' not in captured.out


def test_interrupted_next_step_retries_interrupted_phase(
    tmp_path: Path,
    capsys,
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260625-140321-450919"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "interrupted",
                "phase": "phase1-discover",
                "interrupted_phase": "phase1-discover",
                "completed_phases": ["init"],
            }
        ),
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) == "phase1-discover"

    _print_next_steps(tmp_path, "interrupted")

    captured = capsys.readouterr()
    assert "RUN INTERRUPTED" in captured.out
    assert "phase1-discover" in captured.out
    assert "echelon spec continue" in captured.out
    assert "phase1-constitution has not completed" not in captured.out


def test_done_run_uses_published_artifacts_instead_of_stale_staging_why2(
    tmp_path: Path,
    capsys,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "00-overview.md", "requirements-overview.md",
        "plan-conformance.md", "plan-conformance.json",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else f"# {name}\n"
        )
        (spec_dir / name).write_text(content, encoding="utf-8")
    (spec_dir / "constitution.md").write_text(
        "# Constitution\n\nReady.\n",
        encoding="utf-8",
    )

    run_dir = tmp_path / "runs" / "spec-20260619-153850-805795"
    staging_dir = run_dir / "staging"
    staging_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "done",
                "phase": "DONE",
                "spec_id": "001-demo",
                "spec_dir": "specs/001-demo",
                "staging_dir": str(staging_dir),
                "completed_phases": [
                    "phase1-constitution",
                    "phase1-what",
                    "phase1-why2",
                    "phase3-how",
                    "phase3-plan",
                ],
            }
        ),
        encoding="utf-8",
    )
    (staging_dir / "quality-gates.md").write_text(
        "\n".join(
            [
                "# Quality Gates",
                "",
                "## Verdict: FAIL",
                "",
                "| Gate | Score | Threshold | Result | Note |",
                "| --- | --- | --- | --- | --- |",
                "| Overall | 0.68 | 0.75 | FAIL | hard fail |",
                "| Testability | 0.52 | 0.75 | FAIL | hard fail |",
            ]
        ),
        encoding="utf-8",
    )

    _print_next_steps(tmp_path, "done")

    captured = capsys.readouterr()
    assert "READY TO BUILD" in captured.out
    assert "echelon delivery run 001-demo" in captured.out
    assert "BUILD BLOCKED" not in captured.out
    assert "WHY2 quality gates FAIL" not in captured.out


def test_continue_phase_treats_done_published_artifacts_as_build_ready(
    tmp_path: Path,
) -> None:
    constitution = tmp_path / ".specify" / "memory" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "00-overview.md", "requirements-overview.md",
        "plan-conformance.md", "plan-conformance.json",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        content = (
            _valid_plan_conformance_json()
            if name == "plan-conformance.json"
            else f"# {name}\n"
        )
        (spec_dir / name).write_text(content, encoding="utf-8")
    (spec_dir / "constitution.md").write_text(
        "# Constitution\n\nReady.\n",
        encoding="utf-8",
    )

    run_dir = tmp_path / "runs" / "spec-20260619-153850-805795"
    staging_dir = run_dir / "staging"
    staging_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "done",
                "phase": "DONE",
                "spec_id": "001-demo",
                "spec_dir": "specs/001-demo",
                "staging_dir": str(staging_dir),
                "completed_phases": ["phase1-constitution", "phase3-how", "phase3-plan"],
            }
        ),
        encoding="utf-8",
    )
    (staging_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: FAIL\n",
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) is None
