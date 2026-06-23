import pathlib
import socket
import pytest
from codegen.schema.runnable_contract import parse_runnable_contract
from codegen.runner.runnable_gate import run_runnable_gate, ProbeOutcome, _free_port, make_probe


def _contract(kind="spa"):
    return parse_runnable_contract({
        "kind": kind, "build": "build", "start": "start", "liveness": "HTTP 200",
        "primary_surface": {"req": "FR-001", "assert": "catalog renders rows"},
        "surfaces": [{"req": "FR-006", "assert": "graph renders"}],
    })


@pytest.mark.unit
def test_l1_passes_when_live_and_primary_surface_present():
    probe = lambda ws, c, port: ProbeOutcome(live=True, present={"FR-001": True, "FR-006": True})
    r = run_runnable_gate(_contract(), "/tmp/ws", probe_fn=probe)
    assert r.passed is True
    assert r.level == "L1"
    assert r.surface_score == 1.0


@pytest.mark.unit
def test_l1_fails_when_not_live():
    probe = lambda ws, c, port: ProbeOutcome(live=False, present={})
    r = run_runnable_gate(_contract(), "/tmp/ws", probe_fn=probe)
    assert r.passed is False
    assert any("liveness" in f for f in r.failures)


@pytest.mark.unit
def test_stub_fails_l1_even_though_live():
    # THE HEADLINE ANTI-REGRESSION CASE: app boots (live=True) but the primary
    # surface does not render — exactly this session's Psi=1.0 stub.
    probe = lambda ws, c, port: ProbeOutcome(live=True, present={"FR-001": False, "FR-006": False})
    r = run_runnable_gate(_contract(), "/tmp/ws", probe_fn=probe)
    assert r.passed is False
    assert any("FR-001" in f and "primary" in f.lower() for f in r.failures)


@pytest.mark.unit
def test_free_port_is_bindable_and_unique():
    p1, p2 = _free_port(), _free_port()
    assert isinstance(p1, int) and 1024 < p1 < 65536
    s = socket.socket(); s.bind(("127.0.0.1", p1)); s.close()   # bindable
    assert p1 != p2


@pytest.mark.unit
def test_make_probe_selects_family_by_kind():
    assert make_probe("spa").__name__ == "_browser_probe"
    assert make_probe("service").__name__ == "_http_probe"
    assert make_probe("cli").__name__ == "_exec_probe"



@pytest.mark.unit
def test_runnable_phase_spec_exists_and_blocks_deliver():
    runnable = pathlib.Path("extension/workflow/phases/codegen-6c-runnable.md")
    deliver = pathlib.Path("extension/workflow/phases/codegen-7-deliver.md")
    assert runnable.exists()
    rtext = runnable.read_text()
    assert "run_runnable_gate" in rtext
    assert "runnable_gate" in rtext and "reopen" in rtext.lower()
    # DELIVER must refuse unless runnable_gate == pass
    assert 'runnable_gate' in deliver.read_text()
