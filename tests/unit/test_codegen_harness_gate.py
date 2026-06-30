from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegen.runner.runnable_gate import ProbeOutcome


def _write_state(workspace: Path, **overrides) -> Path:
    state = {
        "tier1_gate": "pass",
        "psi": {"score": 1.0, "threshold": 0.7},
        "security_gate": "pass",
        "runnable_contract": {
            "kind": "spa",
            "build": "true",
            "liveness": "static composition evidence",
            "primary_surface": {
                "req": "FR-001",
                "assert": "catalog renders rows",
            },
            "surfaces": [
                {"req": "FR-002", "assert": "details render"},
            ],
        },
    }
    state.update(overrides)
    path = workspace / "codegen-state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


@pytest.mark.unit
def test_codegen_harness_gate_blocks_hollow_app_and_writes_manifest(tmp_path: Path) -> None:
    from codegen.harness_gate import enforce_codegen_verification

    _write_state(tmp_path)

    def hollow_probe(workspace, contract, port):
        return ProbeOutcome(
            live=True,
            present={"FR-001": False, "FR-002": False},
        )

    result = enforce_codegen_verification(tmp_path, probe_fn=hollow_probe)

    assert result.passed is False
    assert result.build_status == "runnable_gate_failed"
    assert any("FR-001" in failure for failure in result.failures)

    state = json.loads((tmp_path / "codegen-state.json").read_text(encoding="utf-8"))
    assert state["runnable_gate"] == "fail"
    assert state["runnable_surface_score"] == 0.0
    assert any("FR-001" in failure for failure in state["runnable_gate_failures"])

    manifest = tmp_path / "codegen-verification.md"
    assert manifest.exists()
    text = manifest.read_text(encoding="utf-8")
    assert "NOT verified" in text
    assert "human must observe" in text.lower()


@pytest.mark.unit
def test_codegen_harness_gate_passes_composed_app_and_records_claim(tmp_path: Path) -> None:
    from codegen.harness_gate import enforce_codegen_verification

    _write_state(tmp_path)

    def composed_probe(workspace, contract, port):
        return ProbeOutcome(
            live=True,
            present={"FR-001": True, "FR-002": True},
        )

    result = enforce_codegen_verification(tmp_path, probe_fn=composed_probe)

    assert result.passed is True
    assert result.build_status == "done"

    state = json.loads((tmp_path / "codegen-state.json").read_text(encoding="utf-8"))
    assert state["runnable_gate"] == "pass"
    assert state["runnable_surface_score"] == 1.0

    text = (tmp_path / "codegen-verification.md").read_text(encoding="utf-8")
    assert "**runnable_gate** (pass)" in text


@pytest.mark.unit
def test_codegen_harness_gate_fails_closed_without_runnable_contract(tmp_path: Path) -> None:
    from codegen.harness_gate import enforce_codegen_verification

    _write_state(tmp_path, runnable_contract=None)

    result = enforce_codegen_verification(tmp_path)

    assert result.passed is False
    assert result.build_status == "runnable_contract_missing"
    assert any("runnable_contract" in failure for failure in result.failures)
    assert (tmp_path / "codegen-verification.md").exists()
