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
    # THE HEADLINE ANTI-REGRESSION CASE: a probe reports liveness but the
    # primary requirement evidence is absent.
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
def test_probe_exception_fails_closed():
    """Any exception from probe_fn must return a fail-closed result — never re-raise."""
    def bad_probe(ws, c, port):
        raise NotImplementedError("nope")
    r = run_runnable_gate(_contract(), "/tmp/ws", probe_fn=bad_probe)
    assert r.passed is False
    assert r.level == "L1"
    assert r.surface_score == 0.0
    assert any("fail-closed" in f and "NotImplementedError" in f for f in r.failures)


@pytest.mark.unit
def test_probe_runtime_error_fails_closed():
    """RuntimeError from probe_fn must also produce a fail-closed failure, not crash."""
    def runtime_probe(ws, c, port):
        raise RuntimeError("boom")
    r = run_runnable_gate(_contract(), "/tmp/ws", probe_fn=runtime_probe)
    assert r.passed is False
    assert any("boom" in f for f in r.failures)


@pytest.mark.unit
def test_runnable_phase_spec_exists_and_blocks_deliver():
    runnable = pathlib.Path("runtime/workflow/phases/codegen-6c-runnable.md")
    deliver = pathlib.Path("runtime/workflow/phases/codegen-7-deliver.md")
    assert runnable.exists()
    rtext = runnable.read_text()
    assert "run_runnable_gate" in rtext
    assert "runnable_gate" in rtext and "reopen" in rtext.lower()
    # DELIVER must refuse unless runnable_gate == pass
    assert 'runnable_gate' in deliver.read_text()


@pytest.mark.unit
def test_runnable_phase_spec_does_not_claim_runtime_render_evidence():
    runnable = pathlib.Path("runtime/workflow/phases/codegen-6c-runnable.md")
    deliver = pathlib.Path("runtime/workflow/phases/codegen-7-deliver.md")
    text = f"{runnable.read_text()}\n{deliver.read_text()}".lower()

    assert "static composition" in text
    assert "static component" in text
    forbidden_claims = [
        "boots and its primary surface renders",
        "boot and render its primary surface",
        "app boots; primary surface renders",
        "non-bootable / hollow app",
    ]
    for claim in forbidden_claims:
        assert claim not in text


# --- SPA composition probe (build + static-composition; catches the stub) ---
from codegen.runner.runnable_gate import (
    composed_components, composition_is_real, _browser_probe,
)

_STUB_APP = "export function App(){ return <main>echelon</main>; }"
_WIRED_APP = """
import { CatalogTable } from './features/catalog/catalog-table.js';
import { RunHeader } from './features/run-header/run-header.js';
import { PhaseGraph } from './features/phase-graph/phase-graph.js';
export function App(){ return (<main><RunHeader/><CatalogTable/><PhaseGraph/></main>); }
"""


@pytest.mark.unit
def test_composed_components_ignores_shell_finds_features():
    assert composed_components(_STUB_APP) == set()
    got = composed_components(_WIRED_APP)
    assert {"CatalogTable", "RunHeader", "PhaseGraph"} <= got
    assert "App" not in got  # shell excluded


@pytest.mark.unit
def test_composition_is_real_stub_vs_wired():
    assert composition_is_real(_STUB_APP) is False
    assert composition_is_real(_WIRED_APP) is True


def _contract_spa():
    return parse_runnable_contract({
        "kind": "spa", "build": "true", "start": "serve", "liveness": "boots",
        "primary_surface": {"req": "FR-001", "assert": "catalog renders"},
        "surfaces": [{"req": "FR-006", "assert": "graph renders"}],
    })


@pytest.mark.unit
def test_browser_probe_blocks_stub_app(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text(_STUB_APP)
    out = _browser_probe(str(tmp_path), _contract_spa(), None)
    assert out.live is False                      # stub: nothing composed
    assert out.present["FR-001"] is False         # primary surface absent


@pytest.mark.unit
def test_browser_probe_passes_wired_app(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text(_WIRED_APP)
    out = _browser_probe(str(tmp_path), _contract_spa(), None)
    assert out.live is True
    assert out.present["FR-001"] is True
