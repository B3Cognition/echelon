from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest


def _write_current_run(project: Path, state: dict) -> Path:
    run_dir = project / "runs" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (project / "runs" / ".current").write_text("run-1\n", encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return run_dir


def _base_state(inputs_dir: Path) -> dict:
    from echelon.product_inputs import immutable_product_input_tree_digest

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
            "manifest_hash": hashlib.sha256(
                (inputs_dir / "manifest.json").read_bytes()
            ).hexdigest(),
            "tree_hash": immutable_product_input_tree_digest(inputs_dir),
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


def test_spec_add_input_rejects_preexisting_unindexed_tree_tamper(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from echelon.spec_add_input import SpecAddInputError, add_input_to_active_run

    project = tmp_path / "workspace"
    base_source = project / "sources/base.md"
    added_source = project / "sources/added.md"
    base_source.parent.mkdir(parents=True)
    base_source.write_text("base\n", encoding="utf-8")
    added_source.write_text("added\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        project / "runs/run-1",
        [parse_input_declaration("reference:sources/base.md")],
    )
    _write_current_run(project, _base_state(resolution.inputs_dir))
    (resolution.inputs_dir / "unindexed.bin").write_bytes(b"tamper")

    with pytest.raises(SpecAddInputError, match="tree hash drift"):
        add_input_to_active_run(project, ["reference:sources/added.md"])

    assert not (resolution.inputs_dir / "attachments/001").exists()


@pytest.mark.parametrize(
    "fault_boundary",
    ["before_intent", "before_write", "partial_write", "before_state_finalize"],
)
def test_spec_add_input_recovers_every_mutation_commit_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_boundary: str,
) -> None:
    from echelon.product_inputs import (
        immutable_product_input_tree_digest,
        parse_input_declaration,
        resolve_product_inputs,
    )
    from echelon.spec_add_input import SpecAddInputError, add_input_to_active_run
    from harness.squad_publication import PreparedSquadPublication
    from harness.squad_state import SquadStateStore
    from harness.state_transaction_namespace import (
        PENDING_EXTERNAL_PUBLICATION_KEY,
        PRODUCT_INPUT_MUTATION_KEY,
    )

    project = tmp_path / "workspace"
    base_source = project / "sources/base.md"
    added_source = project / "sources/added.md"
    base_source.parent.mkdir(parents=True)
    base_source.write_text("base\n", encoding="utf-8")
    added_source.write_text("added\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        project / "runs/run-1",
        [parse_input_declaration("reference:sources/base.md")],
    )
    run_dir = _write_current_run(project, _base_state(resolution.inputs_dir))
    old_hash = immutable_product_input_tree_digest(resolution.inputs_dir)

    if fault_boundary == "before_intent":
        original = SquadStateStore.begin_product_input_publication
        attempts = 0

        def fail_first_begin(self, *args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("injected intent save failure")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(
            SquadStateStore,
            "begin_product_input_publication",
            fail_first_begin,
        )
    elif fault_boundary in {"before_write", "partial_write"}:
        original_publish = PreparedSquadPublication.publish
        attempts = 0

        def fail_first_publish(self, fault_hook=None):
            nonlocal attempts
            attempts += 1
            if attempts != 1:
                return original_publish(self, fault_hook=fault_hook)
            if fault_boundary == "before_write":
                raise RuntimeError("injected before publication")

            def fail(position: int) -> None:
                if position == 1:
                    raise RuntimeError("injected partial publication")

            return original_publish(self, fault_hook=fail)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            fail_first_publish,
        )
    else:
        original_complete = SquadStateStore.complete_external_publication
        attempts = 0

        def fail_first_complete(self, *args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("injected state finalize failure")
            return original_complete(self, *args, **kwargs)

        monkeypatch.setattr(
            SquadStateStore,
            "complete_external_publication",
            fail_first_complete,
        )

    with pytest.raises((SpecAddInputError, OSError)):
        add_input_to_active_run(project, ["reference:sources/added.md"])

    interrupted = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    if fault_boundary == "before_intent":
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in interrupted
        assert PRODUCT_INPUT_MUTATION_KEY not in interrupted
        assert immutable_product_input_tree_digest(resolution.inputs_dir) == old_hash
    else:
        assert interrupted[PENDING_EXTERNAL_PUBLICATION_KEY]["transaction_id"]
        assert interrupted[PRODUCT_INPUT_MUTATION_KEY]["kind"] == "add_input"

    recovered = add_input_to_active_run(
        project,
        ["reference:sources/added.md"],
    )

    final = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert recovered.added_count == 1
    assert recovered.attachment_id == "001"
    assert PENDING_EXTERNAL_PUBLICATION_KEY not in final
    assert PRODUCT_INPUT_MUTATION_KEY not in final
    assert final["product_inputs"]["tree_hash"] == (
        immutable_product_input_tree_digest(resolution.inputs_dir)
    )
    assert [item["id"] for item in final["product_input_attachments"]] == ["001"]
    assert len(list((resolution.inputs_dir / "attachments").glob("001"))) == 1


def test_spec_add_input_completed_retry_is_operation_idempotent(
    tmp_path: Path,
) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from echelon.spec_add_input import add_input_to_active_run

    project = tmp_path / "workspace"
    base_source = project / "sources/base.md"
    added_source = project / "sources/added.md"
    base_source.parent.mkdir(parents=True)
    base_source.write_text("base\n", encoding="utf-8")
    added_source.write_text("added\n", encoding="utf-8")
    resolution = resolve_product_inputs(
        project,
        project / "runs/run-1",
        [parse_input_declaration("reference:sources/base.md")],
    )
    _write_current_run(project, _base_state(resolution.inputs_dir))

    first = add_input_to_active_run(project, ["reference:sources/added.md"])
    second = add_input_to_active_run(project, ["reference:sources/added.md"])

    assert second == first
    ledger = json.loads(
        (resolution.inputs_dir / "attachment-ledger.json").read_text(encoding="utf-8")
    )
    assert [item["id"] for item in ledger["attachments"]] == ["001"]


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
