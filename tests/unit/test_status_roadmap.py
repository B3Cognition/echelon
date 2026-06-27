"""`echelon status` renders a checkbox roadmap of the pipeline from state.json.

[✓] completed · [▶] in progress · [ ] pending, with (×N — re-dispatched) marking
a repeated phase (the early signal of a non-converging loop). A finished run
(status == done) marks every phase complete even when completed_phases never
recorded the terminal nodes.
"""
import pytest

from echelon.cli import _print_roadmap, _ROADMAP_PHASES


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
def test_roadmap_covers_the_full_squad_happy_path():
    # Guards the canonical order against accidental truncation.
    assert _ROADMAP_PHASES[0] == "init" and _ROADMAP_PHASES[-1] == "done"
    assert "phase3-consensus" in _ROADMAP_PHASES
    assert len(_ROADMAP_PHASES) == 16
