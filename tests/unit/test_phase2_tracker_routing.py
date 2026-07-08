"""Regression coverage for tracker routing.

TRACKER returns `verdict: ALIGNED` or `verdict: DRIFT`. The workflow must route
on that verdict directly; there is no separate `alignment` state key unless an
agent explicitly writes one.
"""
from pathlib import Path
from unittest.mock import MagicMock

from harness.phase_graph import PhaseGraph
from harness.squad import SquadController
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore


ROOT = Path(__file__).resolve().parents[2]
DEFINITION = ROOT / "extension" / "workflow" / "definition.yaml"
EXT_YML = ROOT / "extension" / "extension.yml"


def _route_tracker_verdict(tmp_path: Path, phase_id: str, verdict: str) -> str:
    graph = PhaseGraph(DEFINITION, EXT_YML)
    store = SquadStateStore(tmp_path / "squad" / "run-test")
    store.initialize("r", "semi", "msg", 0, phase_id, max_iterations=5)

    ctrl = SquadController(
        provider=MagicMock(),
        state_store=store,
        phase_graph=graph,
        ext_dir=ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=store.squad_dir,
    )
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": verdict,
            "state_updates": {"intent_alignment_check_structural_pass": True},
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    return ctrl._evaluate_transitions(graph.get(phase_id), result)


def _route_phase2_tracker_verdict(tmp_path: Path, verdict: str) -> str:
    return _route_tracker_verdict(tmp_path, "phase2-tracker-alignment", verdict)


def _route_phase1_tracker_verdict(tmp_path: Path, verdict: str) -> str:
    return _route_tracker_verdict(tmp_path, "phase1-tracker", verdict)


def test_tracker_aligned_verdict_routes_to_specialists(tmp_path: Path) -> None:
    assert _route_phase2_tracker_verdict(tmp_path, "ALIGNED") == "phase3-specialists"


def test_tracker_drift_verdict_routes_to_specialists(tmp_path: Path) -> None:
    assert _route_phase2_tracker_verdict(tmp_path, "DRIFT") == "phase3-specialists"


def test_tracker_legacy_drifting_verdict_routes_to_specialists(tmp_path: Path) -> None:
    assert _route_phase2_tracker_verdict(tmp_path, "DRIFTING") == "phase3-specialists"


def test_tracker_stop_and_ask_verdict_stays_on_alignment_phase(tmp_path: Path) -> None:
    assert _route_phase2_tracker_verdict(tmp_path, "STOP_AND_ASK") == "phase2-tracker-alignment"


def test_tracker_legacy_escalate_verdict_stays_on_alignment_phase(tmp_path: Path) -> None:
    assert _route_phase2_tracker_verdict(tmp_path, "ESCALATE") == "phase2-tracker-alignment"


def test_phase1_tracker_clear_intent_routes_to_why1(tmp_path: Path) -> None:
    assert _route_phase1_tracker_verdict(tmp_path, "ALIGNED") == "phase1-why1"


def test_phase1_tracker_stop_and_ask_stays_on_tracker(tmp_path: Path) -> None:
    assert _route_phase1_tracker_verdict(tmp_path, "STOP_AND_ASK") == "phase1-tracker"
