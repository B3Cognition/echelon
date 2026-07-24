"""`echelon status` renders a checkbox roadmap of the pipeline from state.json.

[✓] completed · [▶] in progress · [ ] pending, with (×N — re-dispatched) marking
a repeated phase (the early signal of a non-converging loop). A finished run
(status == done) marks every phase complete even when completed_phases never
recorded the terminal nodes.
"""
import pytest
import yaml
from pathlib import Path

from echelon.cli import _derive_roadmap_phases, _print_roadmap, _ROADMAP_PHASES


ROOT = Path(__file__).resolve().parents[2]


def _workflow_primary_path() -> list[str]:
    workflow = yaml.safe_load((ROOT / "extension/workflow/definition.yaml").read_text())
    phases = {phase["id"]: phase for phase in workflow["phases"]}
    path: list[str] = []
    current = "init"
    seen: set[str] = set()

    while current and current not in seen:
        path.append(current)
        seen.add(current)
        if current == "done":
            break
        transitions = phases[current].get("transitions", [])
        next_phase = ""
        for transition in transitions:
            candidate = transition.get("to")
            if (
                candidate
                and candidate != current
                and candidate != "escalate"
                and candidate != "terminal-blocked"
                and candidate not in seen
            ):
                next_phase = candidate
                break
        current = next_phase

    return path


@pytest.mark.unit
def test_marks_current_completed_and_pending(capsys):
    _print_roadmap({
        "status": "running",
        "completed_phases": ["init", "phase1-discover"],
        "current_phase": "phase1-what",
    })
    out = capsys.readouterr().out
    assert "[✓]" in out and "init" in out          # completed
    assert "[▶]" in out and "phase1-what" in out    # current
    assert "in progress" in out
    assert "[ ]" in out                              # some pending remain


@pytest.mark.unit
def test_done_run_is_all_complete_100pct(capsys):
    # completed_phases omits the terminal nodes, but status==done → all ✓.
    _print_roadmap({
        "status": "done",
        "completed_phases": ["init"],
        "current_phase": "phase4-document",
    })
    out = capsys.readouterr().out
    assert "[ ]" not in out          # nothing left pending
    assert "[▶]" not in out          # nothing left "in progress"
    assert f"{len(_ROADMAP_PHASES)}/{len(_ROADMAP_PHASES)}" in out
    assert "100%" in out


@pytest.mark.unit
def test_redispatch_count_surfaces_loop_signal(capsys):
    _print_roadmap({
        "status": "blocked",
        "completed_phases": ["init", "phase1-discover", "phase1-constitution"],
        "current_phase": "phase3-how",
        "phase_dispatch_counts": {"phase3-how": 8},
    })
    out = capsys.readouterr().out
    assert "×8" in out and "re-dispatched" in out


@pytest.mark.unit
def test_roadmap_is_derived_from_workflow_primary_path():
    assert _ROADMAP_PHASES == _workflow_primary_path()


@pytest.mark.unit
def test_fallback_roadmap_keeps_visible_deterministic_spec_gates(tmp_path):
    phases = _derive_roadmap_phases(tmp_path / "missing-workflow.yaml")

    what_index = phases.index("phase1-what")
    assert phases[what_index : what_index + 4] == [
        "phase1-what",
        "phase1-lexicon",
        "phase1-understanding",
        "phase1-why2",
    ]
    plan_index = phases.index("phase3-plan")
    assert phases[plan_index : plan_index + 5] == [
        "phase3-plan",
        "phase3-tasks-lexicon",
        "phase3-understanding",
        "phase3-consensus",
        "phase3-consensus-tasks-lexicon",
    ]


@pytest.mark.unit
def test_current_phase_that_was_completed_still_counts_toward_progress(capsys):
    _print_roadmap({
        "status": "running",
        "completed_phases": ["init", "phase1-discover"],
        "current_phase": "phase1-discover",
        "phase_dispatch_counts": {"phase1-discover": 2},
    })
    out = capsys.readouterr().out
    assert "[▶]" in out and "phase1-discover" in out
    assert "2/" in out


@pytest.mark.unit
def test_phase_field_wins_over_stale_last_dispatch(capsys):
    """A rewind changes `phase`; last_dispatch only describes the prior attempt."""
    _print_roadmap({
        "status": "running",
        "phase": "phase1-what",
        "completed_phases": ["phase1-why1", "phase1-constitution"],
        "last_dispatch": {"phase_id": "phase2-decide"},
    })
    out = capsys.readouterr().out
    assert "[▶]  phase1-what" in out
    assert "[▶]  phase2-decide" not in out
