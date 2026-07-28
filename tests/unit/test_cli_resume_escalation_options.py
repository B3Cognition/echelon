"""Regression tests for executable squad escalation options."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.blocked_decision import build_blocked_decision_v2
from harness.recovery_instruction import RecoveryKind, RecoveryInstruction


def _write_blocked_run(tmp_path: Path, options: list[dict]) -> Path:
    run_dir = tmp_path / "runs" / "spec-20260619-111111-000001"
    staging_dir = run_dir / "staging"
    staging_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "status": "blocked",
                "phase": "checkpoint-assess",
                "autonomy_mode": "semi",
                "user_message": "make ascii art",
                "staging_dir": str(staging_dir),
                "blocked_reason": "checkpoint-assess human gate",
                "escalation_question": "A: return to WHAT\nB: proceed",
                "escalation_options": options,
                "completed_phases": ["phase1-constitution", "phase1-what", "phase1-why2"],
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _patch_resume_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    config_mod = types.ModuleType("harness.config")
    config_mod.load_config = lambda *a, **k: {}
    config_mod.get_full_resolved_config = lambda *a, **k: {}

    phase_graph_mod = types.ModuleType("harness.phase_graph")

    class FakePhaseNode:
        pass

    class FakePhaseGraph:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def all_phase_ids(self) -> list[str]:
            return [
                "phase1-constitution",
                "phase1-what",
                "phase1-why2",
                "checkpoint-assess",
                "phase2-decide",
                "DONE",
            ]

    phase_graph_mod.PhaseNode = FakePhaseNode
    phase_graph_mod.PhaseGraph = FakePhaseGraph

    provider_mod = types.ModuleType("harness.squad_provider")

    class FakeSquadAgentResult:
        pass

    class FakeProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

    provider_mod.SquadAgentResult = FakeSquadAgentResult
    provider_mod.SquadCliProvider = FakeProvider

    squad_mod = types.ModuleType("harness.squad")

    class FakeSquadController:
        def __init__(self, **kwargs) -> None:
            self._state_store = kwargs["state_store"]

        def run(self, user_message: str = "", mode: str = "semi", next_phase_override: str = ""):
            state = self._state_store.load()
            return SimpleNamespace(
                status=state.get("status", "running"),
                phase=state.get("phase", "?"),
                run_id=state.get("run_id", ""),
            )

    squad_mod.SquadController = FakeSquadController

    monkeypatch.setitem(sys.modules, "harness.config", config_mod)
    monkeypatch.setitem(sys.modules, "harness.phase_graph", phase_graph_mod)
    monkeypatch.setitem(sys.modules, "harness.squad_provider", provider_mod)
    monkeypatch.setitem(sys.modules, "harness.squad", squad_mod)


def test_resume_submits_a_valid_v2_answer_only_through_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "approve",
                "label": "Approve the reviewed boundary",
                "next_phase": "phase2-decide",
            }
        ],
    )
    decision = build_blocked_decision_v2(
        decision_id="dec-cli-resume",
        status="awaiting_human",
        source_kind="human_gate",
        producer_id="checkpoint-assess",
        source_phase="checkpoint-assess",
        reason_code="checkpoint_assessment",
        classification="material",
        question="Approve the reviewed boundary?",
        options=[
            {
                "id": "approve",
                "label": "Approve the reviewed boundary",
                "description": "Accept the reviewed scope.",
                "recommended": True,
                "risk_level": "medium",
                "next_phase": "phase2-decide",
                "outcome": "approved",
            }
        ],
        recommended_answer=None,
        risk_level="medium",
        resolution_handler="gate_outcome",
        autonomy_mode="guided",
        source_state_revision=0,
        now="2026-07-28T10:00:00+00:00",
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.AWAIT_HUMAN_ANSWER,
                reason_code="checkpoint_assessment",
                phase="checkpoint-assess",
                requires_human_input=True,
                schema_version=2,
                decision_id="dec-cli-resume",
            ).to_dict(),
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    answers: list[str] = []
    _patch_resume_dependencies(monkeypatch)
    controller = sys.modules["harness.squad"].SquadController
    controller.resume_with_human_input = lambda self, answer: answers.append(answer) or True

    _cmd_resume(["approve"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    assert answers == ["approve"]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["blocked_decision"] == decision


def test_resume_rejects_stale_v2_reason_before_controller_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(tmp_path, [])
    decision = build_blocked_decision_v2(
        decision_id="dec-cli-stale-reason",
        status="awaiting_human",
        source_kind="provider_escalation",
        producer_id="phase1-investigate",
        source_phase="phase1-investigate",
        reason_code="human_clarification_required",
        classification="material",
        question="Which boundary should be used?",
        options=[],
        recommended_answer=None,
        risk_level="medium",
        resolution_handler="clarification_resume",
        autonomy_mode="guided",
        source_state_revision=0,
        now="2026-07-28T10:00:00+00:00",
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "blocked_decision": decision,
            "recovery_instruction": RecoveryInstruction(
                kind=RecoveryKind.AWAIT_HUMAN_ANSWER,
                reason_code="stale_unrelated_reason",
                phase="phase1-investigate",
                requires_human_input=True,
                schema_version=2,
                decision_id="dec-cli-stale-reason",
            ).to_dict(),
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _patch_resume_dependencies(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _cmd_resume(["Use the public boundary"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    assert exc.value.code == 1


def test_resume_option_a_routes_to_offered_next_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "route_back_to_what",
                "label": "Return to WHAT",
                "next_phase": "phase1-what",
            },
            {
                "id": "proceed_anyway",
                "label": "Proceed to DECIDE",
                "next_phase": "phase2-decide",
            },
        ],
    )
    _patch_resume_dependencies(monkeypatch)

    _cmd_resume(["A"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase1-what"
    assert state["escalation_resolved"] is True
    assert state["escalation_selected_option"] == "route_back_to_what"
    assert state["resume_metadata"]["answer_type"] == "choice"
    assert state["resume_metadata"]["selected_option_id"] == "route_back_to_what"
    assert state["resume_metadata"]["blocked_phase"] == "checkpoint-assess"
    assert state["resume_metadata"]["resumed_phase"] == "phase1-what"
    assert state["blocked_decision"]["status"] == "resolved"
    assert state["blocked_decision"]["resolved_by"] == "user"
    assert state["escalation_question"] is None


def test_resume_rejects_option_with_invalid_next_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "route_to_nowhere",
                "label": "Return to missing phase",
                "next_phase": "phase-does-not-exist",
            }
        ],
    )
    _patch_resume_dependencies(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _cmd_resume(["A"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    assert exc.value.code == 1
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["phase"] == "checkpoint-assess"
    assert state["escalation_question"] == "A: return to WHAT\nB: proceed"
    captured = capsys.readouterr()
    assert "not an executable phase" in captured.err


def test_resume_rejects_unmatched_answer_when_structured_options_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "route_back_to_what",
                "label": "Return to WHAT",
                "next_phase": "phase1-what",
            },
            {
                "id": "proceed_anyway",
                "label": "Proceed to DECIDE",
                "next_phase": "phase2-decide",
            },
        ],
    )
    _patch_resume_dependencies(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _cmd_resume(["surprise third path"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    assert exc.value.code == 1
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["phase"] == "checkpoint-assess"
    assert "escalation_selected_option" not in state
    captured = capsys.readouterr()
    assert "does not match any executable escalation option" in captured.err


def test_resume_accepts_free_text_decision_without_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(tmp_path, options=[])
    _patch_resume_dependencies(monkeypatch)

    _cmd_resume(
        ["Use a narrower audience and keep missions under 10 minutes."],
        project_root=tmp_path,
        ext_dir=Path.cwd() / "extension",
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "checkpoint-assess"
    assert state["escalation_question"] is None
    assert state["blocked_decision"]["answer_type"] == "free_text"
    assert state["blocked_decision"]["status"] == "resolved"
    assert state["resume_metadata"]["answer_type"] == "free_text"
    assert state["resume_metadata"]["answer_text"] == (
        "Use a narrower audience and keep missions under 10 minutes."
    )


def test_resume_uses_existing_blocked_decision_after_process_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "proceed_anyway",
                "label": "Proceed to DECIDE",
                "next_phase": "phase2-decide",
            }
        ],
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["blocked_decision"] = {
        "schema_version": 1,
        "status": "pending",
        "answer_type": "choice",
        "question": state["escalation_question"],
        "blocked_reason": state["blocked_reason"],
        "blocked_phase": state["phase"],
        "blocked_at": "2026-06-23T10:00:00+00:00",
        "options": state["escalation_options"],
        "recommended_answer": "proceed_anyway",
        "default_answer": "proceed_anyway",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _patch_resume_dependencies(monkeypatch)

    _cmd_resume(["proceed_anyway"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    resumed = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed["phase"] == "phase2-decide"
    assert resumed["blocked_decision"]["blocked_at"] == "2026-06-23T10:00:00+00:00"
    assert resumed["blocked_decision"]["status"] == "resolved"
    assert resumed["resume_metadata"]["selected_option_id"] == "proceed_anyway"


def test_resume_terminal_block_delegates_to_continue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(tmp_path, options=[])
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = "terminal-blocked"
    state["blocked_decision"] = {
        "schema_version": 1,
        "status": "pending",
        "answer_type": "free_text",
        "question": state["escalation_question"],
        "blocked_reason": state["blocked_reason"],
        "blocked_phase": state["phase"],
        "blocked_at": "2026-06-23T10:00:00+00:00",
        "options": [],
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _patch_resume_dependencies(monkeypatch)

    calls: list[tuple[list[str], Path, Path]] = []

    def fake_continue(args, project_root, ext_dir):
        calls.append((args, project_root, ext_dir))

    monkeypatch.setattr("echelon.cli._cmd_continue", fake_continue)

    _cmd_resume(["retry with narrower scope"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    resumed = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed["status"] == "running"
    assert resumed["phase"] == "terminal-blocked"
    assert resumed["blocked_reason"] is None
    assert resumed["blocked_decision"]["status"] == "resolved"
    assert calls == [([], tmp_path, Path.cwd() / "extension")]


def test_resume_phase_dispatch_limit_requires_issue_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(tmp_path, options=[])
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "phase": "terminal-blocked",
            "blocked_reason": "phase_dispatch_limit",
            "escalation_question": (
                "Phase 'phase1-what' has been dispatched 6 times (limit 5) "
                "without converging or advancing. Possible routing loop. "
                "How should I proceed?"
            ),
            "phase_dispatch_limit_phase": "phase1-what",
            "phase_dispatch_limit": 5,
            "phase_dispatch_counts": {
                "phase1-what": 6,
                "phase1-why2": 3,
            },
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _patch_resume_dependencies(monkeypatch)
    monkeypatch.setattr("echelon.cli._cmd_continue", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        _cmd_resume(
            ["Authorize one targeted retry of phase1-what using the latest issues.md findings."],
            project_root=tmp_path,
            ext_dir=Path.cwd() / "extension",
        )

    resumed = json.loads(state_path.read_text(encoding="utf-8"))
    assert exc.value.code == 1
    assert resumed["phase"] == "terminal-blocked"
    assert resumed["phase_dispatch_counts"]["phase1-what"] == 6


def test_resolve_records_one_issue_and_starts_targeted_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_spec_resolve

    run_dir = _write_blocked_run(tmp_path, options=[])
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "issues.md").write_text(
        """# Issues

### ISS-001: Advisory wording
- **Severity:** LOW
- **Action Required:** None

### ISS-002: Retry policy needs a product decision
- **Severity:** CRITICAL
- **Action Required:** Choose whether retries are disabled or use exponential backoff.
- **Recommendation:** Document the selected retry behavior.

### ISS-003: Timeout needs a product decision
- **Severity:** HIGH
- **Action Required:** Choose the client timeout.
""",
        encoding="utf-8",
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "phase": "terminal-blocked",
            "blocked_reason": "phase_dispatch_limit",
            "spec_dir": str(spec_dir),
            "escalation_question": "How should I proceed?",
            "phase_dispatch_counts": {
                "phase1-tracker": 1,
                "phase1-what": 6,
                "phase1-understanding": 6,
                "phase1-why2": 5,
            },
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _cmd_spec_resolve(
        ["ISS-002", "Use exponential backoff with a documented cap."],
        project_root=tmp_path,
        ext_dir=Path.cwd() / "extension",
    )

    resolved = json.loads(state_path.read_text(encoding="utf-8"))
    assert resolved["selected_issue_resolution"] == "ISS-002"
    assert resolved["issue_resolution_ledger"]["ISS-002"] == {
        "issue_id": "ISS-002",
        "title": "Retry policy needs a product decision",
        "severity": "CRITICAL",
        "guidance": "Choose whether retries are disabled or use exponential backoff.",
        "status": "selected",
        "decision": "Use exponential backoff with a documented cap.",
        "repair_phase": "phase1-what",
    }
    assert resolved["issue_resolution_recovery"] == {
        "issue_id": "ISS-002",
        "from_phase": "phase1-why2",
        "to_phase": "phase1-what",
        "reason": "issue_resolution",
    }
    assert resolved["issue_resolution_repair_baseline"]["issue_id"] == "ISS-002"
    assert resolved["issue_resolution_repair_baseline"]["repair_phase"] == "phase1-what"
    assert resolved["issue_resolution_repair_baseline"]["recorded_at"]
    assert resolved["status"] == "running"
    assert resolved["phase"] == "phase1-what"
    assert "blocked_reason" not in resolved
    assert "escalation_question" not in resolved
    assert resolved["phase_dispatch_counts"] == {"phase1-tracker": 1}


def test_resolve_requires_sage_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import _cmd_spec_resolve

    run_dir = _write_blocked_run(tmp_path, options=[])
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "issues.md").write_text(
        """### ISS-001: First decision
- **Severity:** CRITICAL
- **Action Required:** Choose the first value.

### ISS-002: Second decision
- **Severity:** HIGH
- **Action Required:** Choose the second value.
""",
        encoding="utf-8",
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["spec_dir"] = str(spec_dir)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr("echelon.cli._cmd_run", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        _cmd_spec_resolve(
            ["ISS-002", "Second value"],
            project_root=tmp_path,
            ext_dir=Path.cwd() / "extension",
        )

    assert exc.value.code == 1
    unchanged = json.loads(state_path.read_text(encoding="utf-8"))
    assert "issue_resolution_ledger" not in unchanged


def test_issue_requests_skip_resolved_issues_and_read_required_amendment(tmp_path: Path) -> None:
    from echelon.cli import _issue_resolution_requests

    run_dir = _write_blocked_run(tmp_path, options=[])
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "issues.md").write_text(
        """### ISS-001: Already fixed ✓ RESOLVED
**Status**: ✓ RESOLVED
No action required.

### ISS-002: State machine incomplete
**Severity**: CRITICAL
**Required Amendment**: Complete every transition with explicit outcomes.
""",
        encoding="utf-8",
    )
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["spec_dir"] = str(spec_dir)

    assert _issue_resolution_requests(tmp_path, run_dir, state) == [
        {
            "issue_id": "ISS-002",
            "title": "State machine incomplete",
            "severity": "CRITICAL",
            "guidance": "Complete every transition with explicit outcomes.",
        }
    ]


def test_issue_screen_guidance_shows_action_command_and_clickable_source(tmp_path: Path) -> None:
    from echelon.cli import _issue_resolution_screen_guidance

    run_dir = _write_blocked_run(tmp_path, options=[])
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    issues_path = spec_dir / "issues.md"
    issues_path.write_text(
        """### ISS-002: Retry policy
- **Severity:** CRITICAL
- **Action Required:** Select retry behavior.

### Resolution Guidance
- **Decision required:** Retry behavior.
- **Suggested option:** Use exponential backoff with a cap of three attempts.
- **Evidence basis:** API reference documents idempotent reads.
- **Values not inferable:** Retry behavior for non-idempotent writes.
- **Banzai eligible:** no
""",
        encoding="utf-8",
    )
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["spec_dir"] = str(spec_dir)

    fields = dict(_issue_resolution_screen_guidance(tmp_path, run_dir, state))
    assert fields["issues file"] == str(issues_path)
    assert fields["open issues"] == issues_path.as_uri()
    assert "action: Select retry behavior." in fields["ISS-002"]
    assert "suggested: Use exponential backoff with a cap of three attempts." in fields["ISS-002"]
    assert "evidence: API reference documents idempotent reads." in fields["ISS-002"]
    assert "user decides: Retry behavior for non-idempotent writes." in fields["ISS-002"]
    assert "echelon spec resolve ISS-002" in fields["ISS-002"]
