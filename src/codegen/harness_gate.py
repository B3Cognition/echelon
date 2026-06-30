"""Deterministic codegen verification gates owned by the Python harness."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from codegen.delivery.verification_manifest import (
    build_manifest,
    render_markdown,
)
from codegen.runner.runnable_gate import (
    ProbeOutcome,
    make_probe,
    run_runnable_gate,
)
from codegen.schema.runnable_contract import RunnableContract, parse_runnable_contract


@dataclass(frozen=True)
class CodegenHarnessGateResult:
    passed: bool
    build_status: str
    failures: list[str] = field(default_factory=list)


def enforce_codegen_verification(
    workspace: str | Path,
    *,
    probe_fn: Callable[[str, RunnableContract, int | None], ProbeOutcome] | None = None,
) -> CodegenHarnessGateResult:
    """Run non-LLM codegen gates and emit the honest verification manifest.

    This is intentionally fail-closed: a codegen build cannot rely on the LLM
    to self-report RUNNABLE or DELIVER evidence. Python owns both the runnable
    gate verdict and `codegen-verification.md` emission.
    """
    root = Path(workspace)
    state_path = root / "codegen-state.json"
    state = _read_state(state_path)
    failures: list[str] = []

    contract_data = state.get("runnable_contract")
    if not isinstance(contract_data, dict):
        state["runnable_gate"] = "fail"
        state["runnable_gate_failures"] = ["missing runnable_contract in codegen-state.json"]
        _write_state(state_path, state)
        _write_manifest(root, state)
        return CodegenHarnessGateResult(
            passed=False,
            build_status="runnable_contract_missing",
            failures=list(state["runnable_gate_failures"]),
        )

    try:
        contract = parse_runnable_contract(contract_data)
    except ValueError as exc:
        state["runnable_gate"] = "fail"
        state["runnable_gate_failures"] = [f"invalid runnable_contract: {exc}"]
        _write_state(state_path, state)
        _write_manifest(root, state)
        return CodegenHarnessGateResult(
            passed=False,
            build_status="runnable_contract_invalid",
            failures=list(state["runnable_gate_failures"]),
        )

    probe = probe_fn or make_probe(contract.kind)
    gate = run_runnable_gate(contract, str(root), probe_fn=probe)
    state["runnable_gate"] = "pass" if gate.passed else "fail"
    state["runnable_surface_score"] = gate.surface_score
    state["runnable_gate_failures"] = gate.failures
    _write_state(state_path, state)
    _write_manifest(root, state)

    if not gate.passed:
        failures.extend(gate.failures)
        return CodegenHarnessGateResult(
            passed=False,
            build_status="runnable_gate_failed",
            failures=failures,
        )

    return CodegenHarnessGateResult(passed=True, build_status="done")


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, state: dict) -> None:
    path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_manifest(workspace: Path, state: dict) -> None:
    manifest = build_manifest(state)
    (workspace / "codegen-verification.md").write_text(
        render_markdown(manifest),
        encoding="utf-8",
    )
