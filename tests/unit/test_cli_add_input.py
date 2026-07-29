from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_current_run(project: Path, state: dict) -> Path:
    run_dir = project / "runs" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (project / "runs" / ".current").write_text("run-1\n", encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return run_dir


def _base_state(inputs_dir: Path) -> dict:
    return {
        "run_id": "run-1",
        "status": "blocked",
        "phase": "phase1-investigate",
        "blocked_reason": "investigation_access_required",
        "evidence_resolution_status": "access_required",
        "escalation_question": "Need Data Engineering evidence.",
        "evidence_requests": {
            "requests": [{"id": "ER-001", "question": "Need mapping"}]
        },
        "phase_dispatch_counts": {"phase1-investigate": 5, "phase1-what": 2},
        "product_inputs": {
            "inputs_dir": str(inputs_dir),
            "manifest": str(inputs_dir / "manifest.json"),
            "catalog": str(inputs_dir / "catalog.json"),
            "input_context": str(inputs_dir / "input-context.md"),
            "requirement_context": str(inputs_dir / "requirement-context.md"),
            "reference_context": str(inputs_dir / "reference-context.md"),
            "traceability": str(inputs_dir / "traceability.json"),
            "traceability_markdown": str(inputs_dir / "traceability.md"),
            "declarations": [{"role": "reference", "location": "sources/base"}],
            "manifest_hash": "old",
        },
    }


def test_spec_add_input_unblocks_investigation_and_resets_only_investigation_cap(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from echelon.spec_add_input import add_input_to_active_run

    project = tmp_path / "workspace"
    base_source = project / "sources" / "base"
    added_source = project / "sources" / "DE-RESOLVER-BENCHMARK"
    base_source.mkdir(parents=True)
    added_source.mkdir(parents=True)
    (base_source / "brief.md").write_text("base\n", encoding="utf-8")
    (added_source / "benchmarks.csv").write_text(
        "filters,p95\n10,42\n",
        encoding="utf-8",
    )
    resolution = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("reference:sources/base")],
    )
    run_dir = _write_current_run(project, _base_state(resolution.inputs_dir))

    result = add_input_to_active_run(
        project,
        ["reference:sources/DE-RESOLVER-BENCHMARK"],
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert result.added_count == 1
    assert state["status"] == "running"
    assert state["phase"] == "phase1-investigate"
    assert state["blocked_reason"] is None
    assert state["escalation_question"] is None
    assert state["escalation_resolver"] == "echelon spec add-input"
    assert state["phase_dispatch_counts"] == {"phase1-what": 2}
    assert state["add_input_recovery"]["previous_blocked_reason"] == "investigation_access_required"
    assert state["add_input_recovery"]["previous_phase1_investigate_dispatch_count"] == 5
    assert state["evidence_requests"]["requests"][0]["id"] == "ER-001"
    assert state["product_input_attachments"][0]["id"] == "001"


def test_spec_add_input_duplicate_only_leaves_state_blocked(tmp_path: Path) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from echelon.spec_add_input import add_input_to_active_run

    project = tmp_path / "workspace"
    base_source = project / "sources" / "base"
    base_source.mkdir(parents=True)
    (base_source / "brief.md").write_text("base\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        project / "runs" / "run-1",
        [parse_input_declaration("reference:sources/base")],
    )
    run_dir = _write_current_run(project, _base_state(resolution.inputs_dir))
    before = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

    result = add_input_to_active_run(project, ["reference:sources/base"])

    after = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert result.added_count == 0
    assert result.duplicate_count == 1
    assert after == before


def test_cmd_spec_add_input_parses_repeatable_inputs(monkeypatch, capsys) -> None:
    from echelon import cli
    from echelon.spec_add_input import SpecAddInputResult

    calls: list[list[str]] = []

    def fake_add_input(project_root: Path, input_values: list[str]) -> SpecAddInputResult:
        calls.append(input_values)
        return SpecAddInputResult(
            run_dir=project_root / "runs" / "run-1",
            attachment_id="001",
            added_count=2,
            duplicate_count=1,
            original_declarations=({"role": "reference", "location": "sources/base"},),
            attached_declarations=({"role": "reference", "location": "sources/new"},),
        )

    monkeypatch.setattr("echelon.spec_add_input.add_input_to_active_run", fake_add_input)

    cli._cmd_spec_add_input([
        "--input",
        "reference:sources/new",
        "--input=reference:sources/bench",
    ])

    assert calls == [["reference:sources/new", "reference:sources/bench"]]
    output = capsys.readouterr().out
    assert "INPUT ADDED" in output
    assert "echelon spec continue" in output


@pytest.mark.parametrize(
    ("status", "phase", "reason", "evidence_status"),
    [
        ("running", "phase1-investigate", "investigation_access_required", "access_required"),
        ("blocked", "phase1-what", "investigation_access_required", "access_required"),
        ("blocked", "phase1-investigate", "human_clarification_required", "access_required"),
        ("blocked", "phase1-investigate", "investigation_access_required", "pending"),
    ],
)
def test_spec_add_input_rejects_non_eligible_run(
    tmp_path: Path,
    status: str,
    phase: str,
    reason: str,
    evidence_status: str,
) -> None:
    from echelon.spec_add_input import SpecAddInputError, add_input_to_active_run

    project = tmp_path / "workspace"
    inputs_dir = project / "runs" / "run-1" / "inputs"
    inputs_dir.mkdir(parents=True)
    for name in ("manifest.json", "catalog.json", "traceability.json"):
        (inputs_dir / name).write_text("{}\n", encoding="utf-8")
    for name in (
        "input-context.md",
        "requirement-context.md",
        "reference-context.md",
        "traceability.md",
    ):
        (inputs_dir / name).write_text("", encoding="utf-8")
    state = _base_state(inputs_dir)
    state.update({
        "status": status,
        "phase": phase,
        "blocked_reason": reason,
        "evidence_resolution_status": evidence_status,
    })
    _write_current_run(project, state)

    with pytest.raises(SpecAddInputError, match="parked investigation access checkpoint"):
        add_input_to_active_run(project, ["reference:sources/new"])
